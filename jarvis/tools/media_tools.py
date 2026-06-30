"""
jarvis/tools/media_tools.py

Music and video playback tools for JARVIS.

Supports Spotify (via URI), YouTube Music, and YouTube (via browser).
Media control keys (play/pause/next/prev) work system-wide using
Windows virtual key codes — no external library required for basic controls.

Optional dependency: pyautogui (for keyboard shortcut fallback)
"""

import subprocess
import urllib.parse
import urllib.request
import re
import json
import webbrowser
import os
import time

from jarvis.tools.browser_utils import open_url


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _send_media_key(vk_code: int) -> bool:
    """
    Send a media key using pyautogui if installed, falling back to
    Windows SendInput API with a 50ms hold delay.
    VK codes: 0xB3=Play/Pause, 0xB0=Next, 0xB1=Prev, 0xB2=Stop
    """
    # Method 1: pyautogui (most reliable system-wide media key dispatcher)
    try:
        import pyautogui
        # Prevent crashes if mouse is in corners
        pyautogui.FAILSAFE = False
        
        vk_map = {
            0xB3: 'playpause',
            0xB0: 'nexttrack',
            0xB1: 'prevtrack',
            0xB2: 'stop'
        }
        if vk_code in vk_map:
            pyautogui.press(vk_map[vk_code])
            return True
    except Exception:
        pass

    # Method 2: ctypes SendInput with hold delay (fallback)
    try:
        import ctypes
        import time

        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk",         ctypes.c_ushort),
                ("wScan",       ctypes.c_ushort),
                ("dwFlags",     ctypes.c_ulong),
                ("time",        ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("_input",)
            _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]

        inp_down = INPUT()
        inp_down.type = 1
        inp_down.ki.wVk = vk_code
        inp_down.ki.dwFlags = KEYEVENTF_EXTENDEDKEY

        inp_up = INPUT()
        inp_up.type = 1
        inp_up.ki.wVk = vk_code
        inp_up.ki.dwFlags = KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP

        # Send Key Down
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
        time.sleep(0.05) # 50ms hold delay
        # Send Key Up
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
        return True
    except Exception:
        return False


def _is_spotify_running() -> bool:
    """Check if Spotify process is currently running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Spotify.exe"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return "Spotify.exe" in result.stdout
    except Exception:
        return False


def _launch_spotify() -> bool:
    """Try to launch Spotify if installed."""
    import shutil
    # Common Spotify locations
    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
        shutil.which("Spotify.exe") or "",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            subprocess.Popen([path], creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(3)
            return True
    # Try Windows shell
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "spotify:"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(3)
        return True
    except Exception:
        return False


def _get_first_youtube_video_id(query: str) -> str | None:
    """
    Fetches the YouTube search results page, parses the ytInitialData JSON blob,
    and returns the first video ID that is NOT a cover/karaoke/instrumental
    (unless the query itself requests those).

    Falls back to a simple regex ID search if JSON parsing fails.
    Returns None if no video is found at all.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"

    query_lower  = query.lower()
    want_cover   = any(w in query_lower for w in ("cover", "karaoke", "lyrics", "instrumental", "remix"))
    skip_words   = ("cover", "karaoke", "instrumental", "tribute", "remake", "version by")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # ── Strategy 1: parse ytInitialData JSON (most reliable) ──────────
        candidates: list[tuple[str, str]] = []
        m = re.search(r'var ytInitialData = (\{.*?\});</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                sections = (
                    data
                    .get("contents", {})
                    .get("twoColumnSearchResultsRenderer", {})
                    .get("primaryContents", {})
                    .get("sectionListRenderer", {})
                    .get("contents", [])
                )
                for section in sections:
                    items = section.get("itemSectionRenderer", {}).get("contents", [])
                    for item in items:
                        vr = item.get("videoRenderer", {})
                        if not vr:
                            continue
                        vid_id = vr.get("videoId", "")
                        title  = (vr.get("title", {}).get("runs") or [{}])[0].get("text", "")
                        if vid_id and title:
                            candidates.append((vid_id, title))
            except Exception:
                pass  # JSON parse failed — fall through to regex

        # ── Strategy 2: regex fallback if JSON gave nothing ───────────────
        if not candidates:
            ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
            seen: set[str] = set()
            for vid_id in ids:
                if vid_id not in seen:
                    seen.add(vid_id)
                    candidates.append((vid_id, ""))  # no title info

        # ── Pick best result ──────────────────────────────────────────────
        fallback_id: str | None = None
        for vid_id, title in candidates:
            if not fallback_id:
                fallback_id = vid_id
            title_lower = title.lower()
            is_unwanted = title and any(w in title_lower for w in skip_words)
            if want_cover or not is_unwanted:
                return vid_id

        return fallback_id  # all were unwanted, return first anyway

    except Exception:
        pass
    return None



# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def play_music(query: str, platform: str = "auto") -> str:
    """
    Plays music — a song, artist, album, or playlist — on the specified platform.
    Platform priority when set to 'auto': Spotify → YouTube Music → YouTube.

    Supports natural queries like:
      - "play Believer by Imagine Dragons"
      - "play Taylor Swift"
      - "play my chill playlist"

    Args:
        query (str): Song name, artist, album, or playlist to play.
        platform (str): 'spotify', 'youtube', 'youtube_music', 'apple_music', or 'auto'.

    Returns:
        str: Status message describing what was launched.
    """
    platform = platform.lower().strip()

    # Cross-delegation fallback: if user requested a video platform, redirect to play_video
    if platform in ("netflix", "prime", "prime video", "amazon prime", "disney", "disney+", "hotstar"):
        return play_video(query, platform=platform)

    # --- Spotify ---
    if platform in ("spotify", "auto"):
        # Build Spotify search URI
        spotify_uri = f"spotify:search:{urllib.parse.quote(query)}"
        # Try to open via URI (works if Spotify is installed)
        try:
            if not _is_spotify_running():
                _launch_spotify()
            # Open search via URI protocol
            subprocess.Popen(["cmd", "/c", "start", "", spotify_uri],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Playing '{query}' on Spotify."
        except Exception:
            if platform == "spotify":
                return f"Spotify is not installed. Try 'play {query} on YouTube'."
            # Fall through to YouTube Music

    # --- YouTube Music ---
    if platform in ("youtube_music", "youtube music", "ytmusic", "auto"):
        search_url = f"https://music.youtube.com/search?q={urllib.parse.quote(query)}"
        try:
            open_url(search_url)
            return f"Searching '{query}' on YouTube Music."
        except Exception as e:
            if platform not in ("auto",):
                return f"Could not open YouTube Music: {e}"

    # --- YouTube ---
    if platform in ("youtube", "yt", "auto"):
        video_id = _get_first_youtube_video_id(query)
        if video_id:
            watch_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
            open_url(watch_url)
            return f"Playing '{query}' on YouTube."
        else:
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            open_url(search_url)
            return f"Opened YouTube search for '{query}'."

    # --- Apple Music ---
    if platform in ("apple_music", "apple music"):
        search_url = f"https://music.apple.com/search?term={urllib.parse.quote(query)}"
        open_url(search_url)
        return f"Searching '{query}' on Apple Music."

    return f"Unknown platform '{platform}'. Use: spotify, youtube, youtube_music, or auto."


def _control_window_media(action: str) -> bool:
    """
    Search for active windows (YouTube in browser, Spotify app) and send direct
    shortcuts to them by bringing them to focus. Returns True if handled.
    """
    try:
        import pygetwindow as gw
        import pyautogui
        import time

        pyautogui.FAILSAFE = False
        action = action.lower().strip()

        # 1. Search for YouTube playing in browser (Brave, Chrome, Edge, etc.)
        yt_windows = [w for w in gw.getAllWindows() if w.title and "youtube" in w.title.lower()]
        if yt_windows:
            w = yt_windows[0]
            try:
                # If window is minimized, restore it
                if w.isMinimized:
                    w.restore()
                w.activate()
                time.sleep(0.2)
                if action in ("play", "pause", "resume", "play/pause", "toggle"):
                    pyautogui.press("k") # YouTube specific play/pause key
                    return True
                elif action in ("next", "next track", "skip"):
                    pyautogui.hotkey("shift", "n") # YouTube next video key
                    return True
                elif action in ("previous", "prev", "back", "previous track", "last"):
                    pyautogui.hotkey("shift", "p") # YouTube previous video key
                    return True
            except Exception:
                pass

        # 2. Search for Spotify desktop application
        spotify_windows = [w for w in gw.getAllWindows() if w.title and "spotify" in w.title.lower()]
        if spotify_windows:
            w = spotify_windows[0]
            try:
                if w.isMinimized:
                    w.restore()
                w.activate()
                time.sleep(0.2)
                if action in ("play", "pause", "resume", "play/pause", "toggle"):
                    pyautogui.press("space")
                    return True
                elif action in ("next", "next track", "skip"):
                    pyautogui.hotkey("ctrl", "right")
                    return True
                elif action in ("previous", "prev", "back", "previous track", "last"):
                    pyautogui.hotkey("ctrl", "left")
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def control_music(action: str) -> str:
    """
    Controls music playback system-wide using media keys or window-specific shortcuts.
    Works with Spotify, Windows Media Player, YouTube in browser, or any media app.

    Supported actions:
      - 'play' or 'resume'  → Play/Pause toggle
      - 'pause'             → Play/Pause toggle
      - 'next'              → Next track
      - 'previous' or 'prev'→ Previous track
      - 'stop'              → Stop playback

    Args:
        action (str): The playback control action.

    Returns:
        str: Confirmation of the action performed.
    """
    action = action.lower().strip()

    # Try focusing YouTube/Spotify windows first and sending direct shortcuts
    if _control_window_media(action):
        if action in ("play", "resume", "pause", "play/pause", "toggle"):
            return "Toggled play/pause in active player."
        elif action in ("next", "next track", "skip"):
            return "Skipped to next track in active player."
        elif action in ("previous", "prev", "back", "previous track", "last"):
            return "Went back to previous track in active player."

    # VK codes for media keys
    VK_MEDIA_PLAY_PAUSE = 0xB3
    VK_MEDIA_NEXT_TRACK = 0xB0
    VK_MEDIA_PREV_TRACK = 0xB1
    VK_MEDIA_STOP       = 0xB2

    if action in ("play", "resume", "pause", "play/pause", "toggle"):
        if _send_media_key(VK_MEDIA_PLAY_PAUSE):
            return "Toggled play/pause."
        return "Could not send media key."

    elif action in ("next", "next track", "skip"):
        if _send_media_key(VK_MEDIA_NEXT_TRACK):
            return "Skipped to next track."
        return "Could not send next-track key."

    elif action in ("previous", "prev", "back", "previous track", "last"):
        if _send_media_key(VK_MEDIA_PREV_TRACK):
            return "Went back to previous track."
        return "Could not send previous-track key."

    elif action in ("stop",):
        if _send_media_key(VK_MEDIA_STOP):
            return "Stopped playback."
        return "Could not send stop key."

    elif action in ("shuffle",):
        # Spotify shuffle shortcut: Ctrl+Shift+S (when Spotify focused)
        try:
            import ctypes
            # Focus Spotify window first by looking for it
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "Spotify")
            if hwnd:
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.2)
            import pyautogui
            pyautogui.hotkey("ctrl", "shift", "s")
            return "Toggled shuffle on Spotify."
        except ImportError:
            return "Shuffle requires pyautogui. Install with: pip install pyautogui"
        except Exception as e:
            return f"Could not toggle shuffle: {e}"

    elif action in ("repeat",):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "Spotify")
            if hwnd:
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.2)
            import pyautogui
            pyautogui.hotkey("ctrl", "shift", "r")
            return "Toggled repeat on Spotify."
        except ImportError:
            return "Repeat requires pyautogui. Install with: pip install pyautogui"
        except Exception as e:
            return f"Could not toggle repeat: {e}"

    return (
        f"Unknown action '{action}'. "
        "Use: play, pause, resume, next, previous, stop, shuffle, or repeat."
    )


