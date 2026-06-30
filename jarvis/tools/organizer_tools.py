"""
jarvis/tools/organizer_tools.py

File-organization tools: moving files between directories.
This module is specific to JARVIS's file organizer capability.
"""

import os
import shutil


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def move_file(source_path: str, destination_path: str) -> str:
    """
    Moves a single file from source_path to destination_path.

    Args:
        source_path (str): Absolute path to the file to be moved.
        destination_path (str): Absolute path of the destination file or directory.

    Returns:
        str: A status message indicating success or failure.
    """
    try:
        src = os.path.abspath(source_path)
        dst = os.path.abspath(destination_path)

        if not os.path.exists(src):
            return f"Error: Source file '{source_path}' does not exist."
        if not os.path.isfile(src):
            return f"Error: Source '{source_path}' is not a file. Use move_folder_contents to move all files inside a folder."

        print(f"[JARVIS] Moving: {src} -> {dst}")

        # Create destination directory if it does not yet exist
        dst_dir = dst if os.path.isdir(dst) else os.path.dirname(dst)
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)

        shutil.move(src, dst)
        return f"Success: Moved '{os.path.basename(src)}' to '{dst}'."
    except Exception as e:
        return f"Error moving file: {str(e)}"


def move_folder_contents(source_folder: str, destination_folder: str) -> str:
    """
    Moves ALL files directly inside source_folder into destination_folder.
    This is a batch operation — all files are moved without individual prompts.
    Subdirectories inside source_folder are NOT moved, only files.

    Use this tool when the user says things like:
      - "move all files from X to Y"
      - "move the contents of X into Y"

    Args:
        source_folder (str): Absolute path to the folder whose files should be moved.
        destination_folder (str): Absolute path to the folder to move the files into.

    Returns:
        str: A summary of how many files were moved, or an error message.
    """
    try:
        src_dir = os.path.abspath(source_folder)
        dst_dir = os.path.abspath(destination_folder)

        if not os.path.exists(src_dir):
            return f"Error: Source folder '{source_folder}' does not exist."
        if not os.path.isdir(src_dir):
            return f"Error: '{source_folder}' is not a folder."

        # Gather files only (not subdirectories)
        files = [
            f for f in os.listdir(src_dir)
            if os.path.isfile(os.path.join(src_dir, f))
        ]

        if not files:
            return f"No files found in '{src_dir}'. Nothing to move."

        print(f"[JARVIS] Moving {len(files)} file(s) from '{src_dir}' to '{dst_dir}'")
        os.makedirs(dst_dir, exist_ok=True)

        moved = []
        failed = []
        for f in files:
            try:
                shutil.move(os.path.join(src_dir, f), os.path.join(dst_dir, f))
                moved.append(f)
                print(f"  Moved: {f}")
            except Exception as e:
                failed.append(f"{f} ({e})")

        result = f"Success: Moved {len(moved)} file(s) from '{src_dir}' to '{dst_dir}'."
        if failed:
            result += f" Failed: {', '.join(failed)}."
        return result
    except Exception as e:
        return f"Error moving folder contents: {str(e)}"


def list_files_recursive(directory_path: str) -> list[str]:
    """
    Recursively lists ALL files inside a directory and all its subdirectories.
    Each entry shows the file's path relative to directory_path.

    Use this tool when the user wants to see all files across all subfolders,
    or when you need to know what files exist before performing a batch operation.

    Args:
        directory_path (str): Absolute path to the root directory to scan.

    Returns:
        list[str]: Relative file paths from directory_path, or an error message list.
    """
    try:
        abs_root = os.path.abspath(directory_path)
        if not os.path.exists(abs_root):
            return [f"Error: Directory '{directory_path}' does not exist."]
        if not os.path.isdir(abs_root):
            return [f"Error: '{directory_path}' is not a directory."]

        results = []
        for dirpath, dirnames, filenames in os.walk(abs_root):
            # Sort for consistent output
            dirnames.sort()
            for fname in sorted(filenames):
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, abs_root)
                results.append(rel_path)

        if not results:
            return ["(no files found in directory or any subdirectory)"]
            
        limit = 35
        truncated = results[:limit]
        if len(results) > limit:
            truncated.append(f"... and {len(results) - limit} more files in subdirectories.")
        return truncated
    except Exception as e:
        return [f"Error scanning directory: {str(e)}"]


def organize_by_date(
    directory_path: str,
    group_by: str = "year-month",
) -> str:
    """
    Organizes all files in a directory into subfolders based on their last
    modified timestamp. Only files sitting directly inside directory_path
    are moved — subdirectories are not recursed into.

    Folder naming is controlled by the group_by argument:
      - "year-month"     (default) : creates folders like  2024-01, 2024-06
      - "year"                     : creates folders like  2024, 2025
      - "year-month-day"           : creates folders like  2024-06-29

    Use this tool when the user says things like:
      - "organize files by date"
      - "sort files by timestamp"
      - "group files by month / year"

    Args:
        directory_path (str): Absolute path to the directory to organize.
        group_by (str): Granularity — 'year', 'year-month' (default), or 'year-month-day'.

    Returns:
        str: A summary of how many files were organized, or an error message.
    """
    import datetime

    VALID_GROUPS = {"year", "year-month", "year-month-day"}

    try:
        abs_dir = os.path.abspath(directory_path)
        if not os.path.exists(abs_dir):
            return f"Error: Directory '{directory_path}' does not exist."
        if not os.path.isdir(abs_dir):
            return f"Error: '{directory_path}' is not a directory."
        if group_by not in VALID_GROUPS:
            return f"Error: group_by must be one of {sorted(VALID_GROUPS)}. Got '{group_by}'."

        # Collect only files at the top level (not subdirectories)
        files = [
            f for f in os.listdir(abs_dir)
            if os.path.isfile(os.path.join(abs_dir, f))
        ]

        if not files:
            return f"No files found in '{abs_dir}'. Nothing to organize."

        print(f"[JARVIS] Organizing {len(files)} file(s) in '{abs_dir}' by {group_by}...")

        moved = []
        failed = []

        for fname in files:
            src = os.path.join(abs_dir, fname)
            try:
                mtime = os.path.getmtime(src)
                dt = datetime.datetime.fromtimestamp(mtime)

                if group_by == "year":
                    folder_name = str(dt.year)
                elif group_by == "year-month-day":
                    folder_name = dt.strftime("%Y-%m-%d")
                else:  # year-month (default)
                    folder_name = dt.strftime("%Y-%m")

                dest_dir = os.path.join(abs_dir, folder_name)
                os.makedirs(dest_dir, exist_ok=True)

                shutil.move(src, os.path.join(dest_dir, fname))
                moved.append(f"{fname} -> {folder_name}/")
                print(f"  {fname} -> {folder_name}/")
            except Exception as e:
                failed.append(f"{fname} ({e})")

        result = f"Success: Organized {len(moved)} file(s) into date folders under '{abs_dir}'."
        if failed:
            result += f" Failed: {', '.join(failed)}."
        return result
    except Exception as e:
        return f"Error organizing by date: {str(e)}"


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [move_file, move_folder_contents, list_files_recursive, organize_by_date]
