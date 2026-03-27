import json
import httpx
import wakeonlan

async def ask_laptop(messages, laptop_ip, laptop_mac=None):
    """
    Invia la richiesta al VLM e restituisce le frasi in streaming.
    Invia il Wake-on-LAN e imposta il timeout SOLO se viene fornito il MAC address.
    """
    url = f"http://{laptop_ip}:8080/v1/chat/completions"
    
    # Di default non mettiamo nessun timeout
    timeout_settings = None
    
    # Se abbiamo il MAC, inviamo il WOL e impostiamo il timeout
    if laptop_mac:
        print(f"[WOL] Invio magic packet a {laptop_mac}...")
        wakeonlan.send_magic_packet(laptop_mac)
        timeout_settings = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
    
    payload = {
        "messages": messages,
        "stream": True
    }

    # Il client userà il timeout lungo se c'è il MAC, altrimenti timeout=None
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
                                
                                if any(punct in token for punct in ['.', '!', '?']):
                                    sentence_to_yield = current_sentence.strip()
                                    if sentence_to_yield:
                                        yield sentence_to_yield
                                    current_sentence = "" 
                                    
                        except (json.JSONDecodeError, IndexError):
                            continue
                
                final_sentence = current_sentence.strip()
                if final_sentence:
                    yield final_sentence

        except httpx.ConnectError:
            yield "[ERRORE] Non riesco a connettermi al laptop. È acceso?"
        except httpx.ReadTimeout:
            yield "[ERRORE] Il laptop ha impiegato troppo tempo a rispondere."
        except httpx.HTTPStatusError as e:
            yield f"[ERRORE] Errore dal server: {e.response.status_code}"
