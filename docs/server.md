# VELA — Server Middleware (Node 2)

Documentazione per il setup, la configurazione e la manutenzione del server middleware centrale del progetto VELA.

---

## Indice

1. [Panoramica](#1-panoramica)
2. [Requisiti Hardware e OS](#2-requisiti-hardware-e-os)
3. [Preparazione dell'Ambiente](#3-preparazione-dellambiente)
4. [Struttura della Directory e Git](#4-struttura-della-directory-e-git)
5. [Autenticazione e Database](#5-autenticazione-e-database)
6. [Gestione Utenti CLI](#6-gestione-utenti-cli)
7. [Setup del Server WebSocket (In arrivo)](#7-setup-del-server-websocket-in-arrivo)
8. [Logica di Archiviazione (In arrivo)](#8-logica-di-archiviazione-in-arrivo)
9. [Worker di Inferenza Audio (In arrivo)](#9-worker-di-inferenza-audio-in-arrivo)
10. [Servizi di Avvio Automatico (In arrivo)](#10-servizi-di-avvio-automatico-in-arrivo)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Panoramica

Il nodo middleware è un Raspberry Pi 5 **sempre attivo** (always-on). Funge da ponte tra il nodo edge (ESP32), il nodo di inferenza visiva (Laptop) e i client (App Android). Gestisce localmente le operazioni audio a bassa latenza e orchestra il sistema.

**Responsabilità principali:**
- Rilevamento continuo della Wake Word ("Hey Vela") tramite `openWakeWord`.
- Speech-to-Text (STT) locale tramite `faster-whisper`.
- Text-to-Speech (TTS) locale tramite `piper-tts`.
- Gestione delle connessioni WebSocket sicure in entrata e uscita.
- Autenticazione utenti e storicizzazione delle conversazioni (SQLite).
- Invio del pacchetto Wake-on-LAN al Node 3 quando è richiesta l'analisi visiva.

---

## 2. Requisiti Hardware e OS

| Componente | Specifiche usate in VELA |
|------------|--------------------------|
| SBC | Raspberry Pi 5 |
| RAM | 4 GB |
| Storage | Unità SSD NVMe/USB (montata come root) |
| OS | Raspberry Pi OS Lite (Debian 13 Trixie) - Headless |
| Rete | Ethernet / Wi-Fi |

> **Nota OS:** Essendo il sistema basato su Debian Trixie, Python impone l'uso degli ambienti virtuali (`externally-managed-environment`). L'installazione globale tramite `pip` è bloccata di default per proteggere i pacchetti di sistema.

---

## 3. Preparazione dell'Ambiente

Aggiornare il sistema e installare i pacchetti base:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install git python3-pip python3-venv -y
```

Creare e attivare l'ambiente virtuale nella directory del progetto (`vela/`):
```bash
cd ~/vela
python3 -m venv venv
source venv/bin/activate
```

Installare le dipendenze software fondamentali per il backend:
```bash
pip install fastapi uvicorn websockets faster-whisper piper-tts wakeonlan openwakeword
```

---

## 4. Struttura della Directory e Git

Per questioni di sicurezza ed evitare di necessitare permessi di `root`, la directory dei dati (database e salvataggi media) risiede localmente nella cartella del progetto.

Creare le cartelle necessarie:
```bash
mkdir -p server/data
mkdir -p server/wake_word
```

**Configurazione `.gitignore`**
Per evitare di esporre dati sensibili, pesi dei modelli e l'ambiente virtuale sulla repository GitHub, aggiungere le seguenti righe al file `.gitignore`:
```gitignore
server/data/
venv/
__pycache__/
*.db
```

---

## 5. Autenticazione e Database

Il sistema rifiuta qualsiasi flusso audio dai client (ESP32 o Android) senza previa autenticazione sicura.
Il modulo `server/auth.py` gestisce l'inizializzazione del database SQLite e l'hashing.

**Caratteristiche:**
- **Database:** SQLite salvato in `server/data/users.db`
- **Sicurezza:** Le password non vengono mai salvate in chiaro, ma viene generato e verificato un hash SHA-256.
- **Handshake:** Il client deve inviare l'hash SHA-256 della password durante la connessione iniziale via WebSocket.

---

## 6. Gestione Utenti CLI

Prima di poter connettere l'ESP32 o l'App Android, è necessario creare almeno un account utente. È stato sviluppato uno strumento a riga di comando per farlo in sicurezza.

**Creazione di un utente:**
```bash
# Assicurarsi di avere il venv attivato
source venv/bin/activate
python server/manage_users.py add <nome_utente>
```
Il sistema chiederà di inserire la password in modo invisibile (senza mostrarla a schermo) e la salverà nel database locale.

---

## 7. Setup del Server WebSocket (In arrivo)
*Questa sezione documenterà il file `server/ws_server.py`, la configurazione di FastAPI, Uvicorn e il routing dei pacchetti JSON/Binary dal Node 1.*

---

## 8. Logica di Archiviazione (In arrivo)
*Questa sezione documenterà il modulo `server/storage.py` per il salvataggio strutturato di log, immagini ricevute dall'ESP32 e metadati utente dentro `server/data/`.*

---

## 9. Worker di Inferenza Audio (In arrivo)
*Questa sezione documenterà `server/inference_worker.py`, il posizionamento del modello `.onnx` di "Hey Vela", l'inizializzazione di Whisper per l'STT e di Piper per il TTS.*

---

## 10. Servizi di Avvio Automatico (In arrivo)
*Questa sezione conterrà le istruzioni per creare i file `systemd` (`vela-server.service` e `vela-worker.service`) in modo che il Node 2 parta automaticamente all'avvio del Raspberry Pi.*

---

## 11. Troubleshooting

### Errore `Error opening terminal: xterm-kitty` usando Nano
**Problema:** Quando ci si connette in SSH da un emulatore terminale come Kitty, l'apertura di editor testuali come `nano` fallisce perché Raspberry Pi OS Lite non contiene le definizioni (terminfo) per quel terminale specifico.

**Soluzione Temporanea:** Impostare una variabile d'ambiente standard prima di lanciare l'editor:
```bash
export TERM=xterm-256color
nano server/auth.py
```

**Soluzione Permanente:** Connettersi dal laptop usando il comando SSH specifico integrato nel terminale:
```bash
kitty +kitten ssh utente@ip-del-raspberry
```

### Pacchetti Python non trovati (`ModuleNotFoundError`)
Se eseguendo uno script Python il sistema non trova librerie come `fastapi` o `websockets`, significa che l'ambiente virtuale non è attivo in quella sessione SSH.

**Soluzione:** Ricaricare l'ambiente:
```bash
cd ~/vela
source venv/bin/activate
```
