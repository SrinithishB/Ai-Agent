# JARVIS — Just A Rather Very Intelligent System

A modular, locally-running AI agent powered by Ollama. JARVIS is built as a generic agentic framework that can be extended with new capabilities (tools) without modifying the core engine.

---

## Project Structure

```
d:\project\agent\
├── main.py                        # CLI entry point
├── requirements.txt               # Python dependencies
├── jarvis/
│   ├── __init__.py
│   ├── agent.py                   # Generic agentic loop (tool-agnostic)
│   ├── parser.py                  # Tool call extraction & JSON fallback parser
│   ├── tool_registry.py           # Central tool discovery and dispatch
│   └── tools/
│       ├── __init__.py
│       ├── file_tools.py          # list_files, create_file, delete_file
│       ├── folder_tools.py        # create_folder
│       └── organizer_tools.py     # move_file
```

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/) running locally
- Recommended model: `qwen2.5-coder:7b`

---

## Setup

1. **Install Ollama** and download a model:
   ```bash
   ollama pull qwen2.5-coder:7b
   ```

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   venv\Scripts\activate       # Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Running JARVIS

```bash
python main.py
```

You will be prompted for:
1. **Ollama model name** — press Enter to use the default `qwen2.5-coder:7b`
2. **Working directory** — the folder JARVIS will manage

Once started, type natural language instructions in the interactive chat loop:

```
You: list all the contents
You: create a programs folder
You: create a hello.py file with print("Hello, World!")
You: move hello.py to the programs folder
You: quit
```

---

## Available Tools

| Tool | Module | Description |
|------|--------|-------------|
| `list_files` | `file_tools` | Lists files in the working directory |
| `create_file` | `file_tools` | Creates a new file with content (requires confirmation) |
| `delete_file` | `file_tools` | Permanently deletes a file (requires confirmation) |
| `create_folder` | `folder_tools` | Creates a new subdirectory |
| `move_file` | `organizer_tools` | Moves a file to a new location (requires confirmation) |

---

## Extending JARVIS with New Tools

Adding a new capability takes **three steps** and requires no changes to the core engine:

1. Create a new file in `jarvis/tools/`, e.g. `web_tools.py`:
   ```python
   def search_web(query: str) -> str:
       """Searches the web for a given query and returns a summary."""
       ...

   TOOLS = [search_web]
   ```

2. Import the module in `jarvis/tool_registry.py` and add it to `_TOOL_MODULES`:
   ```python
   from jarvis.tools import web_tools

   _TOOL_MODULES = [
       file_tools,
       folder_tools,
       organizer_tools,
       web_tools,        # <-- new
   ]
   ```

3. Run `python main.py` — JARVIS will automatically discover and use the new tool.

---

## Safety Architecture

JARVIS implements **Human-in-the-Loop** confirmation for all destructive or write operations:

- `move_file` — prompts before moving
- `delete_file` — prompts before deletion with a danger warning
- `create_file` — shows a content preview and prompts before writing

No files are modified without explicit `Y` confirmation from the user.
