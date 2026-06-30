"""
jarvis/agent.py

Generic Agentic Loop for JARVIS.

This module is entirely tool-agnostic. It does not import or reference any
specific tools. It only knows how to:
  - Send messages to an Ollama model.
  - Extract tool calls from the response (via parser.py).
  - Dispatch them to the tool_registry.
  - Continue the conversation loop until the model finishes.

To add a new capability to JARVIS, you never need to touch this file.
"""

import sys
import ast
import ollama

from jarvis.parser import extract_tool_calls
from jarvis import tool_registry


def _format_tool_output(output_str: str) -> str:
    """Safe evaluation and pretty-formatting of list tool outputs."""
    try:
        parsed = ast.literal_eval(output_str)
        if isinstance(parsed, list):
            formatted_lines = []
            for item in parsed:
                item_str = str(item).strip()
                if item_str.startswith("[DIR]"):
                    name = item_str.replace("[DIR]", "").strip()
                    formatted_lines.append(f"📁 **{name}**")
                elif item_str.startswith("[FILE]"):
                    name = item_str.replace("[FILE]", "").strip()
                    formatted_lines.append(f"📄 {name}")
                elif item_str.startswith("..."):
                    formatted_lines.append(f"*{item_str}*")
                else:
                    formatted_lines.append(f"- {item_str}")
            return "\n".join(formatted_lines)
    except Exception:
        pass
    return output_str



def _is_placeholder(val) -> bool:
    """Check if a tool argument value is a placeholder string (e.g. '[path]' or 'path/to')."""
    if not isinstance(val, str):
        return False
    val_clean = val.strip().lower().replace("\\", "/")
    if val_clean.startswith("[") or val_clean.endswith("]"):
        return True
    placeholders = [
        "path/to",
        "parent_directory",
        "example_folder",
        "file.txt",
        "new_folder",
        "newfolder",
        "[directory",
        "[source",
        "[destination",
        "[file",
        "your_username",
        "some_folder",
        "dummy",
        "placeholder",
    ]
    if any(p in val_clean for p in placeholders):
        return True
    return False


