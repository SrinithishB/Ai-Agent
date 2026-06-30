"""
jarvis/tools/app_tools.py

Application control tools for JARVIS.
Supports launching, closing, focusing, minimizing, and maximizing apps
using Windows-native mechanisms (subprocess, shell, win32gui).

All functions fail gracefully — if an app is not installed the tool
returns a helpful message rather than raising an exception.
"""

import os
import subprocess
import shutil

# ---------------------------------------------------------------------------
# Known application registry
# Maps common names → (executable_or_protocol, launch_args, process_name)
# ---------------------------------------------------------------------------

_APP_MAP: dict[str, dict] = {
    # Browsers
    "chrome":        {"exe": "chrome.exe",           "args": [],           "proc": "chrome.exe"},
    "google chrome": {"exe": "chrome.exe",           "args": [],           "proc": "chrome.exe"},
    "firefox":       {"exe": "firefox.exe",           "args": [],           "proc": "firefox.exe"},
    "edge":          {"exe": "msedge.exe",            "args": [],           "proc": "msedge.exe"},
    "microsoft edge":{"exe": "msedge.exe",            "args": [],           "proc": "msedge.exe"},
    "brave":         {"exe": "brave.exe",             "args": [],           "proc": "brave.exe"},
    "opera":         {"exe": "opera.exe",             "args": [],           "proc": "opera.exe"},

    # Communication
    "discord":       {"exe": "Discord.exe",           "args": [],           "proc": "Discord.exe"},
    "whatsapp":      {"exe": "WhatsApp.exe",          "args": [],           "proc": "WhatsApp.exe"},
    "telegram":      {"exe": "Telegram.exe",          "args": [],           "proc": "Telegram.exe"},
    "slack":         {"exe": "slack.exe",             "args": [],           "proc": "slack.exe"},
    "teams":         {"exe": "Teams.exe",             "args": [],           "proc": "Teams.exe"},
    "microsoft teams":{"exe": "Teams.exe",            "args": [],           "proc": "Teams.exe"},
    "zoom":          {"exe": "Zoom.exe",              "args": [],           "proc": "Zoom.exe"},
    "skype":         {"exe": "Skype.exe",             "args": [],           "proc": "Skype.exe"},

    # Music / Media
    "spotify":       {"exe": "Spotify.exe",           "args": [],           "proc": "Spotify.exe"},
    "vlc":           {"exe": "vlc.exe",               "args": [],           "proc": "vlc.exe"},
    "itunes":        {"exe": "iTunes.exe",            "args": [],           "proc": "iTunes.exe"},
    "foobar":        {"exe": "foobar2000.exe",        "args": [],           "proc": "foobar2000.exe"},
    "foobar2000":    {"exe": "foobar2000.exe",        "args": [],           "proc": "foobar2000.exe"},
    "groove music":  {"shell": "shell:AppsFolder\\Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"},
    "windows media player": {"exe": "wmplayer.exe",  "args": [],           "proc": "wmplayer.exe"},

    # Development
    "vs code":       {"exe": "Code.exe",              "args": [],           "proc": "Code.exe"},
    "vscode":        {"exe": "Code.exe",              "args": [],           "proc": "Code.exe"},
    "visual studio code": {"exe": "Code.exe",         "args": [],          "proc": "Code.exe"},
    "cursor":        {"exe": "Cursor.exe",            "args": [],           "proc": "Cursor.exe"},
    "visual studio": {"exe": "devenv.exe",            "args": [],           "proc": "devenv.exe"},
    "pycharm":       {"exe": "pycharm64.exe",         "args": [],           "proc": "pycharm64.exe"},
    "android studio":{"exe": "studio64.exe",          "args": [],           "proc": "studio64.exe"},
    "notepad++":     {"exe": "notepad++.exe",         "args": [],           "proc": "notepad++.exe"},
    "notepad":       {"exe": "notepad.exe",           "args": [],           "proc": "notepad.exe"},
    "sublime":       {"exe": "sublime_text.exe",      "args": [],           "proc": "sublime_text.exe"},
    "sublime text":  {"exe": "sublime_text.exe",      "args": [],           "proc": "sublime_text.exe"},
    "atom":          {"exe": "atom.exe",              "args": [],           "proc": "atom.exe"},
    "vim":           {"shell": "vim"},
    "neovim":        {"exe": "nvim-qt.exe",           "args": [],           "proc": "nvim.exe"},

    # DevOps / Tools
    "docker":        {"exe": "Docker Desktop.exe",    "args": [],           "proc": "Docker Desktop.exe"},
    "docker desktop":{"exe": "Docker Desktop.exe",    "args": [],           "proc": "Docker Desktop.exe"},
    "postman":       {"exe": "Postman.exe",           "args": [],           "proc": "Postman.exe"},
    "github desktop":{"exe": "GitHubDesktop.exe",     "args": [],           "proc": "GitHubDesktop.exe"},
    "xampp":         {"exe": "xampp-control.exe",     "args": [],           "proc": "xampp-control.exe"},
    "mysql workbench":{"exe": "MySQLWorkbench.exe",   "args": [],           "proc": "MySQLWorkbench.exe"},
    "mongodb compass":{"exe": "MongoDBCompass.exe",   "args": [],           "proc": "MongoDBCompass.exe"},
    "dbeaver":       {"exe": "dbeaver.exe",           "args": [],           "proc": "dbeaver.exe"},

    # Office
    "word":          {"exe": "WINWORD.EXE",           "args": [],           "proc": "WINWORD.EXE"},
    "excel":         {"exe": "EXCEL.EXE",             "args": [],           "proc": "EXCEL.EXE"},
    "powerpoint":    {"exe": "POWERPNT.EXE",          "args": [],           "proc": "POWERPNT.EXE"},
    "outlook":       {"exe": "OUTLOOK.EXE",           "args": [],           "proc": "OUTLOOK.EXE"},
    "onenote":       {"exe": "ONENOTE.EXE",           "args": [],           "proc": "ONENOTE.EXE"},
    "access":        {"exe": "MSACCESS.EXE",          "args": [],           "proc": "MSACCESS.EXE"},

    # System
    "settings":      {"shell": "ms-settings:"},
    "control panel": {"exe": "control.exe",           "args": [],           "proc": "control.exe"},
    "calculator":    {"shell": "calculator:"},
    "camera":        {"shell": "microsoft.windows.camera:"},
    "paint":         {"exe": "mspaint.exe",           "args": [],           "proc": "mspaint.exe"},
    "paint 3d":      {"shell": "ms-paint:"},
    "snipping tool": {"exe": "SnippingTool.exe",      "args": [],           "proc": "SnippingTool.exe"},
    "snip":          {"exe": "SnippingTool.exe",      "args": [],           "proc": "SnippingTool.exe"},
    "task manager":  {"exe": "taskmgr.exe",           "args": [],           "proc": "Taskmgr.exe"},
    "file explorer": {"exe": "explorer.exe",          "args": [],           "proc": "explorer.exe"},
    "explorer":      {"exe": "explorer.exe",          "args": [],           "proc": "explorer.exe"},
    "regedit":       {"exe": "regedit.exe",           "args": [],           "proc": "regedit.exe"},
    "device manager":{"shell": "devmgmt.msc"},
    "disk management":{"shell": "diskmgmt.msc"},

    # Terminals
    "terminal":      {"exe": "wt.exe",                "args": [],           "proc": "WindowsTerminal.exe"},
    "windows terminal":{"exe": "wt.exe",              "args": [],           "proc": "WindowsTerminal.exe"},
    "cmd":           {"exe": "cmd.exe",               "args": [],           "proc": "cmd.exe"},
    "command prompt":{"exe": "cmd.exe",               "args": [],           "proc": "cmd.exe"},
    "powershell":    {"exe": "powershell.exe",        "args": [],           "proc": "powershell.exe"},
    "powershell 7":  {"exe": "pwsh.exe",              "args": [],           "proc": "pwsh.exe"},
    "pwsh":          {"exe": "pwsh.exe",              "args": [],           "proc": "pwsh.exe"},
    "git bash":      {"exe": "git-bash.exe",          "args": [],           "proc": "bash.exe"},

    # System folders (open in Explorer)
    "downloads":     {"explorer": "%USERPROFILE%\\Downloads"},
    "documents":     {"explorer": "%USERPROFILE%\\Documents"},
    "desktop":       {"explorer": "%USERPROFILE%\\Desktop"},
    "pictures":      {"explorer": "%USERPROFILE%\\Pictures"},
    "videos":        {"explorer": "%USERPROFILE%\\Videos"},
    "music":         {"explorer": "%USERPROFILE%\\Music"},
}

