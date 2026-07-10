"""Runtime generation of the alert chime and the shatter sound.

Both are synthesized into WAV files at runtime rather than committed as binary
assets. That is not only about repo hygiene: the reference shatter recordings
were captured from YouTube, and a processed copy of a copyrighted recording is
still a derivative work. Synthesis has no provenance problem, and it turns
"quieter" and "longer" into parameters rather than ffmpeg passes.

Pure stdlib (``wave``/``math``/``struct``/``random``), so it can be unit-tested
headlessly with no audio device and no Qt.

Note: ``QSoundEffect`` decodes **only uncompressed WAV**. It errors on FLAC.
"""

from __future__ import annotations

import math
import os
import random
import struct
import tempfile
import wave
from typing import Sequence

SAMPLE_RATE = 44100
_DEFAULT_NOTES = (587.33, 880.0)  # D5, A5 — a soft, non-jarring interval

# Bump when the synthesis changes, so cached files in the temp dir are not
# reused after an edit. Without this, tweaking a shatter parameter appears to
# do nothing until you delete the WAV by hand.
_CACHE_VERSION = 1


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


def _write_wav(path: str, samples: Sequence[float], sample_rate: int) -> str:
    """Write float samples in [-1, 1] as 16-bit mono PCM."""
    frames = bytearray()
    for value in samples:
        clipped = max(-1.0, min(1.0, value))
        frames += struct.pack("<h", int(clipped * 32767))

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))
    return path


def _add_decaying_sine(
    buf: list,
    onset: int,
    freq: float,
    decay_samples: float,
    gain: float,
    phase: float,
    sample_rate: int,
) -> None:
    """Mix one exponentially decaying sine into ``buf``, in place.

    Uses a two-term recurrence for the sine and a single multiply for the
    envelope, rather than calling math.sin/math.exp per sample. With ~140
    partials over 100k+ samples that is the difference between two seconds of
    startup freeze and a tenth of one.

    Stops as soon as the envelope is inaudible, which is why the high-frequency
    fragment grains cost almost nothing.
    """
    total = len(buf)
    if onset >= total or decay_samples <= 0.0:
        return

    omega = 2.0 * math.pi * freq / sample_rate
    coeff = 2.0 * math.cos(omega)
    # Seed the recurrence so that s[t] == sin(omega * t + phase).
    previous = math.sin(phase - omega)
    current = math.sin(phase)

    env = gain
    env_step = math.exp(-1.0 / decay_samples)
    cutoff = 1e-4 * gain

    for i in range(onset, total):
        buf[i] += env * current
        current, previous = coeff * current - previous, current
        env *= env_step
        if env < cutoff:
            break


def generate_shatter_wav(
    path: str,
    seconds: float = 2.6,
    amplitude: float = 0.22,
    seed: int = 7,
    resonances: int = 26,
    fragments: int = 110,
    sample_rate: int = SAMPLE_RATE,
) -> str:
    """Synthesize breaking glass and write it to ``path``.

    Three layers, which is roughly what breaking glass actually is:

    1. An **impact transient**: a very short broadband noise burst, one-zero
       high-passed so it reads as a sharp crack rather than a thud.
    2. **Resonant partials**: the plate ringing as it fractures. High, inharmonic
       sines with staggered onsets and decays. Inharmonic matters -- harmonic
       partials sound like a bell, not like glass.
    3. **Fragment tinkles**: a long, thinning scatter of tiny decaying grains as
       the pieces fall and settle. This is what makes it *sound* long rather
       than merely be long, and it is why time-stretching a recording sounds
       underwater: stretching smears the grains instead of spacing them.

    Deterministic for a given ``seed`` -- the same alert every time, and a test
    can pin the bytes. ``amplitude`` is the peak after normalisation, so it maps
    directly to headroom: 0.22 is about -13 dBFS.
    """
    rng = random.Random(seed)
    total = int(seconds * sample_rate)
    buf = [0.0] * total

    # 1a. Impact transient: the crack.
    burst = int(0.05 * sample_rate)
    previous = 0.0
    for i in range(min(burst, total)):
        noise = rng.uniform(-1.0, 1.0)
        highpassed = noise - previous  # one-zero high-pass: kills the thud
        previous = noise
        buf[i] += highpassed * math.exp(-i / (0.012 * sample_rate))

    # 1b. Impact body: the crunch. Low-passed noise over a longer decay. The
    # crack alone is a click; this is what gives the break some weight.
    body = int(0.18 * sample_rate)
    lowpassed = 0.0
    for i in range(min(body, total)):
        noise = rng.uniform(-1.0, 1.0)
        lowpassed += 0.10 * (noise - lowpassed)  # one-pole low-pass
        buf[i] += 2.2 * lowpassed * math.exp(-i / (0.045 * sample_rate))

    # 2. Resonant partials, inharmonic and staggered.
    #
    # A third of them sit low, in the body of the pane. Without those the clip
    # is all treble and reads as a cymbal: measured against the reference
    # recordings, an all-high partial set gave a zero-crossing rate of 13 kHz
    # where real breaking glass sits between 6 and 9 kHz.
    for index in range(resonances):
        low_body = index % 3 == 0
        _add_decaying_sine(
            buf,
            onset=int(rng.uniform(0.0, 0.12) * sample_rate),
            freq=(
                rng.uniform(180.0, 900.0) if low_body
                else rng.uniform(900.0, 6800.0)
            ),
            decay_samples=rng.uniform(0.08, 0.5) * sample_rate,
            gain=rng.uniform(0.25, 0.7) if low_body else rng.uniform(0.15, 0.6),
            phase=rng.uniform(0.0, 2.0 * math.pi),
            sample_rate=sample_rate,
        )

    # 3. Fragment tinkles, thinning toward the end.
    for _ in range(fragments):
        # Bias onsets early: most fragments land soon, a few keep skittering.
        when = rng.random() ** 1.7 * 0.92
        _add_decaying_sine(
            buf,
            onset=int(when * seconds * sample_rate),
            freq=rng.uniform(1600.0, 8500.0),
            decay_samples=rng.uniform(0.015, 0.09) * sample_rate,
            gain=rng.uniform(0.05, 0.35) * (1.0 - when * 0.7),
            phase=rng.uniform(0.0, 2.0 * math.pi),
            sample_rate=sample_rate,
        )

    # Normalise to unity, then scale. Doing it in this order makes `amplitude`
    # mean peak level regardless of how the layers happened to sum.
    peak = max(abs(v) for v in buf) or 1.0
    scale = amplitude / peak
    for i in range(total):
        buf[i] *= scale

    # Fade the last 60 ms so the clip cannot click when it stops.
    fade = min(int(0.06 * sample_rate), total)
    for i in range(fade):
        buf[total - fade + i] *= 0.5 * (1.0 + math.cos(math.pi * i / fade))

    return _write_wav(path, buf, sample_rate)


def _cached(name: str, generate) -> str:
    """A per-user temp path, generated once.

    The uid is in the filename because /tmp is shared: the second user to run
    the app would otherwise collide with the first user's file and be unable to
    overwrite it.
    """
    uid = getattr(os, "getuid", lambda: 0)()
    path = os.path.join(
        tempfile.gettempdir(), f"naive_timer_{name}_{uid}_v{_CACHE_VERSION}.wav"
    )
    if not os.path.exists(path):
        generate(path)
    return path


def default_chime_path() -> str:
    """Generate (once) and return a temp-file path to the default chime."""
    return _cached("chime", generate_chime_wav)


def default_shatter_path() -> str:
    """Generate (once) and return a temp-file path to the shatter sound."""
    return _cached("shatter", generate_shatter_wav)
