// ═══════════════════════════════════════════════════════════════════════════
//  AUTH GUARD
// ═══════════════════════════════════════════════════════════════════════════

const _username = sessionStorage.getItem('username');
const _password = sessionStorage.getItem('password');
if (!_username || !_password) window.location.href = '/';

document.getElementById('header-username').textContent = _username || '';

function logout() {
  sessionStorage.removeItem('username');
  sessionStorage.removeItem('password');
  window.location.href = '/';
}

// ═══════════════════════════════════════════════════════════════════════════
//  CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const SAMPLE_RATE       = 16_000;
const MAIN_FRAME_LENGTH = 512;
const TIMER_CIRC        = 201.1;
const SILENCE_TIMEOUT_S = 10;

// ═══════════════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════════════

let phase          = 'idle';
let wsRouter       = null;
let wsMain         = null;
let routerWsUrl    = null;

let audioCtx       = null;
let micStream      = null;
let workletNode    = null;
let pcmBuffer      = new Float32Array(0);
let currentFrame   = 1280;

let framesSent     = 0;
let detectCount    = 0;
let turnCount      = 0;
let reconnectCount = 0;
let errCount       = 0;

let timerInterval  = null;
let timerLeft      = SILENCE_TIMEOUT_S;
let timerFrozen    = false;

const audioQueue         = [];
let audioPlaying         = false;
let micMuted             = false;
let pendingDoneActions   = false;

// Tracks the current in-progress turn's user bubble (so we can fill it with
// the transcript once we receive it) and the AI bubble.
let pendingUserBubble    = null;
let currentAiBubble      = null;

const waveCanvas   = document.getElementById('waveform');
const wCtx         = waveCanvas.getContext('2d');
const waveData     = new Float32Array(300);
let   wavePos      = 0;
let   waveActive   = false;

// ═══════════════════════════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function setStatus(cls, text) {
  document.getElementById('dot').className           = 'status-dot ' + cls;
  document.getElementById('status-text').textContent = text;
}

function setPhaseSteps(active) {
  const order = ['router', 'main'];
  const ai    = order.indexOf(active);
  order.forEach((p, i) => {
    const el = document.getElementById('ps-' + p);
    if (!el) return;
    if      (i < ai)  el.className = 'phase-step done';
    else if (i === ai) el.className = 'phase-step active';
    else               el.className = 'phase-step';
  });
  document.getElementById('ft-phase').textContent = active;
}

function showRouterUI() {
  document.getElementById('ww-panel').style.display = '';
  document.getElementById('ai-panel').style.display = 'none';
  document.getElementById('convo-panel').classList.remove('visible');
  document.getElementById('idle-placeholder').classList.remove('hidden');
}

function showMainUI() {
  document.getElementById('ww-panel').style.display = 'none';
  document.getElementById('ai-panel').style.display = '';
  document.getElementById('convo-panel').classList.add('visible');
  document.getElementById('idle-placeholder').classList.add('hidden');
}

function setScore(name, score) {
  document.getElementById('model-name').textContent = name || '—';
  document.getElementById('score-val').textContent  = score.toFixed(3);
  const bar = document.getElementById('score-bar');
  bar.style.width = Math.min(100, score * 100).toFixed(1) + '%';
  bar.className   = 'score-bar-fill' + (score >= 0.5 ? ' high' : '');
}

function flashDetection() {
  detectCount++;
  document.getElementById('detect-count').textContent = detectCount;
  document.getElementById('st-det').textContent        = detectCount;
  const badge = document.getElementById('detect-badge');
  badge.className = 'detection-badge active';
  document.getElementById('detect-label').textContent = 'DETECTED!';
  setTimeout(() => {
    badge.className = 'detection-badge';
    document.getElementById('detect-label').textContent = 'Listening…';
  }, 1800);
}

function setAiState(state) {
  const badge = document.getElementById('ai-state-badge');
  const text  = document.getElementById('ai-state-text');
  badge.className = 'ai-state-badge';
  if      (state === 'listening') { badge.classList.add('listening'); text.textContent = 'listening…'; }
  else if (state === 'speaking')  { badge.classList.add('speaking');  text.textContent = 'AI speaking…'; }
  else if (state === 'thinking')  { badge.classList.add('speaking');  text.textContent = 'thinking…'; }
  else if (state === 'timeout')   {                                    text.textContent = 'silence timeout — reconnecting…'; }
  else                             {                                    text.textContent = 'waiting for speech…'; }
}

// ── Silence countdown ring ────────────────────────────────────────────────

