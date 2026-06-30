"""
listener.py - JARVIS System-Level Voice Listener
=================================================
Runs on your PC in the background — no browser needed.
Listens continuously via your microphone.
When you say "Jarvis", it wakes up, captures your command,
sends it to the JARVIS server (starting it automatically if needed),
and speaks the reply aloud.

Requirements:
    pip install SpeechRecognition pyaudio pyttsx3 requests

Usage:
    python listener.py                  # starts server + listener automatically
    python listener.py --port 9000      # custom port
    python listener.py --no-browser     # don't auto-open browser
"""

import sys
import time
import argparse
import subprocess
import winsound
import webbrowser
import requests
import pyttsx3
import speech_recognition as sr
from pathlib import Path

BASE_DIR = Path(__file__).parent


# ── Config ────────────────────────────────────────────────────────────────
WAKE_WORDS = ["jarvis", "hey jarvis", "ok jarvis", "hi jarvis"]


# ── TTS Engine ────────────────────────────────────────────────────────────
def build_tts():
    """Build and configure the pyttsx3 TTS engine."""
    eng = pyttsx3.init()
    eng.setProperty("rate", 165)
    eng.setProperty("volume", 1.0)

    # Pick a natural-sounding voice (prefers David/Mark on Windows SAPI5)
    voices = eng.getProperty("voices")
    for v in voices:
        name = v.name.lower()
        if "david" in name or "mark" in name or "zira" in name:
            eng.setProperty("voice", v.id)
            break

    return eng


def speak(engine, text: str):
    """Speak text, stripping markdown symbols so they aren't read aloud."""
    clean = (
        text.replace("```", "")
            .replace("**", "")
            .replace("*", "")
            .replace("`", "")
            .replace("#", "")
    )
    clean = " ".join(clean.split())
    if clean:
        engine.say(clean)
        engine.runAndWait()


# ── Audio Chimes ─────────────────────────────────────────────────────────
def chime_activate():
    """Ascending two-tone — plays when wake word detected."""
    winsound.Beep(523, 110)   # C5
    winsound.Beep(659, 190)   # E5


def chime_deactivate():
    """Descending two-tone — plays on shutdown."""
    winsound.Beep(659, 100)
    winsound.Beep(523, 160)


def chime_error():
    """Single low beep — plays on error."""
    winsound.Beep(300, 250)


# ── Speech Recognition ────────────────────────────────────────────────────
def build_recognizer() -> sr.Recognizer:
    rec = sr.Recognizer()
    rec.pause_threshold       = 1.1   # seconds of silence = end of phrase
    rec.energy_threshold      = 150   # default baseline
    rec.dynamic_energy_threshold = False  # static is much more stable
    return rec


def transcribe(recognizer: sr.Recognizer, audio: sr.AudioData) -> str:
    """Convert audio to lowercase text; returns '' on failure."""
    try:
        return recognizer.recognize_google(audio).lower().strip()
    except sr.UnknownValueError:
        return ""        # couldn't understand
    except sr.RequestError as e:
        print(f"  [!] STT service error: {e}")
        return ""


