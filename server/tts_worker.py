import asyncio
import os

# --- CONFIGURAZIONE ---
PIPER_EXE = "/home/leo/vela/server/venv/bin/piper" 
PIPER_MODEL = "./it_IT-paola-medium.onnx" # Voce femminile
OUTPUT_WAV = "output_tts.wav"

async def tts_worker(tts_queue, websocket):
    while True:
        text = await tts_queue.get()
        
        # Pulizia testo per una lettura fluida
        clean_text = text.replace("**", "").replace("*", "").replace("#", "").replace("- ", "").strip()
        
        if not clean_text or len(clean_text) < 2:
            continue
            
        print(f"[TTS] Generazione audio per: '{clean_text}'")
        
        try:
            # Rimuoviamo il vecchio file se esiste
            if os.path.exists(OUTPUT_WAV):
                os.remove(OUTPUT_WAV)

            command = [
                PIPER_EXE,
                "--model", PIPER_MODEL,
                "--output_file", OUTPUT_WAV
            ]

            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate(input=clean_text.encode('utf-8'))

            if process.returncode != 0:
                print(f"[TTS] ERRORE PIPER: {stderr.decode()}")
                continue

            if os.path.exists(OUTPUT_WAV) and os.path.getsize(OUTPUT_WAV) > 0:
                with open(OUTPUT_WAV, "rb") as f:
                    audio_data = f.read()
                
                await websocket.send(audio_data)
                print(f"[TTS] Inviati {len(audio_data)} bytes a Paola.")
            else:
                print(f"[TTS] Errore: Il file audio è vuoto.")

        except Exception as e:
            print(f"[TTS] Errore critico: {e}")