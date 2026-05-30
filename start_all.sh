#!/bin/bash

# ── Load .env (selective export — avoids polluting shell with PORT etc.) ───────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "[!] .env file not found at $ENV_FILE — aborting."
    exit 1
fi

# Parse the .env manually: skip blank lines and comments, export only real
# KEY=VALUE pairs.  This avoids "set -a" which would re-export every existing
# shell variable (e.g. an empty PORT) and confuse tools like `fastapi dev` that
# reserve the same names for their own CLI flags.
while IFS= read -r line || [[ -n "$line" ]]; do
    # Strip leading whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    # Skip empty lines and comments
    [[ -z "$line" || "$line" == \#* ]] && continue
    # Must be KEY=VALUE
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    # Skip keys that contain spaces (malformed)
    [[ "$key" =~ [[:space:]] ]] && continue
    export "$key=$value"
done < "$ENV_FILE"

echo "[+] Loaded configuration from $ENV_FILE"

# ── Sanity-check critical variables ───────────────────────────────────────────
missing=()
for var in PORT_ROUTER PORT_DETECTOR PORT_MAIN PORT_TTS PORT_STT \
           PORT_WEBSITE PORT_INFERENCE PORT_MONGODB \
           MAIN_WS_HOST WHISPER_BIN WHISPER_MODEL \
           LLAMA_BIN LLAMA_MODEL LLAMA_GPU_LAYERS \
           PIPER_BIN PIPER_MODEL PIPER_SAMPLE_RATE; do
    [[ -z "${!var}" ]] && missing+=("$var")
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "[!] Missing or empty variables in .env: ${missing[*]}"
    echo "[!] Aborting."
    exit 1
fi

# ── Cleanup ───────────────────────────────────────────────────────────────────

PIDS=()

cleanup() {
    echo -e "\n[!] Stopping all services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done

    echo "[!] Stopping MongoDB container..."
    docker stop local-mongo 2>/dev/null

    wait
    echo "[+] All services stopped successfully."
    exit 0
}

trap cleanup SIGINT SIGTERM

# ── MongoDB ───────────────────────────────────────────────────────────────────

echo "[+] Starting system dependencies..."
sudo systemctl start docker

if [ "$(docker ps -a -q -f name=^local-mongo$)" ]; then
    if [ ! "$(docker ps -q -f name=^local-mongo$)" ]; then
        echo "[+] Starting existing MongoDB container (local-mongo)..."
        docker start local-mongo > /dev/null
    else
        echo "[+] MongoDB container (local-mongo) is already running."
    fi
else
    echo "[+] Provisioning new MongoDB container (local-mongo)..."
    docker run -d --name local-mongo \
        -p "${PORT_MONGODB}:27017" \
        -v mongo_data:/data/db mongo:7 > /dev/null
fi

# ── Python services ───────────────────────────────────────────────────────────
# NOTE: `fastapi dev` reads a PORT env var for its own --port flag, so we
# explicitly unset it in each subshell before passing our own --port value.

echo "[+] Starting services..."

# 1. Engine - main.py (PORT_MAIN)
(cd engine && unset PORT && exec .venv/bin/fastapi dev main.py \
    --host 0.0.0.0 --port "${PORT_MAIN}") &
PIDS+=($!)

# 2. Engine - text_to_speech.py (PORT_TTS)
(cd engine && unset PORT && exec .venv/bin/fastapi dev text_to_speech.py \
    --port "${PORT_TTS}") &
PIDS+=($!)

# 3. whisper-server (PORT_STT)
"${WHISPER_BIN}" \
    --model    "${WHISPER_MODEL}" \
    --host     127.0.0.1 \
    --port     "${PORT_STT}" \
    --language it \
    --threads  "$(nproc)" \
    --beam-size 1 \
    --best-of  1 \
    --no-timestamps &
PIDS+=($!)

# 4. Orchestrator - router.py (PORT_ROUTER)
(cd orchestrator && unset PORT && exec .venv/bin/fastapi dev router.py \
    --host 0.0.0.0 --port "${PORT_ROUTER}") &
PIDS+=($!)

# 5. Orchestrator - wake_word_detector.py (PORT_DETECTOR)
(cd orchestrator && unset PORT && exec .venv/bin/fastapi dev wake_word_detector.py \
    --port "${PORT_DETECTOR}") &
PIDS+=($!)

# 6. Orchestrator - website.py (PORT_WEBSITE)
(cd orchestrator && unset PORT && exec .venv/bin/fastapi dev website.py \
    --host 0.0.0.0 --port "${PORT_WEBSITE}") &
PIDS+=($!)

# 7. llama.cpp server (PORT_INFERENCE)
"${LLAMA_BIN}" \
    -m "${LLAMA_MODEL}" \
    --host 127.0.0.1 \
    --port "${PORT_INFERENCE}" \
    -ngl "${LLAMA_GPU_LAYERS}" \
    --reasoning off &
PIDS+=($!)

echo "[+] All services are up and running!"
echo "[+] Press Ctrl+C to stop all services at once."

wait