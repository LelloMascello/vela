#"""
#Vela — Wake Word Engine (Pi)
#=============================
#Wraps openWakeWord for continuous, chunk-by-chunk detection.
#
#One engine instance per connected client so multiple clients can be
#listened to independently.
#
#Expected audio: 16 kHz, 16-bit signed PCM, mono — same format the
#client streams to the Pi WebSocket.
#
#openWakeWord internally expects chunks of exactly 1 280 samples
#(~80 ms).  Smaller or larger chunks from the network are buffered and
#consumed in 1 280-sample windows automatically.
#
#Wake word:
#    By default this uses the built-in 'hey_jarvis' model as a stand-in.
#    To use a custom "Vela" model, set the WAKE_WORD_MODEL env var to
#    the path of your trained .onnx file.  See setup_manual.md for
#    training instructions.
#"""

import logging
import os
from collections import deque

import numpy as np

logger = logging.getLogger("vela.wakeword")

# openWakeWord processes frames of exactly this many samples
OWW_CHUNK_SAMPLES = 1_280
SAMPLE_RATE       = 16_000

# Lower threshold → fewer missed detections, more false positives
DETECTION_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))

# Path to a custom .onnx wake-word model (optional)
CUSTOM_MODEL_PATH = os.getenv("WAKE_WORD_MODEL", "")


class WakeWordEngine:
    #"""
    #Instantiate one per client connection.
#
    #    engine = WakeWordEngine()
    #    ...
    #    if engine.process_chunk(raw_pcm_bytes):
    #        # wake word detected — start session
    #        engine.reset()
    #"""

    def __init__(self):
        # Lazy import so the Pi's main.py starts even if openwakeword
        # hasn't been installed yet (helps during initial setup).
        try:
            import openwakeword
            from openwakeword.model import Model
            openwakeword.utils.download_models()

            if CUSTOM_MODEL_PATH and os.path.isfile(CUSTOM_MODEL_PATH):
                model_list = [CUSTOM_MODEL_PATH]
                logger.info(f"Using custom wake word model: {CUSTOM_MODEL_PATH}")
            else:
                model_list = ["hey_jarvis"]
                logger.warning(
                    "WAKE_WORD_MODEL not set or file missing — "
                    "using built-in 'hey_jarvis' as placeholder. "
                    "See setup_manual.md to train a 'Vela' model."
                )

            self._model = Model(
                wakeword_models=model_list,
                inference_framework="onnx",
            )
            self._available = True
        except ImportError:
            logger.error(
                "openwakeword is not installed. "
                "Run: pip install openwakeword --break-system-packages"
            )
            self._available = False
            self._model = None

        # Rolling sample buffer for sub-chunk alignment
        self._buf = np.array([], dtype=np.int16)

    # ------------------------------------------------------------------
    def process_chunk(self, audio_bytes: bytes) -> bool:
        #"""
        #Feed a raw PCM bytes chunk of any size.
        #Returns True the first frame in which the wake word score exceeds
        #DETECTION_THRESHOLD; False otherwise.
        #"""
        if not self._available:
            return False

        new_samples = np.frombuffer(audio_bytes, dtype=np.int16)
        self._buf   = np.concatenate([self._buf, new_samples])

        detected = False
        while len(self._buf) >= OWW_CHUNK_SAMPLES:
            window        = self._buf[:OWW_CHUNK_SAMPLES]
            self._buf     = self._buf[OWW_CHUNK_SAMPLES:]
            predictions   = self._model.predict(window)

            for word, score in predictions.items():
                if score >= DETECTION_THRESHOLD:
                    logger.info(
                        f"Wake word detected — keyword='{word}' score={score:.3f}"
                    )
                    detected = True

        return detected

    # ------------------------------------------------------------------
    def reset(self):
        """
        Clear internal state after a wake word fires.
        Call this before entering relay mode so old audio doesn't
        re-trigger detection when returning to idle.
        """
        self._buf = np.array([], dtype=np.int16)
        if self._available and self._model:
            # openWakeWord models keep a short prediction history;
            # resetting avoids a double-trigger on the next idle cycle.
            try:
                self._model.reset()
            except AttributeError:
                pass  # older versions may not expose reset()
