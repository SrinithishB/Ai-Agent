"""
jarvis/tools/browser_tools.py

Browser, website, and file-explorer navigation tools for JARVIS.

Tools in this module:
  - open_website(url_or_name)    : open any website or known service by name
  - search_on(engine, query)     : run a search on Google/YouTube/GitHub/etc.
  - browser_tab_action(action)   : new tab, close tab, reopen, prev/next
  - open_folder(folder_name)     : open a system folder in File Explorer

All browser keyboard shortcuts use Windows SendInput so pyautogui is
optional (tab actions fall back gracefully if not available).
"""

import os
import webbrowser
import subprocess
import urllib.parse

from jarvis.tools.browser_utils import open_url


# ---------------------------------------------------------------------------
# Known website / service registry
# ---------------------------------------------------------------------------

_SITE_MAP: dict[str, str] = {
    # Google services
    "gmail":         "https://mail.google.com",
    "google mail":   "https://mail.google.com",
    "google":        "https://www.google.com",
    "google drive":  "https://drive.google.com",
    "google docs":   "https://docs.google.com",
    "google sheets": "https://sheets.google.com",
    "google slides": "https://slides.google.com",
    "google meet":   "https://meet.google.com",
    "google calendar": "https://calendar.google.com",
    "google maps":   "https://maps.google.com",
    "google photos": "https://photos.google.com",
    "google translate": "https://translate.google.com",
    "youtube":       "https://www.youtube.com",
    "youtube music": "https://music.youtube.com",
    "youtube shorts":"https://www.youtube.com/shorts/",

    # Social / Communication
    "twitter":       "https://twitter.com",
    "x":             "https://twitter.com",
    "instagram":     "https://www.instagram.com",
    "facebook":      "https://www.facebook.com",
    "whatsapp web":  "https://web.whatsapp.com",
    "telegram web":  "https://web.telegram.org",
    "reddit":        "https://www.reddit.com",
    "linkedin":      "https://www.linkedin.com",
    "discord":       "https://discord.com/app",
    "tiktok":        "https://www.tiktok.com",
    "snapchat":      "https://www.snapchat.com",
    "pinterest":     "https://www.pinterest.com",
    "tumblr":        "https://www.tumblr.com",

    # Development
    "github":        "https://github.com",
    "gitlab":        "https://gitlab.com",
    "bitbucket":     "https://bitbucket.org",
    "stack overflow":"https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "npm":           "https://www.npmjs.com",
    "pypi":          "https://pypi.org",
    "docker hub":    "https://hub.docker.com",
    "vercel":        "https://vercel.com",
    "netlify":       "https://app.netlify.com",
    "heroku":        "https://dashboard.heroku.com",
    "aws":           "https://aws.amazon.com/console",
    "azure":         "https://portal.azure.com",
    "gcp":           "https://console.cloud.google.com",
    "google cloud":  "https://console.cloud.google.com",
    "firebase":      "https://console.firebase.google.com",
    "supabase":      "https://supabase.com/dashboard",
    "replit":        "https://replit.com",
    "codepen":       "https://codepen.io",
    "codesandbox":   "https://codesandbox.io",
    "leetcode":      "https://leetcode.com",
    "hackerrank":    "https://www.hackerrank.com",
    "codeforces":    "https://codeforces.com",
    "geeksforgeeks": "https://www.geeksforgeeks.org",
    "w3schools":     "https://www.w3schools.com",
    "mdn":           "https://developer.mozilla.org",
    "devdocs":       "https://devdocs.io",
    "wikipedia":     "https://www.wikipedia.org",

    # AI & Tools
    "chatgpt":       "https://chat.openai.com",
    "openai":        "https://openai.com",
    "claude":        "https://claude.ai",
    "gemini":        "https://gemini.google.com",
    "perplexity":    "https://www.perplexity.ai",
    "copilot":       "https://copilot.microsoft.com",
    "midjourney":    "https://www.midjourney.com",
    "huggingface":   "https://huggingface.co",
    "kaggle":        "https://www.kaggle.com",
    "notion":        "https://www.notion.so",
    "obsidian":      "https://obsidian.md",
    "figma":         "https://www.figma.com",
    "canva":         "https://www.canva.com",

    # Shopping
    "amazon":        "https://www.amazon.com",
    "flipkart":      "https://www.flipkart.com",
    "ebay":          "https://www.ebay.com",
    "etsy":          "https://www.etsy.com",
    "aliexpress":    "https://www.aliexpress.com",

    # Entertainment
    "netflix":       "https://www.netflix.com",
    "prime video":   "https://www.primevideo.com",
    "amazon prime":  "https://www.primevideo.com",
    "disney+":       "https://www.disneyplus.com",
    "hotstar":       "https://www.hotstar.com",
    "hulu":          "https://www.hulu.com",
    "spotify":       "https://open.spotify.com",
    "twitch":        "https://www.twitch.tv",

    # News / Finance
    "bbc":           "https://www.bbc.com",
    "cnn":           "https://www.cnn.com",
    "techcrunch":    "https://techcrunch.com",
    "hackernews":    "https://news.ycombinator.com",
    "hacker news":   "https://news.ycombinator.com",
    "yahoo finance": "https://finance.yahoo.com",
    "google finance":"https://finance.google.com",
    "coinmarketcap": "https://coinmarketcap.com",

    # Productivity
    "trello":        "https://trello.com",
    "asana":         "https://app.asana.com",
    "jira":          "https://www.atlassian.com/software/jira",
    "confluence":    "https://www.atlassian.com/software/confluence",
    "monday":        "https://monday.com",
    "airtable":      "https://airtable.com",
    "dropbox":       "https://www.dropbox.com",
    "onedrive":      "https://onedrive.live.com",
    "icloud":        "https://www.icloud.com",
    "zoom":          "https://zoom.us",
    "meet":          "https://meet.google.com",
    "calendar":      "https://calendar.google.com",
    "outlook":       "https://outlook.live.com",
}


