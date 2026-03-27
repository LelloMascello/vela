import asyncio
import websockets
# Importa i worker che svilupperemo
# from workers import stt_worker, inference_worker, tts_worker
from stt_worker import stt_worker
from tts_worker import tts_worker
from inference_worker import inference_worker

async def handle_client(websocket):
    """
    Questa funzione viene chiamata AUTOMATICAMENTE ogni volta che 
    un nuovo client (ESP32 o Android) si connette al Raspberry Pi.
    """
    client_ip = websocket.remote_address[0]
    print(f"[SERVER] Nuovo client connesso da {client_ip}")

    # 1. Creiamo code INDIPENDENTI per questo specifico utente
    audio_queue = asyncio.Queue()
    text_queue = asyncio.Queue()
    tts_queue = asyncio.Queue()

    # 2. Avviamo i worker dedicati a questa sessione in background
    # (Usiamo create_task per non bloccare la ricezione dei messaggi)
    stt_task = asyncio.create_task(stt_worker(audio_queue, text_queue))
    inference_task = asyncio.create_task(inference_worker(text_queue, tts_queue))
    tts_task = asyncio.create_task(tts_worker(tts_queue, websocket))
    try:
        # 3. Loop di ricezione: ascoltiamo l'audio in arrivo dal WebSocket
        async for message in websocket:
            # message conterrà i chunk audio inviati dall'ESP32
            await audio_queue.put(message)
            
    except websockets.exceptions.ConnectionClosed:
        print(f"[SERVER] Client {client_ip} disconnesso.")
    finally:
        # 4. Pulizia: se il client cade o si disconnette, fermiamo i suoi worker
        stt_task.cancel()
        inference_task.cancel()
        tts_task.cancel()
        print(f"[SERVER] Risorse liberate per {client_ip}")

async def main():
    # Avviamo il server WebSocket sulla porta 8765
    print("[SERVER] Avvio del server WebSocket in ascolto su 0.0.0.0:8765...")
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        # Mantiene il server in esecuzione all'infinito
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
