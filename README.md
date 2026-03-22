# VELA — Voice Edge Local Assistant

A fully local, privacy-first multimodal AI assistant. VELA listens continuously via a wake word, sees via camera, and responds via synthesised speech. No cloud services are involved; all processing occurs within the local network.

Developed as a *Tesina di Maturità* (Italian high school final examination project).

---

## Table of Contents

- [Overview](#overview)
- [Hardware Architecture](#hardware-architecture)
- [Software Stack](#software-stack)
- [Repository Structure](#repository-structure)
- [Communication Protocol](#communication-protocol)
- [Data Flows](#data-flows)
- [AI Models](#ai-models)
- [Pinout Reference](#pinout-reference)
- [Error Handling](#error-handling)
- [OLED Display](#oled-display)
- [Storage and Retrieval](#storage-and-retrieval)
- [Multi-User System](#multi-user-system)
- [Android Client](#android-client)
- [Latency Budget](#latency-budget)
- [Setup and Deployment](#setup-and-deployment)

---

## Overview

VELA is composed of three hardware nodes working in concert:

| Node | Hardware | Role |
|---|---|---|
| Node 1 | Seeed Studio XIAO ESP32-S3 Sense | Edge device — continuous audio streaming, camera, display |
| Node 2 | Raspberry Pi 5, 4 GB RAM | Middleware — always on, wake word detection, STT, TTS, storage |
| Node 3 | Laptop (Ryzen 7 8840HS, Radeon 780M) | Inference server — on-demand vision language model |

VELA is always listening. Interaction is initiated entirely by voice — there are no buttons. Saying **"Hey Vela"** activates the assistant; saying **"Hey Vela, take a photo"** triggers the vision flow. After every response, an active-listening window allows the user to continue the conversation naturally, say **"Save this"** to store the last exchange on the Pi 5's SSD, or simply stay silent to end the session.

VELA supports multi-turn conversations. Each **"Hey Vela"** starts a new conversation and clears the previous history. Within a single conversation, the assistant retains the full exchange as context for follow-up questions. History is held in RAM on the Pi 5 and is only cleared when a new wake word is detected — not on timeout or disconnect.

The system supports multiple users. Each client authenticates with a username and password on connection; all saved exchanges are stored per-user and are only accessible to their owner. The OLED display stays off when idle and lights up only during speech playback, showing the response text as subtitles.

The system also supports an Android application as an alternative client. The Android app mirrors the ESP32 behaviour exactly: always-on microphone, wake word detection pipeline, camera-triggered vision flow, and the same authentication and save functionality.

---

## Hardware Architecture

### Node 1 — Edge Device (ESP32-S3)

- **MCU:** Seeed Studio XIAO ESP32-S3 Sense
  - Integrated OV2640 camera
  - Onboard PDM microphone (internal GPIO 41/42, uses no header pins)
  - 8 MB PSRAM for audio and image buffering
  - MicroSD slot
- **Audio output:** MAX98357A I2S Class-D amplifier (3.2 W) with passive 3 W 4 Ω/8 Ω speaker. The `SD_MODE` pin is driven by the firmware state machine — muted during listening to prevent feedback, unmuted only during TTS playback.
- **Display:** SSD1306 OLED 0.96" I2C — off when idle, subtitle display during speech, camera viewfinder during the photo countdown.
- **Power:** USB-C power bank (always-on model recommended)
- **Firmware:** state machine (Arduino framework, PlatformIO)

The ESP32 streams PCM audio continuously once connected and authenticated. It has no local wake word or STT logic — all audio intelligence runs on the Pi 5. The amplifier is kept muted via `SD_MODE` at all times except during audio playback.

On first boot, if no WiFi credentials or account details are stored in NVS flash, the ESP32 enters Access Point mode and guides the user through setup entirely by voice and a small captive-portal web page (see [Setup and Deployment](#setup-and-deployment)).

### Node 2 — Middleware (Raspberry Pi 5)

- **Always on** (~5–8 W)
- Runs a FastAPI server exposing both a WebSocket endpoint (real-time client communication) and an authenticated HTTP REST API (save retrieval).
- Runs **openWakeWord** continuously as a first-stage keyword spotter. Whisper STT is invoked only after the wake word is confirmed or during the post-response follow-up window, keeping CPU usage low.
- Authenticates each client on connection against a local SQLite user database before accepting any audio stream.
- Maintains a per-session **conversation history buffer** — a list of `{role, content}` pairs representing the current conversation. The buffer is passed to the inference layer on every turn, enabling multi-turn exchanges. It is cleared only when a new "Hey Vela" wake word is detected. History is capped at the last 8 turns to stay within the VLM context window; older turns are silently dropped.
- Manages per-user save storage on the SSD: one JSON file per saved exchange, organised in per-user directories.
- A separate inference worker process holds a shared `asyncio.Queue`. Handler coroutines push jobs into the queue; the worker processes them sequentially and routes results back to the originating handler.
- Sends a Wake-on-LAN magic packet to the laptop when a vision request arrives.
- Plays an audio filler clip ("Un momento...") if processing delay exceeds 1.5 seconds.

### Node 3 — Inference Server (Laptop)

- **On-demand** — sleeps when idle, woken by the Pi 5 via Wake-on-LAN.
- Runs a llama.cpp WebSocket server with Vulkan backend.
- Communicates with the Pi 5 via WebSocket, streaming tokens as they are generated. The Pi 5 collects the full response before passing it to TTS.
- Receives the full conversation history on each request as a multi-turn messages array, enabling contextual follow-up responses.
- BIOS UMA Frame Buffer set to 8 GB for the integrated Radeon 780M.
- The `--mlock` flag pins the model in physical RAM, preventing paging to ZRAM under memory pressure.

**Recommended llama.cpp flags:**
```
--n-gpu-layers 32
--ctx-size 2048
--batch-size 512
--mlock
```

---

## Software Stack

| Layer | Tool | Node |
|---|---|---|
| Firmware | C++ / PlatformIO (Arduino framework) | ESP32 |
| WebSocket + HTTP server | FastAPI + uvicorn | Pi 5 |
| Wake word detection | openWakeWord | Pi 5 |
| STT | faster-whisper (CTranslate2) — Small model, VAD enabled | Pi 5 |
| TTS | piper-tts — `it_IT-riccardo-x_low` | Pi 5 |
| User database | SQLite (via Python `sqlite3`) | Pi 5 |
| Save storage | JSON files on SSD, per-user directory tree | Pi 5 |
| Wake-on-LAN | wakeonlan (Python) | Pi 5 |
| VLM runtime | llama.cpp (Vulkan backend) | Laptop |
| VLM model | qwen2-vl:7b Q8 | Laptop |
| Android client | Kotlin, OkHttp WebSocket + HTTP, AudioTrack, CameraX | Android device |

---

## Repository Structure

```
vela/
├── firmware/              # ESP32 firmware (C++, PlatformIO)
│   ├── src/
│   │   └── main.cpp
│   └── platformio.ini
│
├── server/                # Pi 5 server (Python)
│   ├── ws_server.py           # FastAPI WebSocket + HTTP server
│   ├── inference_worker.py    # Wake word + STT + TTS worker, asyncio queue
│   ├── auth.py                # User authentication, SQLite user DB
│   ├── storage.py             # Per-user save logic, JSON file management
│   ├── manage_users.py        # CLI tool for creating/removing user accounts
│   ├── wake_word/             # openWakeWord model and config
│   └── requirements.txt
│
├── inference/             # Laptop inference configuration
│   ├── start_server.sh        # llama.cpp launch script with flags
│   └── models/                # Model weights (not committed to git)
│
├── android/               # Android application (Kotlin)
│   └── app/
│       └── src/
│
└── docs/                  # Tesina documentation, diagrams, schematics
```

---

## Communication Protocol

All clients (ESP32 and Android) communicate with the Pi 5 via a persistent WebSocket connection. Every message is a JSON object with a `type` field. Authentication is mandatory and must be completed before any other message is accepted.

### Connection handshake

The first message sent by the client on every new connection must be an `auth` message. The Pi 5 responds with the result. If authentication fails, the connection is closed immediately.

```json
→ { "type": "auth", "username": "alice", "password_hash": "<sha256>" }
← { "type": "auth_result", "success": true }
← { "type": "auth_result", "success": false, "reason": "Invalid credentials" }
```

The password is hashed with SHA-256 on the client before transmission. The Pi 5 stores only the hash and never receives the plaintext password over the network.

### Client → Pi 5 (after authentication)

```json
{ "type": "audio_chunk", "data": "<base64_pcm>", "seq": 42 }
```
Sent **continuously** while the client is active. Contains a sequential chunk of raw PCM audio (16 kHz, mono, 16-bit). The Pi 5 passes this stream through the wake word detector at all times.

```json
{ "type": "image", "data": "<base64_jpeg>" }
```
Sent after the photo countdown completes. No voice prompt is required — the VLM is asked to describe the image automatically.

```json
{ "type": "control", "cmd": "reset" }
```
Resets the current session state on the Pi 5.

### Pi 5 → Client

```json
{ "type": "control", "cmd": "photo_mode" }
```
Instructs the client to enter camera preview mode and begin the 3–2–1 countdown.

```json
{ "type": "control", "cmd": "save_window_open" }
```
Sent after `audio_end` to notify the client that the post-response window is now active. The client keeps the OLED on (still showing the last response) and awaits speech, a save command, or a timeout.

```json
{ "type": "control", "cmd": "save_window_closed" }
```
Sent when the window expires without any detected speech. Client turns OLED off and returns to idle.

```json
{ "type": "control", "cmd": "save_confirmed" }
```
Sent after the Pi 5 successfully writes the last exchange to disk. The Pi 5 also plays a short TTS clip ("Salvato").

```json
{ "type": "audio_chunk", "data": "<base64_pcm_or_wav>", "seq": 5 }
```
A chunk of synthesised TTS audio to be played back immediately.

```json
{ "type": "audio_end" }
```
Signals that TTS playback is complete. Immediately followed by `save_window_open`.

```json
{ "type": "status", "state": "listening" }
```
Optional status update. Possible states: `idle`, `wake_word_detected`, `processing`, `speaking`, `save_window`.

### Pi 5 HTTP REST API (save retrieval)

Authentication uses HTTP Basic Auth with the same username and SHA-256 password hash as the WebSocket connection. All endpoints are local-network only.

```
GET  /saves              → list all saves for the authenticated user
GET  /saves/{id}         → retrieve a specific saved exchange
DELETE /saves/{id}       → delete a specific save
```

Each save is returned as:

```json
{
  "id": "2026-03-22T14-30-00",
  "timestamp": "2026-03-22T14:30:00",
  "question": "What is the boiling point of water?",
  "response": "Water boils at 100 degrees Celsius at sea level."
}
```

For vision exchanges, the `question` field contains the VLM's description prompt and `response` contains the description. Saved image data is not stored; only the text exchange is retained.

### Pi 5 → Laptop

The Pi 5 communicates with the llama.cpp server via WebSocket. For text queries it sends the full conversation history as a multi-turn messages array plus the new user turn; for vision queries it sends the image and a fixed description prompt. The laptop streams tokens back and the Pi 5 accumulates the full response before dispatching to Piper TTS.

---

## Data Flows

### Boot and setup flow

```
POWER ON
 └─ WiFi credentials + account details in NVS?
     ├─ NO  → start Access Point ("VELA-Setup")
     │         TTS speaks: "Connettiti alla rete VELA-Setup e apri il browser"
     │         captive portal: SSID, WiFi password, VELA username, VELA password
     │         credentials saved to NVS → reboot
     └─ YES → connect to saved WiFi network
               └─ connected?
                   ├─ NO  → TTS speaks error → retry or re-enter setup
                   └─ YES → WebSocket connect to Pi 5
                             send auth message
                             └─ auth success?
                                 ├─ NO  → TTS speaks auth error → halt
                                 └─ YES → language selection (first run only)
                                           TTS: "Di' italiano o inglese"
                                           Whisper transcribes → language saved to NVS
                                           → IDLE — always-listening loop begins
```

### Conversation lifecycle

Each "Hey Vela" starts a new conversation. History is cleared at that moment and accumulated for the lifetime of the conversation. It is never cleared on timeout or disconnect — only on the next "Hey Vela".

```
Hey Vela                      → clear history, play "Ti ascolto", listen for query
Hey Vela [query]              → clear history, no "Ti ascolto", process [query] directly
follow-up speech (in-window)  → append to history, full pipeline, new save window opens
Hey Vela [query] (in-window)  → post-STT: clear history, no "Ti ascolto", process [query]
Save this (in-window)         → write last exchange to disk, window closes, history retained
silence × 8 s                 → window closes, history retained in RAM
```

### Voice flow

1. ESP32 streams PCM chunks to the Pi 5 continuously. Amplifier is muted via `SD_MODE`.
2. Pi 5 openWakeWord detector processes each chunk in real time.
3. Wake word **"Hey Vela"** detected → Pi 5 clears conversation history → sends `{ "type": "status", "state": "wake_word_detected" }`.
4. Pi 5 plays "Ti ascolto" confirmation clip.
5. Pi 5 enables faster-whisper with VAD. Whisper records until 1.5 s of silence, then transcribes (400–700 ms).
6. Transcription is checked for content:
   - **Begins with "Hey Vela"** (mid-window wake) → clear history, strip wake phrase, treat remainder as new query if present; otherwise play "Ti ascolto" and listen again.
   - **Photo intent** ("fai una foto", "take a photo", etc.) → vision flow (see below).
   - **"Save this" / "Salva questo"** → save flow (see below).
   - **General query** → append user turn to history, send full history to inference, generate response.
7. Pi 5 sends full conversation history (all previous turns + new user turn) to the laptop as a multi-turn messages array.
8. Piper TTS synthesises the response (< 200 ms to first chunk). Response is appended to history as the assistant turn.
9. Pi 5 sends `{ "type": "status", "state": "speaking" }`.
10. Pi 5 streams PCM audio chunks. Client unmutes `SD_MODE`, plays audio. OLED shows subtitle text.
11. Pi 5 sends `audio_end`. Client mutes amplifier.
12. Pi 5 sends `save_window_open`. OLED remains on showing the last response.
13. Pi 5 enters follow-up/save window: openWakeWord suppressed, Whisper listens directly.
    - **Speech detected** → timer paused until speech ends, then Whisper transcribes → go to step 6.
    - **Silence × 8 s** → Pi 5 sends `save_window_closed` → OLED off → return to idle. History retained.

### Save flow

Triggered when "Save this" / "Salva questo" is detected during the window (step 6 above):

1. Pi 5 writes the **last exchange only** (the most recent user turn and assistant response) as a JSON file to the authenticated user's directory on the SSD.
2. Pi 5 sends `save_confirmed`.
3. Pi 5 plays "Salvato" clip.
4. Window closes. OLED off. History retained in RAM.
5. Return to idle.

### Vision flow

1. Pi 5 detects photo intent in transcription (step 6 of voice flow above).
2. Pi 5 sends `{ "type": "control", "cmd": "photo_mode" }`.
3. Client enters camera preview loop: OV2640 at ~5 fps, downsampled and dithered to 128×64. OLED shows live preview with 3–2–1 countdown.
4. At zero, client captures full-resolution JPEG and sends `{ "type": "image", "data": "..." }`.
5. OLED turns off and waits.
6. Pi 5 sends Wake-on-LAN to laptop if sleeping.
7. Pi 5 sends image + fixed description prompt to laptop via WebSocket. Vision exchanges are single-turn and do not carry conversation history.
8. llama.cpp streams tokens. Pi 5 accumulates full response. Response is appended to history as the assistant turn.
9. Piper TTS synthesises response.
10. Pi 5 streams audio → OLED shows subtitle text → client plays audio.
11. `audio_end` received. Amplifier muted.
12. Follow-up/save window opens (same as steps 12–13 in the voice flow above).

### Save retrieval flow

Any device on the local network can retrieve saves via the HTTP API:

```
browser or curl → GET http://<pi5-ip>:8765/saves
                  Authorization: Basic <base64(username:sha256hash)>
                ← JSON list of saved exchanges
```

This makes the Pi 5's SSD act as a personal NAS for each user's saved VELA interactions.

---

## AI Models

| Stage | Model | Quantisation | RAM usage | Speed | Node |
|---|---|---|---|---|---|
| Wake word | openWakeWord (custom "Hey Vela") | — | < 50 MB | real-time | Pi 5 |
| STT | Faster-Whisper Small (VAD enabled) | — | ~1.5 GB | 400–700 ms | Pi 5 |
| VLM | qwen2-vl:7b | Q8 | ~8 GB | 14–20 t/s | Laptop |
| VLM (alt) | llama3.2-vision:11b | Q8 | ~11 GB | 8–12 t/s | Laptop |
| VLM (alt) | InternVL2-26B | Q4 | ~19 GB | 4–7 t/s | Laptop |
| TTS | Piper it_IT-riccardo-x_low | — | < 200 MB | < 200 ms | Pi 5 |

The recommended VLM is `qwen2-vl:7b Q8`, which provides the best speed-to-quality balance. STT and TTS are offloaded entirely to the Pi 5, freeing approximately 13 GB of laptop RAM for higher-quality quantisation.

Vulkan is used as the llama.cpp backend instead of ROCm due to greater stability on the RDNA3 gfx1103 integrated GPU.

The openWakeWord model for "Hey Vela" can be trained for free using the tools in the openWakeWord repository; a pretrained generic model is used as the base.

---

## Pinout Reference

| Pin | Connected to | Function |
|---|---|---|
| D7 | MAX98357A BCLK | I2S bit clock |
| D8 | MAX98357A LRC | I2S word select |
| D10 | MAX98357A DIN | I2S audio data out |
| D3 | MAX98357A SD_MODE | Amplifier mute (state-machine controlled) |
| D4 | SSD1306 SDA | I2C data |
| D5 | SSD1306 SCL | I2C clock |
| 3V3 | VIN (amp), VCC (OLED) | Power |
| GND | All module grounds | Ground |
| D0, D1, D2, D6, D9 | — | Reserved / unused |

The onboard PDM microphone uses internal GPIO 41/42 and does not occupy any header pins. There are no user-facing buttons.

---

## Error Handling

All user-facing errors are communicated through audio, keeping the interaction model fully voice-driven.

| Failure | Behaviour |
|---|---|
| Authentication failure on connect | Pi 5 sends `auth_result` with error; TTS plays auth error clip; connection closed |
| WebSocket drop (ESP32 ↔ Pi 5) | Automatic silent reconnection and re-authentication in the background |
| WiFi connection failure on boot | TTS speaks error message; device retries or re-enters AP setup mode |
| Wake-on-LAN timeout (laptop unreachable) | Pi 5 plays a TTS error clip |
| STT returns empty or invalid transcription | Pi 5 plays "Non ho capito" clip; save window does not open |
| Wake word false positive (ambient noise) | Whisper VAD rejects the audio; Pi 5 returns to idle silently |
| Save write failure (disk full, permissions) | Pi 5 plays "Non è stato possibile salvare" clip |
| History exceeds token budget | Oldest turns are silently dropped; most recent 8 turns are retained |

---

## OLED Display

The SSD1306 display has three operating states:

- **Off** — default when idle, listening, or during the inference wait. The display is fully powered off to save energy and avoid distraction.
- **Subtitle mode** — active during TTS playback and throughout the post-response follow-up/save window. Shows the response text as a scrolling display synchronised with audio, and remains on until the window closes.
- **Camera viewfinder** — active during the photo countdown. Shows a live grayscale preview from the OV2640 at ~5 fps (128×64, dithered), with a 3–2–1 countdown overlay rendered directly into the frame buffer.

The display never shows system status, IP addresses, or connection indicators during normal operation. All such feedback is delivered by voice.

---

## Storage and Retrieval

The Pi 5's SSD stores each user's saved exchanges as individual JSON files, organised in a per-user directory tree:

```
/vela-data/
  users/
    alice/
      saves/
        2026-03-22T14-30-00.json
        2026-03-22T16-45-11.json
    bob/
      saves/
        2026-03-23T09-12-44.json
```

Each file contains the question, the response, and a timestamp. Only the **last exchange** of a conversation is saved per "Save this" command — the full conversation history is not written to disk. Saves are triggered exclusively by the user saying "Save this" within the post-response window; they cannot be created any other way.

The Pi 5 exposes saves over the local network via an authenticated HTTP API (see [Communication Protocol](#communication-protocol)). Any browser, `curl` command, or custom script can query a user's saves without any special software — the Pi 5 acts as a minimal personal NAS for each user's VELA history.

User account management is handled via a CLI tool on the Pi 5:

```bash
# Create a new user account
python server/manage_users.py add alice

# Remove a user and all their saves
python server/manage_users.py remove alice

# List all users
python server/manage_users.py list
```

There is no web-based admin interface. Account creation is a deliberate action by the Pi 5 owner.

---

## Multi-User System

VELA supports multiple simultaneous users, each with isolated credentials and save storage.

- **Accounts** are created by the Pi 5 owner using the `manage_users.py` CLI tool. Passwords are stored as SHA-256 hashes in a local SQLite database.
- **Authentication** occurs on every WebSocket connection, as the first message. The Pi 5 does not accept audio from unauthenticated clients.
- **Session isolation** is maintained by the per-client async handler coroutine on the Pi 5. Each connection carries its authenticated username and its own conversation history buffer for the lifetime of the session.
- **Saves** are written to and read from the authenticated user's directory only. No user can access another user's saves via the API.
- **Concurrent connections** are fully supported. Multiple ESP32 and Android clients can be connected simultaneously, each authenticated as a different (or the same) user. Inference requests are serialised through the shared queue regardless of user. Each connection maintains its own independent conversation history.
- **Language preference** is stored per-device in NVS (ESP32) or app storage (Android), not per-user on the server. Two devices logged in as the same user can therefore use different languages.

---

## Android Client

The Android application replicates the ESP32 behaviour exactly, including authentication and save functionality. There are no on-screen controls for triggering the assistant — the app is always-on.

- **Settings screen:** on first launch, the user enters the Pi 5 IP address, their VELA username, and their VELA password. These are stored in encrypted SharedPreferences and sent as a SHA-256 hash on every WebSocket connection.
- **Authentication:** the app sends an `auth` message immediately on connection and handles failure with an on-screen error and a spoken error clip from the server.
- **Audio streaming:** the microphone is opened on launch and PCM chunks (16 kHz, mono, 16-bit) are streamed continuously via OkHttp WebSocket, using the same `audio_chunk` protocol as the ESP32.
- **Wake word:** detection runs on the Pi 5. The app streams audio and reacts to status messages.
- **Photo flow:** on `photo_mode`, the app opens the rear camera (CameraX) full-screen with a 3–2–1 countdown overlay, captures a JPEG, and sends `{ "type": "image", "data": "..." }`.
- **Audio playback:** TTS chunks are played via `AudioTrack`. The app unmutes on the first `audio_chunk` and stops on `audio_end`.
- **Subtitle display:** during playback and the follow-up/save window, the response text is shown on screen, matching the OLED subtitle behaviour of the ESP32.
- **Follow-up/save window:** on `save_window_open`, the subtitle display remains visible. If the user speaks, the timer resets and the pipeline runs again. On `save_confirmed`, a brief on-screen indicator confirms the save. On `save_window_closed`, the display clears.
- **Save retrieval:** a separate screen in the app lists the authenticated user's saves by querying the Pi 5 HTTP API. Saves can be viewed and deleted from within the app.
- **Language selection:** handled by voice on first connection, stored locally in SharedPreferences.

---

## Latency Budget

Measured with the laptop already awake and on a local network.

| Phase | Estimated time |
|---|---|
| Audio streaming (continuous, no added latency) | — |
| Wake word detection — openWakeWord | < 100 ms |
| STT — Whisper Small on Pi 5 (after silence) | 400–700 ms |
| Wake-on-LAN + laptop boot (if sleeping) | ~5 s |
| VLM time-to-first-token — voice query (with history) | 800–2000 ms |
| VLM time-to-first-token — vision query | 800–2000 ms |
| TTS first chunk — Piper | < 200 ms |
| Audio transmission to client | ~20 ms |
| Follow-up/save window duration | up to 8 s |
| Save write to SSD | < 50 ms |
| **Total perceived latency — voice query (laptop awake)** | **~1.5–3 s** |
| **Total perceived latency — vision query (laptop awake)** | **~3–5 s** |

Latency for follow-up turns within a conversation is marginally higher than for the first turn due to the increased prompt size from conversation history. In practice the difference is within the normal variance of the STT step.

---

## Setup and Deployment

### Node 2 — Pi 5

```bash
pip install fastapi uvicorn websockets faster-whisper piper-tts wakeonlan openwakeword
uvicorn server.ws_server:app --host 0.0.0.0 --port 8765
python server/inference_worker.py
```

Create user accounts before connecting any clients:

```bash
python server/manage_users.py add alice
# prompts for password, stores SHA-256 hash in SQLite
```

Train or download the openWakeWord model for "Hey Vela" and place it in `server/wake_word/`. See the [openWakeWord documentation](https://github.com/dscripka/openWakeWord) for training instructions.

Ensure the SSD is mounted and the `/vela-data/` directory is writable by the server process.

### Node 3 — Laptop

```bash
# Build llama.cpp with Vulkan backend
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release

# Start the server
./build/bin/llama-server \
  --model ./inference/models/qwen2-vl-7b-q8.gguf \
  --n-gpu-layers 32 \
  --ctx-size 2048 \
  --batch-size 512 \
  --mlock \
  --host 0.0.0.0 \
  --port 8080
```

### Node 1 — ESP32

```bash
cd firmware
pio run --target upload
```

Configure the Pi 5 IP address and default language in `firmware/src/main.cpp` before flashing, or expose them as compile-time flags in `platformio.ini`. On first boot with no stored credentials, the device enters AP setup mode and guides the user through WiFi and account configuration by voice. The VELA username and password entered during setup must match an account created on the Pi 5 via `manage_users.py`.

---

## License

To be defined.
