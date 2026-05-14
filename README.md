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
- [Vela Orchestrator — Setup Guide](#vela-orchestrator--setup-guide)
- [Vela — Engine setup](#vela--engine-setup)
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
- Python 3.10+ on Pi and