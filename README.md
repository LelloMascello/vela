# VELA — Voice Edge Local Assistant

A fully local, privacy-first multimodal AI assistant. VELA listens continuously, sees via camera, and responds via synthesised speech. No cloud services are involved; all processing occurs within the local network.

Developed as a *Tesina di Maturità* (Italian high school final examination project).

---

## Table of Contents

- [Overview](#overview)
- [Hardware Architecture](#hardware-architecture)
- [Software & Services](#software--services)
- [Operational Flow](#operational-flow)

---

## Overview

VELA is an intelligent local assistant composed of a client node and two server nodes working in concert. The system supports continuous audio upstreaming, live transcription, and intelligent text-to-speech responses with a privacy-first design.

---

## Hardware Architecture

- **Client Node:** ESP32-S3 Sense (equipped with microphone, speaker, and display) OR a dedicated Android Application.
- **Server 1 (Orchestrator & Database):** Raspberry Pi 5 (4GB RAM, 512GB SSD).
- **Server 2 (AI Processing Engine):** High-performance laptop (AMD Ryzen 7 8840HS, 24GB RAM).

---

## Software & Services

### Client Responsibilities
- Initial network configuration.
- Continuous upstream of audio data.
- Downstream playback of received audio responses.

### Server 1 (Raspberry Pi) Responsibilities
- **Database Management:** Stores and retrieves chat histories.
- **Web/Configuration Server:** Hosts the user interface for viewing saved chats and managing configurations.
- **Wake Word Engine:** Continuously analyzes the incoming audio stream for the wake word ("Vela").
- **Connection Routing:** Hands off the active client connection to Server 2 upon wake word detection.

### Server 2 (Laptop) Responsibilities
- **Speech-to-Text (STT):** Live transcription of incoming audio chunks.
- **Vision-Language Model (VLM):** Generates intelligent responses based on the transcribed text (and visual context, if utilizing the ESP32-S3 Sense camera).
- **Text-to-Speech (TTS):** Converts the VLM's text tokens into streamable audio chunks.

---

## Operational Flow

### 1. Initial Setup & Configuration
The ESP32 initializes an Access Point using the WiFiManager library to allow the user to input local network credentials and connect the device to the Wi-Fi.

### 2. Profile Synchronization
Once connected to the network, the client connects to Server 1 (Raspberry Pi) to retrieve and load the user profile and system configurations.

### 3. Wake Word Detection (Idle State)
- The client begins continuously streaming audio to the Raspberry Pi.
- The Pi processes this stream specifically to detect the wake word, "Vela".
- When the wake word is detected, the Pi routes the active audio stream connection to Server 2 (Laptop).
- An audio cue is immediately sent back to the client to notify the user that the system is actively listening.

### 4. Active Transcription & AI Generation
Server 2 receives the audio stream in chunks and performs live transcription.
- When the STT engine detects a natural pause or long silence in the user's speech, it sends the completed transcription to the VLM.
- As the VLM generates text tokens, they are immediately piped into the TTS engine.
- The generated audio chunks are streamed directly back to the client and played out of the speaker.

### 5. Follow-up Window & Session Closure
After the final audio chunk of the VLM's response is sent to the client, Server 2 enters a 5-second active listening phase. During this window, the laptop continues to transcribe incoming audio:
- **If speech is detected:** The new text is appended to the ongoing chat history (maintaining conversational context) and sent back to the VLM. The generation and TTS playback cycle repeats, and the 5-second timer is reset.
- **If 5 seconds pass in silence:** Server 2 closes the active connection to the client. Routing control defaults back to the Raspberry Pi (returning to the Wake Word Detection state). Server 2 then sends the full conversation transcript to the Pi to be saved in the database.
