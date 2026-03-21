# VELA — Voice Edge Local Assistant

A fully local, privacy-first multimodal AI assistant. VELA listens via voice, sees via camera, and responds via synthesised speech. No cloud services are involved; all processing occurs within the local network.

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
- [Android Client](#android-client)
- [Latency Budget](#latency-budget)
- [Setup and Deployment](#setup-and-deployment)

---

## Overview

VELA is composed of three hardware nodes working in concert:

| Node | Hardware | Role |
|---|---|---|
| Node 1 | Seeed Studio XIAO ESP32-S3 Sense | Edge device — user input/output |
| Node 2 | Raspberry Pi 5, 8 GB RAM | Middleware — always on, handles STT and TTS |
| Node 3 | Laptop (Ryzen 7 8840HS, Radeon 780M) | Inference server — on-demand vision language model |

The system also supports an Android application as an alternative client, implementing identical functionality to the ESP32 over the same WebSocket protocol.

---

## Hardware Architecture

### Node 1 — Edge Device (ESP32-S3)

- **MCU:** Seeed Studio XIAO ESP32-S3 Sense
  - Integrated OV2640 camera
  - Onboard PDM microphone (internal GPIO 41/42, uses no header pins)
  - 8 MB PSRAM for audio and image buffering
  - MicroSD slot
- **Audio output:** MAX98357A I2S Class-D amplifier (3.2 W) with passive 3 W 4 Ω/8 Ω speaker. The `SD_MODE` pin is connected to a GPIO for software mute during recording, preventing echo without additional hardware.
- **Display:** SSD1306 OLED 0.96" I2C
- **Input:** two tactile push-buttons
  - Button 1 (D1): Push-to-Talk
  - Button 2 (D2): Photo capture
- **Power:** USB-C power bank (always-on model recommended)
- **Firmware:** single-loop state machine (Arduino framework, PlatformIO)

The ESP32 connects to the Pi 5 on the first user button press and auto-reconnects silently in the background if the WebSocket connection drops.

### Node 2 — Middleware (Raspberry Pi 5)

- **Always on** (~5–8 W)
- Runs a FastAPI WebSocket server accepting connections from multiple clients concurrently. Each client gets an independent async handler coroutine.
- A separate inference worker process holds a shared `asyncio.Queue`. Handler coroutines push jobs into the queue; the worker processes them sequentially and routes results back to the originating handler.
- Sends a Wake-on-LAN magic packet to the laptop when a vision request arrives.
- Plays an audio filler clip ("Un momento...") if processing delay exceeds 1.5 seconds.
- All request handling is stateless: no conversation history is retained between requests.

### Node 3 — Inference Server (Laptop)

- **On-demand** — sleeps when idle, woken by the Pi 5 via Wake-on-LAN.
- Runs a llama.cpp WebSocket server with Vulkan backend.
- Communicates with the Pi 5 via WebSocket, streaming tokens as they are generated. The Pi 5 collects the full response before passing it to TTS.
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
| WebSocket server | FastAPI + websockets | Pi 5 |
| STT | faster-whisper (CTranslate2) — Small model | Pi 5 |
| TTS | piper-tts — `it_IT-riccardo-x_low` | Pi 5 |
| Wake-on-LAN | wakeonlan (Python) | Pi 5 |
| VLM runtime | llama.cpp (Vulkan backend) | Laptop |
| VLM model | qwen2-vl:7b Q8 | Laptop |
| Android client | Kotlin, OkHttp WebSocket, AudioTrack | Android device |

---

## Repository Structure

```
vela/
├── firmware/          # ESP32 firmware (C++, PlatformIO)
│   ├── src/
│   │   └── main.cpp
│   └── platformio.ini
│
├── server/            # Pi 5 server (Python)
│   ├── ws_server.py       # FastAPI WebSocket server, connection pool
│   ├── inference_worker.py # STT + TTS worker process, asyncio queue
│   └── requirements.txt
│
├── inference/         # Laptop inference configuration
│   ├── start_server.sh    # llama.cpp launch script with flags
│   └── models/            # Model weights (not committed to git)
│
├── android/           # Android application (Kotlin)
│   └── app/
│       └── src/
│
└── docs/              # Tesina documentation, diagrams, schematics
```

---

## Communication Protocol

All clients (ESP32 and Android) communicate with the Pi 5 via a persistent WebSocket connection. Every message is a JSON object with a `type` field.

### Client → Pi 5

```json
{ "type": "audio_chunk", "data": "<base64_pcm>", "seq": 42 }
```
Sent continuously while the user holds the Push-to-Talk button. Contains a sequential chunk of raw PCM audio (16 kHz, mono, 16-bit).

```json
{ "type": "audio_end", "sample_rate": 16000, "channels": 1 }
```
Sent when the PTT button is released. Signals that the full audio has been transmitted and STT can proceed.

```json
{ "type": "image", "data": "<base64_jpeg>", "prompt": "<transcribed_voice_prompt>" }
```
Sent after the user takes a photo and speaks a voice prompt. The Pi 5 waits for the voice prompt transcription before dispatching this message to the laptop.

```json
{ "type": "control", "cmd": "reset" }
```
Resets the current session state on the Pi 5.

### Pi 5 → Client

```json
{ "type": "audio_chunk", "data": "<base64_pcm_or_wav>", "seq": 5 }
```
A chunk of synthesised TTS audio to be played back immediately. Streamed sequentially.

```json
{ "type": "audio_end" }
```
Signals that TTS playback is complete.

```json
{ "type": "status", "state": "processing" }
```
Optional status update for display purposes (e.g., OLED state updates).

### Pi 5 → Laptop

Communication between the Pi 5 and the laptop uses a WebSocket connection to the llama.cpp server endpoint. The Pi 5 sends the image and prompt; the laptop streams tokens back. The Pi 5 accumulates the full response before dispatching to Piper TTS.

---

## Data Flows

### Voice flow

1. User holds Button 1 (PTT). Firmware mutes the MAX98357A via `SD_MODE`.
2. PDM microphone captures audio. ESP32 encodes PCM chunks and streams them over WebSocket.
3. User releases PTT. ESP32 sends `audio_end`.
4. Pi 5 inference worker runs Whisper STT (400–700 ms).
5. Pi 5 generates a text response (no VLM involved for voice-only requests).
6. Piper TTS synthesises the response (< 200 ms to first chunk).
7. Pi 5 streams PCM audio chunks back to the client.
8. Client plays audio via MAX98357A (ESP32) or `AudioTrack` (Android). `SD_MODE` is unmuted.

### Vision flow

1. User presses Button 2. OV2640 captures a JPEG image. OLED shows a waiting indicator.
2. Pi 5 receives the image and waits.
3. User holds Button 1 and speaks a prompt describing what they want to know about the image.
4. PTT released. Pi 5 transcribes the prompt via Whisper STT.
5. Pi 5 bundles the image (base64 JPEG) and the transcribed prompt into a single `image` message.
6. Pi 5 sends a Wake-on-LAN packet to the laptop if it is sleeping.
7. Pi 5 sends the request to the laptop via WebSocket.
8. llama.cpp streams tokens back. Pi 5 accumulates the full response.
9. Piper TTS synthesises the full response.
10. Pi 5 streams PCM audio back to the client.

---

## AI Models

| Stage | Model | Quantisation | RAM usage | Speed | Node |
|---|---|---|---|---|---|
| STT | Faster-Whisper Small | — | ~1.5 GB | 400–700 ms | Pi 5 |
| VLM | qwen2-vl:7b | Q8 | ~8 GB | 14–20 t/s | Laptop |
| VLM (alt) | llama3.2-vision:11b | Q8 | ~11 GB | 8–12 t/s | Laptop |
| VLM (alt) | InternVL2-26B | Q4 | ~19 GB | 4–7 t/s | Laptop |
| TTS | Piper it_IT-riccardo-x_low | — | < 200 MB | < 200 ms | Pi 5 |

The recommended VLM is `qwen2-vl:7b Q8`, which provides the best speed-to-quality balance given the available hardware. STT and TTS are offloaded entirely to the Pi 5, freeing approximately 13 GB of laptop RAM for a higher-quality quantisation level.

Vulkan is used as the llama.cpp backend instead of ROCm due to greater stability on the RDNA3 gfx1103 integrated GPU.

---

## Pinout Reference

| Pin | Connected to | Function |
|---|---|---|
| D7 | MAX98357A BCLK | I2S bit clock |
| D8 | MAX98357A LRC | I2S word select |
| D10 | MAX98357A DIN | I2S audio data out |
| D3 | MAX98357A SD_MODE | Amplifier mute (software-controlled) |
| D4 | SSD1306 SDA | I2C data |
| D5 | SSD1306 SCL | I2C clock |
| D1 | Button 1 | Push-to-Talk (INPUT_PULLUP → GND) |
| D2 | Button 2 | Photo capture (INPUT_PULLUP → GND) |
| 3V3 | VIN (amp), VCC (OLED) | Power |
| GND | All module grounds | Ground |
| D0, D6, D9 | — | Reserved for future use |

The onboard PDM microphone uses internal GPIO 41/42 and does not occupy any header pins.

---

## Error Handling

All user-facing errors are communicated through audio, keeping the interaction model consistent.

| Failure | Behaviour |
|---|---|
| WebSocket drop (ESP32 ↔ Pi 5) | Automatic silent reconnection in the background |
| Wake-on-LAN timeout (laptop unreachable) | Pi 5 plays a TTS error clip |
| STT returns empty or invalid transcription | Pi 5 plays "Non ho capito" audio clip |

---

## OLED Display

The SSD1306 display shows four categories of information:

- **System state** — one of: `idle`, `recording`, `processing`, `speaking`
- **Response text** — scrolling display of the last synthesised response
- **Connection status** — IP address of the Pi 5, WebSocket connection indicator
- **Language** — active language, as set at startup

---

## Android Client

The Android application provides identical functionality to the ESP32 hardware client, implemented natively in Kotlin.

- WebSocket communication via OkHttp, using the same protocol described above.
- PTT: hold button streams PCM audio chunks; release sends `audio_end`.
- Photo + prompt: camera capture followed by a spoken prompt, bundled into a single `image` message.
- TTS audio played back via `AudioTrack`.
- Settings screen for server IP address and language selection at startup.

Multiple clients (ESP32 and Android) may be connected to the Pi 5 simultaneously. Each connection is handled by an independent coroutine; inference requests are serialised through a shared queue.

---

## Latency Budget

Measured with the laptop already awake and on a local network.

| Phase | Estimated time |
|---|---|
| Audio transmission over LAN | ~10 ms |
| STT — Whisper Small on Pi 5 | 400–700 ms |
| Wake-on-LAN + laptop boot (if sleeping) | ~5 s |
| VLM time-to-first-token | 800–2000 ms |
| TTS first chunk — Piper | < 200 ms |
| Audio transmission to client | ~20 ms |
| **Total perceived latency (laptop awake)** | **~1.5–3 seconds** |

---

## Setup and Deployment

### Node 2 — Pi 5

```bash
pip install fastapi uvicorn websockets faster-whisper piper-tts wakeonlan
uvicorn server.ws_server:app --host 0.0.0.0 --port 8765
python server/inference_worker.py
```

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

Configure the Pi 5 IP address and language selection in `firmware/src/main.cpp` before flashing, or expose them as compile-time flags in `platformio.ini`.

---

## License

To be defined.
