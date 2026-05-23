#!/bin/bash

# 1. Start MongoDB service (will prompt for sudo password if required)
echo "[+] Starting MongoDB service..."
sudo systemctl start mongodb

# Array to keep track of background process IDs (PIDs)
PIDS=()

# Function to cleanly stop all services when you press Ctrl+C
cleanup() {
    echo -e "\n[!] Stopping all FastAPI services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    wait
    echo "[+] All services stopped successfully."
    exit 0
}

# Trap Ctrl+C (SIGINT) and termination signals to trigger cleanup
trap cleanup SIGINT SIGTERM

echo "[+] Starting FastAPI dev services..."

# 2. Engine - main.py (Port 8002)
(cd engine && exec .venv/bin/fastapi dev main.py --port 8002) &
PIDS+=($!)

# 3. Orchestrator - router.py (Port 8000)
(cd orchestrator && exec .venv/bin/fastapi dev router.py --port 8000) &
PIDS+=($!)

# 4. Orchestrator - wake_word_detector.py (Port 8001)
(cd orchestrator && exec .venv/bin/fastapi dev wake_word_detector.py --port 8001) &
PIDS+=($!)

# 5. Orchestrator - website.py (Port 8005)
(cd orchestrator && exec .venv/bin/fastapi dev website.py --port 8005) &
PIDS+=($!)

echo "[+] All services are up and running!"
echo "[+] Press Ctrl+C to stop all services at once."

# Keep the script running to monitor background processes
wait