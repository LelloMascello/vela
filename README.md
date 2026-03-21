# VELA — Voice Edge Local Assistant

> A fully local, privacy-first multimodal AI assistant built on a three-node edge-to-server architecture.
> No cloud dependency. No data leaves the local network.

---

## Overview

VELA is an embedded AI assistant capable of processing voice input and visual input in real time.
The system captures audio and images at the edge, performs speech recognition and text-to-speech synthesis
on a dedicated middleware node, and delegates vision-language inference to a local server.
The entire pipeline operates on a local Wi-Fi network, with a measured end-to-end latency under two seconds.

The project explores the intersection of embedded systems, edge computing, and on-device AI,
demonstrating that multimodal AI assistants can be deployed without relying on external cloud services.

---

## Architecture

The system is composed of three hardware nodes, each with a distinct and non-overlapping responsibility.

```
[ESP32-S3 Sense]  ←— Wi-Fi LAN —→  [Raspberry Pi 5]  ←— Ethernet —→  [Laptop / Server]
  Edge Node                          Middleware Node                     Inference Node
  Mic · Camera · OLED                STT · TTS · WebSocket              Vision LLM (VLM)
  Speaker · Buttons                  Always-on (5–8W)                   On-demand via WoL
```

### Node 1 — Edge Device (XIAO ESP32-S3 Sense)

The edge node is the physical interface between the user and the system.
It captures audio via the onboard PDM microphone and images via the integrated OV2640 camera.
A push-to-talk button initiates audio capture; a second button triggers a still image.
Audio is buffered in the 8MB PSRAM and streamed in chunks over WebSocket.
Images are JPEG-encoded and transmitted as Base64 JSON payloads.
An I2C OLED display provides real-time visual feedback: recording state, processing indicator,
and a scrolling transcription of the assistant's response.
Audio output is handled by a MAX98357A Class-D I2S amplifier connected to a passive speaker.
The amplifier's `SD_MODE` pin is software-controlled to mute the output during recording,
preventing microphone feedback.

### Node 2 — Middleware (Raspberry Pi 5, 8 GB)

The middleware node runs continuously at low power and manages the full voice pipeline.
It hosts a FastAPI WebSocket server, receives audio and image data from the edge node,
and coordinates the processing pipeline.

Speech-to-Text is handled by Faster-Whisper (Base or Small), running on the ARM CPU.
Text-to-Speech synthesis is performed by Piper TTS, using the `it_IT-riccardo-x_low` acoustic model.
Responses are streamed sentence-by-sentence to the edge node as audio begins playing
while synthesis of the remainder continues in parallel.

When an image arrives, the middleware checks whether the inference server is reachable.
If not, it transmits a Wake-on-LAN magic packet to power on the laptop, then forwards the request.
A pre-generated audio filler ("Un momento...") is sent to the edge node during any processing delay
exceeding 1.5 seconds, ensuring the user receives immediate feedback.

### Node 3 — Inference Server (Laptop)

The laptop is powered on exclusively when vision inference is required.
Because STT and TTS have been offloaded to the Raspberry Pi 5, the laptop's 24 GB of DDR5
are available almost entirely for the Vision Language Model.

The VLM runs under `llama.cpp` with Vulkan backend, which provides stable GPU acceleration
on the AMD Radeon 780M integrated GPU (RDNA3 architecture, gfx1103).
With a UMA frame buffer of 8 GB allocated in the BIOS, the model's layers can be fully
offloaded to the iGPU, improving token throughput significantly over CPU-only inference.
The `--mlock` flag ensures the model is pinned to physical RAM and never paged to ZRAM.

---

## Hardware Components

| Component | Model | Node |
|---|---|---|
| Microcontroller | Seeed Studio XIAO ESP32-S3 Sense | Edge |
| Microphone | Onboard PDM (GPIO 41/42, internal) | Edge |
| Camera | OV2640 (integrated on XIAO) | Edge |
| Amplifier | MAX98357A I2S Class-D, 3.2W | Edge |
| Speaker | Passive 3W 4Ω or 8Ω | Edge |
| Display | SSD1306 OLED 0.96" I2C | Edge |
| Buttons | 2× tactile push-button | Edge |
| Power | USB-C Power Bank | Edge |
| Middleware | Raspberry Pi 5 8GB | Middleware |
| Storage (Pi) | MicroSD 32GB Class A2 | Middleware |
| Inference | Laptop — Ryzen 7 8840HS, 24GB DDR5, Radeon 780M | Server |

