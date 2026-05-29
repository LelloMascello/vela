#!/bin/bash

WHISPER_BIN="/home/leo/whisper.cpp/build/bin/whisper-server"
WHISPER_MODEL="/home/leo/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin"

# Function to cleanly stop all services when you press Ctrl+C
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

# Trap Ctrl+C (SIGINT) and termination signals to trigger cleanup
trap cleanup SIGINT SIGTERM

echo "[+] Starting system dependencies..."
sudo systemctl start docker

# Check if the local-mongo container already exists
if [ "$(docker ps -a -q -f name=^local-mongo$)" ]; then
    if [ ! "$(docker ps -q -f name=^local-mongo$)" ]; then
        echo "[+] Starting existing MongoDB container (local-mongo)..."
        docker start local-mongo > /dev/null
    else
        echo "[+] MongoDB container (local-mongo) is already running."
    fi
else
    echo "[+] Provisioning new MongoDB container (local-mongo)..."
    docker run -d --name local-mongo -p 27017:27017 -v mongo_data:/data/db mongo:7 > /dev/null
fi

echo "[+] Starting services..."

# 1. Engine - main.py (Port 8002)
(cd engine && exec .venv/bin/fastapi dev main.py --host 0.0.0.0 --port 8002) &
PIDS+=($!)

# 2. Engine - text_to_speech.py (Port 8003)
(cd engine && exec .venv/bin/fastapi dev text_to_speech.py --port 8003) &
PIDS+=($!)

# 3. whisper-server replaces speech_to_text.py (Port 8004)
"$WHISPER_BIN" \
    --model "$WHISPER_MODEL" \
    --host 127.0.0.1 \
    --port 8004 \
    --language it \
    --threads $(nproc) \
    --beam-size 1 \
    --best-of 1 \
    --no-timestamps &
PIDS+=($!)

# 4. Orchestrator - router.py (Port 8000)
(cd orchestrator && exec .venv/bin/fastapi dev router.py --host 0.0.0.0 --port 8000) &
PIDS+=($!)

# 5. Orchestrator - wake_word_detector.py (Port 8001)
(cd orchestrator && exec .venv/bin/fastapi dev wake_word_detector.py --port 8001) &
PIDS+=($!)

# 6. Orchestrator - website.py (Port 8005)
(cd orchestrator && exec .venv/bin/fastapi dev website.py --host 0.0.0.0 --port 8005) &
PIDS+=($!)

# 7. llama.cpp server (Port 8080)
/home/leo/llama.cpp/build/bin/llama-server \
    -m /home/leo/llama.cpp/mymodels/gemma-4-E2B-it-UD-Q4_K_XL.gguf \
    --host 127.0.0.1 --port 8080 -ngl 99 --reasoning off &
PIDS+=($!)

echo "[+] All services are up and running!"
echo "[+] Press Ctrl+C to stop all services at once."

wait