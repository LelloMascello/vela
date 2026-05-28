# Progetto per l'Esame di Stato · *Maturità 2025*

Un assistente vocale distribuito, attivato tramite *wake-word*, in esecuzione su tre nodi fisici: un dispositivo client (ESP32-S3 o Android/Web), un server orchestratore e un server AI (motore di inferenza).

---

## Indice

* [Panoramica](#panoramica)  
* [Architettura](#architettura)  
* [Flusso di Conversazione](#flusso-di-conversazione)  
* [Struttura del Progetto](#struttura-del-progetto)  
* [Componenti del Sistema](#componenti-del-sistema)  
* [Setup e Utilizzo](#setup-e-utilizzo)

---

## Panoramica

**Jarvis** è un assistente vocale *general-purpose* progettato per funzionare su hardware consumer distribuito. Il nome stesso funge da parola di attivazione: pronunciare *"Jarvis"* avvia una sessione conversazionale. 

Il sistema è stato concepito per l'elaborazione audio in tempo reale e si compone di tre nodi interconnessi in rete locale:  
1. **Client (ESP32-S3, Android o Interfaccia Web):** Cattura l'audio in ingresso tramite microfono e riproduce le risposte in streaming.  
2. **Orchestratore (es. Raspberry Pi 5 o istanza dedicata):** Gestisce il routing iniziale dei flussi, l'autenticazione tramite database relazionale e lo storage delle chat.  
3. **Engine AI (Laptop / Server GPU):** Esegue la pipeline di intelligenza artificiale pesante (VAD, STT, LLM locale e TTS).

---

## Architettura

```  
┌─────────────────────┐  flusso audio continuo   ┌──────────────────────────┐  
│  ESP32-S3 / Android │ ───────────────────────> │       Orchestratore      │  
│      (client)       │ <─────────────────────── │    (Router + Auth)       │  
│                     │ segnale wake word / sync │                          │  
│  · microfono        │                          │  · router.py (Port 8766) │  
│  · altoparlante     │                          │  · auth.py (SQLite DB)   │  
│  · WiFi             │                          │  · website.py (MongoDB)  │  
└─────────────────────┘                          └───────────┬──────────────┘  
          ^                                                  │  
          │                                                  │ passaggio del flusso  
          │                                                  v  
          │                                      ┌──────────────────────────┐  
          │        risposta audio (chunk)        │         Engine AI        │  
          └───────────────────────────────────── │    (main.py - Port 8002) │  
                                                 │                          │  
                                                 │  · Silero VAD / OpenWW   │  
                                                 │  · Whisper STT (Large)   │  
                                                 │  · Gemma 4 (LLM locale)  │  
                                                 │  · Piper TTS (Riccardo)  │  
                                                 └──────────────────────────┘
```

## **Flusso di Conversazione**

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
│  si resetta a 10s    │  
└──────────┬───────────┘  
           │ silenzio > 10 s  
           v  
┌──────────────────────┐  
│  Chiusura sessione   │──> Salvataggio cronologia su MongoDB  
└──────────────────────┘
```

**Passaggi operativi:**

1. **Ascolto passivo:** Il client invia l'audio al Router dell'orchestratore. Quest'ultimo lo analizza tramite openwakeword. Il motore AI principale rimane in attesa.  
2. **Wake word:** Al rilevamento della parola chiave, il router reindirizza il client verso l'hub WebSocket dell'Engine AI (main.py).  
3. **Ascolto attivo:** L'Engine AI analizza i frame audio. Se l'utente non parla entro 10 secondi, la sessione scade e il client torna al router in modalità ascolto passivo.  
4. **Generazione della risposta:** Quando l'utente termina una frase (rilevata con precisione da Silero VAD), l'audio viene trascritto da Whisper. Il testo viene processato da Gemma 4; i token generati vengono inviati a blocchi (frasi) a Piper TTS, che sintetizza l'audio rimandandolo immediatamente al client in streaming.  
5. **Finestra di follow-up:** Finita la riproduzione dell'audio, il client rimane in ascolto attivo per altri 10 secondi. Se l'utente parla ancora, il sistema risponde direttamente senza bisogno di ripetere la wake-word.  
6. **Chiusura della sessione:** Scaduto il timeout, l'Engine si disconnette, invia la cronologia completa all'orchestratore (che la salva permanentemente) e rimanda il client in modalità passiva.

## **Struttura del Progetto**
```
Plaintext  
Pollini/  
├── client/  
│   ├── esp32/                              # Firmware C++ (ESP32-S3)  
│   └── JarvisApp/                          # App Android Studio in Kotlin  
├── orchestrator/  
│   ├── auth.py                             # Gestione utenti (SQLite)  
│   ├── router.py                           # WebSocket proxy & Wake Word manager (Port 8766)  
│   ├── wake_word_detector.py               # Analisi acustica locale (openwakeword)  
│   ├── website.py                          # Web Server & API Storico Chat (MongoDB - Port 8005)  
│   ├── users.db                            # Database SQLite credenziali (auto-generato)  
│   └── public/                             # Dashboard Web Frontend  
│       ├── index.html, index.js            # Login / Registrazione  
│       ├── home.html, home.js              # Pannello di controllo e Client Web  
│       ├── chats.html, chats.js            # Consultazione storico conversazioni  
│       └── style.css                       # Fogli di stile globali  
├── engine/  
│   ├── main.py                             # Hub di coordinamento della pipeline vocale (Port 8002)  
│   ├── audio.py                            # Gestione Silero VAD e utility audio PCM/WAV  
│   ├── inference.py                        # Client per Whisper STT e streaming LLM (llama.cpp)  
│   └── text_to_speech.py                   # Integrazione locale con Piper TTS  
├── README.md  
└── start_all.sh
```
## **Componenti del Sistema**

Il backend si appoggia interamente su **FastAPI** ed è strutturato in moduli specializzati per massimizzare le performance di streaming asincrono.

### **1. Router e Gestione Wake-Word (orchestrator/router.py & wake_word_detector.py)**

Il router è il punto di ingresso per i client. Per garantire la stabilità ed evitare falsi positivi:

* Implementa un **periodo di warm-up** di 10 frame iniziali per svuotare i buffer audio residui del client.  
* Interfaccia l'audio grezzo a 16 kHz con openwakeword, applicando algoritmi di riduzione del rumore (noisereduce).  
* Gestisce una logica a doppia soglia di attivazione (**Latch Path** per attivazione istantanea ad alta confidenza, **Smooth Path** con media mobile su 5 frame per sussurri o parole prolungate).

### **2. Autenticazione e Sicurezza (orchestrator/auth.py)**

Il sistema di login isola i dati delle sessioni tra diversi utenti:

* Utilizza un database relazionale leggero **SQLite** (users.db).  
* Le password non sono salvate in chiaro, ma protette tramite cifratura **SHA256 con Salt casuale a 16 byte** generato crittograficamente via OS.

### **3. Storico Conversazioni (orchestrator/website.py)**

Le chat completate e le relative trascrizioni vengono inviate al server web:

* Utilizza **MongoDB** per memorizzare le sessioni in formato documentale non relazionale, flessibile per i testi generati dalle AI.  
* Sfrutta la validazione dei dati a runtime tramite schemi **Pydantic** (ChatSession), garantendo l'integrità dei timestamp e delle strutture dei messaggi.

### **4. Core Pipeline Vocale (engine/main.py & audio.py)**

Coordina lo streaming bidirezionale una volta attivato l'assistente:

* Integra **Silero VAD** caricato direttamente in memoria per identificare l'inizio e la fine del parlato in modo asincrono.  
* Gestisce lo stato del client inviando messaggi di controllo come listening_stop durante la sintesi vocale per evitare l'eco acustico (auto-ascolto del client).

### **5. Inferenza AI e Sintesi Vocale (engine/inference.py & text_to_speech.py)**

Ottimizzato per l'esecuzione in locale:

* **STT:** Invia l'audio a un'istanza Whisper (ggml-large-v3-turbo) forzando il parametro della lingua su italiano (it) per saltare la fase di auto-rilevamento e tagliare la latenza.  
* **LLM:** Interroga il modello Gemma tramite l'endpoint compatibile di llama.cpp, applicando un *System Prompt* restrittivo che vieta l'uso di liste lunghe e formattazione markdown (inutilizzabile da un sintetizzatore vocale).  
* **TTS:** Isola i confini delle frasi (usando punteggiatura come ., !, ?) e invia i blocchi di testo a **Piper TTS** configurato con il modello italiano ad alta efficienza it_IT-riccardo-x_low.onnx.

## **Setup e Utilizzo**

L'applicazione espone un'interfaccia di amministrazione e un client web completo accessibile da browser.

### **Prerequisiti hardware/software**

* Python 3.10+  
* Server MongoDB locale attivo (mongodb://localhost:27017/)  
* Modelli AI scaricati nelle rispettive cartelle (Whisper GGML, Piper ONNX).

### **Avvio rapido**

Per avviare tutti i nodi dell'orchestratore e dell'engine contemporaneamente, eseguire lo script di orchestrazione automatica dal terminale della macchina server:

Bash  
chmod +x start_all.sh  
./start_all.sh

### **Accesso e test**

1. Apri il browser all'indirizzo dell'orchestratore: http://localhost:8005/  
2. Registra un account nella scheda **Create account** ed effettua il login.  
3. Nella dashboard principale (/home), clicca su **Connect** per abilitare il microfono del browser.  
4. Pronuncia *"Jarvis"* ed inizia a parlare con l'assistente.  
5. Accedi alla scheda **Chats** (/chats) per visualizzare lo storico di tutte le conversazioni salvate nel database con ricerca dinamica.