function startSilenceTimer() {
  stopSilenceTimer();
  timerLeft   = SILENCE_TIMEOUT_S;
  timerFrozen = false;
  updateTimerRing();
  timerInterval = setInterval(() => {
    if (timerFrozen) return;
    timerLeft = Math.max(0, timerLeft - 0.25);
    updateTimerRing();
  }, 250);
}

function stopSilenceTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function resetSilenceTimer() {
  timerLeft   = SILENCE_TIMEOUT_S;
  timerFrozen = false;
  updateTimerRing();
}

function freezeTimer()   { timerFrozen = true; }
function unfreezeTimer() { timerFrozen = false; }

function updateTimerRing() {
  const frac   = timerLeft / SILENCE_TIMEOUT_S;
  const offset = TIMER_CIRC * (1 - frac);
  const ring   = document.getElementById('timer-ring');
  ring.style.strokeDashoffset = offset;
  ring.style.stroke = frac > 0.5 ? 'var(--accent)' : frac > 0.25 ? 'var(--amber)' : 'var(--red)';
  document.getElementById('timer-seconds').textContent = Math.ceil(timerLeft);
}

// ═══════════════════════════════════════════════════════════════════════════
//  CONVERSATION BUBBLES
//  Each turn consists of:
//    • a user .turn element (role label + bubble)
//    • an AI  .turn element (role label + bubble)
// ═══════════════════════════════════════════════════════════════════════════

function addUserTurn() {
  const convo = document.getElementById('convo');

  const turn  = document.createElement('div');
  turn.className = 'turn user-turn';

  const role  = document.createElement('div');
  role.className   = 'bubble-role';
  role.textContent = 'You';

  const bubble = document.createElement('div');
  bubble.className = 'bubble user pending';
  bubble.textContent = 'Speaking…';

  turn.appendChild(role);
  turn.appendChild(bubble);
  convo.appendChild(turn);
  convo.scrollTop = convo.scrollHeight;

  // Save reference so we can fill in the transcript later.
  pendingUserBubble = bubble;
  return bubble;
}

function fillTranscript(text) {
  if (!pendingUserBubble) return;
  pendingUserBubble.classList.remove('pending');
  pendingUserBubble.textContent = text || '(no transcript)';
  pendingUserBubble = null;
  document.getElementById('convo').scrollTop = 9999;
}

function startAiTurn() {
  const convo = document.getElementById('convo');

  const turn  = document.createElement('div');
  turn.className = 'turn ai-turn';

  const role  = document.createElement('div');
  role.className   = 'bubble-role';
  role.textContent = 'flow.ai';

  const bubble = document.createElement('div');
  bubble.className = 'bubble ai streaming';

  turn.appendChild(role);
  turn.appendChild(bubble);
  convo.appendChild(turn);
  convo.scrollTop = convo.scrollHeight;

  currentAiBubble = bubble;
  return bubble;
}

function appendAiBubbleText(text) {
  if (!currentAiBubble) startAiTurn();
  currentAiBubble.textContent = currentAiBubble.textContent + text;
  document.getElementById('convo').scrollTop = 9999;
}

function finaliseAiBubble(fullText) {
  if (!currentAiBubble) return;
  currentAiBubble.textContent = fullText;
  currentAiBubble.classList.remove('streaming');
  currentAiBubble = null;
}

function clearConvo() {
  document.getElementById('convo').innerHTML = '';
  pendingUserBubble = null;
  currentAiBubble   = null;
}

// ═══════════════════════════════════════════════════════════════════════════
//  TTS AUDIO PLAYBACK
// ═══════════════════════════════════════════════════════════════════════════

function enqueueAudio(b64wav) {
  audioQueue.push(b64wav);
  if (!audioPlaying) drainAudioQueue();
}

async function drainAudioQueue() {
  if (!audioQueue.length) {
    audioPlaying = false;
    if (pendingDoneActions) {
      pendingDoneActions = false;
      micMuted  = false;
      pcmBuffer = new Float32Array(0);
      unfreezeTimer();
      resetSilenceTimer();
      setAiState('waiting');
      if (wsMain && wsMain.readyState === WebSocket.OPEN) {
        wsMain.send(JSON.stringify({ type: 'mic_open' }));
      }
    }
    return;
  }

  if (!audioCtx) { audioPlaying = false; audioQueue.length = 0; return; }
  audioPlaying = true;
  const b64 = audioQueue.shift();

  try {
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const buf   = await audioCtx.decodeAudioData(bytes.buffer);
    if (!audioCtx || audioCtx.state === 'closed') {
      audioPlaying = false; audioQueue.length = 0; return;
    }
    const src  = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    src.onended = () => drainAudioQueue();
    src.start();
  } catch (e) {
    console.error('TTS playback error:', e.message);
    drainAudioQueue();
  }
}

