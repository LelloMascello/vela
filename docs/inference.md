# VELA — Nodo Inference
### Documentazione Tecnica — Node 3 (Laptop)

---

## Panoramica

Il nodo di inference è il componente responsabile dell'elaborazione multimodale (visione + linguaggio). Si attiva **su richiesta** tramite Wake-on-LAN inviato dal Pi 5, rimanendo in sleep quando non necessario.

| Proprietà | Valore |
|-----------|--------|
| Hardware | Laptop AMD Ryzen 7 8840HS |
| GPU | AMD Radeon 780M (RDNA3, gfx1103) |
| VRAM (UMA) | 8 GB (configurare nel BIOS) |
| Backend GPU | Vulkan (preferito a ROCm per stabilità su RDNA3) |
| Runtime | llama.cpp |
| OS testato | Arch Linux |

---

## Struttura della Directory

```
vela/inference/
├── llama-server          # Binario llama.cpp (non committato su git)
├── start_server.sh       # Script di avvio
└── models/               # Pesi modelli (non committati su git)
    ├── Qwen2-VL-7B-Instruct-Q8_0.gguf
    └── mmproj-Qwen2-VL-7B-Instruct-f16.gguf
```

> **Nota:** il binario `llama-server` e la cartella `models/` sono esclusi da git tramite `.gitignore`.

---

## Modelli Supportati

Il modello raccomandato è **Qwen2-VL-7B Q8**: entra completamente negli 8 GB di VRAM, offrendo il miglior rapporto qualità/velocità sull'hardware disponibile.

| Modello | Quantizzazione | VRAM richiesta | Velocità stimata | Note |
|---------|----------------|----------------|------------------|------|
| **Qwen2-VL-7B** | **Q8** | **~8 GB** | **14–20 t/s** | **Raccomandato** |
| Llama3.2-Vision-11B | Q4_K_M | ~7 GB | 10–14 t/s | Fit completo in VRAM |
| Llama3.2-Vision-11B | Q8 | ~11 GB | 8–12 t/s | ~3 GB spill in RAM di sistema |
| InternVL2-26B | Q4 | ~19 GB | 4–7 t/s | Troppo lento per uso live |

Ogni modello VLM richiede il relativo file **mmproj** (vision encoder). Senza di esso llama.cpp carica il modello in modalità solo testo e rifiuta le immagini.

---

## Setup

### 1. Dipendenze di sistema

```bash
sudo pacman -S git cmake vulkan-headers vulkan-radeon vulkan-tools base-devel
```

Verificare che Vulkan rilevi la GPU:
```bash
vulkaninfo --summary
# Atteso: AMD Radeon 780M Graphics (RADV PHOENIX)
```

### 2. Build llama.cpp

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

Copiare il binario nella directory inference di VELA:
```bash
cp build/bin/llama-server ~/vela/inference/
```

### 3. Download modelli

```bash
# Impostare il token HF per evitare rate limiting
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx

# Modello principale
hf download bartowski/Qwen2-VL-7B-Instruct-GGUF \
  --include "Qwen2-VL-7B-Instruct-Q8_0.gguf" \
  --local-dir ~/vela/inference/models

# Vision encoder (mmproj) — obbligatorio per le immagini
hf download bartowski/Qwen2-VL-7B-Instruct-GGUF \
  --include "mmproj-Qwen2-VL-7B-Instruct-f16.gguf" \
  --local-dir ~/vela/inference/models
```

---

## Avvio

```bash
cd ~/vela/inference
./start_server.sh
```

**`start_server.sh`:**
```bash
#!/bin/bash
cd "$(dirname "$0")"
./llama-server \
  --model ./models/Qwen2-VL-7B-Instruct-Q8_0.gguf \
  --mmproj ./models/mmproj-Qwen2-VL-7B-Instruct-f16.gguf \
  --n-gpu-layers 32 \
  --ctx-size 2048 \
  --batch-size 512 \
  --mlock \
  --host 0.0.0.0 \
  --port 8080
```

Output atteso all'avvio:
```
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = AMD Radeon 780M Graphics (RADV PHOENIX)
llm_load_tensors: offloaded 32/32 layers to GPU
llama server listening at http://0.0.0.0:8080
```

Se `offloaded` è inferiore a 32, parte del modello gira su CPU — controllare la VRAM disponibile nel BIOS.

---

## Test

### Web UI integrata
Con il server attivo, aprire `http://localhost:8080` nel browser. L'interfaccia integrata di llama.cpp permette di testare testo e immagini (drag & drop) direttamente.

### curl — solo testo
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role":"user","content":"Ciao, chi sei?"}], "max_tokens": 200}'
```

### curl — con immagine
```bash
IMAGE_B64=$(base64 -w0 /percorso/foto.jpg)
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"messages\": [{\"role\":\"user\",\"content\":[
    {\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/jpeg;base64,$IMAGE_B64\"}},
    {\"type\":\"text\",\"text\":\"Cosa vedi in questa immagine?\"}
  ]}], \"max_tokens\": 300}"
```

### Health check
```bash
curl http://localhost:8080/health
# {"status":"ok"}
```

---

## Rebuild del Binario

Quando llama.cpp viene aggiornato:
```bash
cd ~/llama.cpp   # o clonare di nuovo se eliminato
git pull
cmake --build build --config Release -j$(nproc)
cp build/bin/llama-server ~/vela/inference/
```

---

## Note

- **`--mlock`** mantiene il modello in RAM fisica prevenendo il paging su ZRAM sotto pressione di memoria. Richiede privilegi sufficienti; se fallisce aggiungere `LimitMEMLOCK=infinity` all'unità systemd o testare temporaneamente come root.
- **Wake-on-LAN** deve essere abilitato nel BIOS e l'interfaccia di rete deve supportarlo. Il Pi 5 invia il magic packet all'indirizzo MAC del laptop.
- Il server espone le API su `0.0.0.0:8080` — assicurarsi che la porta sia accessibile nella rete locale dal Pi 5.
- Vulkan è usato al posto di ROCm per maggiore stabilità su RDNA3 (gfx1103). ROCm non supporta ufficialmente le GPU integrate AMD.
