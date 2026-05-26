// ═══════════════════════════════════════════════════════════════════════════
//  AUTH GUARD — redirect to login if session missing
// ═══════════════════════════════════════════════════════════════════════════

const _username = sessionStorage.getItem('username');
const _password = sessionStorage.getItem('password');
if (!_username || !_password) {
  window.location.href = '/';
}

document.getElementById('header-username').textContent = _username || '';

function logout() {
  sessionStorage.removeItem('username');
  sessionStorage.removeItem('password');
  window.location.href = '/';
}

// ═══════════════════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════════════════

const SAMPLE_RATE        = 16_000;
const MAIN_FRAME_LENGTH  = 512;
const TIMER_CIRC         = 201.1;
const SILENCE_TIMEOUT_S  = 10;

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

const audioQueue   = [];
let audioPlaying   = false;
let micMuted       = false;   // true while AI audio is playing — mic captured but not sent
let pendingDoneActions = false; // true when 'done' arrived but audio is still draining

let currentBubble  = null;

const waveCanvas   = document.getElementById('waveform');
const wCtx         = waveCanvas.getContext('2d');
const waveData     = new Float32Array(300);
let   wavePos      = 0;
let   waveActive   = false;

// ═══════════════════════════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function setStatus(cls, text) {
  document.getElementById('dot').className          = 'status-dot ' + cls;
  document.getElementById('status-text').textContent = text;
}

function setPhaseSteps(active) {
  const order = ['router', 'main'];
  const ai    = order.indexOf(active);
  order.forEach((p, i) => {
    const el = document.getElementById('ps-' + p);
    if (!el) return;
    if (i < ai)        el.className = 'phase-step done';
    else if (i === ai) el.className = 'phase-step active';
    else               el.className = 'phase-step';
  });
  document.getElementById('ft-phase').textContent = active;
}

function showRouterUI() {
  document.getElementById('ww-panel').style.display = '';
  document.getElementById('ai-panel').style.display = 'none';
  document.getElementById('convo-panel').classList.remove('visible');
  document.getElementById('right-panel').classList.remove('has-convo');
}

function showMainUI() {
  document.getElementById('ww-panel').style.display = 'none';
  document.getElementById('ai-panel').style.display = '';
  document.getElementById('convo-panel').classList.add('visible');
  document.getElementById('right-panel').classList.add('has-convo');
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
  document.getElementById('st-det').textContent       = detectCount;
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
  if (state === 'listening')     { badge.classList.add('listening'); text.textContent = 'listening…'; }
  else if (state === 'speaking') { badge.classList.add('speaking');  text.textContent = 'AI speaking…'; }
  else if (state === 'timeout')  { text.textContent = 'silence timeout — reconnecting…'; }
  else                           { text.textContent = 'waiting for speech…'; }
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
  const stroke = frac > 0.5  ? 'var(--accent)'
               : frac > 0.25 ? 'var(--amber)'
               :               'var(--red)';
  ring.style.stroke = stroke;
  document.getElementById('timer-seconds').textContent = Math.ceil(timerLeft);
}

// ═══════════════════════════════════════════════════════════════════════════
//  CONVERSATION BUBBLES
// ═══════════════════════════════════════════════════════════════════════════

function addUserBubble() {
  const convo = document.getElementById('convo');
  const el    = document.createElement('div');
  el.className = 'bubble user';
  el.innerHTML = '<span>🎙</span><span>spoken</span>';
  convo.appendChild(el);
  convo.scrollTop = convo.scrollHeight;
}

function startAiBubble() {
  const convo = document.getElementById('convo');
  const wrap  = document.createElement('div');
  wrap.style.alignSelf = 'flex-start';
  wrap.style.width = '85%';
  const meta  = document.createElement('div');
  meta.className   = 'bubble-meta';
  meta.textContent = 'AI';
  const el    = document.createElement('div');
  el.className = 'bubble ai streaming';
  wrap.appendChild(meta);
  wrap.appendChild(el);
  convo.appendChild(wrap);
  convo.scrollTop = convo.scrollHeight;
  currentBubble = el;
  return el;
}

function appendAiBubbleText(text) {
  if (!currentBubble) startAiBubble();
  currentBubble.textContent = currentBubble.textContent.replace(/▌$/, '') + text;
  document.getElementById('convo').scrollTop = 9999;
}

function finaliseAiBubble(fullText) {
  if (!currentBubble) return;
  currentBubble.textContent = fullText;
  currentBubble.className   = 'bubble ai';
  currentBubble = null;
}

