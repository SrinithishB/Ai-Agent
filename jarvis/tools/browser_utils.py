"""
jarvis/tools/browser_utils.py

Shared browser-launching utility for JARVIS tools.

Provides open_url() which tries the configured preferred browser first
(default: Brave), then falls back to the system default browser.

To change the preferred browser, set PREFERRED_BROWSER at module level or
call set_preferred_browser("chrome") / set_preferred_browser("edge") etc.
"""

import os
import subprocess
import shutil
import webbrowser

# ---------------------------------------------------------------------------
# Preferred browser configuration
# ---------------------------------------------------------------------------

# Change this to switch the default browser used by ALL JARVIS tools.
# Supported values: "brave", "chrome", "edge", "firefox", "opera", "system"
PREFERRED_BROWSER = "brave"

# Known browser executable locations (ordered: most common first)
_BROWSER_LOCATIONS: dict[str, list[str]] = {
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(os.environ.get("APPDATA", ""),      r"BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "opera": [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Opera\launcher.exe"),
        r"C:\Program Files\Opera\launcher.exe",
    ],
}

# Cache resolved paths so we don't scan the filesystem on every call
_resolved_cache: dict[str, str | None] = {}


def _find_browser(name: str) -> str | None:
    """
    Find the absolute path of a named browser.
    Returns None if the browser is not installed.
    """
    if name in _resolved_cache:
        return _resolved_cache[name]

    candidates = _BROWSER_LOCATIONS.get(name.lower(), [])
    for path in candidates:
        if path and os.path.isfile(path):
            _resolved_cache[name] = path
            return path

    # Try shutil.which as a final fallback
    exe_name = name.lower().replace(" ", "") + ".exe"
    found = shutil.which(exe_name)
    _resolved_cache[name] = found
    return found


def set_preferred_browser(name: str) -> str:
    """
    Change the preferred browser at runtime.
    Call this from the CLI or a config loader to override the default.

    Args:
        name (str): Browser name — 'brave', 'chrome', 'edge', 'firefox', 'opera', 'system'.

    Returns:
        str: Confirmation message.
    """
    global PREFERRED_BROWSER
    PREFERRED_BROWSER = name.lower().strip()
    return f"Preferred browser set to '{PREFERRED_BROWSER}'."


def open_url(url: str) -> str:
    """
    Opens a URL in the preferred browser (default: Brave).
    Falls back to the system default browser if the preferred one is not found.

    Args:
        url (str): The URL to open.

    Returns:
        str: Name of the browser that was used, or 'system default'.
    """
    browser_name = PREFERRED_BROWSER.lower()

    if browser_name == "system":
        webbrowser.open(url)
        return "system default"

    exe_path = _find_browser(browser_name)
    if exe_path:
        try:
            subprocess.Popen(
                [exe_path, url],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return browser_name.title()
        except Exception:
            pass  # fall through to system default

    # Fallback
    webbrowser.open(url)
    return "system default"


def get_preferred_browser_name() -> str:
    """Returns the display name of the currently preferred browser."""
    return PREFERRED_BROWSER.title()
