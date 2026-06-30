"""
server.py - JARVIS FastAPI + WebSocket Server

Start with:
    python server.py
    python server.py --model qwen2.5-coder:7b --port 8000

Each browser tab gets its own isolated conversation session.
Tool print() outputs are captured per-thread and streamed to the client in real time.
"""

import sys
import json
import asyncio
import argparse
import threading
from pathlib import Path
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from jarvis import agent
from main import SYSTEM_PROMPT

# Default config (override via CLI args)
# ---------------------------------------------------------------------------
# Default to Groq Cloud if API key is present, otherwise fall back to local Ollama
import os
_env_file = Path(__file__).parent / ".env"
_groq_key = None
if _env_file.is_file():
    try:
        with open(_env_file, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == "GROQ_API_KEY":
                        _groq_key = v.strip().strip('"').strip("'")
                        os.environ["GROQ_API_KEY"] = _groq_key
                        break
    except Exception:
        pass
if not _groq_key:
    _groq_key = os.environ.get("GROQ_API_KEY")

MODEL = "groq/compound" if _groq_key else "qwen2.5-coder:1.5b"
CLIENT_DIR = Path(__file__).parent / "client"

# ---------------------------------------------------------------------------
# Thread-safe stdout capture
# Each agent thread writes to its own Queue; the main async loop drains it.
# ---------------------------------------------------------------------------
_thread_local = threading.local()


class _ThreadDispatcher:
    """
    Replaces sys.stdout so that print() inside any thread is routed to
    that thread's per-session capture buffer (if set), or to the real
    stdout otherwise.
    """
    def write(self, text: str):
        capture = getattr(_thread_local, "capture", None)
        if capture is not None:
            capture.write(text)
        else:
            sys.__stdout__.write(text)

    def flush(self):
        capture = getattr(_thread_local, "capture", None)
        if capture is not None:
            capture.flush()
        else:
            sys.__stdout__.flush()

    def isatty(self):
        return sys.__stdout__.isatty()

    def fileno(self):
        return sys.__stdout__.fileno()

    @property
    def encoding(self):
        return sys.__stdout__.encoding


# Install the dispatcher once at module load time
sys.stdout = _ThreadDispatcher()


class _QueueCapture:
    """Collects print() lines from one agent thread into a Queue."""

    def __init__(self, queue: Queue):
        self.queue = queue
        self._buf = ""

    def write(self, text: str):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.queue.put(("log", line))

    def flush(self):
        if self._buf.strip():
            self.queue.put(("log", self._buf))
            self._buf = ""


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="JARVIS")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
executor = ThreadPoolExecutor(max_workers=8)


@app.get("/")
async def index():
    return FileResponse(CLIENT_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")


# ---------------------------------------------------------------------------
# Model management API
# ---------------------------------------------------------------------------
import os
@app.get("/api/models")
async def get_models():
    """Return all locally installed Ollama models and Groq cloud models (if authenticated) and current active model."""
    groq_models = []
    
    # Manually load .env from project root if it exists
    env_path = Path(__file__).parent / ".env"
    if env_path.is_file():
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
    if groq_key:
        try:
            from openai import OpenAI
            client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key
            )
            res = client.models.list()
            # Filter out audio/non-text models
            for m in res.data:
                mid = m.id
                if not any(w in mid.lower() for w in ("whisper", "prompt-guard", "safeguard")):
                    groq_models.append(mid)
            groq_models = sorted(groq_models)
        except Exception:
            pass

    try:
        import ollama as _ollama_lib
        result = _ollama_lib.list()
        ollama_names = sorted(m.model for m in result.models)
    except Exception:
        ollama_names = []

    combined = groq_models + ollama_names
    if not combined:
        combined = [MODEL]

    return {"models": combined, "current": MODEL}


@app.get("/api/model")
async def get_current_model():
    """Return the currently active model."""
    return {"model": MODEL}


@app.post("/api/model")
async def set_model(payload: dict):
    """Switch the active model for all future requests."""
    global MODEL
    new_model = payload.get("model", "").strip()
    if not new_model:
        return {"error": "No model specified."}
    MODEL = new_model
    # Also reset the listener session so it starts fresh with the new model
    _listener_session.clear()
    _listener_session.append({"role": "system", "content": SYSTEM_PROMPT})
    return {"model": MODEL}


# ---------------------------------------------------------------------------
# Persistent session for the system-level voice listener (listener.py)
# ---------------------------------------------------------------------------
_listener_session: list = [{"role": "system", "content": SYSTEM_PROMPT}]
_listener_lock = threading.Lock()


