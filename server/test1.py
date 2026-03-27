import asyncio
import json
import httpx

# --- CONFIGURATION ---
LAPTOP_IP = "172.18.57.90"  # <--- CHANGE THIS to your laptop's IP!
LLAMA_URL = f"http://{LAPTOP_IP}:8080/v1/chat/completions"

async def ask_laptop(messages):
    payload = {
        "messages": messages,
        "stream": True
    }

    print(f"Connecting to {LLAMA_URL}...")
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream("POST", LLAMA_URL, json=payload, timeout=None) as response:
                # Check if the laptop refused the connection or returned a 404/500
                response.raise_for_status() 
                
                current_sentence = ""
                print("\n--- INFERENCE START ---\n")
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            
                            # Safely extract delta and content
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content")
                            
                            # Only proceed if we actually got text (ignores None and empty strings)
                            if token:
                                current_sentence += token
                                
                                # Print the token immediately so you can see it streaming
                                print(token, end="", flush=True)
                                
                                # Basic sentence boundary detection for TTS
                                if any(punct in token for punct in ['.', '!', '?']):
                                    print(f"\n[SENTENCE READY FOR TTS]: {current_sentence.strip()}")
                                    current_sentence = "" 
                                
                        except (json.JSONDecodeError, IndexError):
                            continue
                
                # Catch any leftover text that didn't end in punctuation
                if current_sentence.strip():
                    print(f"\n[SENTENCE READY FOR TTS]: {current_sentence.strip()}")
                    
                print("\n\n--- INFERENCE COMPLETE ---")
                
        except httpx.ConnectError:
            print("\n[ERROR] Could not connect to the laptop. Is llama-server running and is the IP correct?")
        except httpx.HTTPStatusError as e:
             print(f"\n[ERROR] HTTP Error: {e.response.status_code} - {e.response.text}")

async def main():
    # Constructing a dummy conversation history as required by your architecture
    test_messages = [
        {"role": "system", "content": "Sei VELA, un assistente AI vocale. Rispondi in modo conciso."},
        {"role": "user", "content": "Ciao Vela, mi scrivi una breve spiegazione di come funzionano le API REST?"}
    ]
    
    await ask_laptop(test_messages)

if __name__ == "__main__":
    asyncio.run(main())
