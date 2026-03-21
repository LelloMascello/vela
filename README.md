# VELA — Voice Edge Local Assistant
### Assistente Vocale Multimodale Locale — Architettura a Tre Nodi

> VELA listens, sees, and speaks — entirely on your own hardware. An open-source multimodal assistant built on ESP32-S3, Raspberry Pi 5, and a local VLM stack. No cloud, no subscriptions, no data leaving your network.


---

## 1. Architettura Generale

Il sistema è distribuito su **tre nodi distinti**, ognuno con un ruolo specializzato:

```
[ESP32-S3 Sense]  ←—Internet (WSS)—→  [Raspberry Pi 5]  ←—Ethernet—→  [Laptop]
   Occhio + Orecchio                    Middleware AI                    Cervello Visivo
   Mic PDM onboard                      STT (Whisper)                    VLM (Vision LLM)
   Camera OV2640                        TTS (Piper)                      llama/qwen Q8
   Display OLED                         FastAPI + WebSocket              llama.cpp + Vulkan
   Speaker + Amp                        Cloudflare Tunnel                Solo su richiesta foto
   2x Pulsanti                          Wake-on-LAN trigger
```

**Principio guida:** Il Pi 5 è sempre acceso e raggiungibile da qualsiasi rete tramite
Cloudflare Tunnel — nessun IP statico, nessuna porta aperta sul router. Gli ESP32 si
connettono all'endpoint pubblico `wss://vela.tuodominio.com` indipendentemente da dove si trovano.
Il laptop si sveglia via Wake-on-LAN **solo** quando arriva una foto da analizzare,
poi torna in sospensione, massimizzando la RAM DDR5 dedicata al VLM.

---

## 2. Hardware

### Nodo Edge — L'Occhio, l'Orecchio e il Volto

Dispositivo compatto, portatile, alimentato a batteria. Zero saldature sull'alimentazione.

| Componente | Modello | Note |
|---|---|---|
| MCU | Seeed Studio XIAO ESP32-S3 Sense | OV2640 + slot MicroSD integrati, PSRAM 8MB |
| Input Audio | **Microfono PDM onboard** | Pin interni 41/42, zero pin header consumati |
| Output Audio | Amplificatore I2S MAX98357A (3.2W) | Classe D, con pin SD_MODE per mute via GPIO |
| Speaker | Mini speaker passivo 3W 4Ω o 8Ω | Connettore 2P Dupont |
| Display | OLED I2C SSD1306 (0.96" o 1.3") | SDA→D4, SCL→D5, feedback visivo e trascrizione |
| UI | 2x Pulsanti tattili fisici | PTT audio (D1) e scatto foto (D2) |
| Alimentazione | Power Bank USB-C | Collegato direttamente alla USB-C dello XIAO |

**Nota sul Power Bank:** Il regolatore interno dello XIAO converte i 5V USB → 3.3V per tutti i moduli.
Per evitare lo spegnimento automatico del power bank (ESP32 in standby consuma < 20mA):
- **Opzione firmware (consigliata):** task FreeRTOS che attiva/disattiva il Wi-Fi ogni 25s
- **Opzione hardware:** resistore dummy 47Ω in parallelo come carico minimo
- **Opzione acquisto:** power bank con modalità always-on (es. Anker, Baseus low-current mode)

**Nota sul MAX98357A:** Collegare il pin `SD_MODE` a un GPIO libero (es. D3).
Permette di silenziare l'amplificatore via software durante la registrazione,
eliminando il rischio di echo mic→speaker a costo zero.

---

### Nodo Middleware — Il Coordinatore (Raspberry Pi 5, 4GB + SSD 512GB)

Server sempre acceso. Gestisce tutta la pipeline voce e orchestra le richieste verso il laptop. Con 4GB di RAM e SSD da 512GB, i modelli STT e TTS risiedono sull'SSD e vengono caricati in RAM all'avvio — nessun rischio di swap lento su MicroSD.

| Ruolo | Strumento | Prestazioni attese |
|---|---|---|
| Server WebSocket/HTTP | FastAPI (Python) | < 5ms overhead |
| Speech-to-Text | Faster-Whisper Base/Small | 400–700ms su ARM, ~1.5GB RAM |
| Text-to-Speech | Piper TTS (`it_IT-riccardo-x_low`) | < 200ms, CPU puro |
| Wake-on-LAN | `wakeonlan` Python lib | Sveglia il laptop solo per le foto |
| Proxy VLM | Forward HTTP → laptop | Attende risposta in streaming |