def _run_agent_sync(messages: list) -> str:
    """Run the agent synchronously in a thread and return the last reply."""
    log_queue: Queue = Queue()
    _thread_local.capture = _QueueCapture(log_queue)
    # Record where this turn starts so reply extraction never reads old turns
    turn_start_idx = len(messages)
    try:
        agent.run(model_name=MODEL, messages=messages)
        reply = ""
        current_turn_msgs = messages[turn_start_idx:]
        # Prefer a clean text assistant message from this turn
        for m in reversed(current_turn_msgs):
            if m.get("role") == "assistant":
                if m.get("tool_calls"):   # skip pure tool-call stubs
                    continue
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                # Skip if it looks like a bare JSON tool-call blob
                test = content.replace("```json", "").replace("```", "").strip()
                if test.startswith("{") and ('"name"' in test or '"function"' in test):
                    continue
                reply = content
                break
        # Fallback: use the tool result from this turn
        if not reply:
            for m in reversed(current_turn_msgs):
                if m.get("role") == "tool":
                    content = (m.get("content") or "").strip()
                    if content:
                        reply = content
                        break
        return reply or "Done."
    except Exception as exc:
        return f"Error: {exc}"
    finally:
        _thread_local.capture = None


_active_websockets = set()


@app.post("/api/chat")
async def api_chat(payload: dict):
    """
    Simple HTTP chat endpoint for the system-level listener.py voice client.
    Maintains its own persistent conversation session across calls.
    """
    message = payload.get("message", "").strip()
    if not message:
        return {"reply": "No message received."}

    loop = asyncio.get_running_loop()

    # Broadcast user query to WebUI so it shows in browser chat dynamically
    for ws_client in list(_active_websockets):
        try:
            await ws_client.send_text(
                json.dumps({"type": "voice_user_msg", "content": message})
            )
        except Exception:
            pass

    with _listener_lock:
        # Trim session: keep system prompt + last 14 messages (≈7 turns).
        # This prevents context overflow which causes small models to hallucinate
        # or repeat stale results from earlier turns.
        MAX_HISTORY = 14
        if len(_listener_session) > MAX_HISTORY + 1:
            _listener_session[1:] = _listener_session[-MAX_HISTORY:]

        _listener_session.append({"role": "user", "content": message})
        # Run agent in thread (it's synchronous)
        reply = await loop.run_in_executor(
            executor, _run_agent_sync, _listener_session
        )

    # Broadcast reply to WebUI so it prints in browser chat dynamically
    for ws_client in list(_active_websockets):
        try:
            await ws_client.send_text(
                json.dumps({"type": "voice_reply", "content": reply})
            )
        except Exception:
            pass

    return {"reply": reply}


