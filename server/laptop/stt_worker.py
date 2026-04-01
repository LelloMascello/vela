#"""
#stt_worker.py  –  VELA Speech-to-Text worker (sherpa-onnx streaming edition)
#
#Sostituisce faster-whisper + webrtcvad con sherpa-onnx OnlineRecognizer,
#che fornisce riconoscimento vocale in streaming con rilevamento automatico
#della fine dell'utterance (endpoint detection integrato).
#
#Setup modello:
#  Scaricare un modello transducer che supporti l'italiano da:
#  https://github.com/k2-fsa/sherpa-onnx/releases
#
#  Opzione consigliata per l'italiano:
#    sherpa-onnx-streaming-zipformer-multilingual-zh-en-2023-11-22
#    (supporta più lingue europee; per l'italiano puro valutare un modello
#    Vosk-IT convertito in formato sherpa-onnx)
#
#  Installazione:
#    pip install sherpa-onnx
#
#Logica intenti:
#  - "vela foto"  (sole due parole) → photo intent  (bypassa il VLM)
#  - "vela salva" (sole due parole) → save intent   (bypassa il VLM, solo in finestra attiva)
#  - qualsiasi altra frase con "vela" → query al VLM (senza la parola "vela")
#  - frase senza "vela" → ignorata
#"""

import asyncio
import base64
import json

import numpy as np
import sherpa_onnx

# ---------------------------------------------------------------------------
# Percorsi modello – CONFIGURARE prima dell'avvio
# ---------------------------------------------------------------------------
SHERPA_ENCODER = "/home/leo/vela/server/sherpa-models/encoder.onnx"
SHERPA_DECODER = "/home/leo/vela/server/sherpa-models/decoder.onnx"
SHERPA_JOINER  = "/home/leo/vela/server/sherpa-models/joiner.onnx"
SHERPA_TOKENS  = "/home/leo/vela/server/sherpa-models/tokens.txt"

SAMPLE_RATE = 16_000   # Hz – deve corrispondere al formato inviato dal client

# ---------------------------------------------------------------------------
# Parametri endpoint detection (tuning per l'italiano parlato)
# ---------------------------------------------------------------------------
RULE1_SILENCE = 2.4   # secondi di silenzio dopo frase lunga  → endpoint
RULE2_SILENCE = 1.2   # secondi di silenzio dopo frase breve  → endpoint
RULE3_MIN_LEN = 20    # frame minimi per accettare un'utterance

# ---------------------------------------------------------------------------
# Inizializzazione riconoscitore (una sola volta per processo;
# ogni client crea il proprio stream via _recognizer.create_stream())
# ---------------------------------------------------------------------------
print("[STT] Inizializzazione OnlineRecognizer sherpa-onnx...")
_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
    encoder  = SHERPA_ENCODER,
    decoder  = SHERPA_DECODER,
    joiner   = SHERPA_JOINER,
    tokens   = SHERPA_TOKENS,
    num_threads                = 4,
    sample_rate                = SAMPLE_RATE,
    feature_dim                = 80,
    decoding_method            = "greedy_search",
    enable_endpoint_detection  = True,
    rule1_min_trailing_silence = RULE1_SILENCE,
    rule2_min_trailing_silence = RULE2_SILENCE,
    rule3_min_utterance_length = RULE3_MIN_LEN,
    provider                   = "cpu",
)
print("[STT] Riconoscitore pronto.")


# ---------------------------------------------------------------------------
# Classificazione intento
# ---------------------------------------------------------------------------
def _classify_intent(text: str, window_active: bool) -> dict | None:
    """
    Classifica il testo trascritto in uno dei tre intenti riconosciuti:

      "photo"  – utterance contiene ESATTAMENTE le parole "vela" + "foto"/"photo"
                 (nessun'altra parola); bypassa il VLM.

      "save"   – utterance contiene ESATTAMENTE le parole "vela" + "salva"/"save"
                 (nessun'altra parola) E la finestra 8s è attiva; bypassa il VLM.

      "query"  – qualsiasi altra utterance che contiene "vela" in qualunque
                 posizione; la parola "vela" viene rimossa prima di passare
                 la query al VLM.

      None     – utterance senza wake word "vela" → scartata.
    """
    # Pulizia e tokenizzazione
    words    = [w.strip(".,!?;:-") for w in text.lower().strip().split()]
    words    = [w for w in words if w]          # rimuove token vuoti
    word_set = set(words)

    if "vela" not in word_set:
        return None   # nessuna wake word

    # ── Hardware flows: SOLO esattamente due parole ───────────────────────────
    if len(words) == 2:
        if word_set in ({"vela", "foto"}, {"vela", "photo"}):
            return {"type": "photo"}

        if word_set in ({"vela", "salva"}, {"vela", "save"}):
            if window_active:
                return {"type": "save"}
            # Finestra non attiva: ignora silenziosamente
            print("[STT] Ignorato 'vela salva': finestra 8s non attiva.")
            return None

    # ── Query generica: rimuove "vela" e invia il testo rimanente ─────────────
    query_words = [w for w in words if w != "vela"]
    query = " ".join(query_words).strip()
    if query:
        return {"type": "query", "text": query}

    # "vela" da sola, senza payload
    return None


# ---------------------------------------------------------------------------
# Worker asincrono principale
# ---------------------------------------------------------------------------
async def stt_worker(
    audio_queue     : asyncio.Queue,
    stt_event_queue : asyncio.Queue,
    window_state    : dict,          # {"active": bool} – condiviso con main.py
) -> None:
    """
    Riceve chunk audio PCM16 dalla coda, li alimenta allo streaming
    recognizer sherpa-onnx e, a ogni endpoint detection, classifica
    il testo trascritto in un intento che viene emesso su stt_event_queue.
    """
    stream = _recognizer.create_stream()

    while True:
        try:
            # 1. Leggi il prossimo messaggio audio dalla coda
            raw_message = await audio_queue.get()

            try:
                payload = json.loads(raw_message)
                if payload.get("type") != "audio_chunk":
                    continue
                chunk_bytes = base64.b64decode(payload["data"])
            except Exception:
                continue   # pacchetto malformato: scarta silenziosamente

            # 2. Converti PCM16-LE → float32 normalizzato [-1, 1]
            audio_np = (
                np.frombuffer(chunk_bytes, dtype=np.int16)
                  .astype(np.float32) / 32768.0
            )
            #print(f"[DEBUG] Volume: {np.max(np.abs(audio_np)):.4f}")
            # 3. Alimenta il riconoscitore con i nuovi campioni
            stream.accept_waveform(SAMPLE_RATE, audio_np)

            # 4. Decodifica tutti i frame disponibili
            while _recognizer.is_ready(stream):
                _recognizer.decode_stream(stream)

            # 5. Controlla se l'utterance è terminata (endpoint detection)
            if _recognizer.is_endpoint(stream):
                result_text = _recognizer.get_result(stream).strip()
                _recognizer.reset(stream)   # prepara lo stream per l'utterance successiva

                if not result_text:
                    print("[STT] Utterance vuota — scartata.")
                    continue

                print(f"[STT] Trascritto: '{result_text}'")

                intent = _classify_intent(result_text, window_state["active"])
                if intent:
                    print(f"[STT] Intent classificato → {intent}")
                    await stt_event_queue.put(intent)
                else:
                    print("[STT] Ignorato (no wake word o pattern non riconosciuto).")

        except asyncio.CancelledError:
            print("[STT] Worker cancellato.")
            break
        except Exception as e:
            print(f"[STT] Errore critico: {e}")