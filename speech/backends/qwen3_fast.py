"""Pinned Qwen3-TTS CUDA Graph backend. Inference imports stay in the worker."""
import hashlib
import json
from pathlib import Path
import time
from configuration import data_dir
from speech.backends.base import Backend, ROOT
from speech.audio import audio_result


class Qwen3FastBackend(Backend):
    capabilities = {
        'version':2, 'label':'Qwen3-TTS（低遅延）', 'languages':['ja','en'], 'stream':True,
        'repositories':['Qwen/Qwen3-TTS-12Hz-0.6B-Base'],
        'reference':{'required':True,'transcript_required':True,'min_seconds':3,'max_seconds':10},
        'voice_design':False, 'speed':None,
        'settings':{'chunk_size':{'type':'integer','enum':[4,8],'default':4,'label':'音声チャンク（4:応答優先 / 8:効率優先）'}}}

    def __init__(self,*args):
        super().__init__(*args)
        self.model = None
        self.prompts = {}

    def load(self):
        import torch
        if self.config.device != 'cuda':
            raise ValueError('Qwen3低遅延版にはCUDA GPUが必要です')
        torch.set_num_threads(4)
        if self.model is None:
            from importlib.metadata import version
            expected = {'faster-qwen3-tts':'0.5.4','qwen-tts-hf':'0.1.1.post1','transformers':'5.15.1'}
            if any(version(name) != wanted for name,wanted in expected.items()):
                raise ValueError('Qwen3の依存バージョンが異なります。専用セットアップを実行してください')
            from faster_qwen3_tts import FasterQwen3TTS
            model = FasterQwen3TTS.from_pretrained(str(ROOT/self.config.model_path), device='cuda',
                dtype=getattr(torch,self.config.precision), attn_implementation='sdpa', max_seq_len=2048)
            model.warmup()
            self.model = model
        return {'hardware':{'cuda':True,'gpu':torch.cuda.get_device_name(0)}}

    def prepare(self,p):
        self.validate(p,p.get('reference_language','ja'),{},1.)
        self.load()
        import soundfile as sf
        import numpy as np
        path = Path(p['reference_path']).resolve()
        allowed = [ROOT/'voices', data_dir()/'design-voices', ROOT/self.runtime.presets_dir]
        if not any(path.is_relative_to(folder.resolve()) for folder in allowed):
            raise ValueError('参照音声の場所が無効です')
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if p.get('wav_sha256') and p['wav_sha256'] != digest:
            raise ValueError('参照音声が変更されました')
        key = hashlib.sha256(content+json.dumps([p['reference_transcript'],p['clip_start_ms'],p['clip_end_ms']],ensure_ascii=False).encode()).hexdigest()
        if key not in self.prompts:
            values,sr = sf.read(path,dtype='float32',always_2d=True)
            start,end = p['clip_start_ms'],p['clip_end_ms']
            if start < 0 or end > len(values)*1000/sr+1:
                raise ValueError('参照区間が範囲外です')
            values = values[int(start*sr/1000):int(end*sr/1000)].mean(axis=1)
            if not 3 <= len(values)/sr <= 10 or not np.isfinite(values).all() or np.max(np.abs(values)) < .001:
                raise ValueError('声を含む3〜10秒の参照区間が必要です')
            prompt = self.model.model.create_voice_clone_prompt(ref_audio=(values,sr),ref_text=p['reference_transcript'],x_vector_only_mode=False)
            if len(self.prompts) >= 8:
                self.prompts.pop(next(iter(self.prompts)))
            self.prompts[key] = prompt
        return {'key':key,'wav_sha256':digest}

    def synthesize_stream(self,p):
        import numpy as np
        settings = self.validate(p,p['language'],p['settings'],p['speed'])
        ref = self.prepare(p)
        count = 0
        yield {'type':'format','sample_rate':24000,'channels':1,'encoding':'pcm_s16le'}, b''
        for audio,sr,timing in self.model.generate_voice_clone_streaming(text=p['text'],
                language={'ja':'Japanese','en':'English'}[p['language']], voice_clone_prompt=self.prompts[ref['key']],
                ref_text=p['reference_transcript'],chunk_size=settings['chunk_size'],max_new_tokens=375,
                append_silence=False,non_streaming_mode=False):
            values = np.asarray(audio,dtype=np.float32).reshape(-1)
            count += len(values)
            if sr != 24000 or not np.isfinite(values).all() or count > sr*30:
                raise ValueError('音声の形式または長さが不正です（30秒以内）')
            if timing.get('total_steps_so_far',0) >= 375:
                raise ValueError('発話が長すぎます。短く分けてください')
            if len(values):
                yield {'type':'audio'}, (np.clip(values,-1,1)*32767).astype('<i2').tobytes()

    def synthesize(self,p):
        import numpy as np
        start = time.perf_counter()
        chunks = [pcm for meta,pcm in self.synthesize_stream(p) if meta['type']=='audio']
        return audio_result(np.frombuffer(b''.join(chunks),dtype='<i2').astype(np.float32)/32768,24000,start)
