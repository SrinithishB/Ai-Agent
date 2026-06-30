/**
 * app.js — JARVIS Web Client
 *
 * Features:
 *  - WebSocket chat with real-time streaming log
 *  - Voice INPUT  : Web Speech API (SpeechRecognition) — Chrome/Edge
 *  - Voice OUTPUT : SpeechSynthesis (TTS) — all modern browsers
 *  - WAKE WORD    : Always-on "Jarvis" detection — hands-free activation
 */

const inputArea       = document.getElementById('input-area');
const chatArea        = document.getElementById('chat-area');
const logPanel        = document.getElementById('log-panel');
const inputEl         = document.getElementById('message-input');
const sendBtn         = document.getElementById('send-btn');
const micBtn          = document.getElementById('mic-btn');
const ttsToggle       = document.getElementById('tts-toggle');
const wakeToggle      = document.getElementById('wake-toggle');
const statusPill      = document.getElementById('status-pill');
const statusText      = document.getElementById('status-text');
const jarvisAvatar    = document.getElementById('jarvis-avatar');
const wakeIndicator   = document.getElementById('wake-indicator');
const modelSelect     = document.getElementById('model-select');
const stopBtn         = document.getElementById('stop-btn');
const thoughtsPanel   = document.getElementById('thoughts-panel');

// ── State ─────────────────────────────────────────────────────────────────
let isManualListening = false;   // mic-btn push-to-talk
let ttsEnabled        = true;
let agentBusy         = false;
let wakeEnabled       = false;   // always-on wake word mode
let recognition       = null;   // push-to-talk SpeechRecognition
let wakeRecognition   = null;   // continuous wake-word listener
let thinkingEl        = null;

// Wake words to listen for
const WAKE_WORDS = ['jarvis', 'hey jarvis', 'ok jarvis', 'hi jarvis'];

// ── Audio context for activation chime ───────────────────────────────────
let audioCtx = null;

function getAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function playActivationChime() {
  try {
    const ctx = getAudioCtx();
    // Two-tone ascending beep (C5 → E5)
    [523.25, 659.25].forEach((freq, i) => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.value = freq;
      const t = ctx.currentTime + i * 0.14;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.25, t + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.28);
      osc.start(t);
      osc.stop(t + 0.3);
    });
  } catch (_) {}
}

function playDeactivationChime() {
  try {
    const ctx = getAudioCtx();
    // Descending tone (E5 → C5)
    [659.25, 523.25].forEach((freq, i) => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.value = freq;
      const t = ctx.currentTime + i * 0.12;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.15, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
      osc.start(t);
      osc.stop(t + 0.25);
    });
  } catch (_) {}
}

// ── WebSocket ─────────────────────────────────────────────────────────────
const ws = new WebSocket(`ws://${location.host}/ws/chat`);

ws.onopen = () => {
  setStatus('idle', 'Ready');
  sendBtn.disabled = false;
};

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);

  if (msg.type === 'log') {
    // Check if the log contains streamed model thoughts
    if (msg.content.startsWith('[JARVIS_THOUGHT] ')) {
      const hint = thoughtsPanel.querySelector('.log-hint');
      if (hint) hint.remove();
      const thoughtText = msg.content.replace('[JARVIS_THOUGHT] ', '');
      thoughtsPanel.textContent += thoughtText;
      thoughtsPanel.scrollTop = thoughtsPanel.scrollHeight;
    } else {
      addLog(msg.content);
    }

  } else if (msg.type === 'reply') {
    removeThinking();
    addMessage('jarvis', msg.content);
    agentBusy = false;
    sendBtn.disabled = false;

    if (ttsEnabled) {
      speak(msg.content, () => {
        // After speaking, go back to wake-word listening if enabled
        setStatus('idle', 'Ready');
        setAvatarState('idle');
        if (wakeEnabled) resumeWakeListener();
      });
    } else {
      setStatus('idle', 'Ready');
      setAvatarState('idle');
      if (wakeEnabled) resumeWakeListener();
    }

  } else if (msg.type === 'voice_user_msg') {
    addMessage('user', msg.content);
    showThinking();
  } else if (msg.type === 'voice_reply') {
    removeThinking();
    addMessage('jarvis', msg.content);
  } else if (msg.type === 'error') {
    removeThinking();
    addMessage('jarvis', `⚠ Error: ${msg.content}`);
    setStatus('idle', 'Ready');
    setAvatarState('idle');
    agentBusy = false;
    sendBtn.disabled = false;
    if (wakeEnabled) resumeWakeListener();
  }
};

