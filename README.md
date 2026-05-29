# Jarvis — Assistente Vocale Distribuito
### *Progetto per l'Esame di Stato · Maturità 2025*

> Un assistente vocale *general-purpose* attivato tramite wake-word, distribuito su tre nodi fisici interconnessi in rete locale: client (ESP32-S3 / Android / Web), orchestratore e engine AI.

---

## Indice

- [Demo Video](#demo-video)
- [Panoramica](#panoramica)
- [Architettura](#architettura)
- [Flusso di Conversazione](#flusso-di-conversazione)
- [Struttura del Progetto](#struttura-del-progetto)
- [Componenti e Codice](#componenti-e-codice)
  - [1. Wake-Word Detector](#1-wake-word-detector--orchestratorwake_word_detectorpy)
  - [2. Router e Autenticazione](#2-router-e-autenticazione--orchestratorrouterpy--orchestratorauthpy)
  - [3. Storico Conversazioni](#3-storico-conversazioni--orchestratorwebsitepy)
  - [4. Core Pipeline Vocale](#4-core-pipeline-vocale--enginemainpy--engineaudiopy)
  - [5. Inferenza AI (STT + LLM)](#5-inferenza-ai-stt--llm--engineinferencepy)
  - [6. Text-to-Speech](#6-text-to-speech--enginetext_to_speechpy)
  - [7. Script di Avvio](#7-script-di-avvio--start_allsh)
- [Modelli AI Utilizzati](#modelli-ai-utilizzati)
- [Librerie e Dipendenze](#librerie-e-dipendenze)
- [Setup e Utilizzo](#setup-e-utilizzo)
- [Porte e Servizi](#porte-e-servizi)

---

## Demo Video

https://github.com/user-attachments/assets/video.mp4

> *Il video mostra il sistema in azione: dalla pronuncia della wake-word "Jarvis" fino alla risposta vocale in streaming.*

---

## Panoramica

**Jarvis** è un assistente vocale progettato per funzionare interamente su hardware consumer locale, **senza dipendenze da cloud**. Il nome stesso funge da parola di attivazione: pronunciare *"Jarvis"* avvia una sessione conversazionale completa.

Il sistema si compone di **tre nodi** interconnessi:

| Nodo | Hardware consigliato | Ruolo |
|------|----------------------|-------|
| **Client** | ESP32-S3 / Android / Browser | Cattura audio dal microfono, riproduce le risposte |
| **Orchestratore** | Raspberry Pi 5 o PC dedicato | Routing, autenticazione, rilevamento wake-word, storico chat |
| **Engine AI** | Laptop / Server GPU | Pipeline AI completa: VAD → STT → LLM → TTS |

---

## Architettura

```
┌─────────────────────┐  flusso audio continuo   ┌──────────────────────────┐
│  ESP32-S3 / Android │ ───────────────────────> │       Orchestratore      │
│      (client)       │ <─────────────────────── │    (Router + Auth)       │
│                     │ segnale wake word / sync │                          │
│  · microfono        │                          │  · router.py (Port 8000) │
│  · altoparlante     │                          │  · auth.py (SQLite DB)   │
│  · WiFi             │                          │  · website.py (Port 8005)│
└─────────────────────┘                          └───────────┬──────────────┘
          ^                                                  │
          │                                                  │ passaggio del flusso
          │                                                  v
          │                                      ┌──────────────────────────┐
          │        risposta audio (chunk)        │         Engine AI        │
          └───────────────────────────────────── │    (main.py - Port 8002) │
                                                 │                          │
                                                 │  · Silero VAD            │
                                                 │  · Whisper STT (Large)   │
                                                 │  · Gemma 4 (llama.cpp)   │
                                                 │  · Piper TTS (Riccardo)  │
                                                 └──────────────────────────┘
```

---

## Flusso di Conversazione

```
┌──────────────────────┐
│   Ascolto passivo    │<──────────────────────────────────┐
│ Router analizza audio│                                   │
└──────────┬───────────┘                                   │
           │ "Jarvis" rilevato via openwakeword            │
           v                                               │
┌──────────────────────┐   silenzio > 10 s &               │
│    Ascolto attivo    │── nessun input vocale ────────────┘
│ Controllo passa a AI │
└──────────┬───────────┘
           │ fine del parlato (Silero VAD)
           v
┌──────────────────────┐
│ Generazione risposta │<──────────────────────┐
│  Whisper → Gemma 4   │                       │
│  → Piper TTS stream  │                       │
└──────────┬───────────┘                       │
           │                                   │
           v                                   │
┌──────────────────────┐   parlato rilevato    │
│ Finestra di follow-up│───────────────────────┘
│  Il timer silenzio   │
│  si resetta a 10 s   │
└──────────┬───────────┘
           │ silenzio > 10 s
           v
┌──────────────────────┐
│  Chiusura sessione   │──> Salvataggio cronologia su MongoDB
└──────────────────────┘
```

**Passaggi operativi:**

1. **Ascolto passivo** — Il client invia audio raw al Router; quest'ultimo lo analizza tramite `openwakeword`. L'Engine AI rimane in standby.
2. **Wake word** — Al rilevamento di *"Jarvis"*, il router reindirizza il client verso l'hub WebSocket dell'Engine AI (`main.py`).
3. **Ascolto attivo** — L'Engine analizza i frame audio con Silero VAD. Se l'utente non parla entro 10 secondi, la sessione scade e il client torna in modalità passiva.
4. **Generazione risposta** — Quando il VAD rileva la fine del parlato, l'audio viene trascritto da Whisper, il testo processato da Gemma 4 e i token inviati in streaming a Piper TTS per la sintesi vocale immediata.
5. **Finestra di follow-up** — Dopo la riproduzione, il client rimane in ascolto per altri 10 secondi, permettendo conversazioni naturali senza ripetere la wake-word.
6. **Chiusura sessione** — Scaduto il timeout, l'Engine salva la cronologia su MongoDB tramite l'Orchestratore e rimanda il client in modalità passiva.

---

## Struttura del Progetto

```
Pollini/
├── client/
│   ├── esp32/                              # Firmware C++ (ESP32-S3)
│   └── JarvisApp/                          # App Android (Kotlin)
├── orchestrator/
│   ├── auth.py                             # Gestione utenti (SQLite)
│   ├── router.py                           # WebSocket proxy & Wake Word manager (Port 8000)
│   ├── wake_word_detector.py               # Analisi acustica locale (openwakeword, Port 8001)
│   ├── website.py                          # Web Server & API Storico Chat (MongoDB, Port 8005)
│   ├── users.db                            # Database SQLite credenziali (auto-generato)
│   └── public/
│       ├── index.html, index.js            # Login / Registrazione
│       ├── home.html, home.js              # Pannello di controllo e Client Web
│       ├── chats.html, chats.js            # Storico conversazioni
│       └── style.css                       # Fogli di stile globali
├── engine/
│   ├── main.py                             # Hub WebSocket della pipeline vocale (Port 8002)
│   ├── audio.py                            # Silero VAD, denoising, encoding PCM/WAV
│   ├── inference.py                        # STT (Whisper) + streaming LLM (llama.cpp)
│   └── text_to_speech.py                   # Integrazione Piper TTS (Port 8003)
├── README.md
└── start_all.sh
```

---

## Componenti e Codice

### 1. Wake-Word Detector — `orchestrator/wake_word_detector.py`

Microservizio FastAPI che riceve frame audio dal Router ed esegue il rilevamento di *"Jarvis"* tramite `openwakeword`. Implementa un sistema a **doppia soglia** per bilanciare reattività e falsi positivi.

**Logica di rilevamento (doppio percorso):**

```python
# Due percorsi di attivazione — uno qualsiasi è sufficiente:
#   LATCH : un singolo frame supera LATCH_THRESHOLD (trigger istantaneo)
#   SMOOTH: media mobile su 5 frame supera SMOOTH_THRESHOLD (voci sommesse)

LATCH_THRESHOLD  = 0.70   # soglia per trigger immediato su singolo frame
THRESHOLD        = 0.45   # soglia per frame nel percorso smooth
SMOOTH_WINDOW    = 5      # numero di frame per la media mobile (~400 ms)
SMOOTH_THRESHOLD = 0.35   # soglia della media mobile per il percorso smooth

latch_hit  = best_score >= LATCH_THRESHOLD
smooth_hit = best_score >= THRESHOLD and smoothed >= SMOOTH_THRESHOLD
detected   = latch_hit or smooth_hit
```

**Riduzione del rumore pre-modello:**

```python
# Profilo di rumore: accumula i primi 20 frame (silence iniziale del microfono)
# poi applica riduzione spettrale stazionaria prima di passare al modello
if _noise_profile is not None:
    pcm_f32 = nr.reduce_noise(
        y=pcm_f32,
        sr=SAMPLE_RATE,
        y_noise=_noise_profile,
        stationary=True,
        prop_decrease=0.60,   # riduzione al 60% — più aggressiva causa artefatti
    )
```

**Endpoint esposti:**

| Endpoint | Metodo | Funzione |
|----------|--------|----------|
| `/detect` | POST | Analizza un frame audio, ritorna `{"wake_word": bool, "best_score": float}` |
| `/reset` | POST | Azzera history score (chiamato dal Router all'inizio di ogni sessione) |
| `/config` | GET | Espone `frame_length` e parametri soglia per auto-configurazione client |

---

### 2. Router e Autenticazione — `orchestrator/router.py` & `orchestrator/auth.py`

Il **Router** è il punto di ingresso WebSocket per tutti i client. Riceve audio in streaming, interroga il Wake-Word Detector e, al rilevamento, reindirizza il client direttamente all'Engine AI.

**Warm-up anti-falso-positivo:**

```python
# I primi 10 frame vengono inviati al detector per riempire i suoi buffer interni,
# ma il risultato viene IGNORATO — evita trigger immediati da audio residuo
# del client accumulato durante la finestra di riconnessione.
DETECTOR_WARMUP_FRAMES = 10   # ~320 ms @ 16 kHz / 512 campioni per frame

if frames_processed <= DETECTOR_WARMUP_FRAMES:
    continue   # forwarda al detector ma scarta il risultato
```

**Redirect verso l'Engine AI al wake-word:**

```python
if result.get("wake_word"):
    await websocket.send_json({
        "ip":       MAIN_WS_HOST,   # 127.0.0.1
        "port":     MAIN_WS_PORT,   # 8002
        "message":  "server ready",
        "username": username,
    })
```

**Autenticazione HTTP Basic (`auth.py`):**

Le password non sono mai salvate in chiaro. Ogni password viene salata con 16 byte casuali crittograficamente sicuri prima dell'hashing.

```python
def signup(username: str, password: str) -> dict | None:
    salt = os.urandom(16).hex()           # salt casuale a 16 byte (OS CSPRNG)
    password_hash = f"{salt}:{hashlib.sha256((salt + password).encode()).hexdigest()}"
    # Salvato su SQLite come "salt:hash" — il salt è necessario per la verifica

def login(username: str, password: str) -> dict | None:
    salt, stored_hash = row[0].split(":", 1)
    if hashlib.sha256((salt + password).encode()).hexdigest() == stored_hash:
        return {"username": username}   # credenziali valide
    return None
```

---

### 3. Storico Conversazioni — `orchestrator/website.py`

Server web FastAPI che serve il frontend statico (HTML/CSS/JS) ed espone le API per login, signup e gestione dello storico chat su **MongoDB**.

**Schema di validazione con Pydantic:**

```python
class ChatSession(BaseModel):
    username:   str
    created_at: int               # timestamp Unix in millisecondi
    chat:       List[Dict[str, Any]]   # lista di {"role": "user"|"assistant", "content": str}

@app.post("/chats/insert")
def insert_chats(history: ChatSession):
    # Pydantic valida automaticamente la struttura prima dell'inserimento
    result = mycol.insert_one(history.model_dump())
    return {"status": "success", "inserted_id": str(result.inserted_id)}
```

**Endpoint esposti:**

| Endpoint | Metodo | Funzione |
|----------|--------|----------|
| `/` | GET | Pagina di login/registrazione |
| `/home` | GET | Dashboard utente e client Web |
| `/chats` | GET | Storico conversazioni con ricerca |
| `/signup` | POST | Registrazione nuovo utente |
| `/login` | POST | Autenticazione utente |
| `/chats/insert` | POST | Salva sessione completata (chiamato da `main.py`) |
| `/chats/select?username=X` | GET | Restituisce tutte le sessioni di un utente |

---

### 4. Core Pipeline Vocale — `engine/main.py` & `engine/audio.py`

`main.py` è il cuore dell'Engine AI: un hub WebSocket che coordina l'intera pipeline audio bidirezionale dalla ricezione del PCM grezzo fino alla sintesi vocale.

**Pipeline completa per turno conversazionale:**

```python
@app.websocket("/ws")
async def voice_pipeline(websocket: WebSocket, username: str = Query(...)):
    # 1. Riceve chunk PCM binari (512 campioni × 2 byte = 1024 byte per frame)
    pcm_f32 = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32_768.0

    # 2. Silero VAD — rileva inizio/fine parlato sul singolo frame
    vad_event = vad(torch.from_numpy(pcm_f32), return_seconds=False)

    # 3. Silence timeout — chiude sessione dopo 10s senza voce
    if not in_speech and silence_start is not None:
        if time.monotonic() - silence_start >= SILENCE_TIMEOUT_S:
            await websocket.send_json({"type": "silence_timeout"})
            await websocket.close(code=1000)

    # 4. A fine parlato: denoise → WAV → STT → LLM → TTS → client
    if "end" in vad_event:
        await websocket.send_json({"type": "listening_stop"})  # stop eco acustico
        pcm_clean = denoise_pcm(pcm_turn, MIC_SAMPLE_RATE)     # riduzione rumore
        wav_bytes  = encode_pcm_as_wav(pcm_clean, MIC_SAMPLE_RATE)
        full_text, transcript = await stream_llm_response(...)  # pipeline AI
```

**Silero VAD in `audio.py` — parametri di sensibilità:**

```python
VAD_THRESHOLD         = 0.55   # probabilità minima per considerare un frame "parlato"
VAD_MIN_SILENCE_MS    = 600    # ms di silenzio per segnalare fine frase
VAD_SPEECH_PAD_MS     = 60    # padding aggiunto ai bordi del segmento vocale
MIN_SPEECH_DURATION_S = 0.5   # scarta turni più corti di 500 ms (rumori accidentali)

def make_vad_iterator() -> VADIterator:
    return VADIterator(
        silero_vad_model,
        sampling_rate=MIC_SAMPLE_RATE,    # 16.000 Hz
        threshold=VAD_THRESHOLD,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
    )
```

**Salvataggio sessione garantito nel `finally`:**

```python
finally:
    # Eseguito SEMPRE: disconnessione normale, crash, timeout
    if conversation_history:
        async with httpx.AsyncClient(timeout=30.0) as db_client:
            await db_client.post(DATABASE_URL, json={
                "username":   username,
                "created_at": session_started_ms,
                "chat":       conversation_history,
            })
```

---

### 5. Inferenza AI (STT + LLM) — `engine/inference.py`

Gestisce la trascrizione audio (Whisper) e la generazione streaming della risposta (Gemma 4 via llama.cpp), con flush immediato verso il TTS a ogni boundary di frase.

**System prompt ottimizzato per output vocale:**

```python
SYSTEM_PROMPT = (
    "Sei un assistente vocale utile. "
    "Riceverai messaggi in inglese o italiano; rispondi sempre nella stessa lingua parlata dall'utente. "
    "la tua risposta verrà pronunciata ad alta voce, "
    "non mostrata come testo, quindi evita markdown, elenchi puntati e liste lunghe."
)
```

> Il prompt vieta esplicitamente markdown e liste perché i simboli (`*`, `-`, `#`) sarebbero letti letteralmente dal sintetizzatore vocale.

**Pipeline STT → LLM streaming → TTS a frase:**

```python
# 1. Trascrizione con Whisper — lingua forzata su "it" per saltare language detection
resp = await http_client.post(
    SPEECH_TO_TEXT_URL + "inference",
    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
    data={"response_format": "json", "language": "it"},
)
transcript = resp.json().get("text", "").strip()

# 2. Richiesta al LLM con streaming SSE
payload = {
    "model":      "gemma-4-e2b",
    "messages":   [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                   {"role": "user", "content": transcript}],
    "stream":     True,
    "max_tokens": 512,
}

# 3. Flush verso TTS a ogni boundary di frase (. ! ? … \n)
SENTENCE_BOUNDARY_CHARS = (".", "!", "?", "…", "\n")

async with http_client.stream("POST", INFERENCE_URL, json=payload) as stream:
    async for raw_line in stream.aiter_lines():
        token = data["choices"][0]["delta"].get("content", "")
        pending_phrase += token

        if pending_phrase.rstrip().endswith(SENTENCE_BOUNDARY_CHARS):
            # Invia la frase completa al TTS senza aspettare la fine della risposta
            await synthesize_and_forward_audio(websocket, http_client, pending_phrase.strip())
            pending_phrase = ""
```

---

### 6. Text-to-Speech — `engine/text_to_speech.py`

Microservizio FastAPI che lancia Piper TTS come sottoprocesso asincrono e restituisce audio WAV pronto per la riproduzione.

```python
@app.post("/")
async def text_to_speech(request: TTSRequest) -> Response:
    # Piper riceve testo su stdin e scrive PCM raw su stdout
    # --output-raw produce int16 signed mono senza header WAV
    proc = await asyncio.create_subprocess_exec(
        PIPER_BIN,
        "--model", PIPER_MODEL,   # it_IT-riccardo-x_low.onnx
        "--output-raw",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    pcm_bytes, _ = await proc.communicate(input=request.text.encode("utf-8"))

    # Aggiunge l'header WAV al PCM grezzo prima di ritornarlo
    wav_bytes = _pcm_to_wav(pcm_bytes, PIPER_SAMPLE_RATE)   # 22.050 Hz
    return Response(content=wav_bytes, media_type="audio/wav")
```

Il modello `it_IT-riccardo-x_low` è scelto per il basso utilizzo di risorse e la buona intelligibilità in italiano.

---

### 7. Script di Avvio — `start_all.sh`

Avvia tutti i servizi in parallelo con un singolo comando. Gestisce il ciclo di vita di MongoDB (Docker) e termina tutto pulitamente con `Ctrl+C`.

```bash
# Avvio di tutti i servizi
(cd engine && exec .venv/bin/fastapi dev main.py --port 8002) &           # Engine pipeline
(cd engine && exec .venv/bin/fastapi dev text_to_speech.py --port 8003) & # TTS
"$WHISPER_BIN" --model "$WHISPER_MODEL" --port 8004 --language it &       # Whisper STT
(cd orchestrator && exec .venv/bin/fastapi dev router.py --port 8000) &   # Router
(cd orchestrator && exec .venv/bin/fastapi dev wake_word_detector.py --port 8001) & # Wake-word
(cd orchestrator && exec .venv/bin/fastapi dev website.py --port 8005) &  # Web + API
/home/leo/llama.cpp/build/bin/llama-server \
    -m gemma-4-E2B-it-UD-Q4_K_XL.gguf \
    --host 127.0.0.1 --port 8080 -ngl 99 &                               # LLM (GPU)

# Trap Ctrl+C per fermare tutto
trap cleanup SIGINT SIGTERM
```

---

## Modelli AI Utilizzati

| Modello | Tipo | Formato | Utilizzo |
|---------|------|---------|---------|
| **Whisper Large v3 Turbo** (`ggml-large-v3-turbo-q5_0.bin`) | STT | GGML Q5_0 | Trascrizione audio → testo, lingua forzata `it` |
| **Gemma 4 E2B** (`gemma-4-E2B-it-UD-Q4_K_XL.gguf`) | LLM | GGUF Q4_K_XL | Generazione risposta testuale in streaming |
| **Piper it_IT-riccardo-x_low** (`it_IT-riccardo-x_low.onnx`) | TTS | ONNX | Sintesi vocale italiana ad alta efficienza |
| **Silero VAD** | VAD | PyTorch | Rilevamento voce / fine frase |
| **openWakeWord hey_jarvis_v0.1** | Wake-word | ONNX | Rilevamento parola di attivazione |

---

## Librerie e Dipendenze

### Engine AI (`engine/`)

| Libreria | Versione | Utilizzo |
|----------|----------|---------|
| `fastapi` | ≥0.110 | Framework web/WebSocket asincrono |
| `httpx` | ≥0.27 | Client HTTP asincrono per chiamate inter-servizio |
| `torch` | ≥2.0 | Runtime PyTorch per Silero VAD |
| `silero-vad` | ≥4.0 | Voice Activity Detection |
| `noisereduce` | ≥3.0 | Riduzione spettrale del rumore |
| `numpy` | ≥1.24 | Manipolazione array PCM |
| `pydantic` | ≥2.0 | Validazione dati (incluso in FastAPI) |
| `uvicorn` | ≥0.29 | ASGI server per FastAPI |

### Orchestratore (`orchestrator/`)

| Libreria | Versione | Utilizzo |
|----------|----------|---------|
| `fastapi` | ≥0.110 | Framework web e WebSocket proxy |
| `httpx` | ≥0.27 | Chiamate HTTP al Wake-Word Detector |
| `openwakeword` | ≥0.6 | Modello di rilevamento wake-word |
| `noisereduce` | ≥3.0 | Denoising pre-modello wake-word |
| `numpy` | ≥1.24 | Conversione frame PCM int16 → float32 |
| `pymongo` | ≥4.6 | Driver MongoDB per storico chat |
| `pydantic` | ≥2.0 | Validazione schema `ChatSession` |
| `python-multipart` | ≥0.0.9 | Parsing form data (login/signup) |

### Servizi Esterni (binari)

| Servizio | Tecnologia | Utilizzo |
|----------|------------|---------|
| **whisper-server** | C++ (whisper.cpp) | Inference Whisper su CPU/GPU, API REST |
| **llama-server** | C++ (llama.cpp) | Inference Gemma 4 con offload GPU (`-ngl 99`), API OpenAI-compatible |
| **piper** | C++ + ONNX Runtime | TTS via subprocess, stdin/stdout PCM |
| **MongoDB 7** | Docker | Persistenza storico conversazioni |

---

## Setup e Utilizzo

### Prerequisiti

- Python 3.10+ con `venv` in `engine/` e `orchestrator/`
- Docker (per MongoDB)
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) compilato
- [llama.cpp](https://github.com/ggerganov/llama.cpp) compilato con supporto GPU
- [Piper](https://github.com/rhasspy/piper) binario e modello `it_IT-riccardo-x_low.onnx`
- Modello Whisper: `ggml-large-v3-turbo-q5_0.bin`
- Modello LLM: `gemma-4-E2B-it-UD-Q4_K_XL.gguf`

### Installazione dipendenze Python

```bash
# Engine
cd engine && python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn httpx torch silero-vad noisereduce numpy pydantic

# Orchestratore
cd orchestrator && python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn httpx openwakeword noisereduce numpy pymongo pydantic python-multipart
```

### Avvio rapido

```bash
chmod +x start_all.sh
./start_all.sh
```

Lo script avvia automaticamente: MongoDB (Docker), Whisper STT, llama.cpp LLM, Engine pipeline, TTS, Wake-word detector, Router e Web server.

### Test dall'interfaccia web

1. Apri il browser su `http://localhost:8005/`
2. Registra un account nella scheda **Create account** ed effettua il login
3. Nella dashboard (`/home`) clicca **Connect** per abilitare il microfono
4. Pronuncia **"Jarvis"** e inizia a parlare
5. Visita `/chats` per consultare lo storico completo delle conversazioni

---

## Porte e Servizi

| Porta | Servizio | File | Protocollo |
|-------|---------|------|------------|
| **8000** | Router WebSocket + Auth | `orchestrator/router.py` | WS / HTTP |
| **8001** | Wake-Word Detector | `orchestrator/wake_word_detector.py` | HTTP REST |
| **8002** | Engine AI — Pipeline vocale | `engine/main.py` | WS |
| **8003** | Text-to-Speech (Piper) | `engine/text_to_speech.py` | HTTP REST |
| **8004** | Speech-to-Text (Whisper) | whisper-server (binario C++) | HTTP REST |
| **8005** | Web Server + API Chat | `orchestrator/website.py` | HTTP |
| **8080** | LLM Server (Gemma 4) | llama-server (binario C++) | HTTP REST (OpenAI-compat.) |
| **27017** | MongoDB | Docker `local-mongo` | MongoDB Wire Protocol |