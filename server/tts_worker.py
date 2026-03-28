#"""
#tts_worker.py  –  VELA Text-to-Speech worker (processo Piper persistente)
#
#Ottimizzazioni rispetto alla versione originale:
#  - Un singolo processo Piper viene avviato UNA SOLA VOLTA e riutilizzato per
#    tutta la durata della sessione.  L'invio di nuove frasi avviene semplicemente
#    scrivendo su stdin (già aperto), eliminando l'overhead di avvio processo
#    (~300-500 ms) per ogni frase generata.
#  - Rilevamento della fine della sintesi tramite timeout su stdout (200 ms senza
#    dati = Piper ha terminato la frase corrente).
#  - Riavvio automatico di Piper in caso di crash.
#"""

import asyncio
import base64
import json
from typing import AsyncIterator

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
PIPER_EXE   = "/home/leo/vela/server/venv/bin/piper"
PIPER_MODEL = "/home/leo/vela/server/it_IT-paola-medium.onnx"

CHUNK_SIZE       = 4096   # ~93 ms di audio a 22 050 Hz, 16-bit mono
SENTENCE_TIMEOUT = 0.20   # secondi: pausa su stdout che indica "frase terminata"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _avvia_piper() -> asyncio.subprocess.Process:
    """Avvia un processo Piper che rimane aperto in background."""
    process = await asyncio.create_subprocess_exec(
        PIPER_EXE,
        "--model", PIPER_MODEL,
        "--output_raw",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    print("[TTS] Processo Piper avviato (persistente).")
    return process


async def _stream_frase(
    process: asyncio.subprocess.Process,
    text: str,
) -> AsyncIterator[bytes]:
    """
    Invia una riga di testo a Piper e restituisce i chunk audio man mano
    che vengono generati.  SENTENCE_TIMEOUT di silenzio su stdout segnala
    la fine della sintesi per quella frase.
    """
    process.stdin.write((text + "\n").encode("utf-8"))
    await process.stdin.drain()

    while True:
        try:
            chunk = await asyncio.wait_for(
                process.stdout.read(CHUNK_SIZE),
                timeout=SENTENCE_TIMEOUT,
            )
            if not chunk:   # processo terminato inaspettatamente
                return
            yield chunk
        except asyncio.TimeoutError:
            return          # Piper ha finito questa frase


def _pulisci_testo(text: str) -> str:
    return (
        text.replace("**", "")
            .replace("*", "")
            .replace("#", "")
            .replace("- ", "")
            .strip()
    )


# ---------------------------------------------------------------------------
# Worker asincrono principale
# ---------------------------------------------------------------------------
async def tts_worker(tts_queue: asyncio.Queue, websocket) -> None:
    process = await _avvia_piper()

    try:
        while True:
            try:
                text = await tts_queue.get()
                clean = _pulisci_testo(text)

                if not clean or len(clean) < 2:
                    continue

                print(f"[TTS] Sintesi: '{clean}'")

                # Riavvia Piper se il processo è crashato
                if process.returncode is not None:
                    print("[TTS] Processo Piper terminato — riavvio...")
                    process = await _avvia_piper()

                bytes_inviati = 0
                async for audio_chunk in _stream_frase(process, clean):
                    payload = {
                        "type": "tts_chunk",
                        "data": base64.b64encode(audio_chunk).decode("utf-8"),
                    }
                    await websocket.send(json.dumps(payload))
                    bytes_inviati += len(audio_chunk)

                print(f"[TTS] ✔ Frase inviata — {bytes_inviati} byte PCM.")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[TTS] Errore: {e}")
                # Se il processo è morto, riavvialo prima del prossimo turno
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
            print("[TTS] Processo Piper chiuso.")