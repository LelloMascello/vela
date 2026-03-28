#"""
#inference_worker.py  –  VELA Inference worker
#
#Ottimizzazioni rispetto alla versione originale:
#  - Splitting su ';' e ':' oltre a '.', '!', '?' → primo chunk TTS arriva prima
#    per risposte lunghe (il TTS inizia a parlare a metà generazione)
#  - Soglia sulla lunghezza minima della frase (MIN_SENTENCE_CHARS) per evitare
#    di inviare al TTS frammenti di una o due parole
#  - Storico conversazione limitato agli ultimi MAX_HISTORY_TURNS turni:
#    ogni turno in più rallenta il prefill del LLM
#  - Nessun import non necessario rimosso (wakeonlan è opzionale)
#"""

import asyncio
import json
import httpx

try:
    import wakeonlan
    _WOL_AVAILABLE = True
except ImportError:
    _WOL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Parametri di splitting delle frasi
# ---------------------------------------------------------------------------
# Punteggiatura che segnala la fine di una frase inviabile al TTS
SENTENCE_END_CHARS = frozenset(".!?;:")
# Lunghezza minima (caratteri) affinché un frammento venga inviato al TTS.
# Evita di inviare "Ok," o "Sì," come frase separata.
MIN_SENTENCE_CHARS = 20

# Numero massimo di turni (user + assistant) conservati nello storico.
# Oltre questo limite i turni più vecchi vengono rimossi.
MAX_HISTORY_TURNS = 8   # = 4 scambi completi


# ---------------------------------------------------------------------------
# Comunicazione con llama-server (streaming SSE)
# ---------------------------------------------------------------------------
async def ask_laptop(messages: list[dict], laptop_ip: str, laptop_mac: str | None = None):
    """
    Generatore asincrono: invia la richiesta al VLM in streaming e restituisce
    le frasi complete man mano che vengono generate.
    """
    url = f"http://{laptop_ip}:8080/v1/chat/completions"

    timeout = None
    if laptop_mac and _WOL_AVAILABLE:
        print(f"[WOL] Invio magic packet a {laptop_mac}...")
        wakeonlan.send_magic_packet(laptop_mac)
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

    payload = {"messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()

                current_sentence = ""

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data_str)
                        token = (
                            chunk.get("choices", [{}])[0]
                                 .get("delta", {})
                                 .get("content")
                        )
                    except (json.JSONDecodeError, IndexError):
                        continue

                    if not token:
                        continue

                    current_sentence += token

                    # Controlla se l'ultimo carattere del token è un punto di fine frase
                    # e la frase è abbastanza lunga da avere senso da sola
                    if (
                        any(c in SENTENCE_END_CHARS for c in token)
                        and len(current_sentence.strip()) >= MIN_SENTENCE_CHARS
                    ):
                        sentence = current_sentence.strip()
                        if sentence:
                            yield sentence
                        current_sentence = ""

                # Flush del buffer finale (testo senza punteggiatura finale)
                remainder = current_sentence.strip()
                if remainder:
                    yield remainder

        except httpx.ConnectError:
            yield "[ERRORE] Non riesco a connettermi al server di inferenza. Il laptop è acceso?"
        except httpx.ReadTimeout:
            yield "[ERRORE] Timeout: il server di inferenza non ha risposto in tempo."
        except httpx.HTTPStatusError as e:
            yield f"[ERRORE] Errore HTTP dal server: {e.response.status_code}"


# ---------------------------------------------------------------------------
# Worker asincrono principale
# ---------------------------------------------------------------------------
async def inference_worker(text_queue: asyncio.Queue, tts_queue: asyncio.Queue) -> None:
    # ── Configurazione ───────────────────────────────────────────────────────
    LAPTOP_IP  = "127.0.0.1"   # IP del server llama-server
    LAPTOP_MAC = None           # MAC per Wake-on-LAN (None = disabilitato)

    # Prompt di sistema
    system_prompt = (
        "Sei VELA, un assistente AI vocale e visivo completamente locale. "
        "Rispondi in modo conciso, naturale e in italiano. "
        "Usa frasi brevi separate da punteggiatura, così la tua voce parte subito."
    )
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    while True:
        try:
            # 1. Attendi la query dell'utente dallo STT
            testo_utente = await text_queue.get()
            print(f"[INFERENCE] Query utente: '{testo_utente}'")

            # 2. Aggiungi al messaggio allo storico
            messages.append({"role": "user", "content": testo_utente})

            # 3. Interroga il VLM in streaming
            risposta_completa = ""
            print(f"[INFERENCE] Contatto il VLM su {LAPTOP_IP}...")

            async for frase in ask_laptop(messages, LAPTOP_IP, LAPTOP_MAC):
                print(f"[INFERENCE] → TTS: '{frase}'")
                await tts_queue.put(frase)
                risposta_completa += frase + " "

            # 4. Salva la risposta nello storico
            if risposta_completa.strip():
                messages.append({"role": "assistant", "content": risposta_completa.strip()})

            # 5. Tronca lo storico (mantieni solo system + ultimi N turni)
            #    Ogni "turno" = 1 messaggio user + 1 messaggio assistant = 2 elementi
            max_messages = 1 + MAX_HISTORY_TURNS * 2   # system + turni
            if len(messages) > max_messages:
                messages = [messages[0]] + messages[-(MAX_HISTORY_TURNS * 2):]
                print(f"[INFERENCE] Storico troncato a {MAX_HISTORY_TURNS} turni.")

        except asyncio.CancelledError:
            print("[INFERENCE] Worker cancellato.")
            break
        except Exception as e:
            print(f"[INFERENCE] Errore critico: {e}")