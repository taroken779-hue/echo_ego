"""Validated complete PCM16 mono WAV output for all backends."""
import base64
from datetime import datetime, timezone
import io
import time


def audio_result(samples, sr, started, reference_ms=0):
    import numpy as np
    import soundfile as sf
    values = np.asarray(samples, dtype=np.float32).squeeze()
    if not isinstance(sr, int) or sr <= 0 or values.ndim != 1 or not len(values) or not np.isfinite(values).all() or len(values) / sr > 30:
        raise ValueError("合成音声の形式または長さが不正です（30秒以内）")
    signal = np.flatnonzero(np.abs(values) > max(.001, float(np.max(np.abs(values))) * .02))
    if not len(signal):
        raise ValueError("合成音声に声がありません")
    out = io.BytesIO()
    sf.write(out, values, sr, format="WAV", subtype="PCM_16")
    return {"audio": base64.b64encode(out.getvalue()).decode(), "sample_rate": sr, "channels": 1, "headers": {
        "X-Synthesis-Ms": f"{(time.perf_counter()-started)*1000:.1f}", "X-Reference-Ms": f"{reference_ms:.1f}",
        "X-First-Signal-Ms": f"{signal[0]/sr*1000:.1f}", "X-Audio-Duration-Ms": f"{len(values)/sr*1000:.1f}",
        "X-Sample-Rate": str(sr), "X-Channels": "1", "X-Generated-At": datetime.now(timezone.utc).isoformat(), "Cache-Control": "no-store"}}
