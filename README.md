# VELA — Voice Edge Local Assistant

A fully local, privacy-first multimodal AI assistant. VELA listens continuously, sees via camera, and responds via synthesised speech. No cloud services are involved; all processing occurs within the local network.

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
- [Storage, Web UI, and Retrieval](#storage-web-ui-and-retrieval)
- [Multi-User System](#multi-user-system)
- [Android Client](#android-client)
- [Latency Budget](#latency-budget)
- [Setup and Deployment](#setup-and-deployment)

---

## Overview

VELA is composed of three hardware nodes working in concert, with distinct responsibilities:

| Node | Hardware | Role |
|---|---|---|
| Node 1 | Seeed Studio XIAO ESP32-S3 Sense | Edge device — continuous audio streaming, camera, display |
| Node 2 | Raspberry Pi 5, 4 GB RAM | Management — initial client setup, user authentication, save storage, Web UI |
| Node 3 | Laptop (Ryzen 7 8840HS, Radeon 780M) | Main Brain — WebSocket server, streaming STT, VLM, TTS |

VELA is always listening. The interaction model is fluid: the trigger word **"Vela"** can appear anywhere in your sentence (e.g., *"What time is it, Vela?"* or *"Vela, turn on the lights"*). There are no buttons and no separate listening prompts. 

There are two special hardware-level commands that bypass the LLM entirely if detected in the transcript:
1. **Photo Flow:** Saying a phrase containing **"Vela"** and **"photo"** triggers the vision flow. The captured image is received by the server and treated like any other message, opening an 8-second active-listening window to ask questions about it, save it, or continue the conversation.
2. **Save Flow:** Saying a phrase containing **"Vela"** and **"save"** within the 8-second follow-up window sends the last exchange to the Pi 5's storage and confirms with an audio cue, keeping the conversation window open.

VELA supports multi-turn conversations. Each query in the follow-up window adds to the history and sends the full context to the inference layer. History is held in RAM on the Laptop and is cleared only when the 8-second window expires without a new utterance.

The system supports multiple users. Each client authenticates with a username and password via the Pi 5; all saved exchanges are stored per-user and are accessible via a Web UI hosted on the Pi.

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

The ESP32 has no local wake word or STT logic. On boot, it connects to the Pi 5 to authenticate and retrieve the Laptop's current IP address. Once authenticated, it drops the Pi 5 connection and opens a persistent WebSocket directly to the Laptop, continuously streaming PCM audio.

If no WiFi credentials or account details are stored in NVS flash on first boot, the ESP32 enters Access Point mode and guides the user through setup entirely by voice and a small captive-portal web page.

### Node 2 — Management (Raspberry Pi 5)

- **Low Power & Always On** (~5–8 W)
- Runs a lightweight FastAPI web application exposing:
  1. An endpoint for client setup and authentication (validating against a local SQLite database).
  2. An internal REST API for the Laptop to push saves to the SSD.
  3. A user-facing Web UI (accessible via local browser) to register accounts, manage credentials, and view the gallery of saved voice/vision exchanges.
- Manages per-user save storage on the SSD: one folder per saved exchange, containing metadata JSON and (for vision saves) the captured JPEG.

*(Note: The Pi 5 no longer processes STT, TTS, or wake words. Its role is strictly orchestration, storage, and UI).*

### Node 3 — Main Brain (Laptop)

- **Always listening** when the assistant is active. (Wake-on-LAN is deprecated; the laptop manages the live connection).
- Runs the primary FastAPI WebSocket server handling the full continuous audio stream from the ESP32.
- Uses **Sherpa-ONNX** (or Vosk) for real-time streaming Speech-to-Text (STT), transcribing speech *as it arrives* rather than waiting for sentence completion.
- Evaluates the live STT transcript for the word "Vela". If detected, it processes the surrounding words to extract the query or special commands ("photo" / "save").
- Maintains the per-session **conversation history buffer** (capped at 8 turns).
- Runs the Vision Language Model natively within the Python process via `llama-cpp-python` (Vulkan backend) and Piper TTS for instant audio generation, avoiding HTTP loopback overhead.
- BIOS UMA Frame Buffer set to 4 GB (or Auto) for the integrated Radeon 780M.

---

## Software Stack

| Layer | Tool | Node |
|---|---|---|
| Firmware | C++ / PlatformIO (Arduino framework) | ESP32 |
| Management Web UI | Python / FastAPI / Jinja / SQLite | Pi 5 |
| Primary WS Server | Python / FastAPI | Laptop |
| STT (Streaming) | Sherpa-ONNX | Laptop |
| TTS | piper-tts — `it_IT-riccardo-x_low` | Laptop |
| VLM runtime | llama-cpp-python (Vulkan backend) | Laptop |
| VLM model | Qwen3-VL-8B Q4_K_M | Laptop |
| Android client | Kotlin, OkHttp WebSocket + HTTP, AudioTrack, CameraX | Android device |

---

## Repository Structure

```
vela/
├── firmware/              # ESP32 firmware (C++, PlatformIO)
│   ├── src/main.cpp
│   └── platformio.ini
│
├── server_pi5/            # Pi 5 Management Server (Python)
│   ├── main.py                # FastAPI Web UI and Auth server
│   ├── storage.py             # Per-user save logic, folder management
│   ├── templates/             # Jinja HTML templates for Web UI
│   └── requirements.txt
│
├── server_laptop/         # Laptop Main Brain (Python)
│   ├── main_brain.py          # Primary WebSocket server
│   ├── stt_stream.py          # Sherpa-ONNX integration
│   ├── ai_engine.py           # llama-cpp-python and Piper TTS logic
│   └── requirements.txt
│
├── android/               # Android application (Kotlin)
│   └── app/src/
│
└── docs/                  # Tesina documentation, diagrams, schematics
```

---

## Communication Protocol

### Connection & Setup Handshake (Client ↔ Pi 5)

On boot, the client contacts the Pi 5 to authenticate.

```json
→ POST http://<PI5_IP>:8000/auth
  { "username": "alice", "password_hash": "<sha256>" }
← 200 OK
  { "success": true, "laptop_ws_url": "ws://<LAPTOP_IP>:8765/ws", "token": "<session_token>" }
```

### Main Operational Loop (Client ↔ Laptop WebSocket)

Once authenticated, the client connects to the Laptop via WebSocket.

```json
→ { "type": "auth", "token": "<session_token>" }
→ { "type": "audio_chunk", "data": "<base64_pcm>", "seq": 42 } // Continuous stream
→ { "type": "image", "data": "<base64_jpeg>" }                 // Sent after photo countdown
→ { "type": "control", "cmd": "reset" }

← { "type": "control", "cmd": "photo_mode" }           // Trigger camera 3-2-1
← { "type": "control", "cmd": "save_window_open" }     // 8s active listening starts
← { "type": "control", "cmd": "save_window_closed" }   // 8s window expires
← { "type": "control", "cmd": "save_confirmed" }       // Save successful
← { "type": "audio_chunk", "data": "<base64_wav>" }    // Synthesized TTS audio
← { "type": "audio_end" }                              // TTS complete
← { "type": "status", "state": "listening" }           // Optional UI status
```

### Save Storage (Laptop ↔ Pi 5 HTTP REST)

When the user requests a save, the Laptop packages the history and makes an internal request to the Pi 5:

```
POST http://<PI5_IP>:8000/api/saves
Payload: User ID, text exchange JSON, and (if applicable) base64 JPEG.
```

---

## Data Flows

### Boot and setup flow

```
POWER ON
 └─ WiFi credentials + account details in NVS?
     ├─ NO  → start Access Point ("VELA-Setup")
     │         TTS speaks instructions.
     │         Captive portal: SSID, passwords, VELA credentials.
     │         Credentials saved to NVS → reboot
     └─ YES → connect to saved WiFi network
               └─ authenticate with Pi 5 → get Laptop WS URL
                   └─ connect WebSocket to Laptop
                       → IDLE — always-listening loop begins
```

### The "Vela" Trigger & Voice Flow

Because STT is streaming in real-time, the Laptop constantly holds a sliding window of the transcript.

1. ESP32 streams PCM chunks to the Laptop continuously. Amplifier is muted via `SD_MODE`.
2. Laptop's Sherpa-ONNX processes each chunk in real time.
3. If the transcript contains **"Vela"**, the server locks onto that utterance.
4. It parses the string for the keywords `photo` or `save`.
5. If it's a **general query**, the string (minus "Vela") is appended to history and passed directly to the VLM (`llama-cpp-python`).
6. As the VLM generates tokens, sentences are chunked and sent to Piper TTS.
7. Laptop streams PCM/WAV audio chunks. Client unmutes `SD_MODE`, plays audio. TFT display shows subtitle text.
8. Laptop sends `audio_end`. Client mutes amplifier.
9. Laptop sends `save_window_open`. Display remains on showing the last response. 8-second window begins.
10. Any detected "Vela" restarts the pipeline (Step 3). Silence for 8s clears history and closes window.

### Photo Flow

1. User says a phrase with **"Vela"** and **"photo"** (e.g., *"Let's take a photo, Vela"*).
2. Laptop detects intent, bypasses VLM, and sends `{ "type": "control", "cmd": "photo_mode" }`.
3. Client enters camera preview loop: OV2640 at ~5 fps. TFT display shows live preview with 3–2–1 countdown overlay.
4. At zero, client captures full-resolution JPEG and sends it to Laptop.
5. Laptop receives the image. It is added to the conversation context.
6. The Laptop automatically opens the 8-second follow-up window without generating an AI response yet. The user can now say: *"Vela, what is in this picture?"* or *"Vela, save this"*.

### Save Flow

1. User says a phrase with **"Vela"** and **"save"** during an active 8-second follow-up window.
2. Laptop detects intent and extracts the **last exchange only** (most recent user turn + assistant response + optional image) from RAM.
3. Laptop makes a fast HTTP POST to the Pi 5 to write the data to the SSD.
4. Laptop immediately generates a short TTS clip ("Saved" / "Salvato") and streams it to the ESP32.
5. Laptop sends `save_confirmed`. The 8-second window resets, allowing the conversation to continue seamlessly.

---

## AI Models

| Task | Model / Tech | Quantisation | Node |
|---|---|---|---|
| STT | Sherpa-ONNX (Streaming) | — | Laptop |
| VLM | Qwen3-VL-8B | Q4_K_M | Laptop |
| TTS | Piper it_IT-riccardo-x_low | — | Laptop |

**VLM Integration:** Using `llama-cpp-python` allows the VLM to run within the same Python process as the WebSocket server. This drastically reduces latency by avoiding HTTP loopback overhead and allows direct memory access between the text parser and the LLM inference engine. The Vulkan backend (`-DGGML_VULKAN=on`) ensures the Radeon 780M is fully utilized.

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
| Authentication failure on connect | Pi 5 rejects auth; ESP32 plays TTS auth error clip; connection closed |
| WebSocket drop (ESP32 ↔ Laptop) | Automatic silent reconnection and re-authentication in the background |
| WiFi connection failure on boot | TTS speaks error message; device retries or re-enters AP setup mode |
| STT returns empty/no query | Laptop discards the utterance and returns to idle silently |
| Save write failure (disk full) | Laptop plays "Non è stato possibile salvare" clip |
| History exceeds token budget | Oldest turns are silently dropped; most recent 8 turns are retained |

---

## TFT Display

The ILI9341 240×320 SPI TFT has three operating states:

- **Off** — default when idle, listening, or during inference wait. Powered off to save energy.
- **Subtitle mode** — active during TTS playback and throughout the post-response follow-up window. Shows response text as a scrolling display synchronised with audio.
- **Camera viewfinder** — active during the photo countdown. Shows live colour preview from the OV2640 at ~5 fps with a 3–2–1 countdown overlay.

The display never shows system status or IP addresses during normal operation.

---

## Storage, Web UI, and Retrieval

The Pi 5 acts as the secure vault and management interface for VELA. 

By navigating to `http://<PI5_IP>:8000` on any local browser, users can access the **Web UI** to:
1. **Register/Login:** Create and manage user accounts securely.
2. **Dashboard:** View a clean UI of all saved text queries.
3. **Gallery:** View saved images alongside the conversation that accompanied them.

Each saved exchange is stored as a dedicated folder on the Pi 5's SSD:

```
/vela-data/
  users/
    alice/
      saves/
        2026-03-22T14-30-00/
          exchange.json          ← voice save
        2026-03-22T16-45-11/
          exchange.json          ← vision save
          image.jpg              ← captured JPEG
```

---

## Multi-User System

VELA supports multiple simultaneous users, each with isolated credentials and save storage.

- **Authentication** occurs via the Pi 5 on boot. The Pi 5 validates the credentials against an SQLite database and returns a session token.
- **Session isolation** is maintained by the Laptop WebSocket server. Each connection carries its authenticated token and its own conversation history buffer.
- **Saves** are written to the authenticated user's directory on the Pi 5. No user can access another user's saves via the Web UI.
- **Concurrent connections** are fully supported. Multiple clients can be connected simultaneously.

---

## Android Client

The Android application replicates the ESP32 behaviour exactly. There are no on-screen controls for triggering the assistant — the app uses the same flexible **"Vela"** interaction model.

- **Settings screen:** On first launch, the user enters the Pi 5 IP address, their username, and password.
- **Authentication:** The app authenticates with the Pi 5 via HTTP, receives the Laptop WebSocket URL, and connects.
- **Audio streaming:** PCM chunks are streamed continuously via OkHttp WebSocket.
- **Photo flow:** On `photo_mode`, the app opens the rear camera (CameraX) full-screen with a 3–2–1 countdown, captures a JPEG, and sends it to the Laptop.
- **Subtitle display:** During playback and the 8-second window, response text is shown on screen.
- **Save retrieval:** The app can list the authenticated user's saves by querying the Pi 5 HTTP API.

---

## Latency Budget

With Wake-on-LAN deprecated, STT natively streaming, and VLM running in the same Python process, latency is drastically reduced compared to previous iterations.

| Phase | Estimated time |
|---|---|
| Audio streaming (continuous) | — |
| Streaming STT (Sherpa-ONNX) | Instantaneous (partial transcripts arrive live) |
| VLM time-to-first-token (via llama-cpp-python) | 300–800 ms |
| TTS first chunk (Piper) | < 200 ms |
| Audio transmission to client | ~20 ms |
| Save write to Pi 5 SSD (over API) | < 50 ms |
| **Total perceived latency (Voice)** | **~0.5–1.2 s** |
| **Total perceived latency (Vision)** | **~2.0–3.5 s** |

---

## Setup and Deployment

### Node 2 — Pi 5 (Management & Web UI)

```bash
pip install fastapi uvicorn jinja2 aiosqlite
uvicorn server_pi5.main:app --host 0.0.0.0 --port 8000
```
Navigate to `http://<PI5_IP>:8000` to create your first user account before connecting clients. Ensure the SSD is mounted and the `/vela-data/` directory is writable.

### Node 3 — Laptop (Main Brain)

```bash
# Install llama-cpp-python with Vulkan support for the Radeon GPU
CMAKE_ARGS="-DGGML_VULKAN=on" pip install llama-cpp-python
pip install fastapi websockets sherpa-onnx piper-tts

# Start the main WebSocket and AI engine
python server_laptop/main_brain.py
```

### Node 1 — ESP32

```bash
cd firmware
pio run --target upload
```

On first boot with no stored credentials, the device enters AP setup mode and guides the user through WiFi and account configuration by voice. The VELA username and password entered during setup must match an account created on the Pi 5 Web UI.

---

## License

To be defined.
