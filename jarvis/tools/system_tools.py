"""
jarvis/tools/system_tools.py

System-level tools for JARVIS:
  - Volume control (using pycaw or media keys)
  - Window management (snap, center, minimize, maximize via Windows API)
  - Screenshot capture (full, region, window)
  - Clipboard operations (read, write, clear)
  - Expression / unit conversion calculator

All tools degrade gracefully when optional libraries are not installed.
"""

import os
import subprocess
import math
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Volume control
# ---------------------------------------------------------------------------

def _is_android() -> bool:
    return os.path.exists("/system/bin/app_process") or "ANDROID_ROOT" in os.environ


def set_volume(level: int) -> str:
    """
    Sets the system master volume to a specific percentage (0–100).
    On Windows, uses the Windows Core Audio API (pycaw).
    On Android, uses termux-volume.

    Args:
        level (int): Target volume level, 0 (mute) to 100 (max).

    Returns:
        str: Confirmation or error message.
    """
    try:
        level = max(0, min(100, int(level)))
    except (ValueError, TypeError):
        return f"Invalid volume level '{level}'. Use a number from 0 to 100."

    if _is_android():
        try:
            import json
            # Get max volume step for music stream (typically 15)
            vol_info = subprocess.run(["termux-volume"], capture_output=True, text=True, timeout=3)
            streams = json.loads(vol_info.stdout)
            max_vol = 15
            for s in streams:
                if s.get("stream") == "music":
                    max_vol = s.get("max_volume", 15)
                    break
        except Exception:
            max_vol = 15
        
        target = int(level * max_vol / 100)
        try:
            subprocess.run(["termux-volume", "music", str(target)], timeout=3)
            return f"Phone music volume set to {level}% (level {target}/{max_vol})."
        except FileNotFoundError:
            return "Could not set volume. Make sure 'termux-api' package is installed in Termux."

    # Windows Implementation
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        if hasattr(devices, 'EndpointVolume'):
            volume_ctrl = devices.EndpointVolume
        else:
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume_ctrl = cast(interface, POINTER(IAudioEndpointVolume))
        scalar = level / 100.0
        volume_ctrl.SetMasterVolumeLevelScalar(scalar, None)
        return f"Volume set to {level}%."
    except ImportError:
        pass
    except Exception:
        pass

    try:
        ps_code = f"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Audio {{
    [DllImport("winmm.dll")] public static extern int waveOutSetVolume(IntPtr h, uint v);
}}
'@
$vol = {level} * 65535 / 100
$vol = [uint32]$vol
$combined = ($vol -shl 16) -bor $vol
[Audio]::waveOutSetVolume([IntPtr]::Zero, $combined)
"""
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_code],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            return f"Volume set to {level}%."
    except Exception:
        pass

    try:
        nircmd_val = int(level * 65535 / 100)
        result = subprocess.run(
            ["nircmd", "setsysvolume", str(nircmd_val)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            return f"Volume set to {level}%."
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return f"Could not set volume to {level}%."


def adjust_volume(direction: str) -> str:
    """
    Increases, decreases, mutes, or unmutes the system volume.
    On Windows, uses media keys or pycaw.
    On Android, uses termux-volume.

    Args:
        direction (str): 'up'/'increase' or 'down'/'decrease' or 'mute'/'unmute'.

    Returns:
        str: Confirmation of the action.
    """
    direction = direction.lower().strip()

    if _is_android():
        if direction in ("mute", "silent", "silence"):
            try:
                subprocess.run(["termux-volume", "music", "0"], timeout=3)
                return "Muted phone media."
            except Exception:
                return "Could not mute phone. Ensure termux-api is installed."
        
        try:
            import json
            vol_info = subprocess.run(["termux-volume"], capture_output=True, text=True, timeout=3)
            streams = json.loads(vol_info.stdout)
            curr_vol = 7
            max_vol = 15
            for s in streams:
                if s.get("stream") == "music":
                    curr_vol = s.get("volume", 7)
                    max_vol = s.get("max_volume", 15)
                    break
        except Exception:
            curr_vol = 7
            max_vol = 15
            
        if direction in ("up", "increase", "raise", "louder", "volume up", "turn up"):
            target = min(max_vol, curr_vol + 2)
        elif direction in ("down", "decrease", "lower", "quieter", "volume down", "turn down"):
            target = max(0, curr_vol - 2)
        elif direction in ("unmute", "restore sound"):
            target = max(3, curr_vol) # restore to at least 3
        else:
            return f"Unknown direction '{direction}'."
            
        try:
            subprocess.run(["termux-volume", "music", str(target)], timeout=3)
            return f"Phone music volume adjusted to {int(target * 100 / max_vol)}% (level {target}/{max_vol})."
        except Exception:
            return "Failed to adjust phone volume. Ensure termux-api is installed."

    # Windows Implementation
    import ctypes
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        if hasattr(devices, 'EndpointVolume'):
            volume_ctrl = devices.EndpointVolume
        else:
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume_ctrl = ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))

        if direction in ("mute", "silent", "silence"):
            volume_ctrl.SetMute(1, None)
            return "Muted."
        elif direction in ("unmute", "restore sound"):
            volume_ctrl.SetMute(0, None)
            return "Unmuted."
        elif direction in ("up", "increase", "raise", "louder", "volume up", "turn up"):
            current_vol = volume_ctrl.GetMasterVolumeLevelScalar()
            new_vol = min(1.0, current_vol + 0.06)
            volume_ctrl.SetMasterVolumeLevelScalar(new_vol, None)
            if volume_ctrl.GetMute():
                volume_ctrl.SetMute(0, None)
            return f"Volume increased to {int(new_vol * 100)}%."
        elif direction in ("down", "decrease", "lower", "quieter", "volume down", "turn down"):
            current_vol = volume_ctrl.GetMasterVolumeLevelScalar()
            new_vol = max(0.0, current_vol - 0.06)
            volume_ctrl.SetMasterVolumeLevelScalar(new_vol, None)
            return f"Volume decreased to {int(new_vol * 100)}%."
    except Exception:
        pass

    VK_VOLUME_UP   = 0xAF
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_MUTE = 0xAD

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

    def press_vk(vk):
        inp_down = INPUT()
        inp_down.type = 1
        inp_down.ki.wVk = vk
        inp_down.ki.dwFlags = KEYEVENTF_EXTENDEDKEY
        inp_up = INPUT()
        inp_up.type = 1
        inp_up.ki.wVk = vk
        inp_up.ki.dwFlags = KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP
        arr = (INPUT * 2)(inp_down, inp_up)
        ctypes.windll.user32.SendInput(2, arr, ctypes.sizeof(INPUT))

    if direction in ("up", "increase", "raise", "louder", "volume up", "turn up"):
        for _ in range(3):
            press_vk(VK_VOLUME_UP)
        return "Volume increased."
    elif direction in ("down", "decrease", "lower", "quieter", "volume down", "turn down"):
        for _ in range(3):
            press_vk(VK_VOLUME_DOWN)
        return "Volume decreased."
    elif direction in ("mute", "silent", "silence"):
        press_vk(VK_VOLUME_MUTE)
        return "Muted."
    elif direction in ("unmute", "restore sound"):
        press_vk(VK_VOLUME_MUTE)
        return "Unmuted."

    return f"Unknown direction '{direction}'."


# ---------------------------------------------------------------------------
# Window management
# ---------------------------------------------------------------------------

def window_action(action: str) -> str:
    """
    Performs window management operations on the currently focused window
    or switches between windows. Uses Windows keyboard shortcuts.

    Supported actions:
      - 'snap left'      → Win+Left
      - 'snap right'     → Win+Right
      - 'snap top'       → Win+Up (maximize)
      - 'snap bottom'    → Win+Down
      - 'maximize'       → Win+Up
      - 'minimize'       → Win+Down then Down
      - 'restore'        → Win+Down
      - 'switch'         → Alt+Tab
      - 'close'          → Alt+F4
      - 'switch window'  → Alt+Tab

    Args:
        action (str): The window action to perform.

    Returns:
        str: Confirmation message.
    """
    try:
        import pyautogui
    except ImportError:
        return (
            "Window actions require pyautogui. "
            "Install with: pip install pyautogui"
        )

    import time
    action = action.lower().strip()
    time.sleep(0.1)

    action_map = {
        "snap left":        ("win", "left"),
        "move left":        ("win", "left"),
        "snap right":       ("win", "right"),
        "move right":       ("win", "right"),
        "snap top":         ("win", "up"),
        "snap up":          ("win", "up"),
        "maximize":         ("win", "up"),
        "fullscreen":       ("win", "up"),
        "snap bottom":      ("win", "down"),
        "minimize":         ("win", "down"),
        "restore":          ("win", "down"),
        "switch":           ("alt", "tab"),
        "switch window":    ("alt", "tab"),
        "switch windows":   ("alt", "tab"),
        "alt tab":          ("alt", "tab"),
        "close":            ("alt", "f4"),
        "close window":     ("alt", "f4"),
        "show desktop":     ("win", "d"),
        "desktop":          ("win", "d"),
        "task view":        ("win", "tab"),
        "center":           None,   # special
    }

    if action == "center":
        # Move window to center using Win+Left then Win+Right won't center perfectly,
        # so use PowerShell as fallback
        try:
            ps = """
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
$hwnd = [Win]::GetForegroundWindow()
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$w = 900; $h = 600
$x = ($screen.Width - $w) / 2
$y = ($screen.Height - $h) / 2
[Win]::SetWindowPos($hwnd, [IntPtr]::Zero, $x, $y, $w, $h, 0x0040)
"""
            subprocess.run(["powershell", "-Command", ps],
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
        return "Attempted to center window."

    keys = action_map.get(action)
    if not keys:
        # Partial match
        for k, v in action_map.items():
            if action in k or k in action:
                keys = v
                action = k
                break

    if keys:
        pyautogui.hotkey(*keys)
        return f"Window action '{action}' performed."

    return (
        f"Unknown window action '{action}'. "
        "Try: snap left, snap right, maximize, minimize, restore, switch, close, show desktop."
    )


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

def take_screenshot(mode: str = "full", save_dir: str = "") -> str:
    """
    Takes a screenshot. On Windows, saves it to Desktop. On Android/Termux,
    attempts to capture screenshot using screencap (requires root).

    Args:
        mode (str): Screenshot mode — 'full', 'window', or 'region'.
        save_dir (str): Optional folder name or path.

    Returns:
        str: Path to the saved screenshot, or error message.
    """
    import datetime
    from pathlib import Path

    mode = mode.lower().strip()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp}.png"

    if _is_android():
        # Try root screencap first
        save_path = f"/sdcard/Pictures/{filename}"
        res = subprocess.run(["su", "-c", f"/system/bin/screencap -p {save_path}"], capture_output=True)
        if res.returncode == 0:
            return f"Screenshot saved to phone gallery: {save_path} (requires root)"
        
        # Try local screencap
        local_path = f"/data/data/com.termux/files/home/{filename}"
        res2 = subprocess.run(["/system/bin/screencap", "-p", local_path], capture_output=True)
        if res2.returncode == 0:
            return f"Screenshot saved to Termux home: {local_path}"
            
        return "Taking screenshot on Android requires root permission. Try physical buttons (Volume Down + Power)."

    # Windows Implementation
    home = Path.home()
    desktop = home / "OneDrive" / "Desktop"
    if not desktop.is_dir():
        desktop = home / "Desktop"

    target_dir = desktop
    if save_dir:
        from jarvis.tools.browser_tools import _resolve_folder
        resolved = _resolve_folder(save_dir)
        if resolved and os.path.isdir(resolved):
            target_dir = Path(resolved)
        elif os.path.isdir(save_dir):
            target_dir = Path(save_dir)

    save_path = target_dir / filename

    if mode == "region":
        try:
            subprocess.Popen(["SnippingTool.exe"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return "Snipping Tool opened. Select your region."
        except Exception:
            try:
                subprocess.Popen(["explorer", "ms-screenclip:"],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                return "Screen Clip opened. Select your region."
            except Exception:
                pass
        try:
            import pyautogui
            import time
            pyautogui.hotkey("win", "shift", "s")
            return "Region screenshot shortcut (Win+Shift+S) sent."
        except ImportError:
            pass
        return "Could not open region capture. Press Win+Shift+S manually."

    if mode in ("full", "window"):
        try:
            from PIL import ImageGrab
            import time

            if mode == "window":
                import ctypes
                VK_SNAPSHOT = 0x2C
                VK_MENU = 0x12
                ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_SNAPSHOT, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_SNAPSHOT, 0, 2, 0)
                ctypes.windll.user32.keybd_event(VK_MENU, 0, 2, 0)
                time.sleep(0.3)
                img = ImageGrab.grabclipboard()
                if img is None:
                    img = ImageGrab.grab()
            else:
                img = ImageGrab.grab()

            img.save(str(save_path))
            return f"Screenshot saved to: {save_path}"

        except ImportError:
            pass
        except Exception as e:
            pass

        try:
            ps = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bmp.Save('{str(save_path).replace(chr(92), chr(92)+chr(92))}')
"""
            result = subprocess.run(
                ["powershell", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode == 0 and save_path.exists():
                return f"Screenshot saved to: {save_path}"
            return f"Screenshot failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Screenshot error: {e}"

    return f"Unknown screenshot mode '{mode}'."


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def clipboard_action(action: str, text: str = "") -> str:
    """
    Performs clipboard operations: read, write (copy), clear.
    On Windows, uses pyperclip or win32clipboard.
    On Android, uses termux-clipboard-get/set.

    Args:
        action (str): The clipboard action to perform.
        text (str):   Text to copy (only used when action='copy').

    Returns:
        str: Clipboard content (for 'read'), or confirmation message.
    """
    action = action.lower().strip()

    if _is_android():
        if action in ("read", "get", "paste content", "show"):
            try:
                res = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True, timeout=3)
                content = res.stdout.strip()
                return f"Clipboard contents:\n{content}" if content else "Clipboard is empty."
            except Exception as e:
                return "Failed to read phone clipboard. Ensure termux-api is installed."
        elif action in ("copy", "write", "set"):
            if not text:
                return "No text provided to copy."
            try:
                subprocess.run(["termux-clipboard-set", text], timeout=3)
                return f"Copied to phone clipboard: '{text[:80]}...'"
            except Exception as e:
                return "Failed to write to phone clipboard. Ensure termux-api is installed."
        elif action in ("clear", "empty"):
            try:
                subprocess.run(["termux-clipboard-set", ""], timeout=3)
                return "Clipboard cleared."
            except Exception as e:
                return "Failed to clear phone clipboard."
        elif action in ("paste",):
            return "Paste keyboard event is not supported on Android."

    # Windows Implementation
    try:
        import pyperclip

        if action in ("read", "get", "paste content", "show"):
            content = pyperclip.paste()
            if content:
                return f"Clipboard contents:\n{content[:2000]}"
            return "Clipboard is empty."

        elif action in ("copy", "write", "set"):
            if not text:
                return "No text provided to copy."
            pyperclip.copy(text)
            return f"Copied to clipboard: '{text[:80]}{'...' if len(text) > 80 else ''}'"

        elif action in ("clear", "empty"):
            pyperclip.copy("")
            return "Clipboard cleared."

    except ImportError:
        pass

    try:
        import win32clipboard
        import win32con

        if action in ("read", "get", "show"):
            win32clipboard.OpenClipboard()
            try:
                content = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return f"Clipboard contents:\n{content[:2000]}"
            except TypeError:
                return "Clipboard is empty or contains non-text data."
            finally:
                win32clipboard.CloseClipboard()

        elif action in ("copy", "write", "set"):
            if not text:
                return "No text provided to copy."
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return f"Copied to clipboard: '{text[:80]}'"

        elif action in ("clear", "empty"):
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.CloseClipboard()
            return "Clipboard cleared."

    except ImportError:
        pass

    try:
        if action in ("read", "get", "show"):
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            content = result.stdout.strip()
            return f"Clipboard contents:\n{content}" if content else "Clipboard is empty."

        elif action in ("copy", "write", "set"):
            if not text:
                return "No text provided to copy."
            escaped = text.replace("'", "''")
            subprocess.run(
                ["powershell", "-Command", f"Set-Clipboard -Value '{escaped}'"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return f"Copied to clipboard: '{text[:80]}'"

        elif action in ("clear", "empty"):
            subprocess.run(
                ["powershell", "-Command", "Set-Clipboard -Value ''"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return "Clipboard cleared."
    except Exception as e:
        return f"Clipboard error: {e}"

    if action in ("paste",):
        try:
            import pyautogui
            import time
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "v")
            return "Pasted from clipboard."
        except ImportError:
            return "Paste requires pyautogui: pip install pyautogui"

    return f"Unknown clipboard action '{action}'."


# ---------------------------------------------------------------------------
# Calculator / Expression Evaluator
# ---------------------------------------------------------------------------

# Safe built-ins for expression evaluation
_SAFE_GLOBALS = {
    "__builtins__": {},
    "abs": abs, "round": round, "min": min, "max": max, "pow": pow,
    "sum": sum, "int": int, "float": float,
    # math module constants and functions
    "sqrt": math.sqrt, "ceil": math.ceil, "floor": math.floor,
    "log": math.log, "log2": math.log2, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "degrees": math.degrees, "radians": math.radians,
    "pi": math.pi, "e": math.e, "inf": math.inf,
    "factorial": math.factorial,
    "gcd": math.gcd,
}

# Unit conversion table: (from, to) → multiplier
_UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    # Length
    ("km",   "miles"):  0.621371,
    ("miles","km"):     1.60934,
    ("km",   "m"):      1000,
    ("m",    "km"):     0.001,
    ("m",    "ft"):     3.28084,
    ("ft",   "m"):      0.3048,
    ("cm",   "in"):     0.393701,
    ("in",   "cm"):     2.54,
    ("yards","m"):      0.9144,
    ("m",    "yards"):  1.09361,
    # Weight
    ("kg",   "lbs"):    2.20462,
    ("lbs",  "kg"):     0.453592,
    ("g",    "oz"):     0.035274,
    ("oz",   "g"):      28.3495,
    # Temperature handled separately
    # Volume
    ("liters","gallons"):  0.264172,
    ("gallons","liters"):  3.78541,
    ("ml",    "oz"):       0.033814,
    ("oz",    "ml"):       29.5735,
    # Area
    ("sqm",   "sqft"):     10.7639,
    ("sqft",  "sqm"):      0.092903,
    ("acres",  "hectares"): 0.404686,
    ("hectares","acres"):   2.47105,
    # Speed
    ("kmh",   "mph"):   0.621371,
    ("mph",   "kmh"):   1.60934,
    ("mps",   "mph"):   2.23694,
    # Data
    ("gb",    "mb"):    1024,
    ("mb",    "gb"):    0.000976563,
    ("tb",    "gb"):    1024,
    ("gb",    "tb"):    0.000976563,
}

# Currency rates (approximate, static — for live rates the model should use search_web)
_CURRENCY_RATES: dict[str, float] = {
    "usd": 1.0,
    "inr": 83.5,
    "eur": 0.92,
    "gbp": 0.79,
    "jpy": 156.0,
    "cad": 1.37,
    "aud": 1.53,
    "sgd": 1.35,
    "aed": 3.67,
    "chf": 0.90,
    "cny": 7.24,
    "krw": 1340.0,
    "brl": 5.05,
    "mxn": 17.2,
    "rub": 90.5,
}


def evaluate_expression(expression: str) -> str:
    """
    Evaluates a mathematical expression or performs unit/currency conversions.
    Does NOT require internet — all calculations are local.

    Supports:
      - Arithmetic:       25 * 45,  (100 + 50) / 3,  2 ** 10
      - Math functions:   sqrt(144),  log(1000),  sin(pi/2),  factorial(5)
      - Constants:        pi,  e
      - Unit conversion:  20 km in miles,  100 lbs in kg,  5 ft in m
      - Currency:         100 USD in INR,  50 EUR in GBP  (approximate rates)

    Args:
        expression (str): A math expression or unit/currency conversion query.

    Returns:
        str: The computed result as a string.
    """
    expr = expression.strip()

    # --- Unit / currency conversion pattern: "X unit1 in unit2" ---
    conv_pattern = re.match(
        r"^([\d,\.]+)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s+(?:in|to|as)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)$",
        expr, re.IGNORECASE
    )
    if conv_pattern:
        raw_val, from_unit, to_unit = conv_pattern.groups()
        try:
            value = float(raw_val.replace(",", ""))
        except ValueError:
            return f"Invalid number '{raw_val}'."

        fu = from_unit.lower().strip()
        tu = to_unit.lower().strip()

        # Temperature conversion (special case)
        if fu in ("c", "celsius") and tu in ("f", "fahrenheit"):
            return f"{value} degC = {value * 9/5 + 32:.4g} degF"
        if fu in ("f", "fahrenheit") and tu in ("c", "celsius"):
            return f"{value} degF = {(value - 32) * 5/9:.4g} degC"
        if fu in ("c", "celsius") and tu in ("k", "kelvin"):
            return f"{value} degC = {value + 273.15:.4g} K"
        if fu in ("k", "kelvin") and tu in ("c", "celsius"):
            return f"{value} K = {value - 273.15:.4g} degC"

        # Currency conversion
        if fu in _CURRENCY_RATES and tu in _CURRENCY_RATES:
            rate = _CURRENCY_RATES[tu] / _CURRENCY_RATES[fu]
            result = value * rate
            return f"{value:,.2f} {from_unit.upper()} approx. {result:,.2f} {to_unit.upper()} (approximate rate)"

        # Unit conversion
        key = (fu, tu)
        if key in _UNIT_CONVERSIONS:
            result = value * _UNIT_CONVERSIONS[key]
            return f"{value} {from_unit} = {result:.6g} {to_unit}"

        # Try common aliases
        alias_map = {
            "kilometer": "km", "kilometers": "km",
            "mile": "miles", "meter": "m", "meters": "m",
            "foot": "ft", "feet": "ft", "inch": "in", "inches": "in",
            "pound": "lbs", "pounds": "lbs", "kilogram": "kg", "kilograms": "kg",
            "gram": "g", "grams": "g", "ounce": "oz", "ounces": "oz",
            "liter": "liters", "litre": "liters", "litres": "liters",
            "gallon": "gallons",
        }
        fu2 = alias_map.get(fu, fu)
        tu2 = alias_map.get(tu, tu)
        key2 = (fu2, tu2)
        if key2 in _UNIT_CONVERSIONS:
            result = value * _UNIT_CONVERSIONS[key2]
            return f"{value} {from_unit} = {result:.6g} {to_unit}"

        return (
            f"Unknown unit conversion: {from_unit} → {to_unit}. "
            "Supported: length (km/miles/m/ft/cm/in), weight (kg/lbs/g/oz), "
            "temperature (C/F/K), volume (liters/gallons), "
            "data (GB/MB/TB), currency (USD/INR/EUR/GBP/JPY/etc)."
        )

    # --- Math expression ---
    # Sanitize: strip markdown formatting
    expr_clean = expr.replace("^", "**")  # support ^ for exponentiation
    expr_clean = re.sub(r"[^\w\s\.\+\-\*\/\(\)\,\%\!\=\<\>\.\[\]]", "", expr_clean)

    try:
        result = eval(expr_clean, _SAFE_GLOBALS, {})  # nosec - safe globals only
        if isinstance(result, float):
            # Format nicely
            if result == int(result):
                return f"{expr} = {int(result)}"
            return f"{expr} = {result:.10g}"
        return f"{expr} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as e:
        return (
            f"Could not evaluate '{expression}'. "
            f"Make sure it's a valid math expression. Error: {e}"
        )


# ---------------------------------------------------------------------------
# Tool registration list (consumed by tool_registry.py)
# ---------------------------------------------------------------------------

TOOLS = [
    set_volume,
    adjust_volume,
    window_action,
    take_screenshot,
    clipboard_action,
    evaluate_expression,
]
