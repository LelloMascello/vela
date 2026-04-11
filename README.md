# VELA — Voice Edge Local Assistant

A fully local, privacy-first voice AI assistant. VELA listens continuously, responds via synthesised speech, and keeps all processing within the local network.

Developed as a *Tesina di Maturità* (Italian high school final examination project).

---

## Table of Contents

- [Overview](#overview)
- [Hardware Architecture](#hardware-architecture)
- [Software & Services](#software--services)
- [Operational Flow](#operational-flow)

---

## Overview

VELA is composed of a client node and two server nodes. The Raspberry Pi orchestrates the session and owns the wake word engine; the laptop runs all AI inference. The key design choice is **native audio inference**: Gemma 4 E4B accepts raw audio directly, eliminating the traditional STT → LLM pipeline in favour of a single end-to-end model call.

---

## Hardware Architecture

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

---

## Software & Services

### Client responsibilities

- Initial network configuration via WiFiManager access point
- Continuous upstream of raw audio to Server 1
- Downstream playback of received audio response chunks

### Server 1 — Raspberry Pi responsibilities

- **Wake word engine** — continuously analyses the audio stream and detects "Vela"
- **Connection router** — hands the live stream to the laptop on detection; resumes control after session closure
- **Database** — stores full conversation transcripts and user profiles
- **Web / config server** — hosts the chat history viewer and system settings interface

### Server 2 — Laptop responsibilities

- **Gemma 4 E4B (VLM)** — accepts raw audio natively; no separate STT engine required
- **TTS engine** — converts token output to audio chunks gated by sentence boundary, streamed in real time
- **Session management** — active listening loop, unified silence counter, follow-up window, session closure

---

## Operational Flow

### States overview

```
                     ┌──────────────────────┐
                ┌───>│  Passive listening   │<──────────────────────────┐
                │    │  Pi owns stream      │                           │
                │    └──────────┬───────────┘                           │
                │               │ "Vela" detected                       │
                │               v                                       │
                │    ┌──────────────────────┐                           │
                │    │  Play audio cue      │                           │
                │    │  "Come posso esserti │                           │
                │    │   utile?"            │                           │
                │    └──────────┬───────────┘                           │
                │               │                                       │
                │               v                                       │
                │    ┌──────────────────────┐   silence > 8 s &         │
                │    │  Active listening    │── never spoke ────────────┘
                │    │  laptop owns stream  │
                │    └──────────┬───────────┘
                │               │ speech ended
                │               v
                │    ┌──────────────────────┐
                │    │  Generate response   │
                │    │  Gemma 4 E4B ──> TTS │<─────────────────┐
                │    │  ──> stream chunks   │                  │
                │    └──────────┬───────────┘                  │
                │               │                              │
                │               v                              │
                │    ┌──────────────────────┐ speech detected  │
                │    │  Follow-up window    │──────────────────┘
                │    │  silence counter     │
                │    │  resets to 0         │
                │    └──────────┬───────────┘
                │               │ silence > 8 s
                │               v
                │    ┌──────────────────────┐
                └────│  Close session       │
                     │  send transcript → Pi│
                     └──────────────────────┘
```

> **Silence counter:** one shared timer. If the user never spoke after the wake word, the session times out at 8 s. The same 8 s threshold applies during the follow-up window after response playback ends.

---

### 1. Setup & profile sync

On first boot the ESP32 opens a WiFiManager access point. After the user enters network credentials, the client connects to the Raspberry Pi and downloads the user profile and system configuration.

### 2. Passive listening

The client streams audio continuously to the Pi. The Pi's wake word engine analyses the stream in real time. Nothing is forwarded to the laptop during this phase.

### 3. Wake word detected

When "Vela" is recognised, the Pi routes the live audio connection to the laptop and immediately sends an audio cue back to the client: *"Come posso esserti utile?"* The silence counter starts at zero and `neverTalked` is set to `true`.

### 4. Active listening

The laptop buffers incoming audio. If speech is detected and then ends, the system moves to response generation and sets `neverTalked = false`. The silence counter increments each second in parallel. If it exceeds 8 s while `neverTalked` is still `true` — the user never spoke after the wake word — the session times out and routing returns to the Pi.

### 5. Response generation

Gemma 4 E4B processes the buffered audio natively — no speech-to-text conversion occurs. As the model emits text tokens they are piped into the TTS engine, which releases an audio chunk each time it reaches a sentence boundary. Chunks stream to the client immediately for low-latency playback.

### 6. Follow-up window & session closure

Once the final audio chunk is sent the silence counter resets to zero. If the user speaks within 8 s, the new audio is appended to the session context and the generation cycle repeats. If 8 s of silence elapse, the laptop sends the full transcript to the Pi for storage and routing returns to passive listening.
