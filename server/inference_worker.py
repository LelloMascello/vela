import asyncio
import json
import httpx
import wakeonlan

async def ask_laptop(messages, laptop_ip, laptop_mac=None):
    """
    Invia la richiesta al VLM (llama-server) e restituisce le frasi in streaming.
    Invia il Wake-on-LAN e imposta il timeout lungo SOLO se viene fornito il MAC address.
    """
    url = f"http://{laptop_ip}:8080/v1/chat/completions"
    
    # Di default non mettiamo nessun timeout
    timeout_settings = None
    
    # Se abbiamo il MAC, inviamo il WOL e impostiamo un timeout lungo per il risveglio
    if laptop_mac:
        print(f"[WOL] Invio magic packet a {laptop_mac}...")
        wakeonlan.send_magic_packet(laptop_mac)
        timeout_settings = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
    
    payload = {
        "messages": messages,
        "stream": True
    }

    async with httpx.AsyncClient(timeout=timeout_settings) as client:
        try:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                
                current_sentence = ""
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content")
                            
                            if token:
                                current_sentence += token
                                
                                # Rileva la fine di una frase e fa yield al worker
                                if any(punct in token for punct in ['.', '!', '?']):
                                    sentence_to_yield = current_sentence.strip()
                                    if sentence_to_yield:
                                        yield sentence_to_yield
                                    current_sentence = "" 
                                    
                        except (json.JSONDecodeError, IndexError):
                            continue
                
                # Svuota il buffer finale se c'è testo residuo senza punteggiatura
                final_sentence = current_sentence.strip()
                if final_sentence:
                    yield final_sentence

        except httpx.ConnectError:
            yield "[ERRORE] Non riesco a connettermi al server di inferenza. Il laptop è acceso?"
        except httpx.ReadTimeout:
            yield "[ERRORE] Il laptop ha impiegato troppo tempo a rispondere. Riprova."
        except httpx.HTTPStatusError as e:
            yield f"[ERRORE] Errore dal server: codice {e.response.status_code}"


async def inference_worker(text_queue, tts_queue):
    """
    Worker che consuma il testo riconosciuto, gestisce lo storico della conversazione
    e invia le frasi generate alla coda del TTS.
    """
    # --- CONFIGURAZIONE LAPTOP ---
    LAPTOP_IP = "127.0.0.1"  # <-- SOSTITUISCI CON L'IP DEL TUO LAPTOP
    LAPTOP_MAC = None          # <-- Metti il MAC ("AA:BB...") se vuoi usare il WOL, altrimenti None
    
    # Storico base della conversazione (è isolato per ogni client connesso,
    # perché questo worker viene istanziato ad ogni nuova connessione WebSocket)
    messages = [
        {"role": "system", "content": "Sei VELA, un assistente AI vocale e visivo completamente locale. Rispondi in modo conciso, naturale e in italiano."}
    ]
    
    while True:
        try:
            # 1. Aspetta che arrivi del testo dallo STT (Whisper)
            testo_utente = await text_queue.get()
            print(f"[INFERENCE] Ricevuto testo dall'utente: {testo_utente}")
            
            # 2. Aggiunge la domanda dell'utente allo storico
            messages.append({"role": "user", "content": testo_utente})
            
            # 3. Interroga il laptop e riceve la risposta in streaming
            risposta_completa = ""
            print(f"[INFERENCE] Contatto il VLM su {LAPTOP_IP}...")
            
            async for frase in ask_laptop(messages, LAPTOP_IP, LAPTOP_MAC):
                print(f"[INFERENCE] Frase generata (invio al TTS): {frase}")
                
                # 4. Mette la singola frase nella coda del TTS per farla pronunciare subito
                await tts_queue.put(frase)
                risposta_completa += frase + " "
                
            # 5. Salva la risposta completa dell'assistente nello storico per il turno successivo
            if risposta_completa.strip():
                messages.append({"role": "assistant", "content": risposta_completa.strip()})
            
        except asyncio.CancelledError:
            print("[INFERENCE] Task cancellato, chiusura worker.")
            break
        except Exception as e:
            print(f"[INFERENCE] Errore critico: {e}")
