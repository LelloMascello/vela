# vela

> Documentation generated automatically by AutoDocs.

## Overview

Vela is a system designed for real-time audio processing, featuring user authentication, a WebSocket interface for audio streaming, and an integrated voice pipeline. The system utilizes a FastAPI backend for handling real-time connections, integrating a Silero VAD for speech detection, a local LLM (Gemma 4), and a Text-to-Speech service to create a complete voice interaction pipeline.

## Components

### Engine Core (`engine/main.py`)

This module sets up the core FastAPI application and orchestrates the entire real-time voice pipeline:
*   **`/ready` (GET):** Launches necessary backend services (LLM server and TTS server) and reports the current operational status, IP, and port.
*   **`/ws` (WebSocket):** Implements the full voice pipeline: client audio (PCM) is processed by a Silero VAD, speech segments are sent to the LLM for text generation, the resulting text is sent to a TTS service, and the audio chunks are streamed back to the client.

### Text-to-Speech Engine (`engine/text_to_speech.py`)

This module handles the text-to-speech functionality, receiving text phrases from the LLM and returning synthesized audio data.

### Authentication Service (`orchestrator/auth.py`)

This module handles user registration and login. It implements secure credential verification by using SQLite to store username and password hashes (using SHA256 and salts). It provides `signup` functionality to register new users and `login` functionality to verify credentials.

### Router and WebSocket Server (`orchestrator/router.py`)

The router acts as the main entry point for the application. It exposes HTTP endpoints (`/login`, `/signup`) for user management and a WebSocket endpoint (`/ws`) for real-time audio data handling, managing the complex voice pipeline flow.

### Wake Word Detector (`orchestrator/wake_word_detector.py`)

This service utilizes the `pvporcupine` library for real-time wake word detection. (Note: This functionality is now integrated into the main voice pipeline via Silero VAD for speech boundary detection.)

## Setup and Usage

The application is served via FastAPI, mounting static files from the `/public` directory.

*   **Accessing the Interface:** The main interface is served by serving `public/index.html` at the root path (`/`).
*   **Server Status Check:** Use the `/ready` endpoint to check the operational status and connection details of the server.
*   **Voice Pipeline Interaction:**
    *   **Audio Streaming:** Connect via WebSocket to `/ws` to stream raw PCM audio data.
    *   **Authentication Endpoints:**
        *   **Sign Up:** POST to `/signup` (requires username and password).
        *   **Login:** POST to `/login` (requires username and password).
        *   **Authentication Check:** The `/auth` endpoint uses the `login` function to validate credentials and returns a WebSocket URL and the authenticated username upon success.
*   **Testing Interface:** A dedicated testing interface (`orchestrator/test_ui.html`) is available to test wake word detection functionality.