#"""
#stt_worker.py  –  VELA Speech-to-Text worker (VAD edition)
#
#Ottimizzazioni rispetto alla versione originale:
#  - Rilevamento fine-frase tramite VAD (webrtcvad) anziché buffer fisso da 4 s
#    → la trascrizione parte ~500 ms dopo l'ultimo sillabo, non dopo un ritardo fisso
#  - Modello "base" + beam_size=1 al posto di "small" + beam_size=2
#    → ~2× più veloce sulla CPU con qualità quasi identica per frasi brevi
#  - Elaborazione frame-by-frame: non accumula più dati del necessario
#"""

import asyncio
import collections
import base64
import json

import numpy as np
import webrtcvad
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Caricamento modello (una sola volta, condiviso da tutti i client)
# ---------------------------------------------------------------------------
print("[STT] Caricamento modello Whisper 'base' in corso...")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("[STT] Modello Whisper caricato!")

# ---------------------------------------------------------------------------
# Costanti audio
# ---------------------------------------------------------------------------
SAMPLE_RATE      = 16_000          # Hz  (atteso dal client Android)
FRAME_MS         = 30              # ms  (unici valori validi per webrtcvad: 10, 20, 30)
FRAME_SAMPLES    = SAMPLE_RATE * FRAME_MS // 1000   # 480 campioni
FRAME_BYTES      = FRAME_SAMPLES * 2                # 960 byte (PCM 16-bit mono)

# ---------------------------------------------------------------------------
# Parametri VAD
# ---------------------------------------------------------------------------
VAD_AGGRESSIVENESS  = 2   # 0 = permissivo  …  3 = aggressivo
# Quanti frame del ring-buffer devono essere "voce" per AVVIARE la registrazione
VOICED_RATIO_START  = 0.75
# Quanti frame del ring-buffer devono essere "silenzio" per TERMINARE la registrazione
SILENCE_RATIO_END   = 0.85
# Durata del ring-buffer: 20 × 30 ms = 600 ms di silenzio per fermarsi
PADDING_FRAMES      = 20
# Audio minimo da trascrivere per evitare falsi positivi
MIN_SPEECH_FRAMES   = 15  # 15 × 30 ms = 450 ms


# ---------------------------------------------------------------------------
# Trascrizione sincrona (viene lanciata in un thread separato)
# ---------------------------------------------------------------------------
def _trascrivi(audio_np: np.ndarray) -> str:
    segments, _ = model.transcribe(
        audio_np,
        beam_size=1,           # Più veloce; per frasi brevi la qualità è invariata
        language="it",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )
    return " ".join(seg.text for seg in segments).strip()


# ---------------------------------------------------------------------------
# Worker asincrono principale
# ---------------------------------------------------------------------------
async def stt_worker(audio_queue: asyncio.Queue, text_queue: asyncio.Queue) -> None:
    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    ring_buffer: collections.deque = collections.deque(maxlen=PADDING_FRAMES)
    voiced_frames: list[bytes] = []
    raw_buffer    = bytearray()
    triggered     = False

    while True:
        try:
            # ------------------------------------------------------------------
            # 1. Leggi il prossimo messaggio dalla coda
            # ------------------------------------------------------------------
            raw_message = await audio_queue.get()

            try:
                payload = json.loads(raw_message)
                if payload.get("type") != "audio_chunk":
                    continue                          # scarta auth, ecc.
                chunk_bytes = base64.b64decode(payload["data"])
                raw_buffer.extend(chunk_bytes)
            except Exception:
                continue                              # pacchetto corrotto

            # ------------------------------------------------------------------
            # 2. Processa tutti i frame completi disponibili nel buffer
            # ------------------------------------------------------------------
            while len(raw_buffer) >= FRAME_BYTES:
                frame = bytes(raw_buffer[:FRAME_BYTES])
                del raw_buffer[:FRAME_BYTES]

                try:
                    is_speech = vad.is_speech(frame, SAMPLE_RATE)
                except Exception:
                    continue

                if not triggered:
                    # ── Stato: in attesa di parlato ──────────────────────────
                    ring_buffer.append((frame, is_speech))
                    voiced_ratio = sum(1 for _, s in ring_buffer if s) / len(ring_buffer)

                    if voiced_ratio >= VOICED_RATIO_START:
                        triggered = True
                        voiced_frames.extend(f for f, _ in ring_buffer)
                        ring_buffer.clear()
                        print("[STT] ▶ Parlato rilevato — registrazione avviata.")

                else:
                    # ── Stato: registrazione in corso ─────────────────────────
                    voiced_frames.append(frame)
                    ring_buffer.append((frame, is_speech))
                    silence_ratio = sum(1 for _, s in ring_buffer if not s) / len(ring_buffer)

                    if silence_ratio >= SILENCE_RATIO_END:
                        # ── Fine del parlato ──────────────────────────────────
                        print(f"[STT] ■ Fine parlato — {len(voiced_frames)} frame acquisiti. Trascrizione...")
                        triggered = False

                        if len(voiced_frames) >= MIN_SPEECH_FRAMES:
                            audio_bytes = b"".join(voiced_frames)
                            audio_np = (
                                np.frombuffer(audio_bytes, dtype=np.int16)
                                .astype(np.float32) / 32768.0
                            )

                            # Trascrizione in thread dedicato (non blocca il loop asyncio)
                            testo = await asyncio.to_thread(_trascrivi, audio_np)

                            if testo:
                                testo_pulito = testo.strip().lower().lstrip(" .,?!-")

                                if testo_pulito.startswith("vela"):
                                    query = testo_pulito[4:].strip(" .,?!-")
                                    if query:
                                        print(f"[STT] ✔ Wake word! Query: '{query}'")
                                        await text_queue.put(query)
                                    else:
                                        print("[STT] Wake word senza domanda successiva.")
                                else:
                                    print(f"[STT] Ignorato (no wake word): '{testo}'")
                            else:
                                print("[STT] Nessun testo trascritto.")
                        else:
                            print("[STT] Audio troppo breve — scartato.")

                        voiced_frames.clear()
                        ring_buffer.clear()

        except asyncio.CancelledError:
            print("[STT] Worker cancellato.")
            break
        except Exception as e:
            print(f"[STT] Errore critico: {e}")