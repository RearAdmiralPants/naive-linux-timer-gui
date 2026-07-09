"""Runtime generation of a gentle alert chime.

We synthesize a soft two-note chime into a WAV file at runtime rather than
committing a binary asset. This keeps the alert self-contained and easy to make
configurable (swap the frequencies, or point the GUI at your own file).

Pure stdlib (``wave``/``math``/``struct``), so it can be unit-tested headlessly:
the test just checks a valid, non-empty WAV is produced.
"""

from __future__ import annotations

import math
import os
import struct
import tempfile
import wave
from typing import Sequence

SAMPLE_RATE = 44100
_DEFAULT_NOTES = (587.33, 880.0)  # D5, A5 — a soft, non-jarring interval


def generate_chime_wav(
    path: str,
    notes: Sequence[float] = _DEFAULT_NOTES,
    note_seconds: float = 0.45,
    tail_silence: float = 1.1,
    amplitude: float = 0.28,
    sample_rate: int = SAMPLE_RATE,
) -> str:
    """Write a looping-friendly chime to ``path`` and return it.

    The clip is: each note played in sequence with a smooth fade in/out,
    followed by ``tail_silence`` seconds of quiet — so looping it yields a
    gentle, spaced repetition rather than a continuous drone.
    """
    frames = bytearray()
    max_amp = int(amplitude * 32767)

    for freq in notes:
        n = int(note_seconds * sample_rate)
        for i in range(n):
            # Raised-cosine envelope: no clicks at note boundaries.
            env = 0.5 * (1 - math.cos(2 * math.pi * i / n))
            sample = env * math.sin(2 * math.pi * freq * i / sample_rate)
            frames += struct.pack("<h", int(sample * max_amp))

    frames += b"\x00\x00" * int(tail_silence * sample_rate)

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return path


def default_chime_path() -> str:
    """Generate (once) and return a temp-file path to the default chime."""
    path = os.path.join(tempfile.gettempdir(), "naive_timer_chime.wav")
    if not os.path.exists(path):
        generate_chime_wav(path)
    return path