# ---------------------------------------------------------------------------
# Search engine URL templates
# ---------------------------------------------------------------------------

_SEARCH_ENGINES: dict[str, str] = {
    "google":          "https://www.google.com/search?q={query}",
    "youtube":         "https://www.youtube.com/results?search_query={query}",
    "github":          "https://github.com/search?q={query}",
    "stack overflow":  "https://stackoverflow.com/search?q={query}",
    "stackoverflow":   "https://stackoverflow.com/search?q={query}",
    "reddit":          "https://www.reddit.com/search/?q={query}",
    "wikipedia":       "https://en.wikipedia.org/w/index.php?search={query}",
    "bing":            "https://www.bing.com/search?q={query}",
    "duckduckgo":      "https://duckduckgo.com/?q={query}",
    "amazon":          "https://www.amazon.com/s?k={query}",
    "npm":             "https://www.npmjs.com/search?q={query}",
    "pypi":            "https://pypi.org/search/?q={query}",
    "twitter":         "https://twitter.com/search?q={query}",
    "x":               "https://twitter.com/search?q={query}",
}


# ---------------------------------------------------------------------------
# System folder registry
# ---------------------------------------------------------------------------

def _resolve_folder(folder_name: str) -> str | None:
    """Resolve a common folder name to its absolute path."""
    home = os.path.expanduser("~")
    base_map = {
        "downloads":  os.path.join(home, "Downloads"),
        "documents":  os.path.join(home, "Documents"),
        "desktop":    os.path.join(home, "Desktop"),
        "pictures":   os.path.join(home, "Pictures"),
        "videos":     os.path.join(home, "Videos"),
        "music":      os.path.join(home, "Music"),
        "onedrive":   os.path.join(home, "OneDrive"),
        "appdata":    os.environ.get("APPDATA", ""),
        "temp":       os.environ.get("TEMP", ""),
        "system":     r"C:\Windows\System32",
        "windows":    r"C:\Windows",
        "program files": r"C:\Program Files",
        "home":       home,
    }
    key = folder_name.strip().lower()
    # Direct match
    if key in base_map:
        return base_map[key]
    # Check OneDrive variants
    for folder in ["Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music"]:
        od_path = os.path.join(home, "OneDrive", folder)
        if key == folder.lower() and os.path.isdir(od_path):
            return od_path
    return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def open_website(url_or_name: str) -> str:
    """
    Opens a website in the default browser. Understands common service names
    like 'Gmail', 'GitHub', 'Netflix', 'Reddit', 'ChatGPT', as well as raw URLs.

    Use for commands like:
      - "Open Gmail"
      - "Go to GitHub"
      - "Visit Stack Overflow"
      - "Take me to Netflix"
      - "Browse Reddit"

    Args:
        url_or_name (str): A website name (e.g. 'Gmail') or a full URL.

    Returns:
        str: Confirmation message.
    """
    name = url_or_name.strip()
    key  = name.lower()

    # Check known site map
    url = _SITE_MAP.get(key)

    # If not in map, check if it's already a URL
    if not url:
        if key.startswith("http://") or key.startswith("https://"):
            url = name
        else:
            # Try adding www. prefix for bare domains like "google.com"
            if "." in name and " " not in name:
                url = f"https://{name}"
            else:
                # Google-search the name as a fallback
                url = f"https://www.google.com/search?q={urllib.parse.quote(name)}"

    try:
        open_url(url)
        return f"Opened {name}."
    except Exception as e:
        return f"Could not open {name}: {e}"


