# Documentazione Setup Server Middleware (Node 2)

Questo documento traccia i passaggi effettuati per configurare il Node 2 del progetto VELA (Raspberry Pi 5) partendo da un'installazione pulita di Raspberry Pi OS Lite (Debian Trixie). Il Pi 5 funge da middleware sempre attivo, gestendo il rilevamento della wake word, STT, TTS e l'archiviazione.

## 1. Preparazione dell'Ambiente
Per evitare conflitti con i pacchetti di sistema di Debian Trixie (errore externally-managed-environment), tutto il codice Python viene eseguito all'interno di un ambiente virtuale isolato.

Creazione e attivazione dell'ambiente virtuale:
python3 -m venv venv
source venv/bin/activate

## 2. Installazione delle Dipendenze
All'interno del virtual environment, sono state installate le librerie fondamentali per il funzionamento del server backend, del sistema audio e della comunicazione WebSocket:
pip install fastapi uvicorn websockets faster-whisper piper-tts wakeonlan openwakeword

## 3. Gestione Dati e Database
Si è scelto di mantenere il database e i salvataggi all'interno della directory del progetto, nel percorso server/data/. Questo elimina la necessità di eseguire il server con i permessi di root (sudo).

Per evitare che il database degli utenti e le conversazioni private finiscano sulla repository GitHub, il file .gitignore è stato aggiornato con le seguenti regole:
server/data/
venv/
__pycache__/

## 4. Sistema di Autenticazione (auth.py)
Il sistema rifiuta qualsiasi flusso audio dai client (ESP32 o Android) senza previa autenticazione. 
È stato implementato il modulo server/auth.py che:
- Inizializza un database locale SQLite in server/data/users.db.
- Salva le password cifrate tramite hashing sicuro SHA-256.
- Verifica le credenziali inviate dai client durante l'handshake WebSocket.

## 5. Strumento di Gestione Utenti (manage_users.py)
Per creare gli account è stato sviluppato uno script CLI. Questo strumento richiede la password in modo sicuro (senza mostrarla a schermo) e la inserisce nel database.

Uso:
python server/manage_users.py add <nome_utente>

---

### Risoluzione Problemi (Troubleshooting)
Problema: Durante l'accesso via SSH da un emulatore terminale Kitty, l'apertura di editor come nano falliva con l'errore "Error opening terminal: xterm-kitty".
Soluzione: Raspberry Pi OS Lite non ha le definizioni per quel terminale. È stato risolto temporaneamente impostando una variabile d'ambiente standard prima di lanciare l'editor:
export TERM=xterm-256color