# Common install paths to search
_SEARCH_PATHS: list[str] = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    os.path.join(os.environ.get("APPDATA", ""), "Local\\Programs"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft\\WindowsApps"),
]


def _find_exe(exe_name: str) -> str | None:
    """Search PATH and common install directories for an executable."""
    # 1. Check PATH first (fastest)
    found = shutil.which(exe_name)
    if found:
        return found
    # 2. Walk common install dirs
    for base in _SEARCH_PATHS:
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            if exe_name.lower() in [f.lower() for f in files]:
                return os.path.join(root, exe_name)
            # Limit depth to 4 to keep it fast
            depth = root.replace(base, "").count(os.sep)
            if depth >= 4:
                dirs.clear()
    return None


def _launch_shell_target(target: str) -> bool:
    """Launch a ms-xxx: URI, msc file, or shell:AppFolder URI via ShellExecute."""
    try:
        os.startfile(target)
        return True
    except Exception:
        try:
            subprocess.Popen(["cmd", "/c", "start", "", target],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def launch_app(app_name: str) -> str:
    """
    Launches an application by name on Windows. Understands common aliases
    like 'VS Code', 'Chrome', 'Spotify', 'Terminal', 'Settings', 'Calculator'.
    If the app is not in the known registry, it tries to find it in PATH
    and common installation directories.

    Use this for commands like:
      - "Open Spotify"
      - "Launch VS Code"
      - "Start Chrome"
      - "Fire up Discord"
      - "Bring up Calculator"

    Args:
        app_name (str): Natural name of the application to launch.

    Returns:
        str: Success or error message.
    """
    key = app_name.strip().lower()
    entry = _APP_MAP.get(key)

    # --- Known entry ---
    if entry:
        # Open a system folder in Explorer
        if "explorer" in entry:
            folder = os.path.expandvars(entry["explorer"])
            try:
                subprocess.Popen(["explorer", folder],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                return f"Opened {app_name} in File Explorer."
            except Exception as e:
                return f"Error opening folder: {e}"

        # Shell URI / msc target
        if "shell" in entry:
            if _launch_shell_target(entry["shell"]):
                return f"Launched {app_name}."
            return f"Could not launch {app_name} via shell."

        # Regular executable
        exe = entry.get("exe", "")
        args = entry.get("args", [])
        found_path = _find_exe(exe)
        if found_path:
            try:
                subprocess.Popen([found_path] + args,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                return f"Launched {app_name}."
            except Exception as e:
                return f"Found {app_name} but failed to launch: {e}"
        # Fallback: try Windows 'start' command
        try:
            subprocess.Popen(["cmd", "/c", "start", "", exe] + args,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Launched {app_name}."
        except Exception as e:
            return f"Could not find or launch {app_name}. It may not be installed. Error: {e}"

    # --- Unknown app: fuzzy search ---
    # Try the name directly as an exe in PATH
    guessed_exe = key.replace(" ", "") + ".exe"
    found_path = _find_exe(guessed_exe) or _find_exe(app_name.replace(" ", "") + ".exe")
    if found_path:
        try:
            subprocess.Popen([found_path], creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Launched {app_name}."
        except Exception as e:
            return f"Error launching {app_name}: {e}"

    # Last resort: Windows 'start' which searches the registry
    try:
        subprocess.Popen(["cmd", "/c", "start", "", app_name],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return f"Attempted to launch {app_name} via Windows shell."
    except Exception as e:
        return (
            f"Could not find '{app_name}'. Make sure it is installed. "
            f"Tip: Try searching for it by its exact executable name. Error: {e}"
        )


def close_app(app_name: str) -> str:
    """
    Closes / terminates a running application by name.
    Sends a graceful terminate signal first, then force-kills if needed.

    Use this for commands like:
      - "Close Notepad"
      - "Quit Chrome"
      - "Kill Spotify"

    Args:
        app_name (str): Name of the application to close.

    Returns:
        str: Success or error message.
    """
    key = app_name.strip().lower()
    entry = _APP_MAP.get(key, {})
    proc_name = entry.get("proc", "")

    # If not in registry, guess the process name
    if not proc_name:
        proc_name = key.replace(" ", "") + ".exe"

    try:
        # /F = force, /IM = image name
        result = subprocess.run(
            ["taskkill", "/F", "/IM", proc_name],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            return f"Closed {app_name}."
        # Try with the guessed name
        alt_proc = app_name.replace(" ", "") + ".exe"
        result2 = subprocess.run(
            ["taskkill", "/F", "/IM", alt_proc],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result2.returncode == 0:
            return f"Closed {app_name}."
        return f"Could not close {app_name}. It may not be running. ({result.stderr.strip()})"
    except Exception as e:
        return f"Error closing {app_name}: {e}"


def focus_app(app_name: str) -> str:
    """
    Brings a running application window to the foreground / gives it focus.
    Use this for "Switch to Chrome", "Bring up Spotify", etc.

    Args:
        app_name (str): Name of the application window to focus.

    Returns:
        str: Success or error message.
    """
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        name_lower = app_name.strip().lower()

        # EnumWindows callback to find the right window
        found_hwnd = [0]

        def enum_callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower()
            if name_lower in title or title in name_lower:
                found_hwnd[0] = hwnd
                return False  # stop enumeration
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        if found_hwnd[0]:
            hwnd = found_hwnd[0]
            # Restore if minimized
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return f"Switched to {app_name}."
        else:
            return f"No window found for '{app_name}'. It may not be open."
    except Exception as e:
        return f"Error focusing {app_name}: {e}"


def minimize_app(app_name: str) -> str:
    """
    Minimizes the window of a running application.

    Args:
        app_name (str): Name of the application to minimize.

    Returns:
        str: Success or error message.
    """
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        name_lower = app_name.strip().lower()
        found_hwnd = [0]

        def enum_callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if name_lower in buf.value.lower():
                found_hwnd[0] = hwnd
                return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        if found_hwnd[0]:
            user32.ShowWindow(found_hwnd[0], 6)  # SW_MINIMIZE
            return f"Minimized {app_name}."
        return f"No window found for '{app_name}'."
    except Exception as e:
        return f"Error minimizing {app_name}: {e}"


def maximize_app(app_name: str) -> str:
    """
    Maximizes the window of a running application.

    Args:
        app_name (str): Name of the application to maximize.

    Returns:
        str: Success or error message.
    """
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        name_lower = app_name.strip().lower()
        found_hwnd = [0]

        def enum_callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if name_lower in buf.value.lower():
                found_hwnd[0] = hwnd
                return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        if found_hwnd[0]:
            user32.ShowWindow(found_hwnd[0], 3)  # SW_MAXIMIZE
            return f"Maximized {app_name}."
        return f"No window found for '{app_name}'."
    except Exception as e:
        return f"Error maximizing {app_name}: {e}"


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [launch_app, close_app, focus_app, minimize_app, maximize_app]
