"""
jarvis/tools/file_tools.py

File-level tools: listing directory contents, creating new files,
and permanently deleting files. All destructive operations require
explicit human-in-the-loop confirmation before execution.
"""

import os


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def list_files(directory_path: str) -> list[str]:
    """
    Lists all files AND subdirectories directly inside the specified directory.
    Entries are prefixed with [FILE] or [DIR] so the model can distinguish them.
    Does NOT recurse into subdirectories.

    Args:
        directory_path (str): The absolute path to the directory to list.

    Returns:
        list[str]: A labelled list of entries, or a list with a single error string.
    """
    try:
        abs_path = os.path.abspath(directory_path)
        if not os.path.exists(abs_path):
            return [f"Error: Directory '{directory_path}' does not exist."]
        if not os.path.isdir(abs_path):
            return [f"Error: Path '{directory_path}' is not a directory."]

        entries = os.listdir(abs_path)
        if not entries:
            return ["(empty directory)"]

        result = []
        sorted_entries = sorted(entries)
        limit = 35
        for name in sorted_entries[:limit]:
            full = os.path.join(abs_path, name)
            label = "[DIR] " if os.path.isdir(full) else "[FILE]"
            result.append(f"{label} {name}")

        if len(sorted_entries) > limit:
            result.append(f"... and {len(sorted_entries) - limit} more items.")
        return result
    except Exception as e:
        return [f"Error listing directory: {str(e)}"]


def create_file(directory_path: str, file_name: str, content: str = "") -> str:
    """
    Creates a new file at the specified directory path with optional text content.

    Args:
        directory_path (str): Absolute path to the target directory.
        file_name (str): Name of the file to create (e.g. 'hello.py').
        content (str): Initial text content of the file. Defaults to empty.

    Returns:
        str: A status message indicating success or failure.
    """
    try:
        abs_parent = os.path.abspath(directory_path)
        if not os.path.exists(abs_parent):
            return f"Error: Directory '{directory_path}' does not exist."

        target_path = os.path.join(abs_parent, file_name)
        print(f"[JARVIS] Creating file: {target_path}")

        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return f"Success: Created file '{file_name}' at '{target_path}'."
    except Exception as e:
        return f"Error creating file: {str(e)}"


def delete_file(file_path: str) -> str:
    """
    Permanently deletes a specific file from the filesystem.

    Args:
        file_path (str): The absolute path to the file to delete.

    Returns:
        str: A status message indicating success or failure.
    """
    try:
        target = os.path.abspath(file_path)
        if not os.path.exists(target):
            return f"Error: File '{file_path}' does not exist."
        if not os.path.isfile(target):
            return f"Error: Target '{file_path}' is not a file."

        print(f"[JARVIS] Deleting file: {target}")
        os.remove(target)
        return f"Success: Deleted file '{os.path.basename(target)}'."
    except Exception as e:
        return f"Error deleting file: {str(e)}"


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [list_files, create_file, delete_file]  # list_files shows both files and folders
