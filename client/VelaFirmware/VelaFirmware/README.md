# VelaFirmware — ESP32 Client

Firmware Arduino (C++) per il nodo ESP32 del sistema **Vela**.

---

## Struttura dei file

```
VelaFirmware/
├── VelaFirmware.ino      # Sketch principale (setup + loop + state machine)
├── config.h              # Pin, costanti, parametri audio
├── vela_state.h          # Enum VelaState, struct VelaCredentials, AuthInfo
├── led.h                 # Pattern LED non-bloccanti
├── nvs_creds.h           # Salva/carica credenziali in NVS (Preferences)
├── wifi_provision.h      # WiFiManager: AP captive portal + parametri custom
├── auth_client.h         # HTTP POST /auth/login → JWT
├── audio_i2s.h           # I2S mic (INMP441) + speaker (MAX98357A)
├── router_ws.h           # WebSocket client per router.py
├── engine_ws.h           # WebSocket client per main.py
└── base64_decode.h       # Decodifica base64 per audio WAV dal server
```

---

## Hardware necessario

| Componente     | Modello consigliato | Note                          |
|----------------|---------------------|-------------------------------|
| Microcontroller| ESP32-WROOM-32      | Qualsiasi board ESP32 va bene |
| Microfono      | INMP441             | I2S MEMS, 3.3 V               |
| Amplificatore  | MAX98357A           | I2S DAC + amp, 5 V            |
| Speaker        | 4 Ω / 3 W          | Collegato al MAX98357A        |
| LED (opzionale)| LED + resistore 220Ω| GPIO 2 (built-in su DevKit)   |

---

## Schema di collegamento

### INMP441 (microfono)

```
INMP441   →   ESP32
───────────────────
VDD       →   3.3V
GND       →   GND
WS        →   GPIO 15
SCK       →   GPIO 14
SD        →   GPIO 32
L/R       →   GND   (seleziona canale sinistro)
```

### MAX98357A (altoparlante)

```
MAX98357A →   ESP32
────────────────────
VIN       →   5V
GND       →   GND
LRC       →   GPIO 27
BCLK      →   GPIO 26
DIN       →   GPIO 25
SD        →   3.3V  (lascia sempre acceso)
```

> Per cambiare i pin modifica le `#define` in **config.h**.

---

## Installazione librerie (Arduino IDE)

Apri **Strumenti → Gestisci librerie…** e installa:

| Libreria       | Autore          | Versione minima |
|----------------|-----------------|-----------------|
| `WiFiManager`  | tzapu           | 2.0.17          |
| `WebSockets`   | Markus Sattler  | 2.4.0           |
| `ArduinoJson`  | Benoit Blanchon | 7.0.0           |

Installa anche il **ESP32 board package** tramite Boards Manager:
URL aggiuntivo: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`

---

## Configurazione Arduino IDE

| Impostazione          | Valore                            |
|-----------------------|-----------------------------------|
| Board                 | ESP32 Dev Module                  |
| Partition Scheme      | **Default 4MB with spiffs**       |
| Upload Speed          | 921600                            |
| CPU Frequency         | 240 MHz                           |
| Flash Frequency       | 80 MHz                            |
| Flash Mode            | QIO                               |
| Core Debug Level      | None (o Verbose per debug)        |

> ⚠️ La partition scheme "Minimal SPIFFS" è necessaria se ArduinoJson
> causa errori OOM durante la risposta del motore AI (audio base64 grande).

---

## Primo avvio – Provisioning via captive portal

Al primo avvio (o dopo un reset delle credenziali) l'ESP32 crea un
Access Point chiamato **`Vela-Setup`** (password: `vela1234`).

1. Connettiti con telefono/PC alla rete **Vela-Setup**
2. Si apre automaticamente il captive portal (o vai su `192.168.4.1`)
3. Compila i campi:

| Campo                  | Esempio           |
|------------------------|-------------------|
| WiFi SSID              | `MiaRete`         |
| WiFi Password          | `miapassword`     |
| **Raspberry Pi 5 IP**  | `192.168.1.42`    |
| **Vela username**      | `mario`           |
| **Vela password**      | `segreto`         |

4. Premi **Save** → l'ESP32 si connette e avvia la sessione

Le credenziali sono salvate in NVS; i riavvii successivi non richiedono
il provisioning (a meno che la rete o l'IP cambino).

---

## Reset completo

Per riprovisionare da zero, aggiungi temporaneamente al `setup()`:

```cpp
WifiProvision::resetAll();   // cancella WiFi + credenziali NVS
ESP.restart();
```

Oppure usa il Serial Monitor per identificare e correggere il problema.

---

## Flusso operativo

```
BOOT
 │
 ▼
WIFI_CONNECT  ──(fallisce)──► AP captive portal ──(timeout)──► ERROR → retry
 │
 ▼
AUTHENTICATING  POST http://<PI>:5001/auth/login
 │  ◄── JWT + ws_host:ws_port
 ▼
ROUTER_CONNECT  ws://<PI>:8766
 │  ──► {"type":"auth","token":"..."}
 │  ◄── {"type":"ready"}
 ▼
LISTENING  streaming PCM mic → router
 │  ◄── binary WAV (audio cue wake word)
 │  ◄── {"type":"handoff","ws_host":"...","ws_port":8765}
 ▼
WAKE_DETECTED  riproduce audio cue
 │
 ▼
ENGINE_CONNECT  ws://<PI>:8765
 │
 ▼
ACTIVE  streaming PCM mic → engine
 │  ◄── {"type":"response_chunk","text":"...","audio":"<b64 WAV>"}
 ▼
RESPONDING  riproduce audio TTS
 │  ◄── {"type":"session_end"}
 │
 └──────────────────────────────────► AUTHENTICATING (nuova sessione)
```

---

## Pattern LED di stato

| Stato              | Pattern LED          |
|--------------------|----------------------|
| BOOT               | Spento               |
| WiFi / Auth        | Lampeggio veloce     |
| LISTENING          | Lampeggio lento (1 Hz)|
| WAKE / ACTIVE      | Doppio impulso (2 s) |
| RESPONDING (TTS)   | Fisso acceso         |
| ERROR              | Lampeggio veloce     |

---

## Parametri audio (config.h)

| Parametro          | Valore default | Descrizione                        |
|--------------------|----------------|------------------------------------|
| `SAMPLE_RATE`      | 16000 Hz       | Deve coincidere col server         |
| `MIC_CHUNK_SAMPLES`| 1600           | ~100 ms per chunk (3200 byte)      |
| `I2S_DMA_BUF_COUNT`| 8              | Buffer DMA I2S                     |
| `I2S_DMA_BUF_LEN`  | 512            | Campioni per buffer DMA            |

---

## Debug

Apri il **Serial Monitor** a **115200 baud**.  
Ogni transizione di stato, pacchetto ricevuto e errore viene loggato con prefisso:

```
[STATE]   transizioni
[AUTH]    login HTTP
[ROUTER]  messaggi WebSocket router
[ENGINE]  messaggi WebSocket engine
[MIC]     I2S microfono
[SPK]     I2S altoparlante
[NVS]     credenziali NVS
[WIFI]    connessione WiFi
```
