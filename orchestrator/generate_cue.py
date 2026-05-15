#!/usr/bin/env python3
"""
generate_cue.py — Generate the wake-word audio cue
===================================================
Produces  audio/standby_cue.wav  ("Sì, di cosa hai bisogno?")

Strategy (tries each in order, stops at first success):
  1. edge-tts  — Microsoft neural TTS, Italian voice, free, pip-installable
                 pip install edge-tts
  2. espeak-ng — Offline system TTS, available on Arch:
                 sudo pacman -S espeak-ng
  3. Silent placeholder — so router.py always has a file to send.

Run once before starting router.py:
    python generate_cue.py
"""

import asyncio
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

OUT_PATH = Path(__file__).parent / "audio" / "standby_cue.wav"
TEXT     = "Sì, di cosa hai bisogno?"
LANG     = "it"

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


# ─── Helper: resample / re-encode any WAV to 16 kHz 16-bit mono ──────────────

def _normalise_wav(src: Path, dst: Path) -> None:
    """
    Convert src WAV → 16 kHz, 16-bit, mono at dst.
    Uses ffmpeg if available, otherwise falls back to Python's audioop.
    """
    if shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src),
             "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(dst)],
            check=True, capture_output=True,
        )
    else:
        # Pure-Python resample (good enough for a short cue clip)
        import audioop
        with wave.open(str(src), "rb") as wf_in:
            n_ch    = wf_in.getnchannels()
            sw      = wf_in.getsampwidth()
            rate_in = wf_in.getframerate()
            data    = wf_in.readframes(wf_in.getnframes())

        # Mono-mix if stereo
        if n_ch == 2:
            data = audioop.tomono(data, sw, 0.5, 0.5)
        # Convert to 16-bit if needed
        if sw != 2:
            data = audioop.lin2lin(data, sw, 2)
        # Resample to 16 kHz
        if rate_in != 16000:
            data, _ = audioop.ratecv(data, 2, 1, rate_in, 16000, None)

        with wave.open(str(dst), "wb") as wf_out:
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)
            wf_out.setframerate(16000)
            wf_out.writeframes(data)


# ─── Method 1: edge-tts ───────────────────────────────────────────────────────

async def _edge_tts_async(tmp_mp3: Path) -> None:
    import edge_tts
    # Best available Italian neural voice (female, natural)
    voice = "it-IT-ElsaNeural"
    communicate = edge_tts.Communicate(TEXT, voice)
    await communicate.save(str(tmp_mp3))


def _try_edge_tts() -> bool:
    try:
        import edge_tts  # noqa: F401 — just checking it's installed
    except ImportError:
        print("[cue] edge-tts not installed  →  pip install edge-tts")
        return False

    print("[cue] Using edge-tts (it-IT-ElsaNeural) …")
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_mp3 = Path(f.name)

        asyncio.run(_edge_tts_async(tmp_mp3))

        # edge-tts produces MP3; convert to WAV
        if shutil.which("ffmpeg"):
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(tmp_mp3),
                 "-ar", "16000", "-ac", "1", "-sample_fmt", "s16",
                 str(OUT_PATH)],
                check=True, capture_output=True,
            )
        else:
            # pydub fallback for MP3 → WAV when ffmpeg is absent
            from pydub import AudioSegment
            seg = AudioSegment.from_mp3(str(tmp_mp3))
            seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            seg.export(str(OUT_PATH), format="wav")

        tmp_mp3.unlink(missing_ok=True)
        print(f"[cue] ✓ Saved {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")
        return True

    except Exception as exc:
        print(f"[cue] edge-tts failed: {exc}")
        return False


# ─── Method 2: espeak-ng (system package) ────────────────────────────────────

def _try_espeak() -> bool:
    if not shutil.which("espeak-ng") and not shutil.which("espeak"):
        print("[cue] espeak-ng not found  →  sudo pacman -S espeak-ng")
        return False

    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    print(f"[cue] Using {Path(binary).name} (offline) …")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_wav = Path(f.name)

        subprocess.run(
            [binary,
             "-v", "it",           # Italian voice
             "-s", "140",          # speed (words/min) — slightly slower = clearer
             "-a", "180",          # amplitude
             "-w", str(tmp_wav),   # write to WAV
             TEXT],
            check=True, capture_output=True,
        )

        _normalise_wav(tmp_wav, OUT_PATH)
        tmp_wav.unlink(missing_ok=True)
        print(f"[cue] ✓ Saved {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes)")
        return True

    except subprocess.CalledProcessError as exc:
        print(f"[cue] espeak-ng error: {exc.stderr.decode()}")
        return False
    except Exception as exc:
        print(f"[cue] espeak-ng failed: {exc}")
        return False


# ─── Method 3: silent placeholder ────────────────────────────────────────────

def _silent_fallback() -> None:
    print("[cue] ⚠  All TTS methods failed — writing silent placeholder.")
    print("[cue]    Fix: pip install edge-tts   OR   sudo pacman -S espeak-ng")
    with wave.open(str(OUT_PATH), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)   # 1 second of silence
    print(f"[cue] Placeholder saved at {OUT_PATH}")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[cue] Generating audio cue for: «{TEXT}»")
    print(f"[cue] Output: {OUT_PATH}")

    if _try_edge_tts():
        sys.exit(0)
    if _try_espeak():
        sys.exit(0)

    _silent_fallback()
    sys.exit(1)