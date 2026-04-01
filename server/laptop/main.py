#"""
#main.py  –  VELA WebSocket Server (state machine edition)
#
#Architettura a code e worker con state machine per la finestra 8s:
#
#  Client Android ──WebSocket──► main.py ─┬─► stt_worker       ──► stt_event_queue
#                                          │                              │
#                                          └─► [loop ricezione]           ▼
#                                                                  _event_router
#                                                                       │
#                                                          ┌────────────┼────────────┐
#                                                          ▼            ▼            ▼
#                                                     photo flow   save flow   inference_queue
#                                                          │            │            │
#                                                          ▼            ▼            ▼
#                                                    controllo     Pi5 API    inference_worker
#                                                    client         + TTS          │
#                                                                              tts_queue
#                                                                                  │
#                                                                             tts_worker
#                                                                                  │
#                                                                            Client (audio)
#
#Finestra 8s:
#  Si apre al termine di ogni risposta del VLM.
#  Durante la finestra:
#    • Il contesto conversazione viene mantenuto per il turno successivo.
#    • L'utente può dire "vela salva" per salvare lo scambio sul Pi 5.
#    • Il client riceve {"type": "control", "cmd": "save_window_open"}.
#  Alla scadenza:
#    • Il prossimo turno di inferenza riceverà reset=True → storico azzerato.
#    • Il client NON riceve notifica esplicita (il timeout è silenzioso).
#"""

import asyncio
import hashlib
import json

import httpx
import websockets

from stt_worker       import stt_worker
from tts_worker       import tts_worker
from inference_worker import inference_worker

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
USERS_DB: dict[str, str] = {
    "alice": hashlib.sha256(b"tua_password_segreta").hexdigest(),
    # Aggiungi altri utenti:
    # "bob": hashlib.sha256(b"password_di_bob").hexdigest(),
}
REQUIRE_AUTH = True   # False per disabilitare l'autenticazione in sviluppo

# IP e endpoint del Raspberry Pi 5 per il salvataggio degli scambi
PI5_IP      = "192.168.1.X"                    # ← inserire IP reale del Pi 5
PI5_API_URL = f"http://{PI5_IP}:8000/api/saves"

WINDOW_SECONDS = 8.0   # durata finestra 8s (salvataggio + contesto)