ws.onclose = () => setStatus('disconnected', 'Disconnected');
ws.onerror = () => setStatus('disconnected', 'Disconnected');

// ── Send message ──────────────────────────────────────────────────────────
function sendMessage(text) {
  const msg = (typeof text === 'string') ? text.trim() : inputEl.value.trim();
  if (!msg || ws.readyState !== WebSocket.OPEN || agentBusy) return;

  if (typeof text !== 'string') inputEl.value = '';
  addMessage('user', msg);
  clearLog();
  showThinking();

  agentBusy = true;
  sendBtn.disabled = true;
  setStatus('thinking', 'Thinking...');
  setAvatarState('thinking');

  ws.send(JSON.stringify({ message: msg }));
}

// ── WAKE WORD LISTENER ─────────────────────────────────────────────────────
function setupWakeRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    wakeToggle.disabled = true;
    wakeToggle.title = 'Wake word requires Chrome or Edge';
    wakeToggle.style.opacity = '0.3';
    return;
  }

  wakeRecognition = new SR();
  wakeRecognition.continuous      = true;
  wakeRecognition.interimResults  = true;
  wakeRecognition.lang            = 'en-US';
  wakeRecognition.maxAlternatives = 1;

  wakeRecognition.onresult = (e) => {
    if (agentBusy || isManualListening) return;

    // Build transcript from all results in this session
    const segments  = Array.from(e.results);
    const fullText  = segments.map(r => r[0].transcript).join(' ').toLowerCase().trim();
    const isFinal   = e.results[e.results.length - 1].isFinal;

    // Find if any wake word appears in the text
    let wakeWordEnd = -1;
    let foundWake   = '';
    for (const w of WAKE_WORDS) {
      const idx = fullText.lastIndexOf(w);
      if (idx !== -1 && idx + w.length > wakeWordEnd) {
        wakeWordEnd = idx + w.length;
        foundWake   = w;
      }
    }

    if (wakeWordEnd === -1) return;  // no wake word yet

    // Flash the indicator
    flashWakeIndicator();

    // Extract the command spoken after the wake word
    const command = fullText.slice(wakeWordEnd).replace(/^[,\s]+/, '').trim();

    if (isFinal) {
      // Stop the wake listener while agent processes
      stopWakeListener();
      if (command.length > 1) {
        // Command was in the same utterance: "Jarvis list my files"
        playActivationChime();
        inputEl.value = command;
        setTimeout(() => sendMessage(), 300);
      } else {
        // Wake word only — activate manual listening for the command
        playActivationChime();
        setStatus('listening', 'Speak your command...');
        startManualListening(true); // pass flag: return to wake after done
      }
    }
  };

  wakeRecognition.onend = () => {
    // Auto-restart if wake mode is still on and agent is idle
    if (wakeEnabled && !agentBusy && !isManualListening) {
      setTimeout(() => {
        try { wakeRecognition.start(); } catch (_) {}
      }, 300);
    }
  };

  wakeRecognition.onerror = (err) => {
    if (err.error === 'not-allowed') {
      disableWakeMode();
      alert('Microphone access denied. Please allow microphone permission and reload.');
    }
    // Other errors (no-speech, network) — auto-restart handled by onend
  };
}

function startWakeListener() {
  if (!wakeRecognition) return;
  try {
    wakeRecognition.start();
    wakeIndicator.classList.add('active');
    wakeToggle.classList.add('active');
  } catch (_) {}
}

function stopWakeListener() {
  if (!wakeRecognition) return;
  try { wakeRecognition.stop(); } catch (_) {}
  wakeIndicator.classList.remove('active');
}

function resumeWakeListener() {
  if (!wakeEnabled || isManualListening) return;
  stopWakeListener();
  setTimeout(() => {
    if (wakeEnabled && !agentBusy && !isManualListening) {
      startWakeListener();
    }
  }, 500);
}