def play_video(query: str, platform: str = "youtube") -> str:
    """
    Searches for and opens a video on YouTube or another video platform.
    Opens the first search result page in the default browser.

    Supported commands like:
      - "play Python tutorial on YouTube"
      - "search YouTube for cooking recipes"
      - "open YouTube Shorts"
      - "play latest Avengers trailer"

    Args:
        query (str): The video title, topic, or search terms.
        platform (str): 'youtube' (default), 'netflix', 'prime', 'disney'.

    Returns:
        str: Status message.
    """
    platform = platform.lower().strip()

    # Cross-delegation fallback: if user requested a music platform, redirect to play_music
    if platform in ("spotify", "youtube_music", "youtube music", "ytmusic", "apple_music", "apple music"):
        return play_music(query, platform=platform)

    if platform in ("youtube", "yt") or platform == "":
        # Special cases
        if "shorts" in query.lower():
            open_url("https://www.youtube.com/shorts/")
            return "Opened YouTube Shorts."

        # Try to find and open the first result directly (actually plays the video)
        video_id = _get_first_youtube_video_id(query)
        if video_id:
            watch_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
            open_url(watch_url)
            return f"Playing '{query}' on YouTube."
        else:
            # Fallback: open search results if we couldn't get the video ID
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            open_url(search_url)
            return f"Opened YouTube search for '{query}'."

    elif platform in ("netflix",):
        search_url = f"https://www.netflix.com/search?q={urllib.parse.quote(query)}"
        open_url(search_url)
        return f"Searching Netflix for '{query}'."

    elif platform in ("prime", "amazon prime", "prime video"):
        search_url = f"https://www.amazon.com/s?k={urllib.parse.quote(query)}&i=instant-video"
        open_url(search_url)
        return f"Searching Prime Video for '{query}'."

    elif platform in ("disney", "disney+", "hotstar"):
        open_url(f"https://www.disneyplus.com/search?q={urllib.parse.quote(query)}")
        return f"Searching Disney+ for '{query}'."

    else:
        # Unknown platform — default to YouTube with direct play
        video_id = _get_first_youtube_video_id(query)
        if video_id:
            open_url(f"https://www.youtube.com/watch?v={video_id}&autoplay=1")
            return f"Playing '{query}' on YouTube."
        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        open_url(search_url)
        return f"Opened YouTube search for '{query}'."


