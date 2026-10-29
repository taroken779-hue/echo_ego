let streamPlayback = null, pcmModule = null;

async function* audioFrames(response) {
  const reader = response.body.getReader();
  let bytes = new Uint8Array(0);
  async function take(count) {
    while (bytes.length < count) {
      const value = await reader.read();
      if (value.done) throw Error('音声の接続が途中で切れました');
      const joined = new Uint8Array(bytes.length + value.value.length);
      joined.set(bytes); joined.set(value.value, bytes.length); bytes = joined;
    }
    const result = bytes.slice(0, count); bytes = bytes.slice(count); return result;
  }
  try {
    while (true) {
      const prefix = await take(4), size = new DataView(prefix.buffer).getUint32(0);
      if (size < 1 || size > 8192) throw Error('音声ヘッダーが不正です');
      const meta = JSON.parse(new TextDecoder().decode(await take(size)));
      if (!Number.isInteger(meta.bytes) || meta.bytes < 0 || meta.bytes > 192000) throw Error('音声データ長が不正です');
      const pcm = await take(meta.bytes);
      yield {meta, pcm};
      if (['end','complete','error'].includes(meta.type)) return;
    }
  } finally { await reader.cancel().catch(()=>{}); reader.releaseLock(); }
}

async function consumeSpeechStream(job) {
  const {token, payload, start} = job;
  // Preserve utterance ordering across complete-WAV and streaming models.
  while (playing || prepared.length) {
    if (token !== generation) throw Error('取消済み');
    pumpPlayback(); await new Promise(resolve=>setTimeout(resolve,20));
  }
  if (token !== generation) throw Error('取消済み');
  pcmModule ||= ctx.audioWorklet.addModule('/static/pcm-worklet.js?v=20261030-qwen1');
  await pcmModule;
  if (token !== generation) throw Error('取消済み');
  const abort = new AbortController(); controller = abort;
  const response = await fetch('/api/v2/speech-jobs/'+job.serverId+'/stream?client_id='+encodeURIComponent(payload.client_id),{signal:abort.signal});
  if (!response.ok) throw Error('逐次音声を取得できません');
  let player = null, node = null, ended = false, next = 0, received = null, startedMs = null, sampleCount = 0, result;
  try {
    for await (const {meta,pcm} of audioFrames(response)) {
      if (token !== generation || job.cancelled) throw Error('取消済み');
      if (meta.type === 'error') throw Error(meta.message || '音声生成に失敗しました');
      if (meta.type === 'complete') return false; // An already-complete phrase cache.
      if (meta.type === 'end') { result = meta.job; ended = true; break; }
      if (meta.sequence !== next++) throw Error('音声の順序が不正です');
      if (meta.type === 'format') {
        if (node || meta.sample_rate !== 24000 || meta.channels !== 1 || meta.encoding !== 'pcm_s16le') throw Error('音声形式が不正です');
        node = new AudioWorkletNode(ctx,'echo-pcm',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[1],processorOptions:{rate:meta.sample_rate}});
        node.connect(gain);
        let finish;
        player = {done:new Promise(resolve=>finish=resolve),stop:()=>{ node.port.postMessage({type:'stop'}); node.disconnect(); finish(); }};
        streamPlayback = player; playing = true; job.state = 'streaming'; updateStatus();
        node.port.onmessage = ({data}) => {
          if (token !== generation || streamPlayback !== player) return;
          if (data.type === 'started') {
            startedMs = performance.now()-start;
            $('total').innerHTML = seconds(startedMs)+'<small> 秒</small>';
            $('received').innerHTML = seconds(received)+'<small> 秒</small>';
            $('message').textContent = '音声を受信しながら再生しています。';
          }
          if (data.type === 'drained' || data.type === 'error') {
            $('message').textContent = data.type === 'error' ? '音声の再生に失敗しました。' : '再生が完了しました。';
            player.stop(); streamPlayback = null; playing = false; playingItemId = null; updateStatus(); pumpPlayback();
          }
        };
      } else if (meta.type === 'audio') {
        if (!node || !pcm.length || pcm.length % 2) throw Error('音声チャンクが不正です');
        sampleCount += pcm.length/2;
        if (sampleCount > 24000*30) throw Error('音声が30秒を超えました');
        received ??= performance.now()-start;
        node.port.postMessage({type:'pcm',buffer:pcm.buffer},[pcm.buffer]);
      } else throw Error('未対応の音声イベントです');
    }
    if (!ended || !player || !sampleCount || result?.state !== 'ready') throw Error('音声が完了しませんでした');
    node.port.postMessage({type:'end'});
    const audio = await fetch('/api/v2/speech-jobs/'+job.serverId+'/audio',{signal:abort.signal});
    if (!audio.ok) throw Error('完成音声を取得できません');
    const bytes = await audio.arrayBuffer(), buffer = await ctx.decodeAudioData(bytes.slice(0));
    if (token !== generation) throw Error('取消済み');
    const s = result.snapshot;
    const metadata = {speech_text:s.speech_text,translated_text:s.translated_text,engine:s.engine,reading_revision:s.reading_revision,model_identity:s.model,voice_revision:s.voice_revision,translation_identity:s.translation_identity,generation_settings:s.settings};
    $('translated-text').hidden = !s.translated_text; $('translated-text').textContent = s.translated_text || '';
    $('silence').innerHTML = seconds(Number(audio.headers.get('X-First-Signal-Ms')))+'<small> 秒</small>';
    if (!payload.audition) {
      const id = addHistory(payload.text,buffer,new Blob([bytes],{type:'audio/wav'}),{total:startedMs ?? performance.now()-start,received,synthesis:Number(audio.headers.get('X-Synthesis-Ms'))},job.voiceName,audio.headers.get('X-Generated-At'),metadata);
      if (streamPlayback === player) playingItemId = id;
    }
    await player.done;
    return true;
  } catch (error) {
    player?.stop();
    if (streamPlayback === player) { streamPlayback=null; playing=false; playingItemId=null; }
    await fetch('/api/v2/speech-jobs/'+job.serverId,{method:'DELETE'}).catch(()=>{});
    throw error;
  } finally { if (controller===abort) controller=null; }
}
