#!/usr/bin/env python3
"""
wake_word_detector.py — Vela Orchestrator · Wake Word Detection Service
=======================================================================
HTTP server (port 5002, internal — not exposed to clients).

Endpoints
---------
POST /detect
    Headers : Content-Type: application/octet-stream
              X-Client-Id: <unique string per active client>
    Body    : raw PCM audio bytes — 16 kHz, 16-bit, mono (little-endian)
    Response: { "detected": bool, "score": float, "client_id": str }

POST /reset
    Headers : X-Client-Id: <unique string>
    Resets the internal audio buffer and model state for that client.
    Response: { "status": "ok" }

GET /health
    Returns { "status": "ok", "loaded_models": [...] }

Implementation notes
--------------------
openWakeWord maintains an internal ring-buffer of recent audio frames so
that detections work correctly even when audio arrives in small chunks.
Because this state is per-client we keep a dict mapping client_id → Model
instance.  Instances are created lazily on the first /detect call and
destroyed on /reset (called by router.py when a client disconnects).

The default wake word is "hey_jarvis".  On first run openWakeWord will
download the ONNX model from GitHub Releases (~2 MB) into
~/.local/share/openwakeword/models/.
"""

import os
import threading
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request
from openwakeword.model import Model

# ─── Configuration ────────────────────────────────────────────────────────────

DETECTOR_PORT       = int(os.environ.get("VELA_DETECTOR_PORT", 5002))
WAKE_WORD           = os.environ.get("VELA_WAKE_WORD",         "hey_jarvis")
DETECTION_THRESHOLD = float(os.environ.get("VELA_THRESHOLD",   0.5))
INFERENCE_FRAMEWORK = os.environ.get("VELA_INFERENCE",         "onnx")

# ─── Per-client model registry ────────────────────────────────────────────────

_registry_lock  = threading.Lock()
_client_models: dict[str, Model] = {}   # client_id → openWakeWord Model


def _get_model(client_id: str) -> Model:
    """Return the Model instance for client_id, creating it if needed."""
    with _registry_lock:
        if client_id not in _client_models:
            print(f"[detector] Creating model instance for client={client_id!r}")
            _client_models[client_id] = Model(
                wakeword_models=[WAKE_WORD],
                inference_framework=INFERENCE_FRAMEWORK,
            )
        return _client_models[client_id]


def _drop_model(client_id: str) -> None:
    with _registry_lock:
        if client_id in _client_models:
            del _client_models[client_id]
            print(f"[detector] Released model for client={client_id!r}")


# Pre-load a "template" model at startup to trigger the one-time download
# and to verify the model name is valid before any client connects.
print(f"[detector] Pre-loading wake word model '{WAKE_WORD}' …")
try:
    _template_model = Model(
        wakeword_models=[WAKE_WORD],
        inference_framework=INFERENCE_FRAMEWORK,
    )
    print(f"[detector] Model ready.  Wake word: '{WAKE_WORD}'  "
          f"threshold: {DETECTION_THRESHOLD}")
except Exception as exc:
    print(f"[detector] ✗ Failed to load model: {exc}")
    raise SystemExit(1)


# ─── Flask app ────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/detect", methods=["POST"])
def detect():
    client_id  = request.headers.get("X-Client-Id", "default")
    audio_data = request.data

    if len(audio_data) < 2:
        return jsonify({"detected": False, "score": 0.0, "client_id": client_id})

    # Convert raw PCM bytes → int16 numpy array
    try:
        audio = np.frombuffer(audio_data, dtype=np.int16)
    except Exception as exc:
        return jsonify({"error": f"Bad audio data: {exc}"}), 400

    if len(audio) == 0:
        return jsonify({"detected": False, "score": 0.0, "client_id": client_id})

    # Run prediction (model accumulates audio internally)
    model      = _get_model(client_id)
    prediction = model.predict(audio)

    score    = float(prediction.get(WAKE_WORD, 0.0))
    detected = score >= DETECTION_THRESHOLD

    return jsonify({
        "detected":  detected,
        "score":     score,
        "client_id": client_id,
    })


@app.route("/reset", methods=["POST"])
def reset():
    client_id = request.headers.get("X-Client-Id", "default")
    _drop_model(client_id)
    return jsonify({"status": "ok", "client_id": client_id})


@app.route("/health", methods=["GET"])
def health():
    with _registry_lock:
        active = list(_client_models.keys())
    return jsonify({
        "status":        "ok",
        "service":       "wake_word_detector",
        "wake_word":     WAKE_WORD,
        "threshold":     DETECTION_THRESHOLD,
        "active_clients": active,
    })


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[detector] Listening on 127.0.0.1:{DETECTOR_PORT}  (internal only)")
    # threaded=True so concurrent audio chunks don't block each other
    app.run(host="127.0.0.1", port=DETECTOR_PORT, threaded=True)