function enableWakeMode() {
  wakeEnabled = true;
  wakeToggle.classList.add('active');
  wakeToggle.title = 'Wake word active — say "Jarvis" to activate';
  startWakeListener();
  showToast('👂 Listening for "Jarvis"...');
}

function disableWakeMode() {
  wakeEnabled = false;
  wakeToggle.classList.remove('active');
  wakeToggle.title = 'Enable wake word ("Jarvis")';
  stopWakeListener();
  wakeIndicator.classList.remove('active');
  playDeactivationChime();
}

function flashWakeIndicator() {
  jarvisAvatar.classList.add('flash');
  wakeIndicator.classList.add('flash');
  setTimeout(() => {
    jarvisAvatar.classList.remove('flash');
    wakeIndicator.classList.remove('flash');
  }, 600);
}

// ── Push-to-talk recognition ──────────────────────────────────────────────
let returnToWake = false;

function setupRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    micBtn.disabled = true;
    micBtn.title = 'Voice input requires Chrome or Edge';
    micBtn.style.opacity = '0.3';
    return;
  }

  recognition = new SR();
  recognition.lang            = 'en-US';
  recognition.continuous      = false;
  recognition.interimResults  = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    setStatus('listening', 'Listening...');
    micBtn.classList.add('active');
    inputEl.placeholder = '🎤 Listening — speak your command...';
  };

  recognition.onresult = (e) => {
    const transcript = Array.from(e.results)
      .map(r => r[0].transcript).join('');
    inputEl.value = transcript;

    if (e.results[e.results.length - 1].isFinal) {
      stopManualListening();
      setTimeout(() => sendMessage(), 200);
    }
  };

  recognition.onend = () => {
    stopManualListening();
  };

  recognition.onerror = (err) => {
    console.warn('SpeechRecognition error:', err.error);
    stopManualListening();
  };
}

function startManualListening(fromWake = false) {
  if (!recognition || agentBusy) return;
  returnToWake = fromWake;

  // Pause wake listener while manual listening
  if (wakeEnabled) stopWakeListener();

  isManualListening = true;
  inputEl.value = '';
  try { recognition.start(); } catch (_) {}
}

function stopManualListening() {
  if (!recognition) return;
  isManualListening = false;
  micBtn.classList.remove('active');
  inputEl.placeholder = 'Ask JARVIS anything...';
  setStatus('idle', 'Ready');
  try { recognition.stop(); } catch (_) {}

  // Resume wake listener if it was paused
  if (returnToWake && wakeEnabled && !agentBusy) {
    returnToWake = false;
    setTimeout(resumeWakeListener, 400);
  }
}

// ── Voice OUTPUT ─────────────────────────────────────────────────────────
let preferredVoice = null;

function loadVoices() {
  const voices = speechSynthesis.getVoices();
  preferredVoice =
    voices.find(v => v.name === 'Google UK English Male')   ||
    voices.find(v => v.name.includes('Microsoft David'))    ||
    voices.find(v => v.lang === 'en-US' && !v.localService) ||
    voices.find(v => v.lang.startsWith('en'))               ||
    null;
}

speechSynthesis.onvoiceschanged = loadVoices;
loadVoices();

