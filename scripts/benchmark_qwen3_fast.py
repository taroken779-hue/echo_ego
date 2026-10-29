"""Measure actual PCM chunk arrivals using the isolated CUDA Graph runtime."""
import importlib.metadata
import json
from pathlib import Path
import time
from benchmark_qwen3 import ROOT, OUT, TEXTS, REFERENCE_TEXT


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from faster_qwen3_tts import FasterQwen3TTS
    torch.set_num_threads(4)
    reference = OUT/'data/design-voices/reference.wav'
    start = time.perf_counter()
    model = FasterQwen3TTS.from_pretrained(str(ROOT/'runtime/qwen3-tts/model-0.6b'),
        device='cuda', dtype=torch.bfloat16, attn_implementation='sdpa', max_seq_len=1024)
    torch.cuda.synchronize()
    report = {'load_ms':(time.perf_counter()-start)*1000, 'rows':[],
        'packages':{p:importlib.metadata.version(p) for p in ['faster-qwen3-tts','qwen-tts-hf','transformers','torch']},
        'sampling':{'temperature':0.9,'top_k':50,'top_p':1.0,'repetition_penalty':1.05},
        'reference_sha256':__import__('hashlib').sha256(reference.read_bytes()).hexdigest()}
    start = time.perf_counter()
    prompt = model.model.create_voice_clone_prompt(ref_audio=str(reference), ref_text=REFERENCE_TEXT, x_vector_only_mode=False)
    torch.cuda.synchronize()
    report['prepare_ms'] = (time.perf_counter()-start)*1000
    print('loaded', report, flush=True)
    for rep, index in [(-1,0)]+[(r,t) for r in range(3) for t in range(3)]:
        for size in [4,8]:
            torch.manual_seed(20261029+max(rep,0))
            torch.cuda.synchronize()
            start=time.perf_counter()
            chunks=[]
            arrivals=[]
            for audio, rate, timing in model.generate_voice_clone_streaming(text=TEXTS[index],language='Japanese',
                    voice_clone_prompt=prompt, ref_text=REFERENCE_TEXT, chunk_size=size, max_new_tokens=350,
                    append_silence=False, non_streaming_mode=False):
                torch.cuda.synchronize()
                arrivals.append({'ms':(time.perf_counter()-start)*1000,'samples':len(audio),'timing':timing})
                chunks.append(np.asarray(audio).copy())
            total=(time.perf_counter()-start)*1000
            assert chunks and all(np.isfinite(a).all() for a in chunks)
            wave=np.concatenate(chunks)
            signal=np.flatnonzero(np.abs(wave)>max(.001,float(np.max(np.abs(wave)))*.02))
            assert len(signal)
            elapsed_audio=0.
            required_start=0.
            for item in arrivals:
                required_start=max(required_start,item['ms']-elapsed_audio)
                elapsed_audio+=item['samples']/rate*1000
            row={'repeat':rep,'text_index':index,'text':TEXTS[index],'chunk_size':size,
                 'first_pcm_ms':arrivals[0]['ms'],'complete_ms':total,'seconds':len(wave)/rate,
                 'rtf':total/1000/(len(wave)/rate),'first_signal_ms':float(signal[0]/rate*1000),
                 'extra_buffer_needed_ms':max(0,required_start-arrivals[0]['ms']),
                 'chunks':arrivals,'file':f'qwen-fast-{size}-{rep}-{index}.wav'}
            sf.write(OUT/row['file'],wave,rate)
            report['rows'].append(row)
            report['peak_allocated_gb']=torch.cuda.max_memory_allocated()/1024**3
            (OUT/'qwen-fast.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k!='chunks'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