**Nota RAM Pi 5 (4GB):** Faster-Whisper Small (~1.5GB) + Piper (~200MB) + FastAPI + OS
lasciano ~1.5GB liberi — sufficiente per il middleware, ma senza margine per modelli aggiuntivi.
Tutti i modelli AI pesanti restano esclusivamente sul laptop.

---

### Nodo Server — Il Cervello Visivo (Laptop)

Dedicato **esclusivamente** al Vision Language Model. Non esegue STT né TTS.

| Componente | Dettaglio |
|---|---|
| CPU | Ryzen 7 8840HS (8 core / 16 thread) |
| iGPU | AMD Radeon 780M (RDNA3, gfx1103) |
| RAM | 24 GB DDR5 5600MHz (~90 GB/s bandwidth) |
| ZRAM | 10 GB (da escludere per i modelli AI, vedi ottimizzazioni) |

**Distribuzione RAM sul laptop:**

```
├── OS + Desktop:      ~3.5 GB
├── VLM (fino a):      ~20.0 GB
└── Libera per iGPU:   generosa (con UMA 8GB dedicati alla 780M)
```

**Ottimizzazioni BIOS/OS:**
- UMA Frame Buffer: impostare **8GB** nel BIOS per dedicare VRAM contigua alla 780M
- Usare `--mlock` in llama.cpp per ancorare il modello in RAM fisica (mai in ZRAM)
- Configurare `vm.swappiness=10` nell'OS per minimizzare la paginazione

---

## 3. Pinout e Cablaggio — XIAO ESP32-S3 Sense

Con il microfono PDM onboard (pin interni 41/42), il bus I2S è **solo in uscita**.
Il cablaggio si semplifica notevolmente.

### Bus I2S (Solo Output → Amplificatore MAX98357A)

| Pin XIAO | Pin MAX98357A | Funzione |
|---|---|---|
| D7 | BCLK | Bit Clock |
| D8 | LRC | Word Select (Left/Right Clock) |
| D10 | DIN | Dati audio digitali |
| D3 *(opzionale)* | SD_MODE | Mute/unmute amplificatore via GPIO |

### Display OLED SSD1306 (I2C)

| Pin XIAO | Pin SSD1306 | Funzione |
|---|---|---|
| D4 | SDA | Dati I2C |
| D5 | SCL | Clock I2C |

### Pulsanti (INPUT_PULLUP via software)

| Pin XIAO | Funzione | Altro piedino |
|---|---|---|
| D1 | Pulsante 1 — Push-to-Talk (audio) | → GND |
| D2 | Pulsante 2 — Scatto foto | → GND |

### Alimentazione

| Pin XIAO | Destinazione |
|---|---|
| 3V3 | VIN (MAX98357A), VCC (SSD1306) |
| GND | GND di tutti i moduli e pulsanti |

### Pin Liberi Dopo la Configurazione

D0, D6, D9 rimangono disponibili per espansioni future
(es. sensore di prossimità, LED RGB, secondo pulsante, sensore ambientale).

---

## 4. Connettività Internet — Accesso Remoto degli ESP32

Gli ESP32 non si connettono tramite LAN locale ma tramite **WebSocket sicuro (WSS) su internet**,
raggiungendo il Pi 5 attraverso un tunnel crittografato.

### Soluzione Raccomandata: Cloudflare Tunnel

Il Pi 5 esegue un daemon `cloudflared` che apre una connessione uscente verso i server Cloudflare.
Nessuna porta da aprire sul router, nessun IP statico necessario.

```
ESP32 (qualsiasi rete)
    │
    ▼  wss://vela.tuodominio.com  (TLS, porta 443)
Cloudflare Edge
    │
    ▼  tunnel crittografato
cloudflared sul Pi 5
    │
    ▼  ws://localhost:8765  (locale)
FastAPI WebSocket Server
```

**Setup sul Pi 5:**
```bash
# Installazione
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 \
     -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# Autenticazione e creazione tunnel
cloudflared tunnel login
cloudflared tunnel create vela
cloudflared tunnel route dns vela vela.tuodominio.com

# Avvio come servizio systemd
cloudflared service install
```

