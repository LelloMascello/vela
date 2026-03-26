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
- [TFT Display](#tft-display)
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

VELA is always listening. Every interaction follows the same structure: the user says **"Hey Vela, \<query\>"** — wake phrase and query in a single utterance. There are no buttons and no separate listening prompt. Saying **"Hey Vela, take a photo"** triggers the vision flow. After every response, an 8-second active-listening window allows the user to continue the conversation with the same **"Hey Vela, \<query\>"** format. If the window expires without a new request, conversation history is cleared.

VELA supports multi-turn conversations. Each **"Hey Vela, \<query\>"** in the follow-up window adds to the history and sends the full context to the inference layer. History is held in RAM on the Pi 5 and is cleared only when the 8-second window expires without a new utterance — not on mid-window wake words or saves.

Within the follow-up window, saying **"Hey Vela, save this"** writes the last exchange to the Pi 5's SSD and keeps the window open, allowing the conversation to continue.

The system supports multiple users. Each client authenticates with a username and password on connection; all saved exchanges are stored per-user and are only accessible to their owner. The TFT display stays off when idle and lights up during speech playback, showing the response text as subtitles.

---

## Hardware Architecture

### Node 1 — Edge Device (ESP32-S3)

- **MCU:** Seeed Studio XIAO ESP32-S3 Sense
  - Integrated OV2640 camera
  - 8 MB PSRAM for audio and image buffering
- **Microphone:** INMP441 I2S MEMS omnidirectional microphone — external module wired via I2S. Replaces the onboard PDM microphone for improved audio quality and signal level.
- **Audio output:** MAX98357A I2S Class-D amplifier (3 W) with passive 3 W 4 Ω speaker. The `SD_MODE` pin is driven by the firmware state machine — muted during listening to prevent feedback, unmuted only during TTS playback.
- **Display:** ILI9341 SPI TFT LCD 2.4" (240×320) — off when idle, subtitle display during speech, camera viewfinder during the photo countdown.
- **Power:** USB-C power bank (always-on model recommended)
- **Firmware:** state machine (Arduino framework, PlatformIO)

The ESP32 streams PCM audio continuously once connected and authenticated. It has no local wake word or STT logic — all audio intelligence runs on the Pi 5. The amplifier is kept muted via `SD_MODE` at all times except during audio playback.

On first boot, if no WiFi credentials or account details are stored in NVS flash, the ESP32 enters Access Point mode and guides the user through setup entirely by voice and a small captive-portal web page (see [Setup and Deployment](#setup-and-deployment)).

### Node 2 — Middleware (Raspberry Pi 5)

- **Always on** (~5–8 W)
- Runs a FastAPI server exposing both a WebSocket endpoint (real-time client communication) and an authenticated HTTP REST API (save retrieval).
- Runs **openWakeWord** continuously as a first-stage keyword spotter. Whisper STT is invoked only after the wake word is confirmed, keeping CPU usage low.
- Authenticates each client on connection against a local SQLite user database before accepting any audio stream.
- Maintains a per-session **conversation history buffer** — a list of `{role, content}` pairs representing the current conversation. The buffer is passed to the inference layer on every turn, enabling multi-turn exchanges. It is cleared when the post-response 8-second follow-up window expires without a new utterance. History is capped at the last 8 turns to stay within the VLM context window; older turns are silently dropped.
- Manages per-user save storage on the SSD: one folder per saved exchange, containing a metadata JSON file and (for vision saves) the captured JPEG, organised in per-user directories.
- A separate inference worker process holds a shared `asyncio.Queue`. Handler coroutines push jobs into the queue; the worker processes them sequentially and routes results back to the originating handler.
- Sends a Wake-on-LAN magic packet to the laptop when a vision request arrives.
- Plays an audio filler clip ("Un momento...") if processing delay exceeds 1.5 seconds.

### Node 3 — Inference Server (Laptop)

- **On-demand** — sleeps when idle, woken by the Pi 5 via Wake-on-LAN.
- Runs a llama.cpp WebSocket server with Vulkan backend.
- Communicates with the Pi 5 via WebSocket, streaming tokens as they are generated. The Pi 5 collects the full response before passing it to TTS.
- Receives the full conversation history on each request as a multi-turn messages array, enabling contextual follow-up responses.
- BIOS UMA Frame Buffer set to 4 GB (or Auto) for the integrated Radeon 780M. The open-source `amdgpu` driver dynamically borrows up to ~10 GB of additional system RAM (GTT) as needed.

**Recommended llama.cpp flags:**
```
--n-gpu-layers 99
--ctx-size 8192
--batch-size 256
```
*(Note: Do not use the `--mlock` flag, as it prevents the dynamic GTT memory sharing required for larger models on integrated graphics).*

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
| Save storage | Per-exchange folder (JSON + optional JPEG) on SSD | Pi 5 |
| Wake-on-LAN | wakeonlan (Python) | Pi 5 |
| VLM runtime | llama.cpp (Vulkan backend) | Laptop |
| VLM model | Qwen3-VL-8B Q4_K_M | Laptop |
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
│   ├── storage.py             # Per-user save logic, folder management
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
Sent after the photo countdown completes. The VLM is asked to describe the image automatically.

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
Sent after `audio_end` to notify the client that the post-response 8-second window is now active. The client keeps the display on (still showing the last response) and awaits a new "Hey Vela, \<query\>" utterance.

```json
{ "type": "control", "cmd": "save_window_closed" }
```
Sent when the window expires without any detected speech. Client turns display off, history is cleared, and the system returns to idle.

```json
{ "type": "control", "cmd": "save_confirmed" }
```
Sent after the Pi 5 successfully writes the last exchange to disk. The Pi 5 also plays a short TTS clip ("Salvato"). The follow-up window immediately reopens.

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
GET  /saves/{id}         → retrieve a specific saved exchange (JSON + image URL if present)
DELETE /saves/{id}       → delete a specific save (removes the folder and all its contents)
GET  /saves/{id}/image   → retrieve the captured JPEG for a vision save
```

Each text save is returned as:

```json
{
  "id": "2026-03-22T14-30-00",
  "timestamp": "2026-03-22T14:30:00",
  "type": "voice",
  "question": "What is the boiling point of water?",
  "response": "Water boils at 100 degrees Celsius at sea level."
}
```

Each vision save includes an additional `image_url` field pointing to the `/saves/{id}/image` endpoint:

```json
{
  "id": "2026-03-22T16-45-11",
  "timestamp": "2026-03-22T16:45:11",
  "type": "vision",
  "question": "Describe what you see in this image.",
  "response": "The image shows a cluttered desk with ...",
  "image_url": "/saves/2026-03-22T16-45-11/image"
}
```

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

Every interaction — whether the first turn or a follow-up — uses the same **"Hey Vela, \<query\>"** structure. The wake phrase and the query are always in the same utterance. There is no separate "Ti ascolto" prompt; the query is captured inline.

History is accumulated across turns for the lifetime of a conversation. It is cleared only when the 8-second follow-up window expires without a new utterance. Saves do not close the window or clear history.

```
[IDLE]
  Hey Vela, <query>              → process query, generate response, history starts
  Hey Vela, take a photo         → vision flow

[POST-RESPONSE WINDOW — 8 s timer running]
  Hey Vela, <query>              → reset timer, append to history, full pipeline, new window opens
  Hey Vela, take a photo         → reset timer, vision flow, new window opens
  Hey Vela, save this            → save last exchange to SSD, confirm, window reopens immediately
  silence × 8 s                  → clear history, display off → return to IDLE
```

### Voice flow

1. ESP32 streams PCM chunks to the Pi 5 continuously via the INMP441. Amplifier is muted via `SD_MODE`.
2. Pi 5 openWakeWord detector processes each chunk in real time.
3. Wake word **"Hey Vela"** detected → Pi 5 sends `{ "type": "status", "state": "wake_word_detected" }`. If a follow-up window is open, its timer is cancelled.
4. Pi 5 enables faster-whisper with VAD. Whisper records from the same audio stream, capturing the in-progress utterance until 1.5 s of silence, then transcribes (400–700 ms). The transcription includes the full "Hey Vela, \<query\>" string; the Pi 5 strips the wake phrase before processing.
5. Transcription (after wake phrase stripped) is checked for content:
   - **Empty / only wake phrase** → discard, return to idle or restart window timer. No response.
   - **"Take a photo" / "Fai una foto"** → vision flow (see below).
   - **"Save this" / "Salva questo"** → save flow (see below).
   - **General query** → append user turn to history, send full history to inference, generate response.
6. Pi 5 sends full conversation history (all previous turns + new user turn) to the laptop as a multi-turn messages array.
7. Piper TTS synthesises the response (< 200 ms to first chunk). Response is appended to history as the assistant turn.
8. Pi 5 sends `{ "type": "status", "state": "speaking" }`.
9. Pi 5 streams PCM audio chunks. Client unmutes `SD_MODE`, plays audio. TFT display shows subtitle text.
10. Pi 5 sends `audio_end`. Client mutes amplifier.
11. Pi 5 sends `save_window_open`. Display remains on showing the last response. 8-second window begins.
12. Pi 5 re-enables openWakeWord. Any detected wake word restarts the pipeline (step 3).
    - **Wake word + query detected** → reset timer, go to step 3.
    - **Silence × 8 s** → Pi 5 clears conversation history, sends `save_window_closed` → display off → return to idle.

### Save flow

Triggered when **"Hey Vela, save this"** is detected during the follow-up window:

1. Pi 5 writes the **last exchange only** (the most recent user turn and assistant response) as a new folder under the authenticated user's directory on the SSD. The folder contains `exchange.json` and, for vision saves, `image.jpg`.
2. Pi 5 sends `save_confirmed`.
3. Pi 5 plays "Salvato" clip.
4. Pi 5 sends `save_window_open` again — the window reopens immediately. History is retained. The conversation may continue.

### Vision flow

1. Pi 5 detects photo intent in transcription ("take a photo" / "fai una foto") after stripping the wake phrase.
2. Pi 5 sends `{ "type": "control", "cmd": "photo_mode" }`.
3. Client enters camera preview loop: OV2640 at ~5 fps, scaled and rendered to 240×320. TFT display shows live preview with 3–2–1 countdown overlay.
4. At zero, client captures full-resolution JPEG and sends `{ "type": "image", "data": "..." }`.
5. TFT display turns off and waits.
6. Pi 5 sends Wake-on-LAN to laptop if sleeping.
7. Pi 5 sends image + fixed description prompt to laptop via WebSocket. Vision exchanges are single-turn and do not carry conversation history.
8. llama.cpp streams tokens. Pi 5 accumulates full response. Response is appended to history as the assistant turn; the captured JPEG is held in memory for the duration of the window in case the user saves it.
9. Piper TTS synthesises response.
10. Pi 5 streams audio → TFT display shows subtitle text → client plays audio.
11. `audio_end` received. Amplifier muted.
12. Follow-up/save window opens (same as steps 11–12 in the voice flow above). If "Hey Vela, save this" is spoken, both the text exchange and the JPEG are written to the save folder.

### Save retrieval flow

Any device on the local network can retrieve saves via the HTTP API:

```
browser or curl → GET http://<pi5-ip>:8765/saves
                  Authorization: Basic <base64(username:sha256hash)>
                ← JSON list of saved exchanges (image_url included for vision saves)

                  GET http://<pi5-ip>:8765/saves/2026-03-22T16-45-11/image
                ← raw JPEG
```

---

## AI Models

| Stage | Model | Quantisation | RAM usage | Speed | Node |
|---|---|---|---|---|---|
| Wake word | openWakeWord (custom "Hey Vela") | — | < 50 MB | real-time | Pi 5 |
| STT | Faster-Whisper Small (VAD enabled) | — | ~1.5 GB | 400–700 ms | Pi 5 |
| VLM | Qwen3-VL-8B | Q4_K_M | ~4.8 GB | ~12 t/s | Laptop |
| VLM (alt) | Llama3.2-Vision-11B | Q4_K_M | ~7.0 GB | 10–14 t/s | Laptop |
| VLM (alt) | InternVL2-26B | Q4 | ~19 GB | 4–7 t/s | Laptop |
| TTS | Piper it_IT-riccardo-x_low | — | < 200 MB | < 200 ms | Pi 5 |

The recommended VLM is `Qwen3-VL-8B Q4_K_M`, which provides an incredible generational leap in reasoning and OCR, while perfectly balancing speed and hardware requirements. It fits comfortably within the 4 GB VRAM + GTT allocation, running at a highly responsive ~12 tokens/second on the integrated Radeon 780M. STT and TTS are offloaded entirely to the Pi 5, freeing laptop resources purely for visual and language inference.

Vulkan is used as the llama.cpp backend instead of ROCm due to greater stability on the RDNA3 gfx1103 integrated GPU.

The openWakeWord model for "Hey Vela" can be trained for free using the tools in the openWakeWord repository; a pretrained generic model is used as the base.

---

## Pinout Reference

The INMP441 and MAX98357A share the I2S bus (full-duplex). The ILI9341 uses hardware SPI. The INMP441's L/R pin must be tied to GND to assign the microphone to the left channel.

| Pin | Connected to | Function |
|---|---|---|
| D0 | ILI9341 BL | TFT backlight enable (or tie to 3.3 V) |
| D1 | ILI9341 RST | TFT reset |
| D2 | ILI9341 DC | TFT data/command select |
| D3 | ILI9341 CS | TFT SPI chip select |
| D4 | ILI9341 MOSI | SPI data out |
| D5 | ILI9341 SCK | SPI clock |
| D6 | MAX98357A SD_MODE | Amplifier mute (state-machine controlled) |
| D7 | MAX98357A BCLK / INMP441 SCK | I2S shared bit clock |
| D8 | MAX98357A LRC / INMP441 WS | I2S shared word select |
| D9 | INMP441 SD | I2S microphone data in |
| D10 | MAX98357A DIN | I2S audio data out |
| 3V3 | VIN (amp), VDD (INMP441), VCC (ILI9341) | Power |
| GND | All module grounds, INMP441 L/R | Ground |

ILI9341 MISO is not connected (display is write-only). The OV2640 camera uses the ESP32-S3's internal camera interface and does not occupy any header pins.

---

## Error Handling

All user-facing errors are communicated through audio, keeping the interaction model fully voice-driven.

| Failure | Behaviour |
|---|---|
| Authentication failure on connect | Pi 5 sends `auth_result` with error; TTS plays auth error clip; connection closed |
| WebSocket drop (ESP32 ↔ Pi 5) | Automatic silent reconnection and re-authentication in the background |
| WiFi connection failure on boot | TTS speaks error message; device retries or re-enters AP setup mode |
| Wake-on-LAN timeout (laptop unreachable) | Pi 5 plays a TTS error clip |
| STT returns empty or only wake phrase | Pi 5 discards the utterance and returns to idle or restarts the window timer silently |
| Wake word false positive (ambient noise) | Whisper VAD rejects the audio; Pi 5 returns to idle silently |
| Save write failure (disk full, permissions) | Pi 5 plays "Non è stato possibile salvare" clip |
| History exceeds token budget | Oldest turns are silently dropped; most recent 8 turns are retained |

---

## TFT Display

The ILI9341 240×320 SPI TFT has three operating states:

- **Off** — default when idle, listening, or during the inference wait. The display is fully powered off to save energy and avoid distraction.
- **Subtitle mode** — active during TTS playback and throughout the post-response follow-up window. Shows the response text as a scrolling display synchronised with audio, and remains on until the window closes or times out.
- **Camera viewfinder** — active during the photo countdown. Shows a live colour preview from the OV2640 at ~5 fps (scaled to 240×320), with a 3–2–1 countdown overlay rendered directly into the frame buffer.

The display never shows system status, IP addresses, or connection indicators during normal operation. All such feedback is delivered by voice.

---

## Storage and Retrieval

Each saved exchange is stored as a **dedicated folder** on the Pi 5's SSD, containing the text metadata and (for vision saves) the captured JPEG. This avoids embedding binary image data in JSON and keeps both files independently accessible.

```
/vela-data/
  users/
    alice/
      saves/
        2026-03-22T14-30-00/
          exchange.json          ← voice save
        2026-03-22T16-45-11/
          exchange.json          ← vision save
          image.jpg              ← captured JPEG (vision saves only)
    bob/
      saves/
        2026-03-23T09-12-44/
          exchange.json
```

**`exchange.json` for a voice save:**
```json
{
  "id": "2026-03-22T14-30-00",
  "timestamp": "2026-03-22T14:30:00",
  "type": "voice",
  "question": "What is the boiling point of water?",
  "response": "Water boils at 100 degrees Celsius at sea level."
}
```

**`exchange.json` for a vision save:**
```json
{
  "id": "2026-03-22T16-45-11",
  "timestamp": "2026-03-22T16:45:11",
  "type": "vision",
  "question": "Describe what you see in this image.",
  "response": "The image shows a cluttered desk with a laptop, ..."
}
```

The JPEG file is stored alongside `exchange.json` in the same folder. Deleting a save removes the entire folder.

Only the **last exchange** of a conversation is saved per "Hey Vela, save this" command — the full conversation history is not written to disk. Saves are triggered exclusively by voice within the post-response window.

The Pi 5 exposes saves over the local network via an authenticated HTTP API (see [Communication Protocol](#communication-protocol)). Any browser or `curl` command can query a user's saves and retrieve images without any special software.

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

The Android application replicates the ESP32 behaviour exactly, including authentication and save functionality. There are no on-screen controls for triggering the assistant — the app is always-on and uses the same **"Hey Vela, \<query\>"** interaction model.

- **Settings screen:** on first launch, the user enters the Pi 5 IP address, their VELA username, and their VELA password. These are stored in encrypted SharedPreferences and sent as a SHA-256 hash on every WebSocket connection.
- **Authentication:** the app sends an `auth` message immediately on connection and handles failure with an on-screen error and a spoken error clip from the server.
- **Audio streaming:** the microphone is opened on launch and PCM chunks (16 kHz, mono, 16-bit) are streamed continuously via OkHttp WebSocket, using the same `audio_chunk` protocol as the ESP32.
- **Wake word:** detection runs on the Pi 5. The app streams audio continuously and reacts to status messages.
- **Photo flow:** on `photo_mode`, the app opens the rear camera (CameraX) full-screen with a 3–2–1 countdown overlay, captures a JPEG, and sends `{ "type": "image", "data": "..." }`.
- **Audio playback:** TTS chunks are played via `AudioTrack`. The app unmutes on the first `audio_chunk` and stops on `audio_end`.
- **Subtitle display:** during playback and the follow-up window, the response text is shown on screen. On `save_window_open`, the subtitle remains visible. On `save_window_closed`, the display clears and history is cleared.
- **Save flow:** on `save_confirmed`, a brief on-screen indicator confirms the save and the window reopens immediately.
- **Save retrieval:** a separate screen in the app lists the authenticated user's saves by querying the Pi 5 HTTP API. Voice saves show question and response text; vision saves include the captured JPEG loaded from `/saves/{id}/image`. Saves can be viewed and deleted from within the app.
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
  --model ./inference/models/Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  --mmproj ./inference/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --batch-size 256 \
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
