#"""
#inference_worker.py  –  VELA Inference worker (llama-cpp-python nativo)
#
#Il modello Qwen3VL-8B viene caricato direttamente nel processo Python tramite
#llama-cpp-python, eliminando la dipendenza dal processo llama-server separato.
#Sostituisce completamente httpx e ask_laptop().
#
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#Installazione llama-cpp-python con GPU Vulkan (AMD Radeon 780M / Ryzen 8840HS):
#
#  CMAKE_ARGS="-DGGML_VULKAN=ON" pip install llama-cpp-python --no-cache-dir
#
#  Oppure con HIP/ROCm (richiede driver ROCm installato):
#  CMAKE_ARGS="-DGGML_HIP=ON" ROCM_PATH=/opt/rocm pip install llama-cpp-python
#
#  Verifica GPU nei log di avvio:
#    "ggml_vulkan: Found 1 Vulkan device"  → accelerazione GPU attiva  ✓
#    "ggml_cuda: no CUDA devices found"   → solo CPU (ricompilare)      ✗
#
#Equivalenza parametri llama-server → llama-cpp-python Llama():
#  --n-gpu-layers 99   → n_gpu_layers=99
#  --ctx-size 4096     → n_ctx=4096
#  --batch-size 512    → n_batch=512
#  --ubatch-size 512   → n_ubatch=512
#  --threads 4         → n_threads=4
#  --threads-batch 8   → n_threads_batch=8
#  --no-mmap           → use_mmap=False
#━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
#Messaggi accettati da inference_queue:
#  {
#    "text"  : str,        # query testuale (senza la parola "vela")
#    "image" : str | None, # base64 JPEG opzionale (foto inviata dal client)
#    "reset" : bool,       # True → azzera lo storico conversazione prima di rispondere
#  }
#
#Callback on_response_done():
#  Funzione async chiamata al termine di ogni risposta → main.py apre la
#  finestra 8s e notifica il client.
#"""

import asyncio
import threading
import queue as thread_queue
from collections.abc import AsyncIterator
from typing import Callable, Awaitable

from llama_cpp import Llama
from llama_cpp.llama_chat_format import Llava15ChatHandler

# ---------------------------------------------------------------------------
# Percorsi modello – CONFIGURARE prima dell'avvio
# ---------------------------------------------------------------------------
MODEL_PATH  = "/home/leo/vela/inference/models/Qwen3VL-8B-Instruct-Q4_K_M.gguf"
MMPROJ_PATH = "/home/leo/vela/inference/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf"

# ---------------------------------------------------------------------------
# Parametri generazione
# ---------------------------------------------------------------------------
SENTENCE_END_CHARS = frozenset(".!?;:")
MIN_SENTENCE_CHARS = 20    # caratteri minimi per inviare una frase al TTS
MAX_HISTORY_TURNS  = 8     # turni conversazione conservati (1 turno = user + assistant)
MAX_NEW_TOKENS     = 512
TEMPERATURE        = 0.7

SYSTEM_PROMPT = (
    "Sei VELA, un assistente AI vocale e visivo completamente locale. "
    "Rispondi in modo conciso, naturale e in italiano. "
    "Usa frasi brevi separate da punteggiatura, così la tua voce parte subito."
)

# ---------------------------------------------------------------------------
# Caricamento modello – avviene UNA SOLA VOLTA all'importazione del modulo.
# Il tempo di caricamento varia da 30 s a qualche minuto a seconda della GPU.
# ---------------------------------------------------------------------------
print("[INFERENCE] Caricamento Qwen3VL-8B in corso…")
print("[INFERENCE] (Prima esecuzione: trasferimento layer su GPU Vulkan, attendere)")

#_chat_handler = Qwen2VLChatHandler(clip_model_path=MMPROJ_PATH, verbose=False)
# Nota: se Qwen2VLChatHandler causa errori su Qwen3VL, usare Llava15ChatHandler:
from llama_cpp.llama_chat_format import Llava15ChatHandler
_chat_handler = Llava15ChatHandler(clip_model_path=MMPROJ_PATH, verbose=False)

_llm = Llama(
    model_path       = MODEL_PATH,
    chat_handler     = _chat_handler,
    n_gpu_layers     = 99,    # carica tutti i layer sulla GPU (Vulkan/CUDA/HIP)
    n_ctx            = 4096,  # ridotto da 8192 → più VRAM per i layer GPU
    n_batch          = 512,   # batch prefill più grande → prima risposta più veloce
    n_ubatch         = 512,   # micro-batch allineato (riduce overhead)
    n_threads        = 4,     # thread decoding: 4 core fisici ottimali
    n_threads_batch  = 8,     # thread prefill: usa tutti i core logici
    use_mmap         = False, # no memory-map → evita page fault durante l'inferenza
    logits_all       = False,
    verbose          = False,
)
print("[INFERENCE] Modello caricato e pronto!")


# ---------------------------------------------------------------------------
# Streaming bloccante in thread separato
# ---------------------------------------------------------------------------
def _stream_to_queue(messages: list[dict], out_q: "thread_queue.Queue[str | Exception | None]") -> None:
    """
    Esegue create_chat_completion(stream=True) in un thread OS separato e
    invia ogni token alla coda thread-safe out_q.

    Segnali speciali:
      None      → generazione completata normalmente
      Exception → errore durante la generazione
    """
    try:
        for chunk in _llm.create_chat_completion(
            messages    = messages,
            stream      = True,
            max_tokens  = MAX_NEW_TOKENS,
            temperature = TEMPERATURE,
        ):
            token: str = chunk["choices"][0]["delta"].get("content") or ""
            out_q.put(token)
    except Exception as exc:
        out_q.put(exc)
    finally:
        out_q.put(None)   # sentinel: fine stream


