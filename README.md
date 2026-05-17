# vela

> Documentation generated automatically by AutoDocs.

## Overview

Vela is a system designed for real-time audio processing, featuring user authentication, a WebSocket interface for audio streaming, and an integrated wake word detection mechanism. The system utilizes a FastAPI backend for handling real-time connections and status reporting.

## Components

### Engine Core (`engine/main.py`)

This module sets up the core FastAPI application, configuring CORS middleware and defining critical endpoints:
*   **`/ready` (GET):** Returns the current operational status, including readiness status, IP, and port.
*   **`/ws` (WebSocket):** Handles real-time audio streaming connections.

### Text-to-Speech Engine (`engine/text_to_speech.py`)

This module handles the text-to-speech functionality within the system.

### Authentication Service (`orchestrator/auth.py`)

This module handles user registration and login. It implements secure credential verification by using SQLite to store username and password hashes (using SHA256 and salts). It provides `signup` functionality to register new users and `login` functionality to verify credentials.

### Router and WebSocket Server (`orchestrator/router.py`)

The router acts as the main entry point for the application. It exposes HTTP endpoints (`/login`, `/signup`) for user management and a WebSocket endpoint (`/ws`) for real-time audio data handling. It manages communication between the client, the wake word detector, and other necessary servers.

### Wake Word Detector (`orchestrator/wake_word_detector.py`)

This service utilizes the `pvporcupine` library to perform real-time wake word detection on incoming audio streams. It exposes configuration endpoints (`/config`) and a detection endpoint (`/detect`) to process audio frames.

## Setup and Usage

The application is served via FastAPI, mounting static files from the `/public` directory.

*   **Accessing the Interface:** The main interface is served by serving `public/index.html` at the root path (`/`).
*   **Server Status Check:** Use the `/ready` endpoint to check the operational status and connection details of the server.
*   **Authentication Endpoints:**
    *   **Sign Up:** POST to `/signup` (requires username and password).
    *   **Login:** POST to `/login` (requires username and password).
    *   **Authentication Check:** The `/auth` endpoint uses the `login` function to validate credentials and returns a WebSocket URL and the authenticated username upon success.
*   **Testing Interface:** A dedicated testing interface (`orchestrator/test_ui.html`) is available to test wake word detection functionality.