**Configurazione `~/.cloudflared/config.yml`:**
```yaml
tunnel: <tunnel-id>
credentials-file: /home/pi/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: vela.tuodominio.com
    service: ws://localhost:8765
  - service: http_status:404
```

**Sul firmware ESP32:** sostituire l'IP locale con l'endpoint pubblico:
```cpp
// Prima (LAN only):
const char* ws_host = "192.168.1.100";
const int   ws_port = 8765;
const char* ws_path = "/ws";

// Dopo (internet):
const char* ws_host = "vela.tuodominio.com";
const int   ws_port = 443;
const char* ws_path = "/ws";
bool        ws_ssl  = true;   // TLS obbligatorio
```

L'ESP32 supporta WebSocket TLS nativo tramite la libreria `ArduinoWebsockets`
con certificato root CA di Cloudflare incluso nel firmware.

### Autenticazione dei Nodi ESP32

Poiché l'endpoint è pubblico, ogni ESP32 si autentica con un **token condiviso**
inviato nell'header HTTP durante l'handshake WebSocket:

```cpp
client.setExtraHeaders("Authorization: Bearer YOUR_SECRET_TOKEN");
```

Il server FastAPI valida il token prima di accettare la connessione. Token diversi
per ESP32 diversi permettono di identificare il nodo e gestire sessioni separate.

### Alternative (Scenari Specifici)

| Soluzione | Pro | Contro | Quando usarla |
|---|---|---|---|
| **Cloudflare Tunnel** | Zero config router, TLS automatico | Richiede dominio | **Default consigliato** |
| **Tailscale** | VPN mesh, semplicissimo | ESP32 non supporta client nativo* | Solo con gateway ESP32↔Pi sulla stessa LAN |
| **DDNS + port forward** | Nessun servizio terzo | IP dinamico, porta aperta | Router con DDNS integrato |
| **VPS relay** | Controllo totale | Costo mensile, latenza extra | Deployment produzione |

*\*Tailscale può essere usato tra Pi 5 e laptop; per gli ESP32 serve comunque un endpoint pubblico.*

---

## 5. Architettura del Protocollo e Flusso Dati

### Uplink: ESP32 → Pi 5 (via Internet WSS)

**Flusso Audio (Pulsante 1 tenuto premuto):**
1. ESP32 attiva il mic PDM onboard e l'amplificatore viene silenziato (SD_MODE LOW)
2. L'OLED mostra "● REC" con waveform animata
3. Audio PCM 16kHz/16-bit bufferizzato in PSRAM (8MB)
4. Chunk inviati in streaming via WebSocket al Pi 5

**Flusso Foto (Pressione Pulsante 2):**
1. ESP32 scatta JPEG con OV2640
2. L'OLED mostra "📷 Invio..."
3. JPEG codificato in Base64, inviato come payload JSON WebSocket al Pi 5
4. Pi 5 valuta se il laptop è acceso; se no, invia Wake-on-LAN e attende (~5s)

### Payload WebSocket (Struttura Consigliata)

```json
// Audio chunk
{ "type": "audio_chunk", "data": "<base64_pcm>", "seq": 42 }

// Fine registrazione
{ "type": "audio_end", "sample_rate": 16000, "channels": 1 }

// Foto
{ "type": "image", "data": "<base64_jpeg>", "prompt": "Descrivi cosa vedi" }

// Controllo
{ "type": "control", "cmd": "reset" | "change_lang" | "status" }
```

### Downlink: Pi 5 → ESP32

**Risposta vocale in streaming:**
1. Pi 5 riceve testo da Whisper (o risposta parziale dal VLM del laptop)
2. Alla prima punteggiatura (`.`, `?`, `!`, `,` lunga), passa il frammento a Piper TTS
3. Invia pacchetti audio PCM/WAV in streaming all'ESP32
4. ESP32 attiva l'amplificatore (SD_MODE HIGH) e riproduce mentre Pi 5 continua a generare

**Gestione latenza — Audio Filler:**
Se il VLM sul laptop impiega > 1.5s per il primo token (es. caricamento modello, wake-up),
il Pi 5 invia un pacchetto audio pre-generato ("Uhm...", "Un momento...", respiro)
per comunicare all'utente che il sistema sta elaborando.

**Feedback visivo OLED durante le fasi:**

| Fase | Display |
|---|---|
| Standby | Orologio / indicatore Wi-Fi |
| Registrazione | "● REC" + waveform |
| Elaborazione STT | "…" animato |
| Risposta VLM | Trascrizione testo in scorrimento |
| Riproduzione audio | Equalizzatore animato |
| Errore | "⚠ Riprova" |

