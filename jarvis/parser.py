"""
jarvis/parser.py

Handles robust extraction of tool calls from LLM responses.
Local LLMs (e.g. Qwen via Ollama) sometimes return tool calls as raw JSON
text in the content field instead of using the structured tool_calls attribute.
This module handles both cases transparently.
"""

import json
import re
import ast


class ToolCallProxy:
    """
    A lightweight proxy that normalises tool call data into a consistent
    interface regardless of whether the source was a native Ollama tool call
    object or a manually-parsed JSON block from the content string.
    """

    class FunctionProxy:
        def __init__(self, name: str, arguments: dict):
            self.name = name
            self.arguments = arguments

    def __init__(self, name: str, arguments: dict):
        self.function = self.FunctionProxy(name, arguments)


def _parse_json_tool(data: dict) -> "ToolCallProxy | None":
    """
    Convert a raw dict into a ToolCallProxy.
    Handles multiple schemas produced by different model sizes:

      Schema A (standard):  {"name": "func", "arguments": {...}}
      Schema B (1.5b qwen): {"function": "func", "arguments": {...}}
      Schema C (nested):    {"function": {"name": "func", "arguments": {...}}}
    """
    # Schema A
    if "name" in data and "arguments" in data:
        return ToolCallProxy(data["name"], data["arguments"])

    # Schema B  — function is a plain string key
    if "function" in data and "arguments" in data:
        func = data["function"]
        if isinstance(func, str):
            return ToolCallProxy(func, data["arguments"])

    # Schema C  — function is a nested dict
    if "function" in data and isinstance(data["function"], dict):
        inner = data["function"]
        name  = inner.get("name") or inner.get("function")
        args  = inner.get("arguments", inner.get("parameters", {}))
        if name:
            return ToolCallProxy(name, args)

    return None


def extract_tool_calls(message) -> list:
    """
    Extracts tool calls from an assistant message object.

    Strategy:
      1. Use native Ollama `tool_calls` attribute if present and non-empty.
      2. Attempt to parse the content string as JSON (single dict or list).
      3. Fall back to regex matching for JSON objects embedded in free-form text.

    Args:
        message: The Ollama response message object.

    Returns:
        list[ToolCallProxy]: A (possibly empty) list of normalised tool call proxies.
    """
    # 1. Native Ollama structured tool calls
    native_calls = getattr(message, 'tool_calls', None)
    if native_calls:
        return native_calls

    # 2. Parse from content string
    content = getattr(message, 'content', '') or ''
    if not content:
        return []

    tool_calls = []

    # Find all code fences and bare JSON blocks in the content
    # This handles: ```json ... ```, ``` ... ```, and raw {...} blobs
    candidates = []

    # Extract content from all ```...``` blocks first
    fence_blocks = re.findall(r'```[a-zA-Z0-9-]*\n?([\s\S]*?)```', content)
    candidates.extend(fence_blocks)

    # Also try the whole content stripped of fences as a candidate
    cleaned = re.sub(r'```[a-zA-Z0-9-]*\n?', '', content)
    cleaned = re.sub(r'```', '', cleaned).strip()
    candidates.append(cleaned)

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue

        # Try direct JSON parse
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                tc = _parse_json_tool(data)
                if tc:
                    tool_calls.append(tc)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        tc = _parse_json_tool(item)
                        if tc:
                            tool_calls.append(tc)
            if tool_calls:
                return tool_calls
        except json.JSONDecodeError:
            # Fallback: try parsing as a Python dict literal (handles triple quotes, unescaped newlines, etc.)
            try:
                data = ast.literal_eval(candidate)
                if isinstance(data, dict):
                    tc = _parse_json_tool(data)
                    if tc:
                        tool_calls.append(tc)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            tc = _parse_json_tool(item)
                            if tc:
                                tool_calls.append(tc)
                if tool_calls:
                    return tool_calls
            except Exception:
                pass

    # 3. Regex fallback: match JSON objects with "name"/"function" + "arguments"
    #    Handles both schemas in a single pass
    pattern = (
        r'\{\s*'
        r'(?:"name"\s*:\s*"(?P<name>[^"]+)"\s*,\s*"arguments"\s*:\s*(?P<args_a>\{.*?\})'   # Schema A
        r'|"function"\s*:\s*"(?P<func>[^"]+)"\s*,\s*"arguments"\s*:\s*(?P<args_b>\{.*?\})'  # Schema B
        r')'
        r'\s*\}'
    )
    for match in re.finditer(pattern, content, re.DOTALL):
        try:
            name = match.group('name') or match.group('func')
            raw  = match.group('args_a') or match.group('args_b')
            args = json.loads(raw)
            tool_calls.append(ToolCallProxy(name, args))
        except (json.JSONDecodeError, Exception):
            pass

    if not tool_calls:
        # 4. Regex fallback: match Python/JS-like function calls (e.g. search_web(query="..."))
        #    Specifically matches registered tool names.
        tools_list = [
            "search_web", "read_web_page", "list_files", "list_files_recursive",
            "create_file", "delete_file", "create_folder", "move_file",
            "move_folder_contents", "organize_by_date"
        ]
        tools_pattern = "|".join(re.escape(t) for t in tools_list)
        func_pattern = rf'\b(?P<name>{tools_pattern})\s*\((?P<args>[\s\S]*?)\)'
        
        for match in re.finditer(func_pattern, content):
            name = match.group('name')
            args_str = match.group('args').strip()
            
            # Strip outer curly braces, brackets, and spaces
            cleaned_args_str = args_str.strip('{}[] ')
            
            # Parse keyword or colon-based arguments (e.g., query="...", query: "...")
            pair_pattern = r'(\w+)\s*[:=]\s*(["\'])((?:[^\\]|\\.)*?)\2'
            args = {}
            for pm in re.finditer(pair_pattern, cleaned_args_str, re.DOTALL):
                k = pm.group(1)
                v = pm.group(3)
                v = v.replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                args[k] = v
                
            if not args and args_str:
                # Strip outer braces, parentheses, and spaces
                clean_args_str = args_str.strip('{}[]() ')
                
                # Try matching unquoted key=value or key:value
                loose_match = re.match(r'^(\w+)\s*[:=]\s*(.+)$', clean_args_str, re.DOTALL)
                if loose_match:
                    k = loose_match.group(1)
                    v = loose_match.group(2).strip(' "\'')
                    args[k] = v
                else:
                    val = clean_args_str.strip(' "\'')
                    if val:
                        if name in ("search_web", "read_web_page"):
                            arg_name = "query" if name == "search_web" else "url"
                        elif name in ("list_files", "list_files_recursive", "delete_file", "organize_by_date"):
                            arg_name = "directory_path" if name != "delete_file" else "file_path"
                        else:
                            arg_name = "directory_path"
                        args[arg_name] = val
            
            tool_calls.append(ToolCallProxy(name, args))

    return tool_calls