def _groq_chat_completion_stream(model: str, messages: list, tools: list, api_key: str):
    import requests
    import json
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "stream": True
    }
    if tools:
        payload["tools"] = tools
        
    res = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        stream=True,
        timeout=180
    )
    res.raise_for_status()
    
    class MockFunction:
        def __init__(self, name="", arguments=""):
            self.name = name
            self.arguments = arguments

    class MockToolCall:
        def __init__(self, index, id="", type="function", function=None):
            self.index = index
            self.id = id
            self.type = type
            self.function = function or MockFunction()

    class MockDelta:
        def __init__(self, content="", tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls or []
            
    class MockChoice:
        def __init__(self, delta):
            self.delta = delta
            
    class MockChunk:
        def __init__(self, choices):
            self.choices = choices or []

    for line in res.iter_lines():
        if not line:
            continue
        line_str = line.decode("utf-8").strip()
        if line_str.startswith("data: "):
            data_content = line_str[len("data: "):].strip()
            if data_content == "[DONE]":
                break
            
            try:
                chunk_data = json.loads(data_content)
            except Exception:
                continue
                
            choices_data = chunk_data.get("choices", [])
            choices = []
            for c in choices_data:
                delta_data = c.get("delta", {})
                content = delta_data.get("content", "")
                tool_calls_data = delta_data.get("tool_calls", [])
                
                tool_calls = []
                for tc in tool_calls_data:
                    func_data = tc.get("function", {})
                    fn_name = func_data.get("name", "")
                    fn_args = func_data.get("arguments", "")
                    tool_calls.append(
                        MockToolCall(
                            index=tc.get("index", 0),
                            id=tc.get("id", ""),
                            type=tc.get("type", "function"),
                            function=MockFunction(name=fn_name, arguments=fn_args)
                        )
                    )
                choices.append(MockChoice(MockDelta(content=content, tool_calls=tool_calls)))
            
            yield MockChunk(choices=choices)


def run(
    model_name: str,
    messages: list,
    max_loops: int = 8,
    verbose: bool = True,
    num_thread: int = 8,     # use all CPU threads (Ryzen 5 4000U = 8 threads)
    num_ctx: int = 4096,     # context window — 4096 is a good balance for CPU
    check_abort: callable = None,
) -> None:
    """
    Executes the JARVIS agentic reasoning loop.

    The loop runs until:
      - The model returns a response with no tool calls (task complete), or
      - max_loops is reached (safety guard against infinite execution).

    Args:
        model_name (str): Ollama model identifier (e.g. 'qwen2.5-coder:1.5b').
        messages (list): Conversation history (system + user + assistant turns).
                         Modified in-place so the caller retains full history.
        max_loops (int): Maximum number of LLM calls before force-stopping.
        verbose (bool): Whether to print agent reasoning and tool invocations.
        num_thread (int): CPU threads for inference. Set to your logical core count.
        num_ctx (int): Context window size. Smaller = faster on CPU-only hardware.
    """
    tools_list = tool_registry.get_tools_list()

    # Ollama inference options — tuned for CPU-only laptops
    infer_options = {
        "num_thread": num_thread,
        "num_ctx":    num_ctx,
        "num_batch":  512,      # process 512 tokens at a time (good CPU batch size)
        "low_vram":   True,     # reduces memory pressure even on CPU
        "temperature": 0.0,
    }

    if verbose:
        last_user_msg = next(
            (m['content'] for m in reversed(messages) if m.get('role') == 'user'), ''
        )
        print(f"\n[JARVIS] {last_user_msg}")
        print("-" * 50)

    # Find where the current user turn starts
    current_turn_start = 0
    for idx, msg in enumerate(reversed(messages)):
        if msg.get("role") == "user":
            current_turn_start = len(messages) - 1 - idx
            break

    # Track whether a web search has already run this turn
    web_search_done = False
    action_done     = False   # True after any media/browser/app action fires
    WEB_TOOLS = {"search_web", "read_web_page"}
    FS_TOOLS  = {
        "list_files", "list_files_recursive", "create_file", "delete_file",
        "create_folder", "move_file", "move_folder_contents", "organize_by_date",
    }
    ACTION_TOOLS = {
        # App control
        "launch_app", "close_app", "focus_app", "minimize_app", "maximize_app",
        # Media
        "play_music", "control_music", "play_video", "control_video",
        # Browser / website
        "open_website", "search_on", "browser_tab_action", "open_folder",
        # System
        "set_volume", "adjust_volume", "window_action", "take_screenshot",
        "clipboard_action", "evaluate_expression",
    }

    for loop_index in range(max_loops):
        # ── Check for user abort ──────────────────────────────────────────
        if check_abort and check_abort():
            if verbose:
                print("\n[JARVIS] Aborted by user request.")
            return

        # ── Load Groq API Key if present ──────────────────────────────────
        import os
        # Manually load .env from project root if it exists
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "=" in line and not line.strip().startswith("#"):
                            k, v = line.split("=", 1)
                            if k.strip() == "GROQ_API_KEY":
                                os.environ["GROQ_API_KEY"] = v.strip().strip('"').strip("'")
                                break
            except Exception:
                pass

        groq_key = os.environ.get("GROQ_API_KEY")

        # ── Query the LLM (Groq Cloud or Local Ollama) ─────────────────────
        is_groq = False
        if groq_key:
            # Check if model_name is a Groq model or doesn't look like local-only Ollama
            local_patterns = ("qwen2.5-coder", "coder", "phi3", "llama3:", "mistral", "gemma")
            is_local = any(lp in model_name.lower() for lp in local_patterns)
            if any(gp in model_name.lower() for gp in ("llama-3.3", "llama-3.1", "groq/", "allam", "qwen3", "gpt-oss")):
                is_groq = True
            elif not is_local:
                is_groq = True

        try:
            if is_groq:
                # Use selected model name, or default if generic
                groq_model_name = model_name
                if not any(gp in model_name.lower() for gp in ("llama", "groq", "allam", "qwen3", "gpt-oss")):
                    groq_model_name = "groq/compound"

                # Map system message + history to OpenAI format and sanitize IDs/types
                openai_messages = []
                for i, m in enumerate(messages):
                    role = m.get("role")
                    content = m.get("content")
                    # Ensure content is empty string instead of None for non-assistant/tool roles if desired
                    if content is None:
                        content = ""
                    msg = {"role": role, "content": content}
                    
                    if role == "assistant" and m.get("tool_calls"):
                        formatted_tcs = []
                        for tc_idx, tc in enumerate(m["tool_calls"]):
                            tc_fun = tc.get("function", {})
                            name = tc_fun.get("name", "")
                            args = tc_fun.get("arguments", {})
                            if isinstance(args, dict):
                                import json
                                args = json.dumps(args)
                            
                            tc_id = tc.get("id") or f"call_{i}_{tc_idx}"
                            formatted_tcs.append({
                                "id": tc_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": args
                                }
                            })
                        msg["tool_calls"] = formatted_tcs
                    elif role == "tool":
                        msg["tool_call_id"] = m.get("tool_call_id") or f"call_{i}_0"
                        msg["name"] = m.get("name") or "tool"
                    openai_messages.append(msg)

                # Pair tool_call_ids between assistant calls and tool responses
                for idx, msg in enumerate(openai_messages):
                    if msg.get("role") == "assistant" and msg.get("tool_calls"):
                        tcs = msg["tool_calls"]
                        tc_map = {tc["function"]["name"]: tc["id"] for tc in tcs}
                        for j in range(idx + 1, len(openai_messages)):
                            next_msg = openai_messages[j]
                            if next_msg.get("role") == "tool":
                                t_name = next_msg.get("name")
                                if t_name in tc_map:
                                    next_msg["tool_call_id"] = tc_map[t_name]
                            elif next_msg.get("role") in ("user", "assistant"):
                                break

                openai_tools = tool_registry.get_openai_tools()
                
                # Stream completion from Groq with rate-limit and tool-calling fallbacks
                stream = None
                model_attempts = [groq_model_name, "llama-3.1-8b-instant"]
                
                attempt_idx = 0
                while attempt_idx < len(model_attempts):
                    attempt_model = model_attempts[attempt_idx]
                    try:
                        stream = _groq_chat_completion_stream(
                            model=attempt_model,
                            messages=openai_messages,
                            tools=openai_tools,
                            api_key=groq_key
                        )
                        break
                    except Exception as exc:
                        err_msg = str(exc).lower()
                        # Handle tool-calling compatibility issues (like with groq/compound)
                        if "tool calling" in err_msg or "tool_call" in err_msg or "not supported with this model" in err_msg:
                            if attempt_model == "llama-3.3-70b-versatile":
                                raise
                            if verbose:
                                print(f"\n[JARVIS] Model '{attempt_model}' does not support tool calling. Falling back to llama-3.3-70b-versatile...")
                            if "llama-3.3-70b-versatile" not in model_attempts:
                                # Try llama-3.3 next
                                model_attempts.insert(attempt_idx + 1, "llama-3.3-70b-versatile")
                            attempt_idx += 1
                            continue
                        # Handle rate limit (429)
                        elif "rate limit" in err_msg or "429" in err_msg:
                            if attempt_idx == len(model_attempts) - 1:
                                # We have exhausted all Groq model attempts, propagate the exception
                                raise
                            else:
                                if verbose:
                                    print(f"\n[JARVIS] Rate limit (429) reached on '{attempt_model}'. Trying fallback '{model_attempts[attempt_idx + 1]}'...")
                                attempt_idx += 1
                                continue
                        else:
                            raise
            else:
                # We stream the response so we can print the reasoning tokens in real-time
                try:
                    stream = ollama.chat(
                        model=model_name,
                        messages=messages,
                        tools=tools_list,
                        options=infer_options,
                        stream=True,
                    )
                except Exception as exc:
                    err_msg = str(exc).lower()
                    if groq_key and ("failed_generation" in err_msg or "failed to call" in err_msg or "connection" in err_msg or "refused" in err_msg or "not found" in err_msg):
                        if verbose:
                            print(f"\n[JARVIS] Local Ollama failed ({exc}). Falling back to Groq Cloud model 'llama-3.3-70b-versatile'...")
                        # Map system message + history to OpenAI format and sanitize IDs/types
                        openai_messages = []
                        for i, m in enumerate(messages):
                            role = m.get("role")
                            content = m.get("content")
                            if content is None:
                                content = ""
                            msg = {"role": role, "content": content}
                            
                            if role == "assistant" and m.get("tool_calls"):
                                formatted_tcs = []
                                for tc_idx, tc in enumerate(m["tool_calls"]):
                                    tc_fun = tc.get("function", {})
                                    name = tc_fun.get("name", "")
                                    args = tc_fun.get("arguments", {})
                                    if isinstance(args, dict):
                                        import json
                                        args = json.dumps(args)
                                    
                                    tc_id = tc.get("id") or f"call_{i}_{tc_idx}"
                                    formatted_tcs.append({
                                        "id": tc_id,
                                        "type": "function",
                                        "function": {
                                            "name": name,
                                            "arguments": args
                                        }
                                    })
                                msg["tool_calls"] = formatted_tcs
                            elif role == "tool":
                                msg["tool_call_id"] = m.get("tool_call_id") or f"call_{i}_0"
                                msg["name"] = m.get("name") or "tool"
                            openai_messages.append(msg)

                        # Pair tool_call_ids between assistant calls and tool responses
                        for idx, msg in enumerate(openai_messages):
                            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                                tcs = msg["tool_calls"]
                                tc_map = {tc["function"]["name"]: tc["id"] for tc in tcs}
                                for j in range(idx + 1, len(openai_messages)):
                                    next_msg = openai_messages[j]
                                    if next_msg.get("role") == "tool":
                                        t_name = next_msg.get("name")
                                        if t_name in tc_map:
                                            next_msg["tool_call_id"] = tc_map[t_name]
                                    elif next_msg.get("role") in ("user", "assistant"):
                                        break

                        openai_tools = tool_registry.get_openai_tools()
                        stream = _groq_chat_completion_stream(
                            model="llama-3.3-70b-versatile",
                            messages=openai_messages,
                            tools=openai_tools,
                            api_key=groq_key
                        )
                        is_groq = True
                    else:
                        raise
        except Exception as exc:
            err_str = str(exc)
            if "model output" in err_str or "empty" in err_str.lower():
                raise
            
            # Secondary fallback: If Groq completely fails (e.g. rate limit exhausted on all models)
            if is_groq:
                err_msg = err_str.lower()
                if "rate limit" in err_msg or "429" in err_msg or "api connection" in err_msg or "groq" in err_msg:
                    if verbose:
                        print(f"\n[JARVIS] Groq Cloud rate-limited or unavailable. Falling back to local Ollama model '{model_name}'...")
                    try:
                        stream = ollama.chat(
                            model=model_name,
                            messages=messages,
                            tools=tools_list,
                            options=infer_options,
                            stream=True,
                        )
                        is_groq = False # Switch flag to bypass Groq chunk parsing
                        exc = None # Clear exception
                    except Exception as local_exc:
                        print(f"\n[JARVIS] Local Ollama fallback also failed: {local_exc}")
            
            if exc is not None:
                provider = "Groq API" if is_groq else "Ollama"
                print(f"\n[JARVIS] Error communicating with {provider}: {exc}")
                if not is_groq:
                    print("Make sure Ollama is running and the model is downloaded.")
                raise RuntimeError(f"{provider} connection error: {exc}")

        # Collect response chunks while printing thoughts to stdout
        full_content = ""
        collected_tool_calls = []

        # Write a prefix to stdout so the capture dispatcher routes it
        sys.stdout.write("[JARVIS_THOUGHT] ")
        sys.stdout.flush()

        def _stream_chunks(stream_iter):
            """Drain a streaming response, returning (content, tool_calls)."""
            content = ""
            
            if is_groq:
                # ── Handle OpenAI/Groq streaming delta format ──────────────
                tcalls_accumulator = {}
                for chunk in stream_iter:
                    if check_abort and check_abort():
                        return None, None
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    piece = delta.content or ""
                    if piece:
                        content += piece
                        try:
                            sys.stdout.write(piece)
                            sys.stdout.flush()
                        except UnicodeEncodeError:
                            try:
                                enc = sys.stdout.encoding or "utf-8"
                                sys.stdout.write(piece.encode(enc, errors="replace").decode(enc))
                                sys.stdout.flush()
                            except Exception:
                                pass
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tcalls_accumulator:
                                tcalls_accumulator[idx] = {
                                    "id": tc.id or "",
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name if tc.function and tc.function.name else "",
                                        "arguments": tc.function.arguments if tc.function and tc.function.arguments else ""
                                    }
                                }
                            else:
                                if tc.id:
                                    tcalls_accumulator[idx]["id"] = tc.id
                                if tc.function:
                                    if tc.function.name:
                                        tcalls_accumulator[idx]["function"]["name"] += tc.function.name
                                    if tc.function.arguments:
                                        tcalls_accumulator[idx]["function"]["arguments"] += tc.function.arguments
                
                # Convert accumulated OpenAI tool calls to compliant format
                tcalls = []
                for tc in tcalls_accumulator.values():
                    args_str = tc["function"]["arguments"]
                    try:
                        import json
                        arguments = json.loads(args_str) if args_str else {}
                    except Exception:
                        arguments = {}
                    
                    # Wrap in standard interfaces compatible with main agent.py loops
                    class FunctionWrapper:
                        def __init__(self, name, arguments):
                            self.name = name
                            self.arguments = arguments
                    class ToolCallWrapper:
                        def __init__(self, tc_id, function):
                            self.id = tc_id
                            self.function = function
                            
                    tcalls.append(ToolCallWrapper(tc["id"], FunctionWrapper(tc["function"]["name"], arguments)))
                return content, tcalls
            else:
                # ── Handle Ollama streaming dict format ────────────────────
                tcalls = []
                for chunk in stream_iter:
                    if check_abort and check_abort():
                        return None, None
                    msg_chunk = chunk.get("message", {})
                    piece = msg_chunk.get("content", "")
                    if piece:
                        content += piece
                        try:
                            sys.stdout.write(piece)
                            sys.stdout.flush()
                        except UnicodeEncodeError:
                            try:
                                enc = sys.stdout.encoding or "utf-8"
                                sys.stdout.write(piece.encode(enc, errors="replace").decode(enc))
                                sys.stdout.flush()
                            except Exception:
                                pass
                    calls = msg_chunk.get("tool_calls", [])
                    if calls:
                        tcalls.extend(calls)
                return content, tcalls

        try:
            full_content, collected_tool_calls = _stream_chunks(stream)
        except Exception as stream_err:
            err_str = str(stream_err)
            if "model output" in err_str or "empty" in err_str.lower():
                if verbose:
                    print(f"\n[JARVIS] Empty model output — synthesizing from tool results...")
                # Extract snippets from any tool results already in message history
                snippets = []
                for msg in messages[current_turn_start:]:
                    if msg.get("role") == "tool":
                        content = msg.get("content", "")
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith("Snippet:"):
                                snip = line[len("Snippet:"):].strip()
                                if snip and snip not in snippets:
                                    snippets.append(snip)
                if snippets:
                    best = max(snippets, key=len)
                    full_content = f"Based on my search:\n\n{best}"
                elif messages and messages[-1].get("role") == "tool":
                    full_content = messages[-1].get("content", "")[:500]
                else:
                    full_content = "I'm sorry, I couldn't generate a response. Please try again."
                collected_tool_calls = []
                # Remove the last assistant turn if it's a stale tool-call blob
                if messages and messages[-1].get("role") == "assistant":
                    messages.pop()
                messages.append({"role": "assistant", "content": full_content})
                sys.stdout.write(f"[JARVIS_THOUGHT] {full_content}\n")
                sys.stdout.flush()
                return
            else:
                raise

        if full_content is None:  # abort signal
            print("\n[JARVIS] Aborted by user request.")
            return
        collected_tool_calls = collected_tool_calls or []

        # Print final newline to complete the thought stream
        sys.stdout.write("\n")
        sys.stdout.flush()

        # Reconstruct message representation
        class AssistantMessageMock:
            def __init__(self, content, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

        assistant_message = AssistantMessageMock(full_content, collected_tool_calls)
        tool_calls = extract_tool_calls(assistant_message)

        # ── Append assistant turn to history ─────────────────────────────
        msg_dict: dict = {
            "role": "assistant",
            "content": assistant_message.content or "",
        }
        tool_call_ids = []
        if tool_calls:
            tool_calls_list = []
            for i, tc in enumerate(tool_calls):
                tc_id = getattr(tc, 'id', None)
                if not tc_id and isinstance(tc, dict):
                    tc_id = tc.get('id')
                if not tc_id:
                    tc_id = f"call_{loop_index}_{i}"
                tool_call_ids.append(tc_id)
                tool_calls_list.append({
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })
            msg_dict["tool_calls"] = tool_calls_list
        messages.append(msg_dict)

        # ── Handle tool calls ─────────────────────────────────────────────
        if tool_calls:
            # Check for duplicate tool calls in the conversation history of this run
            has_duplicate = False
            for tc in tool_calls:
                func_name = tc.function.name
                func_args = tc.function.arguments
                for msg in messages[current_turn_start:-1]:
                    if msg.get("role") == "assistant" and "tool_calls" in msg:
                        for prev_tc in msg["tool_calls"]:
                            p_func = prev_tc.get("function", {})
                            if p_func.get("name") == func_name and p_func.get("arguments") == func_args:
                                has_duplicate = True
                                break
                    if has_duplicate:
                        break
                if has_duplicate:
                    break

            if has_duplicate:
                if verbose:
                    print("\n[JARVIS] Duplicate tool call detected. Synthesizing answer from results...")

                # Pop the assistant turn containing the duplicate tool call
                if messages and messages[-1].get("role") == "assistant":
                    messages.pop()

                # Instead of calling the model again (which produces empty output on 1.5B),
                # directly extract the most useful content from the tool results and
                # compose a plain-text reply ourselves.
                snippets = []
                for msg in messages[current_turn_start:]:
                    if msg.get("role") == "tool":
                        content = msg.get("content", "")
                        # Parse "Snippet: ..." lines from search_web output
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith("Snippet:"):
                                snip = line[len("Snippet:"):].strip()
                                if snip and snip not in snippets:
                                    snippets.append(snip)
                        # For other tools, use full content if no snippets found
                        if not snippets and content.strip():
                            snippets.append(content.strip())

                if snippets:
                    # Use the most informative snippet (longest one tends to have the answer)
                    best = max(snippets, key=len)
                    summary = f"Based on my search:\n\n{best}"
                    if len(snippets) > 1:
                        summary += f"\n\n(Also found: {snippets[0][:120]}...)" if snippets[0] != best else ""
                else:
                    summary = "I found some results but couldn't extract a clear answer. Please try rephrasing your question."

                sys.stdout.write(f"[JARVIS_THOUGHT] {summary}\n")
                sys.stdout.flush()

                messages.append({
                    "role": "assistant",
                    "content": summary
                })
                return




            if verbose:
                print(f"\n[JARVIS] Executing {len(tool_calls)} action(s)...")

            action_results_this_iter = []  # collect results of ACTION_TOOLS run this iteration

            for i, tc in enumerate(tool_calls):
                func_name = tc.function.name
                func_args = tc.function.arguments
                tc_id = tool_call_ids[i] if i < len(tool_call_ids) else f"call_{loop_index}_{i}"

                if verbose:
                    print(f"  >> {func_name}({func_args})")

                # Check if any arguments are placeholder templates
                placeholder_arg = None
                for arg_name, arg_val in func_args.items():
                    if _is_placeholder(arg_val):
                        placeholder_arg = arg_val
                        break

                if placeholder_arg is not None:
                    # Clean the message history by removing the hallucinated assistant tool call
                    if messages and messages[-1].get("role") == "assistant":
                        messages.pop()

                    # Find the last successful file listing tool result to summarize
                    last_tool_output = None
                    for msg in reversed(messages[current_turn_start:]):
                        if msg.get("role") == "tool" and msg.get("name") in ("list_files", "list_files_recursive"):
                            last_tool_output = msg.get("content")
                            break

                    if last_tool_output:
                        formatted = _format_tool_output(last_tool_output)
                        summary = f"Here are the files I found:\n\n{formatted}"
                    else:
                        summary = (
                            "It looks like no folder was successfully listed or specified. "
                            "Please provide a valid, real folder path to list files!"
                        )

                    messages.append({
                        "role": "assistant",
                        "content": summary
                    })

                    if verbose:
                        print(f"\n[JARVIS]: {summary}")
                        print("\n" + "=" * 50)
                        print("  JARVIS completed successfully (safeguard triggered).")
                        print("=" * 50)
                    return
                else:
                    # Guard 1: if we already ran a web search, block stray filesystem calls.
                    if web_search_done and func_name in FS_TOOLS:
                        if verbose:
                            print(f"  [JARVIS] Blocking stray {func_name}() after web search — synthesizing from results instead.")
                        # Extract snippets from search results already in history
                        snippets = []
                        for msg in messages[current_turn_start:]:
                            if msg.get("role") == "tool" and msg.get("name") in WEB_TOOLS:
                                content = msg.get("content", "")
                                for line in content.splitlines():
                                    line = line.strip()
                                    if line.startswith("Snippet:"):
                                        snip = line[len("Snippet:"):].strip()
                                        if snip and snip not in snippets:
                                            snippets.append(snip)
                        # Pop the stray assistant message
                        if messages and messages[-1].get("role") == "assistant":
                            messages.pop()
                        if snippets:
                            best = max(snippets, key=len)
                            summary = f"Based on my search:\n\n{best}"
                        else:
                            summary = "I found some results but couldn't extract a clear answer. Please try rephrasing."
                        messages.append({"role": "assistant", "content": summary})
                        sys.stdout.write(f"[JARVIS_THOUGHT] {summary}\n")
                        sys.stdout.flush()
                        if verbose:
                            print("\n" + "=" * 50)
                            print("  JARVIS completed (web-guard triggered).")
                            print("=" * 50)
                        return

                    # Guard 2: if an action tool already ran, block any follow-up action calls.
                    if action_done and func_name in ACTION_TOOLS:
                        if verbose:
                            print(f"  [JARVIS] Action already completed — blocking stray {func_name}() call.")
                        # Use the last action tool result as the reply
                        last_action_result = ""
                        for msg in reversed(messages[current_turn_start:]):
                            if msg.get("role") == "tool" and msg.get("name") in ACTION_TOOLS:
                                last_action_result = msg.get("content", "Done.")
                                break
                        if messages and messages[-1].get("role") == "assistant":
                            messages.pop()
                        summary = last_action_result or "Done."
                        messages.append({"role": "assistant", "content": summary})
                        sys.stdout.write(f"[JARVIS_THOUGHT] {summary}\n")
                        sys.stdout.flush()
                        if verbose:
                            print("\n" + "=" * 50)
                            print("  JARVIS completed (action-guard triggered).")
                            print("=" * 50)
                        return

                    result = tool_registry.dispatch(func_name, func_args)
                    if func_name in WEB_TOOLS:
                        web_search_done = True
                    if func_name in ACTION_TOOLS:
                        action_done = True
                        action_results_this_iter.append(result)

                if verbose:
                    print(f"  << {result}")

                messages.append({
                    "role": "tool",
                    "content": result,
                    "name": func_name,
                    "tool_call_id": tc_id,
                })

            # ── If any action tool ran this iteration, return immediately ─────
            # Action tools (launch_app, play_video, open_website, etc.) are
            # fire-and-forget. We don't need the model to post-process them.
            if action_results_this_iter:
                summary = action_results_this_iter[0]  # first action result is the reply
                messages.append({"role": "assistant", "content": summary})
                sys.stdout.write(f"[JARVIS_THOUGHT] {summary}\n")
                sys.stdout.flush()
                if verbose:
                    print("\n" + "=" * 50)
                    print("  JARVIS completed (action executed).")
                    print("=" * 50)
                return

            # Feed non-action results back into the model for the next reasoning step
            continue

        # ── No tool calls: agent has finished ────────────────────────────
        if verbose:
            print("\n" + "=" * 50)
            print("  JARVIS completed successfully.")
            print("=" * 50)
        return

    # Reached max_loops without a clean finish
    print(f"\n[JARVIS] Reached safety limit of {max_loops} loops. Stopping.")
