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
try:
    import winsound
except ImportError:
    winsound = None
import webbrowser
import requests
try:
    import pyttsx3
except ImportError:
    pyttsx3 = None
try:
    import speech_recognition as sr
except ImportError:
    sr = None
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _get_groq_key() -> str | None:
    import os
    env_path = BASE_DIR / ".env"
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        if k.strip() == "GROQ_API_KEY":
                            return v.strip().strip('"').strip("'")
        except Exception:
            pass
    return os.environ.get("GROQ_API_KEY")


def record_audio_termux(filepath: str) -> bool:
    """
    Record audio using termux-microphone-record.
    Stops when the user presses Enter.
    """
    import os
    # Ensure any previous recording is stopped
    subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass

    print("[*] Recording started. Speak now...")
    print("[*] Press ENTER to stop recording.")
    
    try:
        # Start recording to filepath
        proc = subprocess.Popen(
            ["termux-microphone-record", "-f", filepath],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for user input to stop
        sys.stdin.readline()
        
        # Stop recording
        subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait a moment for file write to complete
        time.sleep(0.5)
        return os.path.exists(filepath) and os.path.getsize(filepath) > 0
    except Exception as e:
        print(f"[!] Error recording: {e}")
        subprocess.run(["termux-microphone-record", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False


def transcribe_audio_groq(filepath: str, api_key: str, model_list: list) -> str:
    """Send audio file to Groq Whisper API, trying models in model_list sequentially on failure/rate-limit."""
    import requests
    import os
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    for attempt_idx, model in enumerate(model_list):
        try:
            with open(filepath, "rb") as f:
                files = {
                    "file": (os.path.basename(filepath), f, "audio/wav")
                }
                data = {
                    "model": model,
                    "response_format": "json"
                }
                res = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=30
                )
            if res.status_code == 200:
                # Success! Move the successful model to the front of the list so it is used first next time
                if attempt_idx > 0:
                    model_list.insert(0, model_list.pop(attempt_idx))
                return res.json().get("text", "").strip()
            
            # If rate limit (429) or other API errors
            print(f"[!] Groq Whisper ({model}) error {res.status_code}: {res.text}")
            if res.status_code == 429:
                print(f"[!] Rate limit hit on '{model}'. Trying fallback model...")
                continue
        except Exception as e:
            print(f"[!] Groq Whisper ({model}) exception: {e}")
            continue

    return ""


def termux_handsfree_wake_loop(server_url: str, chat_url: str, tts, groq_key: str):
    """Continuous background voice wake loop using Termux:API and Groq Whisper."""
    import os
    import sys
    
    wake_wav = str(BASE_DIR / "wake_temp.wav")
    cmd_wav = str(BASE_DIR / "cmd_temp.wav")
    
    whisper_models = ["whisper-large-v3-turbo", "whisper-large-v3"]
    
    print("=" * 54)
    print("   J.A.R.V.I.S  —  Termux Hands-Free Voice Mode")
    print(f"   Server  : {server_url}")
    print(f"   Wake    : say 'Jarvis' to activate")
    print("   Models  :", ", ".join(whisper_models))
    print("   Press   : Ctrl+C to quit")
    print("=" * 54)
    print()
    
    print("[*] Listening for 'Jarvis' (hands-free)...")
    
    while True:
        try:
            # Record a short 3-second audio clip
            res = subprocess.run(
                ["termux-microphone-record", "-f", wake_wav, "-l", "3"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )
            
            if not os.path.exists(wake_wav) or os.path.getsize(wake_wav) == 0:
                time.sleep(0.5)
                continue
                
            # Transcribe the 3-second clip
            text = transcribe_audio_groq(wake_wav, groq_key, whisper_models).lower().strip()
            
            if not text:
                continue
                
            # Find if wake word was spoken
            triggered = next((w for w in WAKE_WORDS if w in text), None)
            if not triggered:
                continue
                
            # Wake word triggered!
            print(f"[!] Wake word detected in: '{text}'")
            chime_activate()
            speak(tts, "Yes?")
            
            print("[*] Listening for command (6 seconds)...")
            res_cmd = subprocess.run(
                ["termux-microphone-record", "-f", cmd_wav, "-l", "6"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=12
            )
            
            if not os.path.exists(cmd_wav) or os.path.getsize(cmd_wav) == 0:
                speak(tts, "I didn't hear anything.")
                print("[!] No audio captured for command.")
                continue
                
            print("[*] Transcribing command...")
            command = transcribe_audio_groq(cmd_wav, groq_key, whisper_models)
            if not command:
                speak(tts, "Sorry, I couldn't transcribe that.")
                print("[!] Command transcription failed.")
                continue
                
            print(f"[>] Command : {command}")
            
            print("[*] Sending to JARVIS...")
            reply = send_to_jarvis(command, chat_url)
            preview = reply[:120] + ("..." if len(reply) > 120 else "")
            print(f"[<] JARVIS  : {preview}")
            speak(tts, reply)
            
            print("\n[*] Listening for 'Jarvis' (hands-free)...")
            
        except KeyboardInterrupt:
            print("\n[*] Shutting down hands-free listener.")
            chime_deactivate()
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(1)


# ── Config ────────────────────────────────────────────────────────────────
WAKE_WORDS = ["jarvis", "hey jarvis", "ok jarvis", "hi jarvis"]


# ── TTS Engine ────────────────────────────────────────────────────────────
def _is_android() -> bool:
    import os
    return os.path.exists("/system/bin/app_process") or "ANDROID_ROOT" in os.environ


def build_tts():
    """Build and configure the pyttsx3 TTS engine or return Termux fallback."""
    if _is_android():
        return "termux"

    if not pyttsx3:
        return None

    try:
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
    except Exception:
        return None


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
    if not clean:
        return

    if engine == "termux":
        try:
            subprocess.run(["termux-tts-speak", clean], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            print(f"[Speech Fallback]: {clean}")
    elif engine:
        try:
            engine.say(clean)
            engine.runAndWait()
        except Exception:
            print(f"[Speech Fallback]: {clean}")
    else:
        print(f"[Speech Fallback]: {clean}")


# ── Audio Chimes ─────────────────────────────────────────────────────────
def chime_activate():
    """Ascending two-tone — plays when wake word detected."""
    if winsound:
        winsound.Beep(523, 110)   # C5
        winsound.Beep(659, 190)   # E5
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()


def chime_deactivate():
    """Descending two-tone — plays on shutdown."""
    if winsound:
        winsound.Beep(659, 100)
        winsound.Beep(523, 160)
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()


def chime_error():
    """Single low beep — plays on error."""
    if winsound:
        winsound.Beep(300, 250)
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()


# ── Speech Recognition ────────────────────────────────────────────────────
def build_recognizer():
    if not sr:
        return None
    rec = sr.Recognizer()
    rec.pause_threshold       = 1.1   # seconds of silence = end of phrase
    rec.energy_threshold      = 150   # default baseline
    rec.dynamic_energy_threshold = False  # static is much more stable
    return rec


def transcribe(recognizer, audio) -> str:
    """Convert audio to lowercase text; returns '' on failure."""
    if not sr:
        return ""
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
def ensure_server_running(server_url: str, host: str, port: int):
    """
    Check if the JARVIS server is reachable.
    If not, and host is local, start server.py automatically as a background process.
    Returns the subprocess.Popen handle if we started it, else None.
    """
    try:
        r = requests.get(server_url, timeout=2)
        if r.status_code == 200:
            print("[*] Server already running — connecting to it.")
            return None
    except requests.RequestException:
        pass

    if host not in ("localhost", "127.0.0.1"):
        print(f"[!] JARVIS server at {server_url} is unreachable.")
        print(f"[!] Since host is remote ({host}), please ensure server.py is running on your phone.")
        return None

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
        "--host", type=str, default="localhost",
        help="Host/IP the JARVIS server is running on (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port the JARVIS server is running on (default: 8000)"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not open the web browser when JARVIS is first activated"
    )
    parser.add_argument(
        "--hands-free", action="store_true",
        help="Enable continuous hands-free voice wake-word listening on Termux (requires Groq API key)"
    )
    args = parser.parse_args()

    server_url   = f"http://{args.host}:{args.port}"
    chat_url     = f"{server_url}/api/chat"
    open_browser = not args.no_browser
    browser_opened = False

    # ── Auto-start server if not already running ───────────────────────────
    server_proc = ensure_server_running(server_url, args.host, args.port)

    print("=" * 54)
    print("   J.A.R.V.I.S  —  System Voice Listener")
    print(f"   Server  : {server_url}")
    print(f"   Wake    : say 'Jarvis' to activate")
    print(f"   Browser : {'auto-open on first activation' if open_browser else 'disabled'}")
    print("   Press   : Ctrl+C to quit")
    print("=" * 54)
    print()

    # ── Try to setup standard desktop audio. Fall back to Termux console if it fails ──
    use_termux_mode = False
    if _is_android() or sr is None or not pyttsx3:
        use_termux_mode = True

    if use_termux_mode:
        groq_key = _get_groq_key()
        tts = build_tts()

        if args.hands_free and groq_key:
            termux_handsfree_wake_loop(server_url, chat_url, tts, groq_key)
            return

        print("=" * 54)
        print("   J.A.R.V.I.S  —  Termux Console Assistant")
        print(f"   Server  : {server_url}")
        print("   Commands: Press Enter with no text to trigger Voice search,")
        print("             or type your command directly. Type 'exit' to quit.")
        if groq_key:
            print("             Tip: run with --hands-free for hands-free wake word listening!")
        print("=" * 54)
        print()

        temp_wav = str(BASE_DIR / "temp_record.wav")

        while True:
            try:
                user_input = input("You: ").strip()
                if not user_input:
                    success = False
                    if groq_key:
                        success = record_audio_termux(temp_wav)

                    if success:
                        print("[*] Transcribing audio with Groq Whisper model...")
                        command = transcribe_audio_groq(temp_wav, groq_key)
                        if not command:
                            print("[!] Whisper transcription was empty.")
                            continue
                        print(f"[>] Command (Whisper): {command}")
                    else:
                        print("[*] Falling back to Termux Speech Recognition popup...")
                        try:
                            res = subprocess.run(["termux-speech-to-text"], capture_output=True, text=True, timeout=15)
                            command = res.stdout.strip()
                            if not command:
                                print("[!] No speech recognized.")
                                continue
                            print(f"[>] Command (Voice): {command}")
                        except Exception as e:
                            print(f"[!] Termux Speech-to-Text failed. Ensure Termux:API app & package are installed.")
                            continue
                else:
                    if user_input.lower() == "exit":
                        print("Goodbye!")
                        break
                    command = user_input

                print("[*] Sending to JARVIS...")
                reply = send_to_jarvis(command, chat_url)
                preview = reply[:120] + ("..." if len(reply) > 120 else "")
                print(f"[<] JARVIS  : {preview}")
                speak(tts, reply)
            except KeyboardInterrupt:
                print("\n[*] Shutting down listener.")
                break
            except Exception as e:
                print(f"[!] Error: {e}")
                time.sleep(1)
        return

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
