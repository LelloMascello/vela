# VelaApp — Android Client

Client Android per il sistema di assistente vocale distribuito **Vela**.

## Architettura

```
LoginActivity  →  [HTTP POST /auth/login]  →  auth.py  (porta 5001)
                                                  │
                                                  └─► JWT + ws_host:ws_port
                                                            │
MainActivity ──────────────────────────────────────────────►│
     │                                              RouterSocket (porta 8766)
     │   [mic PCM stream ──────────────────────────►]
     │   [◄── audio cue WAV]
     │   [◄── {type:"handoff", ws_host, ws_port}]
     │                                                        │
     │                                              EngineSocket (porta 8765)
     │   [mic PCM stream ──────────────────────────►]
     │   [◄── {type:"response_chunk", text, audio}]
     └   [◄── {type:"session_end"}]
```

## Struttura del progetto

```
VelaApp/
├── app/src/main/
│   ├── AndroidManifest.xml
│   ├── java/com/vela/app/
│   │   ├── LoginActivity.kt          # Schermata login (IP + credenziali)
│   │   ├── MainActivity.kt           # Schermata principale
│   │   ├── audio/
│   │   │   ├── AudioRecorder.kt      # Cattura mic 16kHz/16bit/mono
│   │   │   └── AudioPlayer.kt        # Riproduce WAV dal server
│   │   ├── model/
│   │   │   └── Models.kt             # Data classes (LoginRequest/Response, WsFrame, UiState)
│   │   ├── network/
│   │   │   ├── AuthService.kt        # POST /auth/login
│   │   │   ├── RouterSocket.kt       # WebSocket → router.py
│   │   │   └── EngineSocket.kt       # WebSocket → main.py
│   │   └── ui/
│   │       └── VelaViewModel.kt      # State machine centrale
│   └── res/
│       ├── layout/
│       │   ├── activity_login.xml
│       │   └── activity_main.xml
│       ├── values/
│       │   ├── strings.xml
│       │   ├── colors.xml
│       │   └── themes.xml
│       └── drawable/
│           └── ic_mic.xml
├── app/build.gradle.kts
├── build.gradle.kts
├── settings.gradle.kts
└── gradle/libs.versions.toml
```

## Prerequisiti

| Tool            | Versione minima |
|-----------------|-----------------|
| Android Studio  | Ladybug (2024.2) |
| AGP             | 8.4.2           |
| Kotlin          | 2.0.0           |
| minSdk          | 26 (Android 8)  |
| targetSdk       | 35              |

## Importazione in Android Studio

1. **File → Open** e seleziona la cartella `VelaApp/`
2. Attendi il sync Gradle (scarica ~50 MB di dipendenze)
3. Connetti un dispositivo fisico **oppure** crea un AVD con API 26+
4. Premi **▶ Run**

> ⚠️  Il microfono **non funziona** sull'emulatore Android. Usa un dispositivo fisico per testare la cattura audio.

## Configurazione di rete

L'app usa `android:usesCleartextTraffic="true"` per permettere connessioni `ws://` e `http://` sulla rete locale.  
Per produzione/internet:
- Cambia i server in HTTPS/WSS
- Rimuovi `usesCleartextTraffic` dal Manifest

## Flusso utente

1. **Login** — Inserisci IP del Raspberry Pi, username e password
2. **Autenticazione** — L'app chiama `POST http://<IP>:5001/auth/login`
3. **Ascolto** — Connessione al Router WebSocket, lo streaming PCM parte automaticamente
4. **Wake word** — Il router rileva "Vela", invia un audio cue e poi un `handoff`
5. **Sessione attiva** — L'app si connette all'Engine, lo streaming continua
6. **Risposta** — L'Engine restituisce chunk JSON `{text, audio}` — il testo appare a schermo, l'audio viene riprodotto
7. **Fine sessione** — `session_end` riporta l'app in stato IDLE

## Dipendenze principali

```
OkHttp 4.12    — HTTP + WebSocket
Gson 2.11      — JSON serialization
Coroutines     — async/Flow per mic + playback
Material 1.12  — UI components
Lifecycle 2.8  — ViewModel + StateFlow
```

## Permessi richiesti

| Permesso            | Scopo                        |
|---------------------|------------------------------|
| `RECORD_AUDIO`      | Cattura microfono            |
| `INTERNET`          | WebSocket + HTTP             |
| `ACCESS_NETWORK_STATE` | Verifica connettività     |
| `WAKE_LOCK`         | Mantiene CPU attiva in sessione |