function clearAudioQueue() {
  audioQueue.length  = 0;
  audioPlaying       = false;
  micMuted           = false;
  pendingDoneActions = false;
}

// ═══════════════════════════════════════════════════════════════════════════
//  WAVEFORM
// ═══════════════════════════════════════════════════════════════════════════

function drawWave() {
  const w = waveCanvas.offsetWidth || 240;
  waveCanvas.width = w; waveCanvas.height = 50;
  wCtx.clearRect(0, 0, w, 50);

  const sliceW = w / waveData.length;
  wCtx.beginPath();

  const col = phase === 'main'   ? 'rgba(129,140,248,0.9)'
            : phase === 'router' ? 'rgba(56,189,248,0.9)'
            :                      'rgba(71,85,105,0.6)';
  wCtx.strokeStyle = waveActive ? col : 'rgba(71,85,105,0.3)';
  wCtx.lineWidth   = 1.5;

  for (let i = 0; i < waveData.length; i++) {
    const x = i * sliceW;
    const y = 25 + waveData[(wavePos + i) % waveData.length] * 22;
    i === 0 ? wCtx.moveTo(x, y) : wCtx.lineTo(x, y);
  }
  wCtx.stroke();
  requestAnimationFrame(drawWave);
}

// ═══════════════════════════════════════════════════════════════════════════
//  AUDIO / MIC
// ═══════════════════════════════════════════════════════════════════════════

function downsample(buf, from, to) {
  if (from === to) return buf;
  const ratio = from / to;
  const out   = new Float32Array(Math.floor(buf.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const s  = i * ratio;
    const lo = s | 0;
    const hi = Math.min(lo + 1, buf.length - 1);
    out[i]   = buf[lo] + (buf[hi] - buf[lo]) * (s - lo);
  }
  return out;
}

function pushSamples(samples) {
  if (micMuted) return;

  for (let i = 0; i < samples.length; i++) {
    waveData[wavePos % waveData.length] = samples[i];
    wavePos++;
  }
  waveActive = true;

  const merged = new Float32Array(pcmBuffer.length + samples.length);
  merged.set(pcmBuffer);
  merged.set(samples, pcmBuffer.length);
  pcmBuffer = merged;

  const activeWs = phase === 'main' ? wsMain : wsRouter;
  if (!activeWs || activeWs.readyState !== WebSocket.OPEN) return;

  while (pcmBuffer.length >= currentFrame) {
    const frame = pcmBuffer.slice(0, currentFrame);
    pcmBuffer   = pcmBuffer.slice(currentFrame);
    const int16 = new Int16Array(currentFrame);
    for (let i = 0; i < currentFrame; i++)
      int16[i] = Math.max(-32768, Math.min(32767, frame[i] * 32767 | 0));
    activeWs.send(int16.buffer);
    framesSent++;
    document.getElementById('st-frames').textContent = framesSent;
  }
}

const WORKLET_SRC = `
class PcmSender extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0]?.[0];
    if (ch?.length) this.port.postMessage(new Float32Array(ch), [new Float32Array(ch).buffer]);
    return true;
  }
}
registerProcessor('pcm-sender', PcmSender);
`;

async function startMic() {
  if (audioCtx.state === 'suspended') await audioCtx.resume();
  const nativeRate = audioCtx.sampleRate;
  document.getElementById('ft-frame').textContent = currentFrame;

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, sampleRate: { ideal: 16000 },
             echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    video: false,
  });

  const blob = new Blob([WORKLET_SRC], { type: 'application/javascript' });
  const url  = URL.createObjectURL(blob);

  try {
    await audioCtx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const src = audioCtx.createMediaStreamSource(micStream);
    workletNode = new AudioWorkletNode(audioCtx, 'pcm-sender');
    workletNode.port.onmessage = ev => pushSamples(downsample(ev.data, nativeRate, SAMPLE_RATE));
    src.connect(workletNode);
    const sink = audioCtx.createGain(); sink.gain.value = 0;
    workletNode.connect(sink); sink.connect(audioCtx.destination);
  } catch (_) {
    URL.revokeObjectURL(url);
    const src = audioCtx.createMediaStreamSource(micStream);
    const sp  = audioCtx.createScriptProcessor(4096, 1, 1);
    sp.onaudioprocess = ev =>
      pushSamples(downsample(new Float32Array(ev.inputBuffer.getChannelData(0)), nativeRate, SAMPLE_RATE));
    src.connect(sp);
    const sink = audioCtx.createGain(); sink.gain.value = 0;
    sp.connect(sink); sink.connect(audioCtx.destination);
    workletNode = sp;
  }
}

