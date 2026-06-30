"""
jarvis/tools/folder_tools.py

Directory/folder management tools: creating new folders.
Extend this module with rename_folder, delete_folder, etc. in the future.
"""

import os


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def create_folder(directory_path: str, folder_name: str) -> str:
    """
    Creates a new sub-directory inside the given parent directory.
    Safe to call even if the folder already exists (idempotent).

    Args:
        directory_path (str): Absolute path to the parent directory.
        folder_name (str): Name of the new folder to create.

    Returns:
        str: A status message indicating success or failure.
    """
    try:
        abs_parent = os.path.abspath(directory_path)
        if not os.path.exists(abs_parent):
            return f"Error: Parent directory '{directory_path}' does not exist."

        target_path = os.path.join(abs_parent, folder_name)
        os.makedirs(target_path, exist_ok=True)
        return f"Success: Folder '{folder_name}' created or already exists at '{abs_parent}'."
    except Exception as e:
        return f"Error creating folder: {str(e)}"


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [create_folder]
