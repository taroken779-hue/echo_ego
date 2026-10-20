"""Reference selection shared by the API and the isolated ASR worker."""
import numpy as np

DESIGN_TRANSCRIPT = "こんにちは。お話できてうれしいです。どうぞよろしくお願いします。"


def select_clip(values, sr, start_ms=None, end_ms=None):
    if values.ndim == 2:
        values = values.mean(axis=1)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("録音に有効な音声がありません")
    duration_ms = len(values) * 1000 / sr
    if (start_ms is None) != (end_ms is None):
        raise ValueError("開始と終了を両方指定してください")
    if start_ms is None:
        # Prefer a pause so the candidate does not end in the middle of a word.
        frame = max(1, int(sr * .02))
        rms = np.array([np.sqrt(np.mean(values[i:i+frame] ** 2)) for i in range(0, len(values), frame)])
        threshold = max(.001, float(rms.max()) * .035)
        voiced = np.flatnonzero(rms > threshold)
        if not len(voiced):
            raise ValueError("録音に声がありません。別の音声を選んでください")
        start_ms = max(0, int(voiced[0] * 20 - 120))
        end_ms = min(int(duration_ms), int(voiced[-1] * 20 + 200))
        if end_ms - start_ms > 10000:
            pauses = [i * 20 for i in range(1, len(rms))
                      if 3000 <= i * 20 - start_ms <= 9800
                      and rms[i-1] <= threshold and rms[i] <= threshold]
            end_ms = min(pauses, key=lambda t: abs(t - start_ms - 7000)) if pauses else start_ms + 10000
        # Include available surrounding silence if the utterance itself is short.
        if end_ms - start_ms < 3000:
            start_ms = max(0, min(start_ms, int(duration_ms) - 3000))
            end_ms = min(int(duration_ms), start_ms + 3000)
    if not 0 <= start_ms < end_ms <= duration_ms + 1 or not 3000 <= end_ms - start_ms <= 10000:
        raise ValueError("録音内の3〜10秒が必要です。短い録音は3秒以上で録り直してください")
    clip = values[int(start_ms * sr / 1000):int(end_ms * sr / 1000)]
    if not len(clip) or np.max(np.abs(clip)) < .001:
        raise ValueError("選択区間に声がありません")
    return clip, int(start_ms), int(end_ms)
