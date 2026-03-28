#"""
#main.py  –  VELA WebSocket Server
#
#Ottimizzazioni rispetto alla versione originale:
#  - Autenticazione gestita nel router principale PRIMA di inviare dati alla
#    coda audio: i messaggi di auth non intasano più stt_worker inutilmente
#  - Feedback immediato al client su esito auth (auth_result)
#  - Struttura invariata: architettura a code + worker rimane la stessa
#"""

import asyncio
import hashlib
import json

import websockets
from stt_worker import stt_worker
from tts_worker import tts_worker
from inference_worker import inference_worker

# ---------------------------------------------------------------------------
# Database utenti  (sha256 delle password)
# Aggiungi/modifica gli utenti qui.
# Per generare un hash:  python3 -c "import hashlib; print(hashlib.sha256(b'password').hexdigest())"
# ---------------------------------------------------------------------------
USERS_DB: dict[str, str] = {
    "alice": hashlib.sha256(b"tua_password_segreta").hexdigest(),
    # "bob": hashlib.sha256(b"altra_password").hexdigest(),
}

REQUIRE_AUTH = True   # Metti False per disabilitare l'autenticazione in sviluppo


# ---------------------------------------------------------------------------
# Gestore per ogni connessione client
# ---------------------------------------------------------------------------
async def handle_client(websocket) -> None:
    client_ip = websocket.remote_address[0]
    print(f"[SERVER] Nuovo client connesso da {client_ip}")

    # ------------------------------------------------------------------
    # 1. Autenticazione (se abilitata)
    # ------------------------------------------------------------------
    if REQUIRE_AUTH:
        authenticated = False
        try:
            raw_auth = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_msg = json.loads(raw_auth)

            if auth_msg.get("type") == "auth":
                username      = auth_msg.get("username", "")
                password_hash = auth_msg.get("password_hash", "")
                expected_hash = USERS_DB.get(username)

                if expected_hash and password_hash == expected_hash:
                    authenticated = True
                    print(f"[SERVER] Autenticazione OK per '{username}'")
                    await websocket.send(json.dumps({"type": "auth_result", "status": "ok"}))
                else:
                    print(f"[SERVER] Autenticazione FALLITA per '{username}'")
                    await websocket.send(json.dumps({"type": "auth_result", "status": "failed"}))

        except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
            print(f"[SERVER] Errore autenticazione: {e}")

        if not authenticated:
            await websocket.close(1008, "Autenticazione fallita")
            return
    else:
        print("[SERVER] Autenticazione disabilitata — connessione accettata.")

    # ------------------------------------------------------------------
    # 2. Code di comunicazione tra worker
    # ------------------------------------------------------------------
    audio_queue = asyncio.Queue()
    text_queue  = asyncio.Queue()
    tts_queue   = asyncio.Queue()

    # ------------------------------------------------------------------
    # 3. Avvia i worker in background
    # ------------------------------------------------------------------
    stt_task       = asyncio.create_task(stt_worker(audio_queue, text_queue))
    inference_task = asyncio.create_task(inference_worker(text_queue, tts_queue))
    tts_task       = asyncio.create_task(tts_worker(tts_queue, websocket))

    try:
        # ------------------------------------------------------------------
        # 4. Loop di ricezione: smista i messaggi in arrivo
        # ------------------------------------------------------------------
        async for message in websocket:
            try:
                payload = json.loads(message)
                msg_type = payload.get("type")

                if msg_type == "audio_chunk":
                    # Solo i chunk audio vanno nella coda STT
                    await audio_queue.put(message)
                else:
                    # Qualsiasi altro messaggio viene loggato e ignorato
                    print(f"[SERVER] Messaggio non gestito: type='{msg_type}'")

            except (json.JSONDecodeError, Exception) as e:
                print(f"[SERVER] Pacchetto non valido da {client_ip}: {e}")

    except websockets.exceptions.ConnectionClosed:
        print(f"[SERVER] Client {client_ip} disconnesso.")
    finally:
        # ------------------------------------------------------------------
        # 5. Pulizia: cancella i task del client
        # ------------------------------------------------------------------
        stt_task.cancel()
        inference_task.cancel()
        tts_task.cancel()
        await asyncio.gather(stt_task, inference_task, tts_task, return_exceptions=True)
        print(f"[SERVER] Risorse liberate per {client_ip}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    print("[SERVER] Avvio VELA WebSocket server su 0.0.0.0:8765...")
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        await asyncio.Future()   # Mantiene il server attivo


if __name__ == "__main__":
    asyncio.run(main())