# ---------------------------------------------------------------------------
# WebSocket chat endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    _active_websockets.add(ws)

    # One conversation history per browser tab
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    loop = asyncio.get_running_loop()
    
    abort_event = threading.Event()
    input_queue = asyncio.Queue()

    # Background task to read incoming websocket messages from the client
    async def read_from_client():
        try:
            while True:
                raw = await ws.receive_text()
                payload = json.loads(raw)
                await input_queue.put(payload)
        except WebSocketDisconnect:
            abort_event.set()
        except Exception:
            abort_event.set()

    client_reader = asyncio.create_task(read_from_client())

    try:
        while True:
            # Wait for next payload from queue
            payload = await input_queue.get()
            
            if payload.get("action") == "abort":
                abort_event.set()
                continue
                
            user_msg = payload.get("message", "").strip()
            if not user_msg:
                continue

            abort_event.clear()
            # Record where this turn starts so we only search current-turn messages for the reply
            turn_start_idx = len(messages)
            messages.append({"role": "user", "content": user_msg})
            log_queue: Queue = Queue()

            def run_agent():
                """Runs the synchronous agent in a thread pool worker."""
                _thread_local.capture = _QueueCapture(log_queue)
                try:
                    agent.run(
                        model_name=MODEL,
                        messages=messages,
                        check_abort=lambda: abort_event.is_set(),
                    )
                    
                    if abort_event.is_set():
                        log_queue.put(("error", "Inference stopped by user."))
                        return

                    reply = ""
                    current_turn_msgs = messages[turn_start_idx:]
                    for m in reversed(current_turn_msgs):
                        if m.get("role") == "assistant":
                            # Skip assistant turns that contain tool calls
                            if m.get("tool_calls"):
                                continue
                            content = (m.get("content") or "").strip()
                            if not content:
                                continue
                            # Clean markdown code fences for validation check
                            test_content = content.replace("```json", "").replace("```", "").strip()
                            # Reject JSON-like tool calls
                            if test_content.startswith("{") and ('"name"' in test_content or '"function"' in test_content or "'name'" in test_content):
                                continue
                            # Reject bare function-call strings
                            if any(test_content.startswith(p) for p in ("search_", "list_", "read_", "create_", "delete_", "move_", "organize_")):
                                continue
                            reply = content
                            break

                    # If no clean text reply found, generate a context-aware fallback
                    if not reply:
                        # Detect what tool(s) ran this turn to give a meaningful confirmation
                        tool_names = [m.get("name", "") for m in current_turn_msgs if m.get("role") == "tool"]
                        file_tools_set = {"create_file", "delete_file", "move_file", "create_folder", "move_folder_contents", "organize_by_date"}
                        web_tools  = {"search_web", "read_web_page"}
                        list_tools = {"list_files", "list_files_recursive"}
                        app_tools_set  = {"launch_app", "close_app", "focus_app", "minimize_app", "maximize_app"}
                        media_tools_set = {"play_music", "control_music", "play_video", "control_video"}
                        browser_tools_set = {"open_website", "search_on", "browser_tab_action", "open_folder"}
                        sys_tools_set  = {"set_volume", "adjust_volume", "window_action", "take_screenshot", "clipboard_action", "evaluate_expression"}

                        # Check tool results for context
                        tool_results = {m.get("name", ""): m.get("content", "") for m in current_turn_msgs if m.get("role") == "tool"}

                        if any(t in file_tools_set for t in tool_names):
                            # Pick the first file-tool result as the confirmation
                            for ft in file_tools_set:
                                if ft in tool_results:
                                    reply = tool_results[ft]
                                    break
                            if not reply:
                                reply = "Done! The file operation completed successfully."
                        elif any(t in web_tools for t in tool_names):
                            # Extract best snippet from search results
                            snippets = []
                            for tn in web_tools:
                                if tn in tool_results:
                                    for line in tool_results[tn].splitlines():
                                        line = line.strip()
                                        if line.startswith("Snippet:"):
                                            snip = line[len("Snippet:"):].strip()
                                            if snip:
                                                snippets.append(snip)
                            if snippets:
                                reply = f"Based on my search:\n\n{max(snippets, key=len)}"
                            else:
                                reply = "I searched the web but couldn't extract a clear answer. Please try rephrasing."
                        elif any(t in list_tools for t in tool_names):
                            for lt in list_tools:
                                if lt in tool_results:
                                    reply = tool_results[lt]
                                    break
                        elif any(t in app_tools_set for t in tool_names):
                            # Use the tool result directly (e.g. 'Launched VS Code.')
                            for at in app_tools_set:
                                if at in tool_results:
                                    reply = tool_results[at]
                                    break
                            if not reply:
                                reply = "Done."
                        elif any(t in media_tools_set for t in tool_names):
                            for mt in media_tools_set:
                                if mt in tool_results:
                                    reply = tool_results[mt]
                                    break
                            if not reply:
                                reply = "Done."
                        elif any(t in browser_tools_set for t in tool_names):
                            for bt in browser_tools_set:
                                if bt in tool_results:
                                    reply = tool_results[bt]
                                    break
                            if not reply:
                                reply = "Done."
                        elif any(t in sys_tools_set for t in tool_names):
                            for st in sys_tools_set:
                                if st in tool_results:
                                    reply = tool_results[st]
                                    break
                            if not reply:
                                reply = "Done."
                        else:
                            reply = "Done!"

                    log_queue.put(("reply", reply))
                except Exception as exc:
                    log_queue.put(("error", str(exc)))
                finally:
                    _thread_local.capture = None
                    log_queue.put(("done", None))  # sentinel

            agent_future = loop.run_in_executor(executor, run_agent)

            # Stream queue events to the client while checking for abort requests
            done = False
            while not done:
                # Flush uvicorn log queue to the websocket client
                while True:
                    try:
                        event_type, content = log_queue.get_nowait()
                        if event_type == "done":
                            done = True
                            break
                        await ws.send_text(
                            json.dumps({"type": event_type, "content": content or ""})
                        )
                    except Empty:
                        break
                
                if done:
                    break

                # Process any client commands (like abort) that arrived during execution
                while not input_queue.empty():
                    client_payload = input_queue.get_nowait()
                    if client_payload.get("action") == "abort":
                        abort_event.set()

                await asyncio.sleep(0.05)

            await agent_future  # ensure the thread has fully exited

    except Exception as exc:
        try:
            await ws.send_text(json.dumps({"type": "error", "content": str(exc)}))
        except Exception:
            pass
    finally:
        _active_websockets.discard(ws)
        client_reader.cancel()



# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JARVIS Server")
    parser.add_argument(
        "--model", default="qwen2.5-coder:1.5b",
        help="Ollama model name (default: qwen2.5-coder:1.5b)"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port to listen on (default: 8000)"
    )
    args = parser.parse_args()
    MODEL = args.model

    sys.__stdout__.write(
        f"  JARVIS Server starting...\n"
        f"  Model  : {MODEL}\n"
        f"  URL    : http://localhost:{args.port}\n"
    )
    uvicorn.run("server:app", host="0.0.0.0", port=args.port, reload=False)