async def _iter_sentences(messages: list[dict]) -> AsyncIterator[str]:
    """
    Async generator che avvia il thread di inferenza e restituisce
    frasi complete man mano che vengono generate, pronte per il TTS.
    Usa run_in_executor per non bloccare il loop asyncio mentre aspetta token.
    """
    tq: "thread_queue.Queue[str | Exception | None]" = thread_queue.Queue()
    loop = asyncio.get_running_loop()

    thread = threading.Thread(target=_stream_to_queue, args=(messages, tq), daemon=True)
    thread.start()

    current_sentence = ""

    try:
        while True:
            # Attendi il prossimo token senza bloccare il loop asyncio
            item = await loop.run_in_executor(None, tq.get)

            if item is None:
                # Generazione completata → svuota il buffer residuo
                break
            if isinstance(item, Exception):
                print(f"[INFERENCE] Errore streaming: {item}")
                yield "[ERRORE] Problema interno durante la generazione."
                break

            current_sentence += item

            # Invia la frase al TTS quando è completa e abbastanza lunga
            if (
                any(c in SENTENCE_END_CHARS for c in item)
                and len(current_sentence.strip()) >= MIN_SENTENCE_CHARS
            ):
                sentence = current_sentence.strip()
                if sentence:
                    yield sentence
                current_sentence = ""

    finally:
        # Flush del buffer finale (testo senza punteggiatura terminale)
        remainder = current_sentence.strip()
        if remainder:
            yield remainder

        thread.join(timeout=2.0)   # attendi pulizia thread (daemon → non blocca exit)


# ---------------------------------------------------------------------------
# Costruzione lista messaggi per llama-cpp-python
# ---------------------------------------------------------------------------
def _build_messages(
    history    : list[dict],
    text       : str,
    image_b64  : str | None = None,
) -> list[dict]:
    """
    Costruisce la lista completa di messaggi: system prompt + storico testuale
    + turno corrente (con eventuale immagine).

    Le immagini non vengono mai inserite nello storico dei turni passati
    (troppo costose in VRAM/token); solo il testo viene conservato.
    """
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs.extend(history)   # storico: solo coppie user/assistant testuali

    # Turno corrente: opzionalmente con immagine inline (formato OpenAI multimodal)
    if image_b64:
        user_content = [
            {
                "type"      : "image_url",
                "image_url" : {"url": f"data:image/jpeg;base64,{image_b64}"},
            },
            {
                "type" : "text",
                "text" : text or "Descrivi questa immagine.",
            },
        ]
    else:
        user_content = text

    msgs.append({"role": "user", "content": user_content})
    return msgs


# ---------------------------------------------------------------------------
# Worker asincrono principale
# ---------------------------------------------------------------------------
async def inference_worker(
    inference_queue  : asyncio.Queue,
    tts_queue        : asyncio.Queue,
    last_exchange    : dict,                            # {"query": str, "response": str}
    on_response_done : Callable[[], Awaitable[None]],   # callback → apre finestra 8s
) -> None:
    """
    Attende query da inference_queue, esegue l'inferenza VLM in streaming
    e invia le frasi generate al TTS worker.
    Chiama on_response_done() al termine di ogni risposta completa.

    Storico:
      Conserva al massimo MAX_HISTORY_TURNS turni testuali.
      Viene resettato quando item["reset"] è True (finestra 8s scaduta).
    """
    # Storico SOLO testuale (le immagini non vengono mai inserite qui)
    history: list[dict] = []

    while True:
        try:
            item = await inference_queue.get()

            # ── Gestione reset contesto ───────────────────────────────────────
            if item.get("reset"):
                history = []
                print("[INFERENCE] Contesto conversazione resettato (finestra 8s scaduta).")

            text      = item.get("text", "")
            image     = item.get("image")          # base64 JPEG o None
            has_image = bool(image)

            if not text and not image:
                print("[INFERENCE] Item vuoto ignorato.")
                continue

            print(
                f"[INFERENCE] Query: '{text}'"
                + (" [con immagine allegata]" if has_image else "")
            )
            last_exchange["query"] = text

            # ── Costruzione messaggi e inferenza streaming ────────────────────
            messages = _build_messages(history, text, image)

            full_response = ""
            async for sentence in _iter_sentences(messages):
                print(f"[INFERENCE] → TTS: '{sentence}'")
                await tts_queue.put(sentence)
                full_response += sentence + " "

            full_response = full_response.strip()

            # ── Aggiornamento storico (solo testo; immagine scartata) ─────────
            if full_response:
                history.append({"role": "user",      "content": text})
                history.append({"role": "assistant",  "content": full_response})
                last_exchange["response"] = full_response
                print(f"[INFERENCE] Risposta completa ({len(full_response)} car.).")

                # Tronca se lo storico supera il limite
                max_entries = MAX_HISTORY_TURNS * 2   # coppie user/assistant
                if len(history) > max_entries:
                    history = history[-max_entries:]
                    print(f"[INFERENCE] Storico troncato a {MAX_HISTORY_TURNS} turni.")

            # ── Notifica main.py: risposta completata → apri finestra 8s ─────
            await on_response_done()

        except asyncio.CancelledError:
            print("[INFERENCE] Worker cancellato.")
            break
        except Exception as e:
            print(f"[INFERENCE] Errore critico: {e}")