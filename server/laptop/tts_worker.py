#"""
#tts_worker.py  –  VELA Text-to-Speech worker (processo Piper persistente)
#
#Nessuna modifica architetturale rispetto alla versione precedente.
#
#Il worker sintetizza qualsiasi stringa presente in tts_queue tramite un
#singolo processo Piper mantenuto vivo per tutta la sessione.
#
#Le frasi hardcoded emesse dai flussi hardware di main.py
#(es. "Salvato.", "Errore durante il salvataggio.") vengono gestite
#esattamente come le frasi generate dal VLM: vengono messe in tts_queue
#da main.py e il worker le processa senza logica speciale.
#
#Ottimizzazioni:
#  - Un solo processo Piper avviato per sessione → elimina overhead ~300-500 ms
#    di startup per ogni frase
#  - Rilevamento fine sintesi tramite timeout su stdout (SENTENCE_TIMEOUT)
#  - Riavvio automatico in caso di crash del processo
#"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
PIPER_EXE   = "/home/leo/vela/server/venv/bin/piper"
PIPER_MODEL = "/home/leo/vela/server/it_IT-paola-medium.onnx"

CHUNK_SIZE       = 4096   # ~93 ms di audio a 22 050 Hz, 16-bit mono
SENTENCE_TIMEOUT = 0.20   # secondi senza dati su stdout → Piper ha finito la frase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _avvia_piper() -> asyncio.subprocess.Process:
    """Avvia il processo Piper in modalità raw output e lo mantiene aperto."""
    process = await asyncio.create_subprocess_exec(
        PIPER_EXE,
        "--model", PIPER_MODEL,
        "--output_raw",
        stdin  = asyncio.subprocess.PIPE,
        stdout = asyncio.subprocess.PIPE,
        stderr = asyncio.subprocess.PIPE,
    )
    print("[TTS] Processo Piper avviato (persistente).")
    return process


async def _stream_frase(
    process : asyncio.subprocess.Process,
    text    : str,
) -> AsyncIterator[bytes]:
    """
    Invia una frase a Piper (via stdin) e restituisce i chunk audio PCM
    man mano che vengono generati su stdout.

    SENTENCE_TIMEOUT secondi senza nuovi dati segnalano che Piper ha terminato
    la sintesi della frase corrente.
    """
    process.stdin.write((text + "\n").encode("utf-8"))
    await process.stdin.drain()

    while True:
        try:
            chunk = await asyncio.wait_for(
                process.stdout.read(CHUNK_SIZE),
                timeout = SENTENCE_TIMEOUT,
            )
            if not chunk:   # EOF inaspettato: processo terminato
                return
            yield chunk
        except asyncio.TimeoutError:
            return          # fine sintesi per questa frase


def _pulisci_testo(text: str) -> str:
    """Rimuove simboli Markdown che Piper potrebbe pronunciare letteralmente."""
    return (
        text.replace("**", "")
            .replace("*",  "")
            .replace("#",  "")
            .replace("- ", "")
            .strip()
    )


# ---------------------------------------------------------------------------
# Worker asincrono principale
# ---------------------------------------------------------------------------
async def tts_worker(tts_queue: asyncio.Queue, websocket) -> None:
    """
    Legge frasi da tts_queue, le sintetizza con Piper e invia i chunk audio
    PCM base64 al client WebSocket come {"type": "tts_chunk", "data": "..."}.

    Gestisce trasparentemente:
      - Frasi generate dal VLM (inference_worker)
      - Frasi hardcoded dai flussi hardware (main.py: "Salvato.", errori, ecc.)
    """
    process = await _avvia_piper()

    try:
        while True:
            try:
                text  = await tts_queue.get()
                clean = _pulisci_testo(text)

                if not clean or len(clean) < 2:
                    continue

                print(f"[TTS] Sintesi: '{clean}'")

                # Riavvia Piper se il processo è crashato tra un turno e l'altro
                if process.returncode is not None:
                    print("[TTS] Processo Piper terminato inaspettatamente — riavvio...")
                    process = await _avvia_piper()

                bytes_inviati = 0
                async for audio_chunk in _stream_frase(process, clean):
                    payload = {
                        "type" : "tts_chunk",
                        "data" : base64.b64encode(audio_chunk).decode("utf-8"),
                    }
                    await websocket.send(json.dumps(payload))
                    bytes_inviati += len(audio_chunk)

                print(f"[TTS] ✔ Frase inviata — {bytes_inviati} byte PCM.")

            except asyncio.CancelledError:
                raise   # propaga per uscire dal loop esterno
            except Exception as e:
                print(f"[TTS] Errore: {e}")
                # Se il crash ha ucciso Piper, riavvialo prima del prossimo turno
                if process.returncode is not None:
                    process = await _avvia_piper()

    except asyncio.CancelledError:
        print("[TTS] Worker cancellato.")
    finally:
        # Chiusura pulita del processo Piper
        if process.returncode is None:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                process.kill()
            print("[TTS] Processo Piper chiuso correttamente.")