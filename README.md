# vela

> Documentation generated automatically by AutoDocs.

## Overview

Vela is a system designed for real-time audio processing, featuring user authentication, a WebSocket interface for audio streaming, and an integrated wake word detection mechanism.

## Components

### Authentication Service (`orchestrator/auth.py`)

This module provides the core logic for user authentication, handling credential verification.

### Router and WebSocket Server (`orchestrator/router.py`)

The router acts as the main entry point, providing both HTTP authentication endpoints and a WebSocket endpoint (`/ws`) for real-time audio data handling. It manages communication between the client, the wake word detector, and other necessary servers.

### Wake Word Detector (`orchestrator/wake_word_detector.py`)

This service utilizes the `pvporcupine` library to perform real-time wake word detection on incoming audio streams. It exposes configuration endpoints (`/config`) and a detection endpoint (`/detect`) to process audio frames.

## Setup and Usage

*(No specific setup instructions were provided in the diff, so this section remains minimal, focusing on the architectural components introduced.)*