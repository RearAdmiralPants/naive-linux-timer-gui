"""Headless test that chime generation produces a valid, non-empty WAV."""

import os
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from naive_timer.sound import generate_chime_wav


class SoundTest(unittest.TestCase):
    def test_generates_valid_wav(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "chime.wav")
            generate_chime_wav(path, note_seconds=0.1, tail_silence=0.1)
            self.assertTrue(os.path.exists(path))
            with wave.open(path, "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 44100)
                self.assertGreater(wav.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
