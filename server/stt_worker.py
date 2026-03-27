import asyncio
import io
from faster_whisper import WhisperModel

# Carichiamo il modello in memoria (tiny è perfetto e velocissimo sul Pi 5)
print("[STT] Caricamento modello Whisper in corso...")
model = WhisperModel("large-v3", device="cpu", compute_type="int8")
print("[STT] Modello Whisper caricato!")

async def stt_worker(audio_queue, text_queue):
    while True:
        try:
            # Aspettiamo i dati audio grezzi dal WebSocket
            audio_bytes = await audio_queue.get()
            print(f"[STT] Ricevuti {len(audio_bytes)} bytes di audio. Trascrizione...")

            # Faster-whisper può leggere direttamente da un buffer in memoria
            # Assumiamo che il client invii un file audio valido (es. webm o wav)
            audio_file = io.BytesIO(audio_bytes)
            
            # Eseguiamo la trascrizione
            segments, info = model.transcribe(audio_file, beam_size=5, language="it")
            
            testo_completo = ""
            for segment in segments:
                testo_completo += segment.text + " "
            
            testo_completo = testo_completo.strip()
            
            if testo_completo:
                print(f"[STT] Utente ha detto: {testo_completo}")
                # Passiamo il testo all'Inference Worker
                await text_queue.put(testo_completo)
            else:
                print("[STT] Nessun testo rilevato.")

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[STT] Errore: {e}")
