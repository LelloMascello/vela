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

**IT** — Vela è un assistente vocale general-purpose progettato per girare su hardware consumer distribuito. Il nome è anche la wake word: pronunciare *"Vela"* avvia una sessione conversazionale. Il sistema è composto da tre nodi che si coordinano in rete locale: il client (ESP32-S3 o Android) cattura e riproduce l'audio, il Raspberry Pi 5 gestisce l'orchestrazione e il database, il laptop esegue il modello AI e la sintesi vocale. Inoltre, sono presenti servizi dedicati per la rilevazione vocale (VAD) e l'inferenza del modello linguistico.

**EN** — Vela is a general-purpose voice assistant designed to run across consumer distributed hardware. The name is also the wake word: saying *"Vela"* starts a conversational session. The system is made of three networked nodes: the client (ESP32-S3 or Android) captures and plays back audio, the Raspberry Pi 5 handles orchestration and the database, and the laptop runs the AI model and TTS engine. Additionally, dedicated services for voice detection (VAD) and model inference are implemented.

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
└─────────────────────┘                          │ stream handoff
          ^                                      ┌──────────────────────────┐
          │                                                  │ audio detection
          │                                                  v
          │        audio response (chunks)       │          Audio Detector (9001)
          └───────────────────────────────────── ┌──────────────────────────┐
                                                 │  (VAD Service)
                                                 │  (audio-detector.py)
                                                 └──────────────────────────┘
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │
                                                 │