# Vela — Assistente Vocale Distribuito / Distributed Voice Assistant

> Progetto per l'Esame di Stato · *Maturità 2025*
> 
> A distributed, wake-word-triggered voice assistant running across three physical nodes: a client device (ESP32-S3 or Android), a Raspberry Pi 5 orchestrator, and a laptop AI engine.

---

## Indice / Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Hardware Requirements](#hardware-requirements)
- [Software Stack](#software-stack)
- [Conversation Flow](#conversation-flow)
- [Setup](#setup)
- [Project Structure](#project-structure)
- [Glossary](#glossary)

---

## Overview

**IT** — Vela è un assistente vocale general-purpose progettato per girare su hardware consumer distribuito. Il nome è anche la wake word: pronunciare *"Vela"* avvia una sessione conversazionale. Il sistema è composto da tre nodi che si coordinano in rete locale: il client (ESP32-S3 o Android) cattura e riproduce l'audio, il Raspberry Pi 5 gestisce l'orchestrazione e il database, e il laptop esegue il modello AI e la sintesi vocale.

**EN** — Vela is a general-purpose voice assistant designed to run across consumer distributed hardware. The name is also the wake word: saying *"Vela"* starts a conversational session. The system is made of three networked nodes: the client (ESP32-S3 or Android) captures and plays back audio, the Raspberry Pi 5 handles orchestration and the database, and the laptop runs the AI model and TTS engine.

---

## Architecture

```
┌─────────────────────┐       audio stream       ┌──────────────────────────┐
│  ESP32-S3 / Android │ ───────────────────────> │      Raspberry Pi 5      │
│      (client)       │ <─────────────────────── │   (orchestrator + DB)    │
│                     │  audio cue / prof. sync  │                          │
│  · mic              │                          │  · wake word engine      │
│  · speaker          │                          │  · connection router     │
│  · WiFi             │                          │  · chat database         │
│  · WiFiManager      │                          │  · web / config server   │
└─────────────────────┘                          │  · 4 GB RAM · 512 GB SSD │
          ^                                      └───────────┬──────────────┘
          │                                                  │ stream handoff
          │                                                  v
          │                                      ┌──────────────────────────┐
          │        audio response (chunks)       │          Laptop          │
          └───────────────────────────────────── │  (AI processing engine)  │
                                                 │                          │
                                                 │  · Gemma 4 E4B (VLM)     │
                                                 │  · native audio input    │
                                                 │  · TTS engine            │
                                                 │  · session management    │
                                                 │  · Ryzen 7 8840HS 24 GB  │
                                                 └──────────────────────────┘
```

### Node Responsibilities

| Node | Role | Key Tasks |
|---|---|---|
| **ESP32-S3 / Android** | Client | Microphone input, speaker output, WiFi transport, WiFiManager provisioning |
| **Raspberry Pi 5** | Orchestrator + DB | Wake word detection, stream routing, chat history, web/config server |
| **Laptop** | AI Engine | LLM inference (Gemma 4 E4B), TTS synthesis, session management, audio streaming |

---

## Hardware Requirements

| Component | Spec |
|---|---|
| Client | ESP32-S3 (with mic + speaker) **or** Android device |
| Orchestrator | Raspberry Pi 5 — 4 GB RAM, 512 GB SSD |
| AI Engine | Laptop with AMD Ryzen 7 8840HS, 24 GB RAM (or equivalent) |
| Network | All nodes on the same local WiFi network |

---

## Software Stack

| Layer | Technology |
|---|---|
| Client firmware | C++ (ESP32 Arduino / IDF) |
| Android client | Java / Kotlin |
| Pi orchestrator | Python |
| AI engine | Python |
| LLM | Gemma 4 E4B (Vision-Language Model) |
| Wake word | Configurable engine on Pi (e.g. openWakeWord) |
| TTS | Configurable engine on Laptop |
| Database | SQLite (chat history on Pi) |
| Config UI | Web server hosted on Pi |

---

## Conversation Flow

```
┌──────────────────────┐
│   Passive listening  │<──────────────────────────────────┐
│   Pi owns stream     │                                   │
└──────────┬───────────┘                                   │
           │ "Vela" detected                               │
           v                                               │
┌──────────────────────┐                                   │
│   Play audio cue     │                                   │
│   "Come posso        │                                   │
│    esserti utile?"   │                                   │
└──────────┬───────────┘                                   │
           │                                               │
           v                                               │
┌──────────────────────┐   silence > 8 s &                 │
│   Active listening   │── never spoke ────────────────────┘
│   laptop owns stream │
└──────────┬───────────┘
           │ speech ended
           v
┌──────────────────────┐
│   Generate response  │<──────────────────────┐
│   Gemma 4 E4B → TTS  │                       │
│   → stream chunks    │                       │
└──────────┬───────────┘                       │
           │                                   │
           v                                   │
┌──────────────────────┐   speech detected     │
│   Follow-up window   │───────────────────────┘
│   silence counter    │
│   resets to 0        │
└──────────┬───────────┘
           │ silence > 8 s
           v
┌──────────────────────┐
│   Close session      │──> transcript saved to Pi DB
└──────────────────────┘
```

**Step-by-step / Passo dopo passo:**

1. **Passive listening** — The Pi continuously listens to the audio stream from the client. The laptop is idle.
2. **Wake word** — On detecting *"Vela"*, the Pi plays an audio cue (*"Come posso esserti utile?"*) and hands the stream to the laptop.
3. **Active listening** — The laptop listens for user speech. If silence exceeds 8 seconds and the user never spoke, the session is silently dropped and the Pi resumes passive listening.
4. **Response generation** — After the user finishes speaking, Gemma 4 E4B generates a response. The TTS engine synthesises it and streams audio chunks back to the client in real time.
5. **Follow-up window** — After the response, a silence counter starts. Any detected speech resets it to 0, looping back to response generation (no need to say *"Vela"* again).
6. **Session close** — After 8 seconds of silence with no follow-up, the session closes. The full transcript is sent to the Pi and stored in the database.

---

## Setup

> ⚠️ *Detailed installation instructions will be added per-node in their respective subdirectories.*

### General prerequisites

- All three nodes must be on the same local network.
- Python 3.10+ on Pi and Laptop.
- Arduino IDE or ESP-IDF for the ESP32-S3 firmware.
- Android Studio for the Android client.

### Quick start order

1. Flash the ESP32-S3 firmware **or** install the Android APK.
2. Configure WiFi credentials via the Pi's web config interface (WiFiManager).
3. Start the orchestrator service on the Pi.
4. Start the AI engine service on the Laptop.
5. Say **"Vela"** — the assistant will respond *"Come posso esserti utile?"*.

---

## Project Structure

```
vela/
├── client/
│   ├── esp32/          # C++ firmware (ESP32-S3)
│   └── VelaApp/
│       ├── app/src/main/
│       │   ├── AndroidManifest.xml
│       │   ├── java/com/vela/app/
│       │   │   ├── LoginActivity.kt          # Schermata login (IP + credenziali)
│       │   │   ├── MainActivity.kt           # Schermata principale
│       │   │   ├── audio/
│       │   │   │   ├── AudioRecorder.kt      # Cattura mic 16kHz/16bit/mono
│       │   │   │   └── AudioPlayer.kt        # Riproduce WAV dal server
│       │   │   ├── model/
│       │   │   │   └── Models.kt             # Data classes (LoginRequest Response, WsFrame, UiState)
│       │   │   ├── network/
│       │   │   │   ├── AuthService.kt        # POST /auth/login
│       │   │   │   ├── RouterSocket.kt       # WebSocket → router.py
│       │   │   │   └── EngineSocket.kt       # WebSocket → main.py
│       │   │   └── ui/
│       │   │       └── VelaViewModel.kt      # State machine centrale
│       │   └── res/
│       │       ├── layout/
│       │       │   ├── activity_login.xml
│       │       │   └── activity_main.xml
│       │       ├── values/
│       │       │   ├── strings.xml
│       │       │   ├── colors.xml
│       │       │   └── themes.xml
│       │       └── drawable/
│       │           └── ic_mic.xml
│       ├── app/build.gradle.kts
│       ├── build.gradle.kts
│       ├── settings.gradle.kts
│       └── gradle/libs.versions.toml
├── orchestrator/
│   ├── auth.py                 ← HTTP login service        (port 5001)
│   ├── router.py               ← WebSocket audio router    (port 8766)
│   ├── wake_word_detector.py   ← Internal HTTP detector    (port 5002)
│   ├── generate_cue.py         ← One-time TTS cue builder
│   ├── requirements.txt
│   ├── vela.db                 ← SQLite DB (auto-created)
│   ├── audio/
│   │   └── standby_cue.wav     ← Created by generate_cue.py
│   └── register/
│       ├── app.py              ← Registration website      (port 5000)
│       └── templates/
│           ├── index.html
│           └── success.html
├── engine/
│   ├── standby.py           # Entry point — process lifecycle manager
│   ├── main.py              # WebSocket hub — client orchestrator
│   ├── audio-detector.py    # Silero VAD service
│   ├── inference.py         # LLM inference service
│   ├── text-to-speech.py    # Piper TTS service
│   ├── requirements.txt     # Python dependencies
│   └── test_vela.py  # Self-contained test suite
└── README.md
```
---

# Vela Orchestrator — Setup Guide

---

## 1 — System dependencies

```bash
sudo pacman -S python python-pip sqlite
```

---

## 2 — Python virtual environment

```bash
cd orchestrator/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Every time you open a new terminal**, re-activate with:
> `source .venv/bin/activate`

---

## 3 — Generate the audio cue (once)

```bash
python generate_cue.py
```

This creates `audio/standby_cue.wav` ("Sì, di cosa hai bisogno?").
It tries gTTS (needs internet + `pip install gtts pydub`) first,
then pyttsx3 offline, then a silent placeholder.

---

## 4 — Start the services

Open **four** terminals (all with the venv active):

```bash
# Terminal 1 — Registration website
python register/app.py

# Terminal 2 — Auth service
python auth.py

# Terminal 3 — Wake word detector
python wake_word_detector.py

# Terminal 4 — Audio router
python router.py
```

### Or use a process manager (recommended for the Pi)

```bash
# Install honcho inside the venv
pip install honcho

# Then from orchestrator/:
honcho start
```

Create a `Procfile` (already shown below):

```
web:      python register/app.py
auth:     python auth.py
detector: python wake_word_detector.py
router:   python router.py
```

---

## 5 — Environment variables (optional overrides)

| Variable           | Default                         | Used by              |
|--------------------|---------------------------------|----------------------|
| `VELA_DB_PATH`     | `./vela.db`                     | auth, register       |
| `VELA_SECRET`      | `vela-secret-CHANGE-in-…`       | auth, register       |
| `VELA_AUTH_PORT`   | `5001`                          | auth                 |
| `VELA_ROUTER_PORT` | `8766`                          | auth, router         |
| `VELA_DETECTOR_URL`| `http://127.0.0.1:5002/detect`  | router               |
| `VELA_STANDBY_HOST`| `127.0.0.1`                     | router               |
| `VELA_STANDBY_PORT`| `9000`                          | router               |
| `VELA_CUE_PATH`    | `./audio/standby_cue.wav`       | router               |
| `VELA_DETECTOR_PORT`| `5002`                         | wake_word_detector   |
| `VELA_WAKE_WORD`   | `hey_jarvis`                    | wake_word_detector   |
| `VELA_THRESHOLD`   | `0.5`                           | wake_word_detector   |
| `VELA_REG_PORT`    | `5000`                          | register             |
| `VELA_TOKEN_TTL`   | `24`                            | auth (hours)         |

Set them in a `.env` file and load with `set -a; source .env; set +a`
before activating the venv.

---

## 6 — Connection flow (summary)

```
Client
  │
  ├─ POST http://pi:5001/auth/login  { username, password }
  │       ← { token, ws_host, ws_port }
  │
  ├─ WS ws://pi:8766
  │  ├─ send  { type:"auth", token }
  │  │        ← { type:"ready" }
  │  ├─ send  <binary PCM chunks...>
  │  │
  │  │  [wake word detected internally via detector on port 5002]
  │  │  [router contacts standby.py engine on port 9000]
  │  │
  │  ├─ recv  <binary WAV — audio cue>
  │  └─ recv  { type:"handoff", ws_host, ws_port }
  │
  └─ WS ws://laptop:8765  (main.py — the AI engine)
```

---

## 7 — Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: openwakeword` | `pip install openwakeword` inside venv |
| Wake word model not found | First run downloads it; check internet connection |
| `vela.db` permission error | Run all services from the same directory |
| Audio cue is silent | Re-run `generate_cue.py`; install `gtts pydub` for Italian TTS |
| Clients can't reach the Pi | Check firewall: `sudo ufw allow 5000,5001,8766/tcp` |


---

# Vela — Engine setup

---

## Architecture

Five Python processes collaborate on a single machine, communicating over loopback TCP with a shared length-prefixed JSON protocol.  `llama-server` is an external binary managed by `standby.py`.

```
                        ┌──────────────────────────────────────────────────┐
                        │                    Laptop                        │
                        │                                                  │
  Pi 5 TCP :9000  ────► │  standby.py  ──fork──► llama-server (:8080)     │
                        │      │                                           │
                        │      └──fork──► main.py (:8765 WebSocket)       │
                        │                    │                             │
                        │            ┌───────┼───────┐                    │
                        │            │       │       │                     │
                        │        :9001    :9002   :9003                    │
                        │    audio-det. infer.   tts                       │
                        │    (Silero)  (llama)  (Piper)                   │
                        │                                                  │
  Client WS   ◄──────── │  ws://laptop:8765                               │
                        └──────────────────────────────────────────────────┘
```

### Data flow

```
Client (binary PCM)
        │
        ▼  WebSocket frames
    main.py
        │  audio_chunk  (IPC → :9001)
        ▼
  audio-detector.py  ── Silero VAD ──► segment (IPC → main.py)
        │
        ▼  audio  (IPC → :9002)
    inference.py  ── llama-server HTTP ──► phrase stream
        │
        ▼  phrase text  (IPC → main.py)
    main.py  ──► text-to-speech.py  (:9003)
                        │  Piper
                        ▼
                   WAV audio  (IPC → main.py)
                        │
                        ▼  response_chunk JSON
                    Client (text + base64 WAV)
```

---

## Services

| File | Port | Role |
|---|---|---|
| `standby.py` | TCP **9000** | Entry point. Waits for Pi wake signal; starts llama-server + main.py; shuts them down on idle. |
| `main.py` | WS **8765** | Orchestrator. Accepts WebSocket clients; routes audio to the detector; collects phrases; routes to TTS; streams back to client. |
| `audio-detector.py` | TCP **9001** | Silero VAD. Buffers 512-sample PCM chunks; fires `segment` on speech end; fires `silence_timeout` after 8 s of silence. |
| `inference.py` | TCP **9002** | LLM bridge. Sends WAV to llama-server via OpenAI-compatible API; streams back tokenised phrases with sentence-boundary splitting. |
| `text-to-speech.py` | TCP **9003** | Piper TTS. Calls piper as a subprocess; returns a WAV audio blob for each phrase. |
| `llama-server` | HTTP **8080** | External binary (llama.cpp). Runs Gemma 4 E2B with GPU offload; exposes `/v1/chat/completions` SSE. |

---

## Setup

### Prerequisites

- Arch Linux (or any modern Linux)
- Python 3.12+
- llama.cpp built from source with ROCm/CUDA (or CPU-only)
- Gemma 4 E2B model + mmproj file in `~/llama.cpp/mymodels/`
- A Piper voice model (see below)

### Python environment

```bash
cd engine/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Piper voice model

Download an Italian voice (or any language you prefer):

```bash
mkdir -p ~/piper-models
cd ~/piper-models
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json
```

Then set the environment variable or edit `text-to-speech.py`:

```bash
export VELA_PIPER_MODEL=~/piper-models/it_IT-paola-medium.onnx
```

### llama.cpp models

```
~/llama.cpp/mymodels/
├── gemma-4-E2B-it-Q4_K_M.gguf
└── mmproj-F16.gguf
```

---

## Running

### Normal operation (started by standby)

The Pi 5 sends a TCP `{"type": "wake"}` to port 9000.  `standby.py` handles everything automatically.  You only need `standby.py` running on the laptop:

```bash
source .venv/bin/activate
python standby.py
```

### Manual start (development / testing)

Start services individually in separate terminals — useful when iterating on a single service:

```bash
# Terminal 1 — LLM server
~/llama.cpp/.build/bin/llama-server \
  -m ~/llama.cpp/mymodels/gemma-4-E2B-it-Q4_K_M.gguf \
  --mmproj ~/llama.cpp/mymodels/mmproj-F16.gguf \
  --host 127.0.0.1 --port 8080 -ngl 99 --reasoning off

# Terminal 2 — Engine (starts all sub-services automatically)
source .venv/bin/activate
python main.py
```

Or start them all at once via the test script:

```bash
python test_vela_engine.py --start
```

---

## Configuration

All values have sensible defaults; override with environment variables before starting any service.

| Variable | Default | Description |
|---|---|---|
| `VELA_PIPER_MODEL` | `~/piper-models/it_IT-paola-medium.onnx` | Full path to the Piper `.onnx` voice model |
| `VELA_PIPER_RATE` | `22050` | Sample rate of the Piper model (check `.onnx.json`) |

Service ports are currently hardcoded.  To change them, edit the `PORT` / `*_PORT` constants at the top of each file and keep them consistent across all files.

| Constant | File | Default |
|---|---|---|
| `STANDBY_PORT` | `standby.py` | `9000` |
| `WS_PORT` | `standby.py`, `main.py` | `8765` |
| `AUDIO_DETECTOR_PORT` | `main.py`, `audio-detector.py` | `9001` |
| `INFERENCE_PORT` | `main.py`, `inference.py` | `9002` |
| `TTS_PORT` | `main.py`, `text-to-speech.py` | `9003` |
| `LLAMA_PORT` | `standby.py`, `inference.py` | `8080` |

### VAD tuning (`audio-detector.py`)

| Constant | Default | Effect |
|---|---|---|
| `VAD_THRESHOLD` | `0.50` | Raise to reduce false positives; lower to catch quiet speech |
| `SILENCE_TIMEOUT` | `8.0` s | Seconds of silence before the session is closed |
| `MIN_SILENCE_MS` | `600` ms | Silence gap needed to mark end of a phrase |
| `SPEECH_PAD_MS` | `150` ms | Audio padding added around each speech segment |

### Inference tuning (`inference.py`)

| Constant | Default | Effect |
|---|---|---|
| `MAX_TOKENS` | `768` | Maximum tokens per response |
| `TEMPERATURE` | `0.7` | Model creativity (0 = deterministic, 1 = creative) |
| `AUDIO_INPUT_SUPPORTED` | `True` | Set `False` if your llama.cpp build lacks audio input |
| `MIN_PHRASE_CHARS` | `20` | Minimum characters before flushing a phrase to TTS |

---

## IPC Protocol

All inter-process communication uses a simple binary framing:

```
┌──────────────────┬──────────────────────────────────┐
│  4 bytes         │  N bytes                         │
│  big-endian      │  UTF-8 JSON                      │
│  message length  │  message body                    │
└──────────────────┴──────────────────────────────────┘
```

### Message reference

#### `standby.py` (port 9000)

| Direction | Message | Description |
|---|---|---|
| → standby | `{"type": "wake"}` | Pi requests engine start; standby replies with WS address |
| ← standby | `{"ws_host": "…", "ws_port": 8765}` | WebSocket address for the client to connect to |
| → standby | `{"type": "idle"}` | main.py signals no clients remain; standby shuts down engine |

#### `audio-detector.py` (port 9001)

| Direction | Message | Description |
|---|---|---|
| → detector | `{"type": "init", "client_id": "…"}` | Required first message |
| → detector | `{"type": "audio_chunk", "data": "<b64 PCM>"}` | 16 kHz / 16-bit / mono PCM, any size |
| → detector | `{"type": "reset"}` | Restart the follow-up listening window after inference |
| ← detector | `{"type": "segment", "data": "<b64 PCM>"}` | Complete speech utterance ready for inference |
| ← detector | `{"type": "silence_timeout"}` | 8 s silence elapsed; main.py should close the client |

#### `inference.py` (port 9002)

| Direction | Message | Description |
|---|---|---|
| → inference | `{"type": "init", "client_id": "…"}` | Required first message |
| → inference | `{"type": "audio", "data": "<b64 WAV>"}` | One complete user utterance as a WAV file |
| ← inference | `{"type": "phrase", "text": "…"}` | One speakable sentence; sent as soon as a boundary is reached |
| ← inference | `{"type": "stream_end"}` | No more phrases for this turn |
| ← inference | `{"type": "error", "detail": "…"}` | Something went wrong |

#### `text-to-speech.py` (port 9003)

| Direction | Message | Description |
|---|---|---|
| → tts | `{"type": "init", "client_id": "…"}` | Required first message |
| → tts | `{"type": "synthesize", "text": "…"}` | Phrase to synthesise |
| ← tts | `{"type": "audio", "data": "<b64 WAV>"}` | Synthesised audio |
| ← tts | `{"type": "error", "detail": "…"}` | Synthesis failed |

#### `main.py` WebSocket (port 8765)

| Direction | Frame | Description |
|---|---|---|
| → main.py | `bytes` | Raw 16 kHz / 16-bit / mono PCM (any chunk size) |
| ← main.py | `{"type": "response_chunk", "text": "…", "audio": "<b64 WAV>"}` | One synthesised phrase + its text |
| ← main.py | `{"type": "session_end", "reason": "silence"}` | Session closed (silence timeout reached) |

---

## Testing

Drop `test_vela_engine.py` into the `engine/` folder.

```bash
source .venv/bin/activate

# Run with services already started:
python test_vela_engine.py

# Auto-start everything (embedded mock llama + fake piper), test, then stop:
python test_vela_engine.py --start

# Test only specific groups:
python test_vela_engine.py --only tts inference
python test_vela_engine.py --only e2e
```

The script exits with code `0` on all-pass and `1` on any failure, so it works in CI pipelines.

### Test groups

| Group | What it checks |
|---|---|
| `standby` | TCP wake signal → returns `ws_host`/`ws_port`; second wake is idempotent; unknown message type handled without crash |
| `detector` | Init protocol; silence chunks → no segment; 60 speech + 25 silence chunks → segment emitted; sub-chunk PCM buffering; reset returns to LISTENING |
| `inference` | Single turn → phrases + `stream_end`; follow-up turn keeps context; two concurrent clients; unknown message ignored |
| `tts` | Single phrase → valid WAV returned; sequential phrases; two concurrent clients; unknown message ignored; empty text skipped gracefully |
| `pipeline` | WebSocket connects to main.py; 40 silence chunks streamed without crash; two concurrent WebSocket clients |
| `e2e` | Full flow: wake standby → connect WebSocket → stream sine audio → stream silence → receive `response_chunk` with `text` + valid WAV |

### Requirements for `--start` mode

Only `aiohttp` and `websockets` are needed — the mock llama-server and fake piper binary are embedded in the test script.  No real Piper model or llama.cpp binary required.

```bash
pip install aiohttp websockets
python test_vela_engine.py --start
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `standby` wake times out after 45 s | llama-server is loading the model (normal on first run) | Wait; the 8840HS with ROCm typically loads in 10–20 s |
| `inference` returns `{"type": "error"}` | llama-server returned HTTP 5xx | Check llama-server logs; ensure model path is correct |
| `tts` returns `error: piper not found` | piper binary not on `PATH` | `yay -S piper-tts` or `pip install piper-tts` and ensure the bin is on PATH |
| `tts` returns `error: model not found` | `VELA_PIPER_MODEL` path is wrong | Check the path and that the `.onnx.json` companion file is beside the `.onnx` |
| VAD never emits a segment | Silero threshold too high for the microphone gain | Lower `VAD_THRESHOLD` to `0.35`–`0.45` in `audio-detector.py` |
| VAD emits too many false segments | Background noise above threshold | Raise `VAD_THRESHOLD` to `0.60`–`0.70` |
| Session closes immediately (silence_timeout) | Client sends silence before speaking | Ensure the client sends audio immediately after the WebSocket connects |
| `silero_vad` download fails | No internet or torch.hub cache issue | Pre-download: `python -c "from silero_vad import load_silero_vad; load_silero_vad()"` |
| `AUDIO_INPUT_SUPPORTED = True` but inference returns garbled text | llama.cpp build lacks audio support | Set `AUDIO_INPUT_SUPPORTED = False` in `inference.py` and add a Whisper STT step before it |
| Port already in use on restart | Previous process still running | `pkill -f main.py; pkill -f audio-detector; pkill -f inference; pkill -f text-to-speech` |

---

# VelaApp — Android Client

Client Android per il sistema di assistente vocale distribuito **Vela**.

## Architettura

```
LoginActivity  →  [HTTP POST /auth/login]  →  auth.py  (porta 5001)
                                                  │
                                                  └─► JWT + ws_host:ws_port
                                                            │
MainActivity ──────────────────────────────────────────────►│
     │                                              RouterSocket (porta 8766)
     │   [mic PCM stream ──────────────────────────►]
     │   [◄── audio cue WAV]
     │   [◄── {type:"handoff", ws_host, ws_port}]
     │                                                        │
     │                                              EngineSocket (porta 8765)
     │   [mic PCM stream ──────────────────────────►]
     │   [◄── {type:"response_chunk", text, audio}]
     └   [◄── {type:"session_end"}]
```

## Prerequisiti

| Tool            | Versione minima |
|-----------------|-----------------|
| Android Studio  | Ladybug (2024.2) |
| AGP             | 8.4.2           |
| Kotlin          | 2.0.0           |
| minSdk          | 26 (Android 8)  |
| targetSdk       | 35              |

## Importazione in Android Studio

1. **File → Open** e seleziona la cartella `VelaApp/`
2. Attendi il sync Gradle (scarica ~50 MB di dipendenze)
3. Connetti un dispositivo fisico **oppure** crea un AVD con API 26+
4. Premi **▶ Run**

> ⚠️  Il microfono **non funziona** sull'emulatore Android. Usa un dispositivo fisico per testare la cattura audio.

## Configurazione di rete

L'app usa `android:usesCleartextTraffic="true"` per permettere connessioni `ws://` e `http://` sulla rete locale.  
Per produzione/internet:
- Cambia i server in HTTPS/WSS
- Rimuovi `usesCleartextTraffic` dal Manifest

## Flusso utente

1. **Login** — Inserisci IP del Raspberry Pi, username e password
2. **Autenticazione** — L'app chiama `POST http://<IP>:5001/auth/login`
3. **Ascolto** — Connessione al Router WebSocket, lo streaming PCM parte automaticamente
4. **Wake word** — Il router rileva "Vela", invia un audio cue e poi un `handoff`
5. **Sessione attiva** — L'app si connette all'Engine, lo streaming continua
6. **Risposta** — L'Engine restituisce chunk JSON `{text, audio}` — il testo appare a schermo, l'audio viene riprodotto
7. **Fine sessione** — `session_end` riporta l'app in stato IDLE

## Dipendenze principali

```
OkHttp 4.12    — HTTP + WebSocket
Gson 2.11      — JSON serialization
Coroutines     — async/Flow per mic + playback
Material 1.12  — UI components
Lifecycle 2.8  — ViewModel + StateFlow
```

## Permessi richiesti

| Permesso            | Scopo                        |
|---------------------|------------------------------|
| `RECORD_AUDIO`      | Cattura microfono            |
| `INTERNET`          | WebSocket + HTTP             |
| `ACCESS_NETWORK_STATE` | Verifica connettività     |
| `WAKE_LOCK`         | Mantiene CPU attiva in sessione |


---

## Glossary

| Term | Meaning |
|---|---|
| **Wake word** | The trigger phrase (*"Vela"*) that activates the assistant |
| **Stream handoff** | The act of transferring ownership of the audio stream from Pi to Laptop (and back) |
| **Follow-up window** | The 8-second silence window after a response, during which the user can continue without re-triggering the wake word |
| **VLM** | Vision-Language Model — Gemma 4 E4B, capable of understanding both text and images |
| **TTS** | Text-to-Speech — converts the LLM's text response into spoken audio |
| **WiFiManager** | Library that allows the ESP32 to be provisioned with WiFi credentials via a captive portal |

---

*Progetto di Informatica per l'Esame di Stato · Vela © 2025*