---

## Pinout — XIAO ESP32-S3 Sense

The onboard PDM microphone uses internal GPIO 41/42 and does not occupy any header pins.
The I2S bus is therefore output-only, connecting exclusively to the amplifier.

### I2S Output (MAX98357A Amplifier)

| XIAO Pin | MAX98357A Pin | Signal |
|---|---|---|
| D7 | BCLK | Bit Clock |
| D8 | LRC | Word Select |
| D10 | DIN | Audio Data |
| D3 | SD_MODE | Mute control (GPIO) |

### I2C Display (SSD1306)

| XIAO Pin | SSD1306 Pin | Signal |
|---|---|---|
| D4 | SDA | Data |
| D5 | SCL | Clock |

### Buttons

| XIAO Pin | Function | Wiring |
|---|---|---|
| D1 | Push-to-Talk (audio) | One leg to GND |
| D2 | Photo capture | One leg to GND |

Both buttons are configured as `INPUT_PULLUP` in firmware.

### Power

| XIAO Pin | Destination |
|---|---|
| 3V3 | VIN (MAX98357A), VCC (SSD1306) |
| GND | All module grounds |

Free pins available for future expansion: D0, D6, D9.

---

## Software Stack

### Edge Firmware (ESP32-S3)

- Language: C++ (Arduino framework via PlatformIO)
- Audio capture: ESP-IDF PDM driver (onboard mic)
- Audio playback: ESP-IDF I2S driver (MAX98357A)
- Image capture: ESP32 Camera library (OV2640)
- Display: Adafruit SSD1306 / U8g2
- Network: `WebSocketsClient` library over Wi-Fi

### Middleware (Raspberry Pi 5)

- Runtime: Python 3.11+
- Server: FastAPI + `websockets`
- STT: `faster-whisper` (CTranslate2 backend)
- TTS: `piper-tts` (`it_IT-riccardo-x_low` model)
- Wake-on-LAN: `wakeonlan` Python library
- Async orchestration: `asyncio`

### Inference Server (Laptop)

- Runtime: `llama.cpp` (Vulkan build)
- Model: `qwen2-vl-7b-instruct-Q8_0.gguf` (recommended) or `llama3.2-vision-11b-Q8`
- Acceleration: Vulkan backend targeting AMD gfx1103
- Endpoint: HTTP REST, consumed by the Pi 5 middleware

---

## Communication Protocol

All communication between the edge node and the middleware uses a persistent WebSocket connection.
Each message carries a `type` field for routing.

```json
{ "type": "audio_chunk", "data": "<base64_pcm>", "seq": 42 }
{ "type": "audio_end",   "sample_rate": 16000, "channels": 1 }
{ "type": "image",       "data": "<base64_jpeg>", "prompt": "Descrivi cosa vedi" }
{ "type": "control",     "cmd": "reset" }
```

Downstream audio is sent as raw PCM/WAV chunks. The edge node begins playback
as soon as the first chunk arrives, while the server continues generating the remainder.

---

## AI Models

| Pipeline Stage | Model | Node | Latency |
|---|---|---|---|
| Speech-to-Text | Faster-Whisper Base/Small | Pi 5 (CPU) | 400–700 ms |
| Vision-Language | qwen2-vl:7b Q8 | Laptop (iGPU) | 800–2000 ms (TTFT) |
| Text-to-Speech | Piper TTS it_IT-riccardo-x_low | Pi 5 (CPU) | < 200 ms |

**Total perceived latency:** approximately 1.5–3 seconds from button release to first audio output.

---

## Repository Structure

```
vela/
├── firmware/               # ESP32-S3 PlatformIO project
│   ├── src/
│   │   ├── main.cpp
│   │   ├── audio.cpp
│   │   ├── camera.cpp
│   │   └── display.cpp
│   └── platformio.ini
├── middleware/             # Raspberry Pi 5 Python server
│   ├── server.py           # FastAPI WebSocket server
│   ├── stt.py              # Faster-Whisper wrapper
│   ├── tts.py              # Piper TTS wrapper
│   └── wol.py              # Wake-on-LAN utility
├── inference/              # Laptop-side llama.cpp config
│   └── start_server.sh     # Launch script with optimized flags
├── docs/
│   ├── architecture.md
│   ├── pinout.md
│   └── models.md
└── README.md
```

---

*VELA — Voice Edge Local Assistant*
