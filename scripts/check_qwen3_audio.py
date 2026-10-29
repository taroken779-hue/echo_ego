"""Local ASR and waveform checks for the isolated benchmark; not listening QA."""
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/qwen3-evaluation'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'


def main():
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    from transformers import pipeline
    torch.set_num_threads(4)
    pipe = pipeline('automatic-speech-recognition', model=str(ROOT/'runtime/omnivoice/asr'), device='cpu', dtype=torch.float32)
    rows = json.loads((OUT/'asr.json').read_text(encoding='utf-8')) if (OUT/'asr.json').exists() else []
    files = [OUT/'data/design-voices/reference.wav']
    for label in ['qwen', 'omnivoice', 'qwen-fast']:
        if not (OUT/(label+'.json')).exists():
            continue
        report = json.loads((OUT/(label+'.json')).read_text(encoding='utf-8'))
        files += [OUT/r['file'] for r in report['rows'] if r['repeat'] == 0 or
                  (label == 'qwen-fast' and r['repeat'] > 0 and r['text_index'] == 1 and r['chunk_size'] == 4)]
    for path in files:
        if any(row['file'] == path.name for row in rows):
            continue
        values, rate = sf.read(path, dtype='float32')
        started = time.perf_counter()
        audio = torchaudio.functional.resample(torch.from_numpy(values), rate, 16000).numpy()
        result = pipe({'array':audio, 'sampling_rate':16000}, generate_kwargs={'language':'ja','task':'transcribe'})
        row = {'file':path.name, 'text':result['text'], 'seconds':len(values)/rate,
               'finite':bool(np.isfinite(values).all()), 'peak':float(np.max(np.abs(values))),
               'asr_seconds':time.perf_counter()-started}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        (OUT/'asr.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