function stopMic() {
  waveActive = false;
  if (workletNode) { try { workletNode.disconnect(); } catch (_) {} workletNode = null; }
  if (micStream)   { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
}

// ═══════════════════════════════════════════════════════════════════════════
//  PHASE: ROUTER  (wake-word detection)
// ═══════════════════════════════════════════════════════════════════════════

function connectRouterWs(url) {
  wsRouter = new WebSocket(url);
  wsRouter.binaryType = 'arraybuffer';
  document.getElementById('ft-router').textContent = url.replace('ws://', '');

  wsRouter.onopen = () => {
    phase        = 'router';
    currentFrame = parseInt(document.getElementById('router-frame').value) || 1280;
    pcmBuffer    = new Float32Array(0);
    micMuted     = false;
    document.getElementById('ft-frame').textContent = currentFrame;
    setStatus('router pulse', 'router ws');
    setPhaseSteps('router');
    showRouterUI();
  };

  wsRouter.onmessage = e => {
    let data;
    try { data = JSON.parse(e.data); } catch (_) { return; }

    if (data.error) {
      errCount++;
      document.getElementById('st-err').textContent = errCount;
      console.error('[router]', data.error);
      return;
    }

    if (data.wake_word !== undefined) {
      const score = data.best_score ?? 0;
      setScore(data.best_model, score);
      if (data.wake_word) flashDetection();
      return;
    }

    if (data.ip !== undefined && data.port !== undefined) {
      switchToMain(data.ip, data.port, data.username);
    }
  };

  wsRouter.onclose = () => {
    document.getElementById('ft-router').textContent = 'closed';
  };

  wsRouter.onerror = () => {
    errCount++;
    document.getElementById('st-err').textContent = errCount;
    setStatus('error', 'ws error');
  };
}

// ═══════════════════════════════════════════════════════════════════════════
//  PHASE TRANSITION: router → main
// ═══════════════════════════════════════════════════════════════════════════

function switchToMain(ip, port, username) {
  if (wsRouter && wsRouter.readyState === WebSocket.OPEN) wsRouter.close(1000, 'switching to main');
  wsRouter = null;

  const user = encodeURIComponent(username || _username);
  const url  = `ws://${ip}:${port}/ws?username=${user}`;
  document.getElementById('ft-main').textContent = `${ip}:${port}`;

  // Clear the conversation panel for this fresh session.
  clearConvo();

  wsMain = new WebSocket(url);
  wsMain.binaryType = 'arraybuffer';

  wsMain.onopen = () => {
    phase        = 'main';
    currentFrame = MAIN_FRAME_LENGTH;
    pcmBuffer    = new Float32Array(0);
    document.getElementById('ft-frame').textContent = currentFrame;
    setStatus('main pulse', 'main ws');
    setPhaseSteps('main');
    showMainUI();
    setAiState('listening');
    startSilenceTimer();
  };

  wsMain.onmessage = e => {
    let data;
    try { data = JSON.parse(e.data); } catch (_) { return; }

    if (data.error) {
      errCount++;
      document.getElementById('st-err').textContent = errCount;
      console.error('[main]', data.error);
      return;
    }

    // ── User finished speaking — show a pending user bubble ──────────────
    if (data.type === 'listening_stop') {
      micMuted   = true;
      waveActive = false;
      pcmBuffer  = new Float32Array(0);
      // Create the user bubble immediately (in pending state) so the turn
      // order is preserved visually.
      addUserTurn();
      setAiState('thinking');
      return;
    }

    // ── TTS starting — create the AI bubble ──────────────────────────────
    if (data.type === 'tts_start') {
      turnCount++;
      document.getElementById('st-turns').textContent = turnCount;
      startAiTurn();
      pendingDoneActions = false;
      freezeTimer();
      setAiState('speaking');
      return;
    }

    // ── Streaming text + audio chunk ─────────────────────────────────────
    if (data.type === 'chunk') {
      if (data.text)  appendAiBubbleText(data.text);
      if (data.audio) enqueueAudio(data.audio);
      return;
    }

    if (data.type === 'tts_end') return;

    // ── Turn complete: fill transcript + finalise AI bubble ──────────────
    if (data.type === 'done') {
      finaliseAiBubble(data.full_text || '');
      // Fill in the transcript if the server sent it (add transcript field to
      // main.py's "done" message), or fall back to a generic label.
      fillTranscript(data.transcript || null);

      if (audioPlaying || audioQueue.length) {
        pendingDoneActions = true;
      } else {
        micMuted  = false;
        pcmBuffer = new Float32Array(0);
        unfreezeTimer();
        resetSilenceTimer();
        setAiState('waiting');
        if (wsMain && wsMain.readyState === WebSocket.OPEN) {
          wsMain.send(JSON.stringify({ type: 'mic_open' }));
        }
      }
      return;
    }

    if (data.type === 'silence_timeout') {
      setAiState('timeout');
      switchToRouter();
    }
  };

  wsMain.onclose = () => {
    document.getElementById('ft-main').textContent = 'closed';
    clearAudioQueue();
    stopSilenceTimer();
    // Reset conversation for next session that comes through the router.
    clearConvo();
  };

  wsMain.onerror = () => {
    errCount++;
    document.getElementById('st-err').textContent = errCount;
    setStatus('error', 'ws error');
    stopSilenceTimer();
  };
}

// ═══════════════════════════════════════════════════════════════════════════
//  PHASE TRANSITION: main → router  (after silence timeout)
// ═══════════════════════════════════════════════════════════════════════════

function switchToRouter() {
  stopSilenceTimer();
  clearAudioQueue();
  micMuted = true;
  if (wsMain && wsMain.readyState === WebSocket.OPEN) wsMain.close(1000, 'silence timeout');
  wsMain = null;

  reconnectCount++;
  document.getElementById('st-reconnects').textContent = reconnectCount;
  setScore('—', 0);

  // Clear the live conversation view when returning to router (silence timeout
  // means the session ended and was persisted by the backend).
  clearConvo();

  if (!routerWsUrl) { cleanup(); return; }
  connectRouterWs(routerWsUrl);
}

// ═══════════════════════════════════════════════════════════════════════════
//  CONNECT
// ═══════════════════════════════════════════════════════════════════════════

async function connect() {
  const host     = document.getElementById('host').value.trim();
  const username = _username;
  const password = _password;

  try { audioCtx = new AudioContext(); }
  catch (e) { console.error('AudioContext failed:', e.message); return; }

  document.getElementById('connect-btn').disabled = true;
  setStatus('pulse', 'authenticating…');

  let wsUrl;
  try {
    const resp = await fetch(`http://${host}/auth`, {
      method:  'POST',
      headers: { 'Authorization': 'Basic ' + btoa(username + ':' + password) },
    });
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    const data = await resp.json();
    wsUrl = data.ws_url || `ws://${host}/ws`;
  } catch (err) {
    console.error('Auth error:', err.message);
    setStatus('error', 'auth failed');
    document.getElementById('connect-btn').disabled = false;
    audioCtx.close(); audioCtx = null;
    return;
  }

  routerWsUrl = wsUrl;

  try { await startMic(); }
  catch (e) {
    console.error('Mic error:', e.message);
    document.getElementById('connect-btn').disabled = false;
    audioCtx.close(); audioCtx = null;
    return;
  }

  document.getElementById('connect-btn').style.display    = 'none';
  document.getElementById('disconnect-btn').style.display = '';

  connectRouterWs(wsUrl);
}

// ═══════════════════════════════════════════════════════════════════════════
//  DISCONNECT
// ═══════════════════════════════════════════════════════════════════════════

function disconnect() {
  if (wsRouter) { try { wsRouter.close(1000, 'user disconnect'); } catch (_) {} wsRouter = null; }
  if (wsMain)   { try { wsMain.close(1000, 'user disconnect');   } catch (_) {} wsMain   = null; }
  cleanup();
}

function cleanup() {
  phase = 'idle';
  stopMic();
  stopSilenceTimer();
  clearAudioQueue();
  waveActive  = false;
  routerWsUrl = null;
  pcmBuffer   = new Float32Array(0);
  // Reset conversation view on full disconnect.
  clearConvo();
  setStatus('', 'disconnected');
  setPhaseSteps('router');
  showRouterUI();
  document.getElementById('connect-btn').disabled          = false;
  document.getElementById('connect-btn').style.display    = '';
  document.getElementById('disconnect-btn').style.display = 'none';
  document.getElementById('ft-router').textContent = '—';
  document.getElementById('ft-main').textContent   = '—';
  document.getElementById('ft-frame').textContent  = '—';
  document.getElementById('ft-phase').textContent  = 'idle';
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
}

// ═══════════════════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════════════════

drawWave();