function speak(text, onDone) {
  if (!ttsEnabled || !text.trim()) { onDone && onDone(); return; }

  speechSynthesis.cancel();

  const clean = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`]+`/g, '')
    .replace(/[*_#>\-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!clean) { onDone && onDone(); return; }

  const utter = new SpeechSynthesisUtterance(clean);
  utter.rate   = 1.05;
  utter.pitch  = 0.85;
  utter.volume = 1.0;
  if (preferredVoice) utter.voice = preferredVoice;

  utter.onstart = () => {
    setAvatarState('speaking');
    setStatus('speaking', 'Speaking...');
  };
  utter.onend = utter.onerror = () => {
    onDone && onDone();
  };

  speechSynthesis.speak(utter);
}

// ── Chat bubbles ──────────────────────────────────────────────────────────
function addMessage(role, content) {
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = renderMarkdown(content);
  wrapper.appendChild(bubble);
  chatArea.appendChild(wrapper);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function showThinking() {
  removeThinking();
  thinkingEl = document.createElement('div');
  thinkingEl.className = 'message jarvis thinking-bubble';
  thinkingEl.innerHTML = `<div class="bubble"><div class="dot-flashing"><span></span><span></span><span></span></div></div>`;
  chatArea.appendChild(thinkingEl);
  chatArea.scrollTop = chatArea.scrollHeight;
}

function removeThinking() {
  if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

// ── Markdown-lite renderer ────────────────────────────────────────────────
function renderMarkdown(text) {
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g,
    (_, lang, code) => `<pre><code class="lang-${lang}">${code.trim()}</code></pre>`);
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
  html = html.replace(/\n/g, '<br>');
  return html;
}

// ── Activity log ──────────────────────────────────────────────────────────
function addLog(text) {
  const hint = logPanel.querySelector('.log-hint');
  if (hint) hint.remove();

  // If the log line is a tool result containing a Python list, expand it
  // e.g.  "<< ['[FILE] a.txt', '[DIR] Documents', ...]"
  const resultMatch = text.match(/^(\s*<<\s*)(\[.+\])$/s);
  if (resultMatch) {
    const prefix = resultMatch[1];
    try {
      // Replace Python-style single quotes with double quotes so JSON.parse works
      const jsonStr = resultMatch[2]
        .replace(/'/g, '"')
        .replace(/\\"/g, '\\"');
      const items = JSON.parse(jsonStr);
      if (Array.isArray(items)) {
        // Print the << header line
        const header = document.createElement('p');
        header.className = 'log-line is-result';
        header.textContent = prefix + `[${items.length} items]`;
        logPanel.appendChild(header);
        // Print each item on its own line
        items.forEach(item => {
          const p = document.createElement('p');
          p.className = 'log-line is-result';
          const isDir  = item.includes('[DIR]');
          const isFile = item.includes('[FILE]');
          p.style.paddingLeft = '16px';
          p.style.opacity = isDir ? '1' : '0.75';
          p.textContent = '  ' + item.trim();
          logPanel.appendChild(p);
        });
        logPanel.scrollTop = logPanel.scrollHeight;
        return;
      }
    } catch (_) { /* fall through to normal rendering */ }
  }

  // Normal log line
  const p = document.createElement('p');
  p.className = 'log-line';
  if      (text.includes('>>'))                    p.classList.add('is-arrow');
  else if (text.includes('<<'))                    p.classList.add('is-result');
  else if (text.toLowerCase().includes('error'))   p.classList.add('is-error');
  p.textContent = text;
  logPanel.appendChild(p);
  logPanel.scrollTop = logPanel.scrollHeight;
}

function clearLog() {
  logPanel.innerHTML = '<p class="log-hint">Tool activity will appear here...</p>';
  thoughtsPanel.innerHTML = '<p class="log-hint">Model reasoning will stream here...</p>';
}

// ── Toast notification ───────────────────────────────────────────────────
function showToast(msg, duration = 2500) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => toast.classList.remove('show'), duration);
}

// ── Status helpers ────────────────────────────────────────────────────────
function setStatus(state, label) {
  statusPill.dataset.state = state;
  statusText.textContent   = label;
  
  if (state === 'thinking') {
    stopBtn.style.display = 'inline-flex';
  } else {
    stopBtn.style.display = 'none';
  }
}

function setAvatarState(state) {
  jarvisAvatar.dataset.state = state;
}

// ── Event listeners ───────────────────────────────────────────────────────
micBtn.addEventListener('click', () => {
  if (isManualListening) stopManualListening();
  else startManualListening(false);
});

inputArea.addEventListener('submit', (e) => {
  e.preventDefault();
  sendMessage();
});

ttsToggle.addEventListener('click', () => {
  ttsEnabled = !ttsEnabled;
  ttsToggle.classList.toggle('active', ttsEnabled);
  ttsToggle.textContent = ttsEnabled ? '🔊' : '🔇';
  ttsToggle.title = ttsEnabled ? 'Voice output ON' : 'Voice output OFF';
  if (!ttsEnabled) speechSynthesis.cancel();
});

wakeToggle.addEventListener('click', () => {
  if (wakeEnabled) disableWakeMode();
  else enableWakeMode();
});

stopBtn.addEventListener('click', () => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: 'abort' }));
    showToast('⏹ Stopping JARVIS...');
  }
});