def control_video(action: str) -> str:
    """
    Controls video playback in the browser using keyboard shortcuts.
    The browser window must be in focus for this to work.

    Supported actions:
      - 'pause' / 'play'   → Space bar
      - 'mute'             → M key
      - 'fullscreen'       → F key
      - 'exit fullscreen'  → Escape
      - 'forward'          → Right arrow (5 sec)
      - 'backward'         → Left arrow (5 sec)
      - 'volume up'        → Up arrow
      - 'volume down'      → Down arrow

    Args:
        action (str): The video control action to perform.

    Returns:
        str: Status message.
    """
    try:
        import pyautogui
    except ImportError:
        return (
            "Video controls require pyautogui. "
            "Install it with: pip install pyautogui"
        )

    action = action.lower().strip()
    time.sleep(0.1)

    mapping = {
        "pause":          "space",
        "play":           "space",
        "toggle":         "space",
        "mute":           "m",
        "unmute":         "m",
        "fullscreen":     "f",
        "full screen":    "f",
        "exit fullscreen":"escape",
        "exit full screen":"escape",
        "forward":        "right",
        "seek forward":   "right",
        "backward":       "left",
        "seek backward":  "left",
        "volume up":      "up",
        "volume down":    "down",
    }

    key = mapping.get(action)
    if key:
        pyautogui.press(key)
        return f"Sent '{key}' key for '{action}'."

    return (
        f"Unknown video action '{action}'. "
        "Use: pause, play, mute, fullscreen, exit fullscreen, forward, backward."
    )


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [play_music, control_music, play_video, control_video]
