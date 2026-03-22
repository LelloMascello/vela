# VELA — Inference Node (Node 3)

Documentazione per il setup, la configurazione e la manutenzione del server di inferenza locale.

---

## Indice

1. [Panoramica](#1-panoramica)
2. [Requisiti Hardware](#2-requisiti-hardware)
3. [Dipendenze di Sistema](#3-dipendenze-di-sistema)
4. [Build di llama.cpp](#4-build-di-llamacpp)
5. [Download dei Modelli](#5-download-dei-modelli)
6. [Struttura della Directory](#6-struttura-della-directory)
7. [Avvio del Server](#7-avvio-del-server)
8. [Verifica e Test](#8-verifica-e-test)
9. [Aggiornamento del Binary](#9-aggiornamento-del-binary)
10. [Scelta del Modello](#10-scelta-del-modello)
11. [Wake-on-LAN](#11-wake-on-lan)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Panoramica

Il nodo di inferenza è un laptop **on-demand**: rimane in sleep quando non utilizzato e viene svegliato dal Pi 5 tramite Wake-on-LAN quando arriva una richiesta vision. Esegue un server **llama.cpp** con backend Vulkan che riceve immagine + prompt dal Pi 5 e restituisce la risposta in token streaming.

**Hardware utilizzato:**
- CPU: AMD Ryzen 7 8840HS
- GPU integrata: AMD Radeon 780M (RDNA3, gfx1103)
- UMA Frame Buffer: 8 GB (configurato nel BIOS)
- OS: Arch Linux

**Perché Vulkan e non ROCm?**
ROCm ha supporto instabile sulla GPU integrata RDNA3 (gfx1103). Vulkan tramite RADV offre piena compatibilità e stabilità su Arch Linux con driver Mesa.

---

## 2. Requisiti Hardware

| Componente | Minimo | Usato in VELA |
|------------|--------|---------------|
| GPU VRAM (UMA) | 8 GB | 8 GB (Radeon 780M) |
| RAM di sistema | 16 GB | 32 GB |
| Storage libero | 20 GB | SSD NVMe |
| Rete | Ethernet LAN | Ethernet |

> **Nota BIOS:** impostare il UMA Frame Buffer a **8 GB** nelle impostazioni BIOS/UEFI. Il percorso varia per produttore, cercare "UMA Frame Buffer Size" o "iGPU Memory".

---

## 3. Dipendenze di Sistema

```bash
sudo pacman -S git cmake base-devel vulkan-headers vulkan-radeon vulkan-tools patchelf
```

Verificare che Vulkan veda la GPU:
```bash
vulkaninfo --summary
```

Output atteso:
```
GPU0:
    deviceName         = AMD Radeon 780M Graphics (RADV PHOENIX)
    driverName         = radv
    driverInfo         = Mesa 26.x.x-arch1.x
```

Se la GPU non appare, installare i driver Vulkan AMD:
```bash
sudo pacman -S vulkan-radeon
```

---

## 4. Build di llama.cpp

Clonare e compilare llama.cpp con il backend Vulkan:

```bash
git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)
```

Copiare il binary e le shared library nella directory `vela/inference/`:

```bash
cp build/bin/llama-server ~/vela/inference/
cp build/bin/*.so* ~/vela/inference/
```

Correggere il rpath del binary in modo che carichi le `.so` dalla propria directory invece che dal percorso di build:

```bash
patchelf --set-rpath '$ORIGIN' ~/vela/inference/llama-server
```

Verificare che tutti i link puntino a `vela/inference/` e non alla directory di build:

```bash
ldd ~/vela/inference/llama-server
```

Tutti i `libmtmd`, `libllama`, `libggml*` devono mostrare `/home/<utente>/vela/inference/`. Una volta verificato, la directory di build può essere rimossa:

```bash
rm -rf ~/llama.cpp/
```

> **Nota:** il codice sorgente di llama.cpp non va committato nel repository VELA. Solo il binary e le `.so` compilate vengono copiati in `vela/inference/`, ma sono esclusi da `.gitignore` in quanto artefatti compilati.

---

## 5. Download dei Modelli

### Setup huggingface-hub

```bash
pip install huggingface-hub --break-system-packages
export PATH="$HOME/.local/bin:$PATH"
```

Rendere permanente aggiungendo al `~/.bashrc` o `~/.zshrc`:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

Autenticarsi con un token HuggingFace (necessario per download senza throttling):
```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx
```

Ottenere un token gratuito su: https://huggingface.co/settings/tokens

### Download modello raccomandato (Qwen2-VL-7B Q8)

```bash
hf download bartowski/Qwen2-VL-7B-Instruct-GGUF \
  --include "Qwen2-VL-7B-Instruct-Q8_0.gguf" \
  --local-dir ~/vela/inference/models

hf download bartowski/Qwen2-VL-7B-Instruct-GGUF \
  --include "mmproj-Qwen2-VL-7B-Instruct-f16.gguf" \
  --local-dir ~/vela/inference/models
```

> **Importante:** il file `mmproj` è il vision encoder. Senza di esso llama.cpp carica il modello in modalità solo testo e rifiuta le immagini.

---

## 6. Struttura della Directory

Dopo setup completo, `vela/inference/` deve apparire così:

```
inference/
├── llama-server              # Binary (escluso da .gitignore)
├── libggml.so.0              # Shared libraries (escluse da .gitignore)
├── libggml-base.so.0
├── libggml-cpu.so.0
├── libggml-vulkan.so.0
├── libllama.so.0
├── libmtmd.so.0
├── start_server.sh           # Script di avvio (committato)
└── models/                   # Pesi modelli (esclusi da .gitignore)
    ├── Qwen2-VL-7B-Instruct-Q8_0.gguf
    └── mmproj-Qwen2-VL-7B-Instruct-f16.gguf
```

Le seguenti voci sono escluse da `.gitignore`:
```gitignore
inference/*.so
inference/*.so.*
inference/llama-server
inference/models/*.gguf
```

---

## 7. Avvio del Server

```bash
cd ~/vela/inference
bash start_server.sh
```

Contenuto di `start_server.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
export LD_LIBRARY_PATH="$(dirname "$0"):$LD_LIBRARY_PATH"
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

**Spiegazione dei flag:**

| Flag | Valore | Motivo |
|------|--------|--------|
| `--n-gpu-layers` | 32 | Offload completo su Radeon 780M |
| `--ctx-size` | 2048 | Sufficiente per prompt + immagine, non spreca VRAM |
| `--batch-size` | 512 | Bilanciamento throughput/latenza |
| `--mlock` | — | Mantiene il modello in RAM fisica, evita paging su ZRAM |
| `--host` | 0.0.0.0 | Accetta connessioni da Pi 5 sulla LAN |
| `--port` | 8080 | Porta usata dal Pi 5 per le richieste WebSocket |

---

## 8. Verifica e Test

### Controllo avvio

All'avvio, il log deve mostrare:
```
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = AMD Radeon 780M Graphics (RADV PHOENIX) ...
llm_load_tensors: offloaded 32/32 layers to GPU
llama server listening at http://0.0.0.0:8080
```

Se `offloaded` mostra meno di 32/32, la VRAM non è sufficiente per il modello scelto.

### Health check

```bash
curl http://localhost:8080/health
# Risposta attesa: {"status":"ok"}
```

### Test testo via curl

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role":"user","content":"Ciao! Chi sei?"}], "max_tokens": 200}'
```

### Test vision via curl

```bash
IMAGE_B64=$(base64 -w0 /path/to/foto.jpg)
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [{
      \"role\": \"user\",
      \"content\": [
        {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/jpeg;base64,$IMAGE_B64\"}},
        {\"type\": \"text\", \"text\": \"Cosa vedi in questa immagine?\"}
      ]
    }],
    \"max_tokens\": 300
  }"
```

### Test via browser (Web UI integrata)

Aprire `http://localhost:8080` — llama.cpp include una chat UI dove è possibile trascinare immagini e testare il modello interattivamente.

---

## 9. Aggiornamento del Binary

Quando llama.cpp rilascia una nuova versione:

```bash
git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j$(nproc)

# Rimuovere vecchie librerie da vela/inference/
rm ~/vela/inference/llama-server ~/vela/inference/*.so*

# Copiare nuovi artefatti
cp build/bin/llama-server ~/vela/inference/
cp build/bin/*.so* ~/vela/inference/

# Correggere rpath
patchelf --set-rpath '$ORIGIN' ~/vela/inference/llama-server

# Pulizia
rm -rf ~/llama.cpp/
```

---

## 10. Scelta del Modello

| Modello | Quantizzazione | VRAM richiesta | Velocità stimata | Fit in 8 GB |
|---------|----------------|----------------|------------------|-------------|
| **Qwen2-VL-7B** | **Q8** | **~8 GB** | **14–20 t/s** | **Esatto** |
| Llama3.2-Vision-11B | Q4_K_M | ~7 GB | 10–14 t/s | Comodo |
| Llama3.2-Vision-11B | Q8 | ~11 GB | 8–12 t/s | Spill ~3 GB |
| InternVL2-26B | Q4 | ~19 GB | 4–7 t/s | Spill ~11 GB |

> Il modello **Qwen2-VL-7B Q8** è quello raccomandato per VELA: occupa esattamente la VRAM disponibile, gira interamente su GPU senza spill in RAM di sistema, e offre il miglior rapporto qualità/velocità per un assistente vocale.

Per cambiare modello, modificare i percorsi in `start_server.sh` e scaricare il nuovo `.gguf` + relativo `mmproj` in `inference/models/`.

---

## 11. Wake-on-LAN

Il laptop deve essere configurato per accettare pacchetti WoL dalla rete locale.

### Abilitare WoL sulla scheda di rete

```bash
# Trovare il nome dell'interfaccia ethernet
ip link show

# Abilitare WoL (sostituire eth0 con il nome reale)
sudo ethtool -s eth0 wol g

# Verificare
ethtool eth0 | grep Wake
# Wake-on: g  <- corretto
```

Per rendere permanente creare `/etc/systemd/system/wol.service`:
```ini
[Unit]
Description=Wake-on-LAN
Requires=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/ethtool -s eth0 wol g

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now wol.service
```

### Configurare il Pi 5

Il Pi 5 ha bisogno del MAC address del laptop per inviare il magic packet:

```bash
# Sul laptop
ip link show eth0 | grep ether
# es: aa:bb:cc:dd:ee:ff
```

Inserire questo MAC address nella configurazione del Pi 5 (`server/inference_worker.py`).

### Abilitare sleep/wake nel BIOS

Verificare che nel BIOS sia abilitato:
- **Wake on LAN:** Enabled
- **ErP/EuP:** Disabled (altrimenti WoL non funziona in S3/S4)

---

## 12. Troubleshooting

### `libmtmd.so.0: cannot open shared object file`

Le shared library non vengono trovate. Assicurarsi di aver copiato tutti i `.so*` da `build/bin/` e di aver applicato `patchelf`:

```bash
cp ~/llama.cpp/build/bin/*.so* ~/vela/inference/
patchelf --set-rpath '$ORIGIN' ~/vela/inference/llama-server
ldd ~/vela/inference/llama-server  # verificare i percorsi
```

### `Could NOT find Vulkan` durante cmake

Installare gli header Vulkan mancanti:

```bash
sudo pacman -S vulkan-headers
```

### `offloaded 0/32 layers to GPU`

Vulkan non sta usando la GPU. Verificare:

```bash
vulkaninfo --summary  # la GPU deve apparire
```

Se mancano i driver:
```bash
sudo pacman -S vulkan-radeon
```

### Server lento (< 5 t/s)

Il modello sta andando in spill nella RAM di sistema. Opzioni:
- Ridurre `--ctx-size` a 1024
- Passare a una quantizzazione inferiore (Q4_K_M invece di Q8)
- Ridurre `--n-gpu-layers` e misurare la velocità

### `mlock failed`

Il sistema non permette di bloccare abbastanza memoria. Soluzione temporanea:

```bash
sudo sysctl -w vm.max_map_count=1000000
ulimit -l unlimited
```

Soluzione permanente in `/etc/security/limits.conf`:
```
* soft memlock unlimited
* hard memlock unlimited
```

### Download HuggingFace lento o bloccato

Autenticarsi con un token:
```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxx
hf download ...
```

Il download è ripristinabile: se interrotto, rilanciare lo stesso comando e riprenderà da dove si era fermato.