---

## 6. Stack Software AI

### Nodo Pi 5

**Speech-to-Text:**
- Modello: `faster-whisper` Base o Small (ARM64, CPU puro)
- Latenza: 400–700ms
- RAM: ~1.5 GB

**Text-to-Speech:**
- Modello: `piper-tts` con voce `it_IT-riccardo-x_low`
- Latenza: < 200ms
- RAM: < 200 MB

**Server:**
- Framework: FastAPI + WebSockets (`websockets` o `starlette`)
- Wake-on-LAN: libreria Python `wakeonlan`
- Orchestrazione pipeline: task asincroni con `asyncio`

---

### Nodo Laptop — VLM

Grazie alla RAM liberata dal Pi 5, il VLM può usare quantizzazioni più alte
e offloadare più layer sulla 780M.

**Modelli consigliati (in ordine di bilanciamento qualità/velocità):**

| Modello | Quant | RAM usata | t/s stimati | Caso d'uso |
|---|---|---|---|---|
| `qwen2-vl:7b` | **Q8** | ~8 GB | 14–20 | **Consigliato — velocità + qualità** |
| `llama3.2-vision:11b` | **Q8** | ~11 GB | 8–12 | Qualità notevolmente superiore al Q4 |
| `InternVL2-26B` | Q4 | ~19 GB | 4–7 | Massima comprensione visiva |
| `llava:7b` | Q8 | ~8 GB | 14–18 | Alternativa leggera |

**Esecuzione con llama.cpp (configurazione ottimizzata):**

```bash
./llama-server \
  --model qwen2-vl-7b-instruct-q8_0.gguf \
  --n-gpu-layers 32 \       # Tutti i layer su 780M con 8GB UMA
  --ctx-size 2048 \         # Contesto corto per assistente vocale
  --batch-size 512 \        # Ottimizza throughput
  --mlock \                 # Ancora in RAM fisica (mai in ZRAM)
  --host 0.0.0.0 \
  --port 11434
```

> **Nota GPU:** L'accelerazione sulla 780M richiede llama.cpp compilato con backend **Vulkan**
> (più stabile di ROCm su gfx1103). Testare con `--n-gpu-layers` crescente fino a saturazione VRAM.
> Con UMA 8GB e modello Q8 da 8GB, è possibile offloadare l'intero modello sulla iGPU.

---

## 7. Flusso Completo — Esempio con Foto

```
Utente preme Pulsante 2 sull'ESP32
        │
        ▼
ESP32 scatta JPEG (OV2640) → OLED: "📷 Invio..."
        │
        ▼ WebSocket JSON (Base64 JPEG)
        │
Raspberry Pi 5 riceve l'immagine
        ├─ Laptop online? → forward diretto HTTP POST
        └─ Laptop offline? → invia Wake-on-LAN → attendi ~5s → forward
                │
                ▼ (filler audio: "Sto guardando...")
                │
        Laptop (llama.cpp + 780M) esegue inferenza VLM
                │ streaming token by token
                ▼
        Pi 5 accumula fino a punteggiatura
                │
                ▼ Piper TTS → WAV chunk
                │
        Pi 5 → WebSocket → ESP32
                │
                ▼
ESP32 attiva SD_MODE → MAX98357A → Speaker
OLED mostra testo risposta in scorrimento
```

---

## 8. Componenti Hardware — Lista Acquisti

| Componente | Dove trovarlo |
|---|---|
| Seeed Studio XIAO ESP32-S3 Sense | AliExpress / Seeed Studio ufficiale |
| MAX98357A I2S Amplifier Breakout | AliExpress |
| Speaker 3W 4Ω (connettore 2P Dupont) | AliExpress |
| OLED SSD1306 I2C 0.96" o 1.3" | AliExpress / Amazon |
| 2x Pulsanti tattili 6mm | AliExpress / kit assortiti |
| Power Bank USB-C con always-on | Anker PowerCore (serie Slim) |
| Raspberry Pi 5 4GB + alimentatore ufficiale | RS Components / Farnell / PiShop |
| SSD 512GB (per Pi 5, via adattatore NVMe HAT) | Samsung 980 / Kingston NV2 |
| Breadboard + jumper Dupont M-F | Kit standard |