function clearConvo() {
  document.getElementById('convo').innerHTML = '';
  currentBubble = null;
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
    // Last audio chunk finished — now it's safe to unmute and start the silence timer.
    if (pendingDoneActions) {
      pendingDoneActions = false;
      micMuted  = false;
      pcmBuffer = new Float32Array(0); // discard anything captured while muted
      unfreezeTimer();
      resetSilenceTimer();
      setAiState('waiting');
    }
    return;
  }
  if (!audioCtx)          { audioPlaying = false; audioQueue.length = 0; return; }

  audioPlaying = true;
  const b64 = audioQueue.shift();

  try {
    // Resume the AudioContext if the browser suspended it (tab focus loss,
    // autoplay policy). decodeAudioData works while suspended but start()
    // is a no-op until the context is running.
    if (audioCtx.state === 'suspended') await audioCtx.resume();

    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const buf   = await audioCtx.decodeAudioData(bytes.buffer);

    // Guard: context may have been closed while we awaited decode.
    if (!audioCtx || audioCtx.state === 'closed') {
      audioPlaying = false;
      audioQueue.length = 0;
      return;
    }

    const src  = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    src.onended = () => drainAudioQueue();
    src.start();
  } catch (e) {
    console.error('TTS playback error:', e.message);
    drainAudioQueue();   // skip broken chunk, play next
  }
}

function clearAudioQueue() {
  audioQueue.length    = 0;
  audioPlaying         = false;
  micMuted             = false;
  pendingDoneActions   = false;
}

// ═══════════════════════════════════════════════════════════════════════════
//  WAVEFORM
// ═══════════════════════════════════════════════════════════════════════════

function drawWave() {
  const w = waveCanvas.offsetWidth || 260;
  waveCanvas.width = w; waveCanvas.height = 50;
  wCtx.clearRect(0, 0, w, 50);
  const sliceW = w / waveData.length;
  wCtx.beginPath();
  const col = phase === 'main'   ? '#a78bfa'
            : phase === 'router' ? '#4f8ef7'
            : '#3a3a4a';
  wCtx.strokeStyle = waveActive ? col : '#2a2a3a';
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
  // While the mic is muted (user turn ended, AI processing/speaking),
  // discard everything — don't update the waveform, don't buffer, don't send.
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
    video: false
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
  } catch (e) {
    URL.revokeObjectURL(url);
    const src = audioCtx.createMediaStreamSource(micStream);
    const sp  = audioCtx.createScriptProcessor(4096, 1, 1);
    sp.onaudioprocess = ev => pushSamples(downsample(new Float32Array(ev.inputBuffer.getChannelData(0)), nativeRate, SAMPLE_RATE));
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
    setAiState('waiting');
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

    if (data.type === 'listening_stop') {
      // VAD has confirmed the user's turn is complete and processing has begun.
      // Freeze the waveform and stop sending mic audio immediately — before
      // the first TTS chunk arrives — so there is no gap where the mic stays
      // live while the LLM is thinking.
      micMuted   = true;
      waveActive = false;
      pcmBuffer  = new Float32Array(0);   // discard any in-flight buffered audio
      return;
    }

    if (data.type === 'tts_start') {
      turnCount++;
      document.getElementById('st-turns').textContent = turnCount;
      addUserBubble();
      startAiBubble();
      // micMuted / waveActive already set by 'listening_stop' above.
      pendingDoneActions = false;  // clear any stale flag from a previous turn
      freezeTimer();
      setAiState('speaking');
      return;
    }

    if (data.type === 'chunk') {
      if (data.text)  appendAiBubbleText(data.text);
      if (data.audio) enqueueAudio(data.audio);
      return;
    }

    if (data.type === 'tts_end') return;

    if (data.type === 'done') {
      finaliseAiBubble(data.full_text || '');
      if (audioPlaying || audioQueue.length) {
        // Audio is still playing — drainAudioQueue() will handle unmute + timer
        // once the last chunk finishes.
        pendingDoneActions = true;
      } else {
        // No audio was queued (e.g. TTS was skipped) — act immediately.
        micMuted  = false;
        pcmBuffer = new Float32Array(0);
        unfreezeTimer();
        resetSilenceTimer();
        setAiState('waiting');
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
  if (wsMain && wsMain.readyState === WebSocket.OPEN) wsMain.close(1000, 'silence timeout');
  wsMain = null;

  reconnectCount++;
  document.getElementById('st-reconnects').textContent = reconnectCount;
  setScore('—', 0);

  if (!routerWsUrl) { cleanup(); return; }
  connectRouterWs(routerWsUrl);
}

// ═══════════════════════════════════════════════════════════════════════════
//  CONNECT (entry point)
// ═══════════════════════════════════════════════════════════════════════════

async function connect() {
  const host     = document.getElementById('host').value.trim();
  const username = _username;
  const password = _password;

  try {
    audioCtx = new AudioContext();
  } catch (e) {
    console.error('AudioContext failed:', e.message);
    return;
  }

  document.getElementById('connect-btn').disabled = true;
  setStatus('pulse', 'authenticating…');

  let wsUrl;
  try {
    const resp = await fetch(`http://${host}/auth`, {
      method: 'POST',
      headers: { 'Authorization': 'Basic ' + btoa(username + ':' + password) }
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

  try {
    await startMic();
  } catch (e) {
    console.error('Mic error:', e.message);
    document.getElementById('connect-btn').disabled = false;
    audioCtx.close(); audioCtx = null;
    return;
  }

  document.getElementById('connect-btn').style.display    = 'none';
  document.getElementById('disconnect-btn').style.display = 'block';

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
  setStatus('', 'disconnected');
  setPhaseSteps('router');
  showRouterUI();
  document.getElementById('connect-btn').disabled          = false;
  document.getElementById('connect-btn').style.display    = 'block';
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