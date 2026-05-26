#!/bin/bash

# Function to cleanly stop all services when you press Ctrl+C
cleanup() {
    echo -e "\n[!] Stopping all FastAPI services..."
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
# Ensure the Docker daemon is running (requires sudo)
sudo systemctl start docker

# Check if the local-mongo container already exists
if [ "$(docker ps -a -q -f name=^local-mongo$)" ]; then
    # If it exists but is currently stopped, start it
    if [ ! "$(docker ps -q -f name=^local-mongo$)" ]; then
        echo "[+] Starting existing MongoDB container (local-mongo)..."
        docker start local-mongo > /dev/null
    else
        echo "[+] MongoDB container (local-mongo) is already running."
    fi
else
    # Create and run the container for the first time
    echo "[+] Provisioning new MongoDB container (local-mongo)..."
    docker run -d --name local-mongo -p 27017:27017 -v mongo_data:/data/db mongo:7 > /dev/null
fi

echo "[+] Starting FastAPI dev services..."

# 1. Engine - main.py (Port 8002)
(cd engine && exec .venv/bin/fastapi dev main.py --port 8002) &
PIDS+=($!)

# 2. Engine - text_to_speech.py (Port 8003)
(cd engine && exec .venv/bin/fastapi dev text_to_speech.py --port 8003) &
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