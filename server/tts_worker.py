import asyncio
import subprocess
import tempfile
import os

async def tts_worker(tts_queue, websocket):
    # Sostituisci con il percorso reale del tuo modello Piper
    PIPER_MODEL = "./it_IT-riccardo-x_low.onnx" 
    
    while True:
        try:
            # Prende la frase dallo stream dell'LLM
            frase = await tts_queue.get()
            print(f"[TTS] Generazione audio per: '{frase}'")

            # Creiamo un file temporaneo per salvare l'output audio
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
                temp_audio_path = tmp_audio.name

            # Eseguiamo piper tramite riga di comando (molto efficiente)
            # echo "frase" | piper --model modello.onnx --output_file output.wav
            process = await asyncio.create_subprocess_shell(
                f'echo "{frase}" | piper --model {PIPER_MODEL} --output_file {temp_audio_path}',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()

            # Leggiamo il file WAV e lo inviamo al client tramite WebSocket
            with open(temp_audio_path, "rb") as f:
                audio_data = f.read()
                await websocket.send(audio_data)
                print(f"[TTS] Inviati {len(audio_data)} bytes di audio al client.")

            # Pulizia file temporaneo
            os.remove(temp_audio_path)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[TTS] Errore: {e}")