// ── Model Switcher ────────────────────────────────────────────────────────
async function loadModels() {
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    if (data.models && data.models.length > 0) {
      modelSelect.innerHTML = '';
      data.models.forEach(model => {
        const opt = document.createElement('option');
        opt.value = model;
        opt.textContent = model;
        if (model === data.current) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    } else {
      modelSelect.innerHTML = '<option disabled>No models found</option>';
    }
  } catch (err) {
    console.error('Failed to load models:', err);
    modelSelect.innerHTML = '<option disabled>Error loading models</option>';
  }
}

modelSelect.addEventListener('change', async () => {
  const selectedModel = modelSelect.value;
  if (!selectedModel) return;
  
  try {
    const res = await fetch('/api/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: selectedModel })
    });
    const data = await res.json();
    if (data.model) {
      showToast(`🤖 Switched to: ${data.model}`);
    } else if (data.error) {
      showToast(`⚠ Error: ${data.error}`);
    }
  } catch (err) {
    showToast('⚠ Failed to switch model');
  }
});

// ── Sidebar Section Toggles ────────────────────────────────────────────────
document.querySelectorAll('.sidebar-section .section-header').forEach(header => {
  header.addEventListener('click', () => {
    const section = header.parentElement;
    section.classList.toggle('active');
  });
});

// ── Sidebar Drag Resizing ──────────────────────────────────────────────────
const sidebarResizer = document.getElementById('sidebar-resizer');
const logSidebar = document.getElementById('log-sidebar');
let isDraggingSidebar = false;

sidebarResizer.addEventListener('mousedown', (e) => {
  isDraggingSidebar = true;
  sidebarResizer.classList.add('dragging');
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
});

document.addEventListener('mousemove', (e) => {
  if (!isDraggingSidebar) return;
  const newWidth = window.innerWidth - e.clientX;
  if (newWidth >= 200 && newWidth <= 600) {
    logSidebar.style.width = `${newWidth}px`;
  }
});

document.addEventListener('mouseup', () => {
  if (isDraggingSidebar) {
    isDraggingSidebar = false;
    sidebarResizer.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }
});

// ── Init ──────────────────────────────────────────────────────────────────
sendBtn.disabled = true;
setupRecognition();
setupWakeRecognition();
loadModels();
setStatus('disconnected', 'Connecting...');

// ── Iron Man Telemetry Randomizer ──────────────────────────────────────────
function initTelemetry() {
  const tTemp   = document.getElementById('telemetry-temp');
  const tVolt   = document.getElementById('telemetry-volt');
  const tStable = document.getElementById('telemetry-stable');
  const tLoc    = document.getElementById('telemetry-loc');
  const tAlt    = document.getElementById('telemetry-alt');
  const tVel    = document.getElementById('telemetry-vel');
  const tPower  = document.getElementById('telemetry-power');

  let baseLat = 40.7128;
  let baseLng = -74.0060;
  let baseAlt = 124;
  let powerPercent = 98.2;

  setInterval(() => {
    // Oscillate core stats
    if (tTemp) tTemp.textContent = `${(40 + Math.random() * 5).toFixed(1)}°C`;
    if (tVolt) tVolt.textContent = `${(1.22 + Math.random() * 0.06).toFixed(2)}V`;
    if (tStable) tStable.textContent = `${(99.4 + Math.random() * 0.6).toFixed(2)}%`;
    
    // Simulate slight movement or gps noise
    const latShift = (Math.random() - 0.5) * 0.0005;
    const lngShift = (Math.random() - 0.5) * 0.0005;
    if (tLoc) tLoc.textContent = `${(baseLat + latShift).toFixed(4)}° N, ${(Math.abs(baseLng + lngShift)).toFixed(4)}° W`;

    // Drift altitude and speed
    const altShift = (Math.random() - 0.5) * 2;
    baseAlt = Math.max(10, baseAlt + altShift);
    if (tAlt) tAlt.textContent = `${Math.round(baseAlt)}M`;

    const speed = Math.random() > 0.7 ? (Math.random() * 15).toFixed(2) : '0.00';
    if (tVel) tVel.textContent = `${speed} M/S`;

    // Slow discharge over time
    powerPercent = Math.max(1, powerPercent - 0.001);
    if (tPower) tPower.textContent = `${powerPercent.toFixed(2)}%`;
  }, 1500);
}

initTelemetry();

