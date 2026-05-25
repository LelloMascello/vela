# vela

> Documentation generated automatically by AutoDocs.

## Overview

Vela is a system designed for real-time audio processing, featuring user authentication, a WebSocket interface for audio streaming, and an integrated voice pipeline. The system utilizes a FastAPI backend for handling real-time connections, integrating a Silero VAD for speech detection, a local LLM (Gemma 4), and a Text-to-Speech service to create a complete voice interaction pipeline.

The voice pipeline handles the flow: client audio (PCM) is processed by a Silero VAD, denoised, speech segments are sent to the LLM for text generation, the resulting text is sent to a TTS service, and the audio chunks are streamed back to the client. This process is managed by a sophisticated streaming mechanism that handles LLM token generation, real-time audio synthesis forwarding, and implements a silence timeout mechanism to automatically close connections if no speech is detected for too long.

## Components

### Engine Core (`engine/main.py`)

This module sets up the core FastAPI application and orchestrates the entire real-time voice pipeline:
*   **`/ready` (GET):** Launches necessary backend services (LLM server and TTS server) and reports the current operational status, IP, and port.
*   **`/ws` (WebSocket):** Implements the full voice pipeline. It handles client audio (PCM) processing via VAD, denoising, checks for silence timeouts, feeds speech segments to the LLM for text generation, forwards the resulting text to a TTS service, and streams the synthesized audio chunks back to the client.
*   **Audio Utilities:** Provides core functions for VAD iteration, PCM encoding to WAV format, and TTS audio forwarding.
*   **VAD Integration:** The Silero VAD model is loaded once at startup and shared across all connections, providing speech boundary detection.

### Inference Engine (`engine/inference.py`)

This module manages the interaction with the LLM and TTS services, handling the complex streaming logic:
*   **Service Lifecycle:** Responsible for launching and gracefully shutting down the `llama.cpp` (LLM server) subprocess.
*   **LLM Streaming:** Implements the logic to stream responses from the LLM. It processes incoming audio, sends it to the LLM endpoint, and uses the TTS service to synthesize and forward text chunks to the client in real-time.
*   **System Prompt:** Defines the behavior of the LLM to ensure voice-friendly, concise responses.

### Text-to-Speech Engine (`engine/text_to_speech.py`)

This module handles the text-to-speech functionality, receiving text phrases from the LLM and returning synthesized audio data.

### Authentication Service (`orchestrator/auth.py`)

This module handles user registration and login. It implements secure credential verification by using SQLite to store username and password hashes (using SHA256 and salts). It provides `signup` functionality to register new users and `login` functionality to verify credentials.

### Router and WebSocket Server (`orchestrator/router.py`)

The router acts as the main entry point for the application. It exposes HTTP endpoints (`/login`, `/signup`) for user management and a WebSocket endpoint (`/ws`) for real-time audio data handling, managing the complex voice pipeline flow.

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

## Testing Interface

A dedicated testing interface (`orchestrator/test_ui.html`) is no longer available.