# ---------------------------------------------------------------------------
# Gestore di ogni connessione client
# ---------------------------------------------------------------------------
async def handle_client(websocket) -> None:
    client_ip = websocket.remote_address[0]
    print(f"[SERVER] Nuovo client connesso da {client_ip}")

    # ── Autenticazione ────────────────────────────────────────────────────────
    if REQUIRE_AUTH:
        authenticated = False
        try:
            raw_auth  = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            auth_msg  = json.loads(raw_auth)
            if auth_msg.get("type") == "auth":
                username      = auth_msg.get("username", "")
                password_hash = auth_msg.get("password_hash", "")
                expected_hash = USERS_DB.get(username)
                if expected_hash and password_hash == expected_hash:
                    authenticated = True
                    print(f"[SERVER] Auth OK per '{username}'")
                    await websocket.send(json.dumps({"type": "auth_result", "status": "ok"}))
                else:
                    print(f"[SERVER] Auth fallita per '{username}'")
                    await websocket.send(json.dumps({"type": "auth_result", "status": "failed"}))
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
            print(f"[SERVER] Errore auth: {e}")

        if not authenticated:
            await websocket.close(1008, "Autenticazione fallita")
            return
    else:
        print("[SERVER] Auth disabilitata — connessione accettata.")

    # ── Code di comunicazione ─────────────────────────────────────────────────
    audio_queue     = asyncio.Queue()   # chunk PCM → stt_worker
    stt_event_queue = asyncio.Queue()   # intent classificati → _event_router
    inference_queue = asyncio.Queue()   # query VLM → inference_worker
    tts_queue       = asyncio.Queue()   # frasi → tts_worker

    # ── Stato condiviso tra coroutine ─────────────────────────────────────────
    # window_state è un dict mutabile condiviso con stt_worker per riferimento.
    window_state  = {"active": False}
    last_exchange = {"query": None, "response": None}   # condiviso con inference_worker
    pending_image = {"data": None}                       # ultima foto ricevuta dal client

    # Holder mutabile per il task della finestra (lista di un elemento = puntatore)
    _window_task: list[asyncio.Task | None] = [None]

    # ── Gestione finestra 8s ──────────────────────────────────────────────────
    def _cancel_window() -> None:
        """Cancella il countdown attivo senza effetti collaterali."""
        if _window_task[0] and not _window_task[0].done():
            _window_task[0].cancel()
        _window_task[0] = None

    async def _window_countdown() -> None:
        """
        Task che gira per WINDOW_SECONDS poi chiude silenziosamente la finestra.
        Il prossimo turno di inferenza riceverà reset=True.
        """
        try:
            await asyncio.sleep(WINDOW_SECONDS)
            window_state["active"] = False
            _window_task[0] = None
            print("[SERVER] Finestra 8s scaduta — contesto resettato al prossimo turno.")
        except asyncio.CancelledError:
            pass   # finestra riaperta prima dello scadere (normale)

    async def _open_window() -> None:
        """
        Apre (o re-inizia) la finestra 8s e notifica il client.
        Chiamata da inference_worker via callback on_response_done().
        """
        _cancel_window()
        window_state["active"] = True
        _window_task[0] = asyncio.create_task(_window_countdown())
        print(f"[SERVER] Finestra 8s aperta ({WINDOW_SECONDS:.0f}s).")
        try:
            await websocket.send(json.dumps({"type": "control", "cmd": "save_window_open"}))
        except Exception:
            pass   # client già disconnesso: ignora

    # ── Handler flusso foto ───────────────────────────────────────────────────
    async def _handle_photo_intent() -> None:
        """
        Invia al client il comando photo_mode.
        Il client scatterà una foto e la invierà come {"type": "image", "data": "<b64>"}.
        """
        print("[SERVER] Intent FOTO → invio photo_mode al client.")
        try:
            await websocket.send(json.dumps({"type": "control", "cmd": "photo_mode"}))
        except Exception as e:
            print(f"[SERVER] Errore invio photo_mode: {e}")

    # ── Handler flusso salvataggio ────────────────────────────────────────────
    async def _handle_save_intent() -> None:
        """
        Salva l'ultimo scambio (query + risposta) sul Pi 5 via HTTP POST,
        conferma via TTS e notifica il client.
        """
        if not window_state["active"]:
            # Questo caso non dovrebbe accadere (stt_worker lo filtra), ma per sicurezza:
            await tts_queue.put("Non c'è nulla da salvare in questo momento.")
            return

        payload = {
            "query":    last_exchange.get("query"),
            "response": last_exchange.get("response"),
        }
        print(f"[SERVER] Salvataggio su Pi5: {payload}")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.post(PI5_API_URL, json=payload)
                r.raise_for_status()

            print("[SERVER] Scambio salvato con successo.")
            await tts_queue.put("Salvato.")

            try:
                await websocket.send(json.dumps({"type": "control", "cmd": "save_confirmed"}))
            except Exception:
                pass

        except httpx.ConnectError:
            print(f"[SERVER] Pi5 ({PI5_IP}) non raggiungibile.")
            await tts_queue.put("Errore: non riesco a raggiungere il Pi cinque.")
        except httpx.HTTPStatusError as e:
            print(f"[SERVER] Pi5 risposta HTTP {e.response.status_code}.")
            await tts_queue.put("Errore durante il salvataggio.")
        except Exception as e:
            print(f"[SERVER] Errore salvataggio: {e}")
            await tts_queue.put("Errore durante il salvataggio.")

    # ── Router intenti STT ────────────────────────────────────────────────────
    async def _event_router() -> None:
        """
        Legge gli intenti classificati da stt_worker e li smista:
          "photo" → flusso foto
          "save"  → flusso salvataggio
          "query" → inferenza VLM (con eventuale immagine in attesa)
        """
        while True:
            try:
                event = await stt_event_queue.get()
                etype = event.get("type")

                # ── Flusso foto ───────────────────────────────────────────────
                if etype == "photo":
                    await _handle_photo_intent()

                # ── Flusso salvataggio ────────────────────────────────────────
                elif etype == "save":
                    await _handle_save_intent()

                # ── Flusso inferenza VLM ──────────────────────────────────────
                elif etype == "query":
                    text  = event.get("text", "")
                    reset = not window_state["active"]   # reset se finestra scaduta

                    # Consuma l'immagine pendente (se il client ne ha inviata una)
                    image = pending_image["data"]
                    pending_image["data"] = None

                    print(
                        f"[SERVER] → inference: '{text}' "
                        f"| reset={reset}"
                        + (" [con immagine]" if image else "")
                    )

                    await inference_queue.put({
                        "text":  text,
                        "image": image,
                        "reset": reset,
                    })

                else:
                    print(f"[SERVER] Intent sconosciuto: '{etype}'")

            except asyncio.CancelledError:
                print("[SERVER] Event router cancellato.")
                break
            except Exception as e:
                print(f"[SERVER] Errore event router: {e}")

    # ── Avvio worker ──────────────────────────────────────────────────────────
    stt_task       = asyncio.create_task(
        stt_worker(audio_queue, stt_event_queue, window_state)
    )
    inference_task = asyncio.create_task(
        inference_worker(inference_queue, tts_queue, last_exchange, _open_window)
    )
    tts_task       = asyncio.create_task(tts_worker(tts_queue, websocket))
    router_task    = asyncio.create_task(_event_router())

    try:
        # ── Loop ricezione messaggi dal client ────────────────────────────────
        async for message in websocket:
            try:
                payload  = json.loads(message)
                msg_type = payload.get("type")

                # Chunk audio dal microfono → stt_worker
                if msg_type == "audio_chunk":
                    await audio_queue.put(message)

                # Foto scattata dal client in risposta a "photo_mode"
                elif msg_type == "image":
                    image_b64 = payload.get("data")
                    if image_b64:
                        pending_image["data"] = image_b64
                        print("[SERVER] Immagine ricevuta — in attesa di query vocale.")
                        # Apri la finestra: l'utente può fare subito una domanda
                        # sull'immagine o dire "vela salva" per salvarla
                        await _open_window()
                    else:
                        print("[SERVER] Messaggio 'image' senza dati — ignorato.")

                else:
                    print(f"[SERVER] Messaggio non gestito: type='{msg_type}'")

            except (json.JSONDecodeError, Exception) as e:
                print(f"[SERVER] Pacchetto non valido da {client_ip}: {e}")

    except websockets.exceptions.ConnectionClosed:
        print(f"[SERVER] Client {client_ip} disconnesso.")
    finally:
        # ── Pulizia: cancella tutti i task del client ─────────────────────────
        _cancel_window()
        for task in [stt_task, inference_task, tts_task, router_task]:
            task.cancel()
        await asyncio.gather(
            stt_task, inference_task, tts_task, router_task,
            return_exceptions=True,
        )
        print(f"[SERVER] Risorse liberate per {client_ip}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    print("[SERVER] Avvio VELA WebSocket server su 0.0.0.0:8765...")
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        await asyncio.Future()   # mantiene il server attivo indefinitamente


if __name__ == "__main__":
    asyncio.run(main())