import unittest
import numpy as np
from speech.reference import select_clip


class ClipTests(unittest.TestCase):
    def test_whole_short_recording_and_manual_crop(self):
        audio = np.ones((4000, 2), dtype=np.float32) * .2
        clip, start, end = select_clip(audio, 1000)
        self.assertEqual((start, end, len(clip)), (0, 4000, 4000))
        clip, start, end = select_clip(audio, 1000, 500, 3500)
        self.assertEqual((start, end, len(clip)), (500, 3500, 3000))

    def test_long_recording_ends_in_pause(self):
        audio = np.ones(16000, dtype=np.float32) * .2
        audio[6800:7300] = 0
        _, start, end = select_clip(audio, 1000)
        self.assertEqual(start, 0)
        self.assertTrue(6800 <= end <= 7300)

    def test_reject_short_silent_and_invalid_ranges(self):
        for audio, start, end in [(np.ones(2999), None, None),
                                  (np.zeros(4000), None, None),
                                  (np.ones(4000), 0, 4100),
                                  (np.ones(4000), 0, None),
                                  (np.full(4000, np.nan), None, None)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                select_clip(audio, 1000, start, end)