# ── Server communication ──────────────────────────────────────────────────
def send_to_jarvis(message: str, chat_url: str) -> str:
    """POST the message to the JARVIS server and return the text reply."""
    try:
        resp = requests.post(
            chat_url,
            json={"message": message},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json().get("reply", "(no reply received)")
    except requests.ConnectionError:
        return (
            "I cannot reach the JARVIS server. "
            "Please make sure 'python server.py' is running."
        )
    except requests.Timeout:
        return "The request timed out. The model might be busy."
    except Exception as e:
        return f"Server error: {e}"


# ── Server auto-start ────────────────────────────────────────────────────
def ensure_server_running(server_url: str, port: int):
    """
    Check if the JARVIS server is reachable.
    If not, start server.py automatically as a background process.
    Returns the subprocess.Popen handle if we started it, else None.
    """
    try:
        r = requests.get(server_url, timeout=2)
        if r.status_code == 200:
            print("[*] Server already running — connecting to it.")
            return None
    except requests.RequestException:
        pass

    print(f"[*] Server not found. Starting server.py on port {port}...")
    
    # Locate virtual environment Python to ensure dependencies are present
    python_exe = sys.executable
    venv_python = BASE_DIR / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        python_exe = str(venv_python)

    proc = subprocess.Popen(
        [python_exe, str(BASE_DIR / "server.py"), "--port", str(port)],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # Windows: independent process group
    )

    # Wait until the server responds (up to 15 seconds)
    for attempt in range(30):
        time.sleep(0.5)
        try:
            r = requests.get(server_url, timeout=1)
            if r.status_code == 200:
                print(f"[*] Server started successfully (PID {proc.pid}).")
                return proc
        except requests.RequestException:
            pass

    print("[!] Server did not start in time. Check server.py for errors.")
    return proc  # return anyway so we can clean up


# ── Main loop ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="JARVIS System Voice Listener")
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port the JARVIS server is running on (default: 8000)"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not open the web browser when JARVIS is first activated"
    )
    args = parser.parse_args()

    server_url   = f"http://localhost:{args.port}"
    chat_url     = f"{server_url}/api/chat"
    open_browser = not args.no_browser
    browser_opened = False

    # ── Auto-start server if not already running ───────────────────────────
    server_proc = ensure_server_running(server_url, args.port)

    print("=" * 54)
    print("   J.A.R.V.I.S  —  System Voice Listener")
    print(f"   Server  : {server_url}")
    print(f"   Wake    : say 'Jarvis' to activate")
    print(f"   Browser : {'auto-open on first activation' if open_browser else 'disabled'}")
    print("   Press   : Ctrl+C to quit")
    print("=" * 54)
    print()

    tts        = build_tts()
    recognizer = build_recognizer()
    mic        = sr.Microphone()

    # Calibrate for ambient noise
    print("[*] Calibrating microphone (2 seconds)...")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=2)
    # Clamp energy threshold to ensure it remains sensitive
    if recognizer.energy_threshold < 40:
        recognizer.energy_threshold = 40
    elif recognizer.energy_threshold > 250:
        recognizer.energy_threshold = 250
    print(f"[*] Energy threshold set to: {recognizer.energy_threshold:.0f}")
    print("[*] Listening for 'Jarvis'...\n")

    with mic as source:
        while True:
            try:
                # ── Phase 1: Listen for wake word ─────────────────────
                audio = recognizer.listen(
                    source,
                    timeout=10,           # wait up to 10s for speech to start
                    phrase_time_limit=7,  # cap each chunk at 7s
                )
                text = transcribe(recognizer, audio)

                if not text:
                    continue

                # Find which wake word triggered (if any)
                triggered = next((w for w in WAKE_WORDS if w in text), None)
                if not triggered:
                    continue

                # ── Wake word detected ─────────────────────────────────
                print(f"[!] Wake word: '{text}'")
                chime_activate()

                # Open browser on first activation
                if open_browser and not browser_opened:
                    webbrowser.open(server_url)
                    browser_opened = True
                    time.sleep(0.5)

                # Extract any inline command ("Jarvis, list my files")
                command = (
                    text[text.index(triggered) + len(triggered):]
                    .lstrip(" ,")
                    .strip()
                )

                # ── Phase 2: Get command if not inline ─────────────────
                if not command or len(command) < 2:
                    speak(tts, "Yes?")
                    print("[*] Waiting for your command...")
                    try:
                        cmd_audio = recognizer.listen(
                            source,
                            timeout=7,
                            phrase_time_limit=12,
                        )
                        command = transcribe(recognizer, cmd_audio)
                    except sr.WaitTimeoutError:
                        speak(tts, "I didn't catch that. Please try again.")
                        print("[*] No command heard.\n")
                        continue

                if not command:
                    speak(tts, "I couldn't understand that. Please say it again.")
                    print("[*] Command not recognised.\n")
                    continue

                print(f"[>] Command : {command}")

                # ── Phase 3: Send to JARVIS server and speak reply ────
                print("[*] Sending to JARVIS...")
                reply = send_to_jarvis(command, chat_url)

                preview = reply[:120] + ("..." if len(reply) > 120 else "")
                print(f"[<] JARVIS  : {preview}")

                speak(tts, reply)
                print("\n[*] Listening for 'Jarvis'...\n")

            except sr.WaitTimeoutError:
                # No speech in the timeout window — perfectly normal
                pass

            except KeyboardInterrupt:
                print("\n[*] Shutting down listener.")
                chime_deactivate()
                if server_proc is not None:
                    print(f"[*] Stopping JARVIS server (PID {server_proc.pid})...")
                    server_proc.terminate()
                break

            except Exception as e:
                print(f"[!] Error: {e}")
                chime_error()
                time.sleep(1)


if __name__ == "__main__":
    main()
