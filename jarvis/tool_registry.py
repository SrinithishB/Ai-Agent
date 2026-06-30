"""
jarvis/tool_registry.py

Central tool registry for JARVIS.

All tool modules inside jarvis/tools/ expose a `TOOLS` list. This registry
imports those modules and merges all tools into a unified mapping that the
agent uses at runtime.

---------------------------------------------------------------------------
HOW TO ADD NEW TOOLS IN THE FUTURE
---------------------------------------------------------------------------
1. Create a new file inside `jarvis/tools/`, e.g. `web_tools.py`.
2. Implement your tool functions (with proper type hints and docstrings so
   Ollama can auto-generate the JSON schema).
3. Add a `TOOLS = [your_function, ...]` list at the bottom of that file.
4. Import the module here and add it to `_TOOL_MODULES` below.

That is the ONLY change needed in existing code. The agent loop, parser,
and CLI entry point require zero modifications.
---------------------------------------------------------------------------
"""

from jarvis.tools import (
    file_tools,
    folder_tools,
    organizer_tools,
    web_tools,
    app_tools,
    media_tools,
    browser_tools,
    system_tools,
)

# ── Register tool modules here ───────────────────────────────────────────
_TOOL_MODULES = [
    file_tools,        # list_files, create_file, delete_file
    folder_tools,      # create_folder
    organizer_tools,   # move_file, move_folder_contents, list_files_recursive, organize_by_date
    web_tools,         # search_web, read_web_page
    app_tools,         # launch_app, close_app, focus_app, minimize_app, maximize_app
    media_tools,       # play_music, control_music, play_video, control_video
    browser_tools,     # open_website, search_on, browser_tab_action, open_folder
    system_tools,      # set_volume, adjust_volume, window_action, take_screenshot, clipboard_action, evaluate_expression
]
# ─────────────────────────────────────────────────────────────────────────


def _build_registry() -> dict[str, callable]:
    """Merge TOOLS lists from all registered modules into a name → function map."""
    registry: dict[str, callable] = {}
    for module in _TOOL_MODULES:
        for func in module.TOOLS:
            registry[func.__name__] = func
    return registry


def get_tools_list() -> list:
    """
    Returns the list of callable tool functions to pass to ollama.chat(tools=...).

    Returns:
        list[callable]: All registered tool functions.
    """
    return [func for module in _TOOL_MODULES for func in module.TOOLS]


def get_openai_tools() -> list[dict]:
    """
    Returns the list of registered tools formatted as OpenAI-compliant JSON schemas.
    """
    import inspect
    tools = get_tools_list()
    schemas = []

    for func in tools:
        sig = inspect.signature(func)
        doc = func.__doc__ or ""

        # Extract first paragraph as description
        desc = doc.strip().split("\n\n")[0].strip()

        properties = {}
        required = []

        for name, param in sig.parameters.items():
            if name in ("self", "args", "kwargs"):
                continue

            p_type = "string"
            if param.annotation == int:
                p_type = "integer"
            elif param.annotation == float:
                p_type = "number"
            elif param.annotation == bool:
                p_type = "boolean"
            elif param.annotation == list:
                p_type = "array"
            elif param.annotation == dict:
                p_type = "object"

            p_desc = f"Parameter {name}"
            for line in doc.splitlines():
                line_clean = line.strip().lstrip("-* ")
                if line_clean.startswith(f"{name} ") or line_clean.startswith(f"{name}:") or line_clean.startswith(f"{name} ("):
                    parts = line_clean.split(":", 1)
                    if len(parts) > 1:
                        p_desc = parts[1].strip()
                    break

            properties[name] = {
                "type": p_type,
                "description": p_desc,
            }

            # Enums
            if name == "platform":
                properties[name]["enum"] = ["spotify", "youtube", "youtube_music", "apple_music", "auto"]
            elif name == "action":
                if func.__name__ == "control_music":
                    properties[name]["enum"] = ["play", "pause", "resume", "next", "previous", "stop", "shuffle", "repeat"]
                elif func.__name__ == "control_video":
                    properties[name]["enum"] = ["play", "pause", "mute", "fullscreen", "exit fullscreen", "forward", "backward"]
                elif func.__name__ == "browser_tab_action":
                    properties[name]["enum"] = ["new tab", "close tab", "reopen tab", "next tab", "previous tab", "refresh", "back", "forward"]
                elif func.__name__ == "clipboard_action":
                    properties[name]["enum"] = ["read", "copy", "clear", "paste"]
                elif func.__name__ == "window_action":
                    properties[name]["enum"] = ["snap left", "snap right", "maximize", "minimize", "restore", "switch", "close"]

            if param.default == inspect.Parameter.empty:
                required.append(name)

        schemas.append({
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        })

    return schemas


def dispatch(tool_name: str, arguments: dict) -> str:
    """
    Executes the tool identified by tool_name with the given arguments.

    Args:
        tool_name (str): Name of the tool to call.
        arguments (dict): Keyword arguments to pass to the tool function.

    Returns:
        str: The string result returned by the tool function.
    """
    registry = _build_registry()
    if tool_name not in registry:
        return f"Error: Tool '{tool_name}' is not registered in JARVIS."

    # Auto-redirect legacy user paths to active OneDrive paths if applicable
    try:
        from pathlib import Path
        home = Path.home()
        redirect_map = {
            home / "Desktop": home / "OneDrive" / "Desktop",
            home / "Documents": home / "OneDrive" / "Documents",
            home / "Pictures": home / "OneDrive" / "Pictures",
        }
        # Shallow copy arguments to prevent in-place modification of messages history
        arguments = dict(arguments)
        for key, val in list(arguments.items()):
            if isinstance(val, str):
                # Clean path representation for easy match
                val_clean = val.replace("/", "\\")
                for local_dir, onedrive_dir in redirect_map.items():
                    if onedrive_dir.exists():
                        local_dir_str = str(local_dir)
                        if val_clean.lower().startswith(local_dir_str.lower()):
                            # Replace the legacy path prefix with the OneDrive path prefix
                            remainder = val_clean[len(local_dir_str):].lstrip("\\/")
                            new_path = onedrive_dir / remainder
                            arguments[key] = str(new_path)
                            break
    except Exception:
        pass

    import inspect
    try:
        func = registry[tool_name]
        sig = inspect.signature(func)
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_kwargs:
            filtered_args = arguments
        else:
            filtered_args = {k: v for k, v in arguments.items() if k in sig.parameters}
        return str(func(**filtered_args))
    except Exception as e:
        return f"Error executing tool '{tool_name}': {str(e)}"
