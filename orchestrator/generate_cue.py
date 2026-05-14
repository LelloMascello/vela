#!/usr/bin/env python3
"""
generate_cue.py — Generate the wake-word audio cue
===================================================
Produces  audio/standby_cue.wav  ("Sì, di cosa hai bisogno?")
using pyttsx3 (offline TTS) or, if a better Italian voice is available,
gTTS (requires internet).

Run once before starting router.py:
    python generate_cue.py
"""

import sys
import wave
from pathlib import Path

OUT_PATH = Path(__file__).parent / "audio" / "standby_cue.wav"
TEXT     = "Sì, di cosa hai bisogno?"

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def _try_gtts() -> bool:
    """Try gTTS first — better Italian pronunciation."""
    try:
        from gtts import gTTS
        import io
        from pydub import AudioSegment   # needed to convert mp3 → wav

        print("[cue] Using gTTS (online) …")
        tts = gTTS(text=TEXT, lang="it")
        mp3_buf = io.BytesIO()
        tts.write_to_fp(mp3_buf)
        mp3_buf.seek(0)

        seg = AudioSegment.from_mp3(mp3_buf)
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        seg.export(str(OUT_PATH), format="wav")
        print(f"[cue] Saved {OUT_PATH}  ({OUT_PATH.stat().st_size} bytes)")
        return True
    except Exception as exc:
        print(f"[cue] gTTS failed ({exc}), falling back …")
        return False


def _try_pyttsx3() -> bool:
    """Offline fallback with pyttsx3."""
    try:
        import pyttsx3
        import tempfile, os, shutil

        print("[cue] Using pyttsx3 (offline) …")
        engine = pyttsx3.init()

        # Try to pick an Italian voice
        for voice in engine.getProperty("voices"):
            if "it" in (voice.languages[0].decode() if voice.languages else ""):
                engine.setProperty("voice", voice.id)
                print(f"[cue] Italian voice: {voice.name}")
                break

        engine.setProperty("rate", 150)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        engine.save_to_file(TEXT, tmp_path)
        engine.runAndWait()
        shutil.move(tmp_path, str(OUT_PATH))
        print(f"[cue] Saved {OUT_PATH}  ({OUT_PATH.stat().st_size} bytes)")
        return True
    except Exception as exc:
        print(f"[cue] pyttsx3 failed ({exc})")
        return False


def _silent_fallback() -> None:
    """
    Last resort: write a 1-second silent WAV so router.py doesn't crash
    if neither TTS engine is available.
    """
    print("[cue] ⚠  Writing silent placeholder WAV.")
    sample_rate = 16000
    n_samples   = sample_rate          # 1 second
    with wave.open(str(OUT_PATH), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    print(f"[cue] Placeholder saved at {OUT_PATH}")


if __name__ == "__main__":
    if not _try_gtts():
        if not _try_pyttsx3():
            _silent_fallback()
            sys.exit(1)