def search_on(engine: str, query: str) -> str:
    """
    Searches for a query on a specific search engine or platform.
    Opens the results page in the default browser.

    Use for commands like:
      - "Search Google for React hooks"
      - "Search YouTube for Python tutorial"
      - "Search GitHub for FastAPI"
      - "Search Reddit for gaming laptop recommendations"
      - "Search Stack Overflow for Python async"
      - "Search Wikipedia for machine learning"

    Args:
        engine (str): Search engine to use: google, youtube, github,
                      stackoverflow, reddit, wikipedia, bing, duckduckgo,
                      amazon, npm, pypi, twitter.
        query (str):  The search query.

    Returns:
        str: Confirmation of what was searched.
    """
    engine_key = engine.strip().lower()
    template   = _SEARCH_ENGINES.get(engine_key)

    if not template:
        # Fuzzy: try partial match
        for k, v in _SEARCH_ENGINES.items():
            if engine_key in k or k in engine_key:
                template = v
                break

    if not template:
        # Fall back to Google
        template = _SEARCH_ENGINES["google"]
        engine_key = "google"

    encoded = urllib.parse.quote(query)
    url = template.format(query=encoded)
    try:
        open_url(url)
        return f"Searching {engine_key.title()} for '{query}'."
    except Exception as e:
        return f"Could not open {engine_key}: {e}"


def browser_tab_action(action: str) -> str:
    """
    Performs browser tab and window management actions using keyboard shortcuts.
    The browser window must be active/focused for shortcuts to work.

    Supported actions:
      - 'new tab'             → Ctrl+T
      - 'close tab'           → Ctrl+W
      - 'reopen tab'          → Ctrl+Shift+T
      - 'next tab'            → Ctrl+Tab
      - 'previous tab'        → Ctrl+Shift+Tab
      - 'duplicate tab'       → Alt+D, Enter (address bar trick)
      - 'new window'          → Ctrl+N
      - 'new incognito'       → Ctrl+Shift+N
      - 'close window'        → Alt+F4
      - 'refresh'             → F5
      - 'hard refresh'        → Ctrl+Shift+R
      - 'zoom in'             → Ctrl++
      - 'zoom out'            → Ctrl+-
      - 'reset zoom'          → Ctrl+0
      - 'back'                → Alt+Left
      - 'forward'             → Alt+Right

    Args:
        action (str): The browser action to perform.

    Returns:
        str: Confirmation of the action.
    """
    try:
        import pyautogui
    except ImportError:
        return (
            "Browser tab actions require pyautogui. "
            "Install with: pip install pyautogui"
        )

    import time
    action = action.lower().strip()

    shortcut_map = {
        "new tab":            ("ctrl", "t"),
        "close tab":          ("ctrl", "w"),
        "reopen tab":         ("ctrl", "shift", "t"),
        "reopen closed tab":  ("ctrl", "shift", "t"),
        "next tab":           ("ctrl", "tab"),
        "previous tab":       ("ctrl", "shift", "tab"),
        "new window":         ("ctrl", "n"),
        "new incognito":      ("ctrl", "shift", "n"),
        "incognito":          ("ctrl", "shift", "n"),
        "private window":     ("ctrl", "shift", "n"),
        "close window":       ("alt", "f4"),
        "refresh":            ("f5",),
        "reload":             ("f5",),
        "hard refresh":       ("ctrl", "shift", "r"),
        "zoom in":            ("ctrl", "+"),
        "zoom out":           ("ctrl", "-"),
        "reset zoom":         ("ctrl", "0"),
        "back":               ("alt", "left"),
        "forward":            ("alt", "right"),
        "focus address bar":  ("ctrl", "l"),
        "open address bar":   ("ctrl", "l"),
        "bookmark":           ("ctrl", "d"),
        "print":              ("ctrl", "p"),
        "save":               ("ctrl", "s"),
        "find":               ("ctrl", "f"),
        "developer tools":    ("f12",),
        "devtools":           ("f12",),
    }

    keys = shortcut_map.get(action)
    if not keys:
        # Partial match
        for k, v in shortcut_map.items():
            if action in k or k in action:
                keys = v
                action = k
                break

    if keys:
        time.sleep(0.1)
        pyautogui.hotkey(*keys)
        return f"Performed browser action: {action}."
    return (
        f"Unknown browser action '{action}'. "
        "Try: new tab, close tab, reopen tab, next tab, previous tab, etc."
    )


def open_folder(folder_name: str) -> str:
    """
    Opens a system folder (Downloads, Documents, Desktop, Pictures, Videos, Music)
    in Windows File Explorer.

    Use for commands like:
      - "Open Downloads"
      - "Open my Documents"
      - "Show Desktop folder"
      - "Open Pictures"

    Also accepts full absolute paths.

    Args:
        folder_name (str): Common folder name or absolute path.

    Returns:
        str: Confirmation message.
    """
    folder_name = folder_name.strip()

    # Check if it's already an absolute path
    if os.path.isabs(folder_name) and os.path.isdir(folder_name):
        path = folder_name
    else:
        path = _resolve_folder(folder_name)
        if not path:
            # Try as a raw path anyway
            expanded = os.path.expandvars(os.path.expanduser(folder_name))
            if os.path.isdir(expanded):
                path = expanded
            else:
                return (
                    f"Could not find folder '{folder_name}'. "
                    "Try: Downloads, Documents, Desktop, Pictures, Videos, Music."
                )

    try:
        subprocess.Popen(["explorer", path],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return f"Opened '{folder_name}' in File Explorer."
    except Exception as e:
        return f"Error opening folder: {e}"


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [open_website, search_on, browser_tab_action, open_folder]
