"""Isolated local comparison. Does not change application configuration or history.

Run with the corresponding model's venv. Qwen prefix probe is experimental,
not a production streaming implementation or a browser latency measurement.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / '.runtime/qwen3-evaluation'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['ECHO_EGO_DATA_DIR'] = str(OUT / 'data')

TEXTS = ['にほんばしで待っています。', '午後三時に駅の東口で会いましょう。',
         'こんにちは。今日は予定を確認します。午後三時に駅の東口で待ち合わせて、一緒に会場へ向かいましょう。']
REFERENCE_TEXT = 'こんにちは。お話できてうれしいです。どうぞよろしくお願いします。'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', choices=['qwen', 'omnivoice'], required=True)
    ap.add_argument('--repeats', type=int, default=3)
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--short-only', action='store_true')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--tag', default='')
    ap.add_argument('--no-hooks', action='store_true')
    ap.add_argument('--reference', type=Path, default=ROOT / '.runtime/backend-validation/data/design-voices/calm_male.wav')
    ap.add_argument('--reference-text', default=REFERENCE_TEXT)
    args = ap.parse_args()
    if args.probe and args.no_hooks:
        ap.error('--probe requires hooks')
    import numpy as np
    import soundfile as sf
    import torch
    torch.set_num_threads(args.threads)
    OUT.mkdir(parents=True, exist_ok=True)
    reference = OUT / 'data/design-voices/reference.wav'
    reference.parent.mkdir(parents=True, exist_ok=True)
    original = args.reference.resolve()
    if not original.is_file():
        ap.error('Supply --reference and --reference-text for a complete 3-10 second reference recording')
    if reference.exists() and reference.read_bytes() != original.read_bytes():
        ap.error('Existing evaluation reference differs; use a separate evaluation directory')
    if not reference.exists():
        reference.write_bytes(original.read_bytes())
    values, sr = sf.read(reference, dtype='float32')
    assert values.ndim == 1 and 3 <= len(values)/sr <= 10
    report = {'model': args.model, 'probe': args.probe, 'threads': args.threads, 'hooks': not args.no_hooks, 'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
              'reference_seconds': len(values)/sr, 'reference_text': args.reference_text,
              'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__, 'rows': []}
    label = args.model + ('-probe' if args.probe else '') + args.tag
    dest = OUT / (label + '.json')
    started = time.perf_counter()
    if args.model == 'qwen':
        from qwen_tts import Qwen3TTSModel
        model = Qwen3TTSModel.from_pretrained(str(ROOT / 'runtime/qwen3-tts/model-0.6b'),
                    device_map='cuda:0', dtype=torch.bfloat16, attn_implementation='sdpa')
        torch.cuda.synchronize()
        report['load_ms'] = (time.perf_counter()-started)*1000
        started = time.perf_counter()
        prompt = model.create_voice_clone_prompt(ref_audio=(values, sr), ref_text=args.reference_text, x_vector_only_mode=False)
        torch.cuda.synchronize()
        report['prepare_ms'] = (time.perf_counter()-started)*1000
        report['packages'] = {p: importlib.metadata.version(p) for p in ['qwen-tts','transformers','accelerate']}
        modes = [0]
    else:
        from configuration import load_config
        from speech.backends.omnivoice import OmniVoiceBackend
        config = load_config()
        model = OmniVoiceBackend('omnivoice', config.models['omnivoice'], config)
        model.load()
        torch.cuda.synchronize()
        report['load_ms'] = (time.perf_counter()-started)*1000
        ref = dict(reference_path=str(reference), reference_transcript=args.reference_text, reference_language='ja',
                   clip_start_ms=0, clip_end_ms=round(len(values)/sr*1000))
        model.prepare(ref)
        modes = [16,32]
    print('loaded', report, flush=True)
    # Cold first generation is reported separately; then identical texts/repetitions.
    cases = [(-1, 0)] + [(r, t) for r in range(args.repeats) for t in range(1 if args.short_only else len(TEXTS))]
    for rep, index in cases:
        for step in modes:
            torch.manual_seed(20261029 + max(rep,0))
            torch.cuda.synchronize()
            start = time.perf_counter()
            first_codes = []
            prefix = {}
            handle = None
            if args.model == 'qwen':
                def hook(module, inputs, output):
                    codes = output.hidden_states[-1]
                    if codes is None:
                        return
                    if int(codes[0,0]) == model.model.config.talker_config.codec_eos_token_id:
                        return
                    first_codes.append(codes.detach())
                    if len(first_codes) == 1:
                        torch.cuda.synchronize()
                        prefix['first_code_ms'] = (time.perf_counter()-start)*1000
                    if args.probe and len(first_codes) == 4:
                        ref_codes = prompt[0].ref_code
                        generated = torch.cat(first_codes, dim=0)
                        combined = torch.cat([ref_codes.to(generated.device), generated], dim=0)
                        waves, rate = model.model.speech_tokenizer.decode([{'audio_codes': combined}])
                        cut = int(ref_codes.shape[0]/combined.shape[0]*len(waves[0]))
                        wave = waves[0][cut:]
                        torch.cuda.synchronize()
                        prefix.update(first_prefix_pcm_ms=(time.perf_counter()-start)*1000,
                                      prefix_seconds=len(wave)/rate)
                        # Retain prefix for boundary/quality inspection; not played automatically.
                        sf.write(OUT / f'{label}-prefix-{rep}-{index}.wav', wave, rate)
                if not args.no_hooks:
                    handle = model.model.talker.register_forward_hook(hook)
                try:
                    wavs, rate = model.generate_voice_clone(text=TEXTS[index], language='Japanese',
                        voice_clone_prompt=prompt, non_streaming_mode=False, max_new_tokens=350)
                    wave = wavs[0]
                finally:
                    if handle is not None:
                        handle.remove()
            else:
                import base64, io
                result = model.synthesize({**ref, 'text':TEXTS[index], 'language':'ja', 'settings':{'num_step':step}, 'speed':1.})
                wave, rate = sf.read(io.BytesIO(base64.b64decode(result['audio'])), dtype='float32')
            torch.cuda.synchronize()
            elapsed = (time.perf_counter()-start)*1000
            wave = np.asarray(wave)
            assert np.isfinite(wave).all() and np.max(np.abs(wave)) > .001
            signal = np.flatnonzero(np.abs(wave) > max(.001, float(np.max(np.abs(wave)))*.02))
            row = dict(repeat=rep, text_index=index, text=TEXTS[index], steps=step, complete_ms=elapsed,
                       seconds=len(wave)/rate, sample_rate=rate, first_signal_ms=float(signal[0]/rate*1000),
                       rtf=elapsed/1000/(len(wave)/rate), frames=len(first_codes), **prefix)
            row['possible_token_limit'] = len(first_codes) >= 349
            filename = f'{label}-{step}-{rep}-{index}.wav'
            sf.write(OUT / filename, wave, rate)
            row['file'] = filename
            report['rows'].append(row)
            report['peak_allocated_gb'] = torch.cuda.max_memory_allocated()/1024**3
            dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
