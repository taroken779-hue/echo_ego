async function api(path, options = {}) {
  const r = await fetch(path, options);
  if (!r.ok) { let err; try { err = await r.json(); } catch {} throw Error(typeof err?.detail === 'string' ? err.detail : '入力内容または接続を確認してください'); }
  return r.json();
}
function jsonRequest(method, data) { return {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}; }
function showHistoryError(e) { $('history-notice').hidden = false; $('history-notice-text').textContent = '履歴の保存・削除に失敗しました：' + e.message; $('undo').hidden = true; }
async function loadItemAudio(item) {
  if (!item.blob) {
    const r = await fetch(`/api/history/${item.id}/audio`); if (!r.ok) throw Error('履歴の音声を読み込めません');
    item.blob = await r.blob(); item.url = URL.createObjectURL(item.blob);
  }
  if (!item.buffer && ctx) item.buffer = await ctx.decodeAudioData(await item.blob.arrayBuffer());
}
async function persistItem(item) {
  if (!preferences.history_enabled || !item.blob) return;
  if (item.deleteTask) { await item.deleteTask; item.deleteTask = null; }
  const body = new FormData();
  body.append('metadata', JSON.stringify({id:item.id,text:item.text,voice:item.voice,generatedAt:item.generatedAt,timing:item.timing}));
  body.append('file', item.blob, 'audio.wav');
  try { await api('/api/history', {method:'POST',body}); if (item.deleted) await api('/api/history/' + item.id, {method:'DELETE'}); }
  catch (e) { showHistoryError(e); }
}
function renderQueue() {
  $('queue-list').replaceChildren();
  for (const job of [...(activeJob ? [activeJob] : []), ...prepared, ...queue]) {
    const row = document.createElement('div'); row.className = 'queue-row';
    const label = document.createElement('span'); label.textContent = (job === activeJob ? '生成中：' : '待ち：') + job.payload.text;
    row.append(label);
    if (job !== activeJob) { const b = document.createElement('button'); b.className = 'textbutton'; b.textContent = '取消'; b.onclick = () => { queue = queue.filter(v => v.id !== job.id); prepared = prepared.filter(v => v.id !== job.id); updateStatus(); }; row.append(b); }
    $('queue-list').append(row);
  }
}
function renderVoices() {
  $('voice-list').replaceChildren();
  for (const voice of voiceItems) {
    const row = document.createElement('article'); row.className = 'entry';
    const name = document.createElement('input'); name.value = labels[voice.name] || voice.name; name.maxLength = 48; name.setAttribute('aria-label', voice.name + 'の名前');
    const favorite = document.createElement('input'); favorite.type = 'checkbox'; favorite.checked = voice.favorite;
    const label = document.createElement('label'); label.className = 'check-label'; label.append(favorite, document.createTextNode('お気に入り'));
    const actions = document.createElement('div'); actions.className = 'actions';
    const save = document.createElement('button'); save.textContent = '保存'; save.className = 'secondary';
    save.onclick = async () => { try { await api('/api/voices/' + voice.id, jsonRequest('PATCH',{name:name.value,favorite:favorite.checked})); await refresh(); $('voice-notice').textContent = '声の設定を保存しました。'; } catch(e) { $('voice-notice').textContent = e.message; } };
    const audition = document.createElement('button'); audition.textContent = '試聴'; audition.className = 'secondary';
    audition.onclick = async () => {
      stop(); const token = generation; $('voice-notice').textContent = '試聴用の音声を準備しています…';
      try {
        await audioContext();
        const r = await fetch('/api/voices/' + voice.id + '/audio'); let bytes;
        if (r.status === 404 && voice.kind === 'design') bytes = await apiAudio('/api/speech',{text:'こんにちは。どうぞよろしくお願いします。',voice:voice.id,steps:4,speed:1});
        else { if (!r.ok) { const d = await r.json(); throw Error(d.detail); } bytes = await r.arrayBuffer(); }
        const buffer = await ctx.decodeAudioData(bytes);
        if (token !== generation) return;
        play(buffer); $('voice-notice').textContent = '試聴を開始しました。Escで停止できます。';
      } catch(e) { if (token === generation) $('voice-notice').textContent = e.message; }
    };
    const choose = document.createElement('button'); choose.textContent = 'この声を使う'; choose.className = 'secondary'; choose.onclick = () => { $('voice').value = voice.id; rememberSpeechSettings(); location.hash = 'speak'; };
    actions.append(save, audition, choose);
    if (voice.kind === 'custom') { const remove = document.createElement('button'); remove.textContent = '削除'; remove.className = 'danger-outline'; remove.onclick = async () => { if (!confirm('登録した声と前処理キャッシュを削除します。発話履歴は別に削除してください。')) return; try { await api('/api/voices/' + voice.id, {method:'DELETE'}); await refresh(); $('voice-notice').textContent = '登録した声を削除しました。'; } catch(e) { $('voice-notice').textContent = e.message; } }; actions.append(remove); }
    row.append(name,label,actions); $('voice-list').append(row);
  }
}
function triggerPhrase(index) {
  const phrase = preferences.phrases?.[index]; if (!phrase || !canSpeak()) return;
  $('text').value = phrase.text; $('text').dispatchEvent(new Event('input')); speak(true).catch(e => $('message').textContent = e.message);
}
function renderPhrases() {
  document.querySelector('.phrases').replaceChildren();
  (preferences.phrases || []).forEach((phrase,index) => { const b = document.createElement('button'); b.dataset.text = phrase.text; b.textContent = phrase.label; b.title = 'Alt＋' + (index + 1); b.onclick = () => triggerPhrase(index); document.querySelector('.phrases').append(b); });
}
function editorRow(values, target, reorder = false) {
  const row = document.createElement('div'); row.className = 'editor-row';
  for (const [key, value, placeholder, max] of values) { const input = document.createElement('input'); input.dataset.field = key; input.value = value; input.placeholder = placeholder; input.setAttribute('aria-label',placeholder); input.maxLength = max; row.append(input); }
  if (reorder) { for (const direction of [-1,1]) { const b = document.createElement('button'); b.className = 'textbutton'; b.textContent = direction < 0 ? '↑' : '↓'; b.setAttribute('aria-label', direction < 0 ? '定型句を上へ' : '定型句を下へ'); b.onclick = () => { if (direction < 0 && row.previousElementSibling) target.insertBefore(row, row.previousElementSibling); if (direction > 0 && row.nextElementSibling) target.insertBefore(row.nextElementSibling,row); }; row.append(b); } }
  const remove = document.createElement('button'); remove.className = 'textbutton'; remove.textContent = '削除'; remove.onclick = () => row.remove(); row.append(remove); target.append(row); return row;
}
function addPhrase(phrase = {id:crypto.randomUUID(),label:'',text:''}) {
  if ($('phrase-editor').children.length >= 9) return;
  const row = editorRow([['label',phrase.label,'ボタン名',32],['text',phrase.text,'発話する文章',160]],$('phrase-editor'),true); row.dataset.id = phrase.id;
}
function addReading(reading = {surface:'',reading:''}) {
  if ($('dictionary-editor').children.length >= 100) return;
  editorRow([['surface',reading.surface,'単語',40],['reading',reading.reading,'読み',80]],$('dictionary-editor'));
}
function rowsValue(id) { return [...$(id).children].map(row => { const value = {}; row.querySelectorAll('[data-field]').forEach(input => value[input.dataset.field] = input.value); if(row.dataset.id) value.id = row.dataset.id; return value; }); }
async function rememberSpeechSettings() {
  preferences.voice = $('voice').value; preferences.speed = Number($('speed').value); preferences.steps = Number($('steps').value);
  try { await api('/api/preferences', jsonRequest('PUT',preferences)); } catch(e) { $('message').textContent = '設定を保存できませんでした：' + e.message; }
}
function historyPolicy() { $('history-policy').textContent = preferences.history_enabled ? `音声込みでPC内に保存。最大${preferences.history_count}件・${preferences.history_days}日・${preferences.history_mb}MB。日時は日本時間です。` : '履歴のディスク保存はオフです。このタブ内に最大10件保持し、再読み込みで消えます。日時は日本時間です。'; }
async function saveSettings() {
  const next = {...preferences, volume:Number($('volume').value), output_device:$('output-device').value, history_enabled:$('history-enabled').checked, history_count:Number($('history-limit').value),history_days:Number($('history-days').value),history_mb:Number($('history-mb').value), phrases:rowsValue('phrase-editor'), dictionary:rowsValue('dictionary-editor')};
  try { preferences = await api('/api/preferences',jsonRequest('PUT',next)); renderPhrases(); historyPolicy(); if (gain) gain.gain.value = preferences.volume; if(ctx?.setSinkId) await ctx.setSinkId(preferences.output_device); $('settings-notice').textContent = '設定を保存しました。'; return true; }
  catch(e) { $('settings-notice').textContent = e.message; return false; }
}
let preparing = false;
async function preparePhrases() {
  if (preparing) { preparing = false; return; }
  if (!ready || localBusy || playing || queue.length || prepared.length) { $('cache-notice').textContent = '発話を停止してから準備してください。'; return; }
  if (!await saveSettings()) return; preparing = true; $('phrase-prepare').textContent = '準備を停止'; const token = generation;
  try {
    for (const [index,phrase] of preferences.phrases.entries()) {
      if (!preparing || token !== generation || localBusy || playing || queue.length) break;
      $('cache-notice').textContent = `準備中 ${index + 1}/${preferences.phrases.length}：${phrase.label}`;
      await apiAudio('/api/speech',{text:phrase.text,voice:$('voice').value,steps:Number($('steps').value),speed:Number($('speed').value),use_cache:true});
    }
    $('cache-notice').textContent = '準備を終了しました。生成済みの定型句は即座に再生できます。';
  } catch(e) { $('cache-notice').textContent = e.message; }
  finally { preparing = false; $('phrase-prepare').textContent = '定型句を事前生成'; }
}
async function apiAudio(path,payload) { const r = await fetch(path,jsonRequest('POST',payload)); if(!r.ok) {const err=await r.json(); throw Error(err.detail);} return r.arrayBuffer(); }
let runtimeConfig;
async function loadConfigUI() {
  const info = await api('/api/config'); runtimeConfig = info.saved;
  const labels = {python_path:'Pythonのパス',source_path:'Irodori-TTSソースのパス',model_path:'MFモデルのパス',codec_repo:'Codec（Hugging Face IDまたはweights.pth）',presets_dir:'追加プリセットWAVのフォルダー'};
  for (const [key,label] of Object.entries(labels)) { const l = document.createElement('label'); l.textContent = label; const input = document.createElement('input'); input.id = 'config-' + key; input.value = runtimeConfig[key]; l.append(input); $('runtime-fields').append(l); }
  $('runtime-device').value = runtimeConfig.device; $('runtime-preload').checked = runtimeConfig.preload; $('runtime-offline').checked = runtimeConfig.offline;
  $('diagnostics').textContent = `GPU：${info.diagnostics.gpu || '未検出'} / VRAM ${info.diagnostics.vram_gb}GB / モデル：${info.diagnostics.model_exists ? 'あり' : 'なし'} / 保存先：${info.diagnostics.data_dir}`;
}
async function loadManual(name) { try { const data=await api('/api/manual/'+name); $('manual-content').innerHTML = data.html; } catch(e) { $('manual-content').textContent=e.message; } }
let recorder, stream, recordChunks = [], recordTimer, recordStart, recordBlob, recordURL, micContext, meterTimer;
function releaseMic() { clearInterval(recordTimer); clearInterval(meterTimer); stream?.getTracks().forEach(t=>t.stop()); stream=null; micContext?.close(); micContext=null; $('record-level').value=0; $('record-start').disabled=false; $('record-end').disabled=true; $('record-cancel').disabled=true; }
async function microphoneList() { const access=await navigator.mediaDevices.getUserMedia({audio:true}); access.getTracks().forEach(t=>t.stop()); const devices=await navigator.mediaDevices.enumerateDevices(); $('microphone').replaceChildren(new Option('標準のマイク','')); devices.filter(d=>d.kind==='audioinput').forEach(d=>$('microphone').append(new Option(d.label,d.deviceId))); }
function encodeWav(buffer) {
  const count=Math.min(buffer.length,buffer.sampleRate*30), array=new ArrayBuffer(44+count*2), view=new DataView(array);
  const str=(offset,value)=>[...value].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
  str(0,'RIFF');view.setUint32(4,36+count*2,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,buffer.sampleRate,true);view.setUint32(28,buffer.sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,count*2,true);
  const channels=Array.from({length:buffer.numberOfChannels},(_,i)=>buffer.getChannelData(i));
  for(let i=0;i<count;i++){const value=Math.max(-1,Math.min(1,channels.reduce((a,c)=>a+c[i],0)/channels.length));view.setInt16(44+i*2,value<0?value*32768:value*32767,true);}return new Blob([array],{type:'audio/wav'});
}
async function startRecording() {
  $('record-start').disabled=true;
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:$('microphone').value ? {deviceId:{exact:$('microphone').value}} : true});
    recordChunks=[];recordStart=performance.now();recordBlob=null;$('record-save').hidden=true;$('record-preview').hidden=true;
    recorder=new MediaRecorder(stream);recorder.ondataavailable=e=>{if(e.data.size)recordChunks.push(e.data);};
    recorder.onstop=async()=>{const cancelled=recorder.cancelled;releaseMic();if(cancelled){$('record-status').textContent='録音を取り消しました。';return;}try{await audioContext();const buffer=await ctx.decodeAudioData(await new Blob(recordChunks).arrayBuffer());recordBlob=encodeWav(buffer);if(recordURL)URL.revokeObjectURL(recordURL);recordURL=URL.createObjectURL(recordBlob);$('record-preview').src=recordURL;$('record-preview').hidden=false;$('record-save').hidden=false;$('record-status').textContent='内容を試聴してから登録してください。';}catch(e){$('record-status').textContent='録音を読み込めません：'+e.message;}};
    micContext=new AudioContext();const analyser=micContext.createAnalyser();analyser.fftSize=256;micContext.createMediaStreamSource(stream).connect(analyser);const levels=new Float32Array(analyser.fftSize);meterTimer=setInterval(()=>{analyser.getFloatTimeDomainData(levels);$('record-level').value=Math.min(1,Math.sqrt(levels.reduce((sum,v)=>sum+v*v,0)/levels.length)*5);},100);
    recorder.start();$('record-start').disabled=true;$('record-end').disabled=false;$('record-cancel').disabled=false;
    recordTimer=setInterval(()=>{const seconds=(performance.now()-recordStart)/1000;$('record-status').textContent=`録音中 ${seconds.toFixed(1)} / 30秒`;if(seconds>=30 && recorder.state==='recording')recorder.stop();},100);
  }catch(e){releaseMic();$('record-status').textContent='マイクを利用できません：'+e.message;}
}
function reportTo(id,action) { return async()=>{try{await action();}catch(e){$(id).textContent=e.message;}}; }
$('record-start').onclick=startRecording;
$('record-end').onclick=()=>{if(recorder?.state==='recording')recorder.stop();};
$('record-cancel').onclick=()=>{if(recorder?.state==='recording'){recorder.cancelled=true;recorder.stop();}};
$('mic-devices').onclick=reportTo('record-status',microphoneList);
$('record-save').onclick=reportTo('record-status',async()=>{if(!recordBlob)return;const body=new FormData();body.append('file',recordBlob,'recording.wav');const voice=await api('/api/voices',{method:'POST',body});await refresh();$('voice').value=voice.id;await rememberSpeechSettings();$('record-status').textContent='声を登録しました。';$('record-save').hidden=true;});
$('save-settings').onclick=saveSettings;$('phrase-add').onclick=()=>addPhrase();$('dictionary-add').onclick=()=>addReading();$('phrase-prepare').onclick=preparePhrases;
$('cache-clear').onclick=reportTo('cache-notice',async()=>{await api('/api/cache',{method:'DELETE'});$('cache-notice').textContent='定型句の音声を削除しました。';});
['voice','speed','steps'].forEach(id=>$(id).addEventListener('change',rememberSpeechSettings));
$('volume').oninput=()=>{if(gain)gain.gain.value=Number($('volume').value);};
$('output-devices').onclick=reportTo('output-notice',async()=>{await audioContext();if(!ctx.setSinkId){$('output-notice').textContent='このブラウザーでは出力先選択に対応していません。OSのサウンド設定を使ってください。';return;}let access;if(navigator.mediaDevices.selectAudioOutput){await navigator.mediaDevices.selectAudioOutput();}else{access=await navigator.mediaDevices.getUserMedia({audio:true});access.getTracks().forEach(t=>t.stop());}const devices=await navigator.mediaDevices.enumerateDevices();$('output-device').replaceChildren(new Option('標準の出力先',''));devices.filter(d=>d.kind==='audiooutput').forEach(d=>$('output-device').append(new Option(d.label,d.deviceId)));});
$('test-output').onclick=reportTo('output-notice',async()=>{await audioContext();if(ctx.setSinkId)await ctx.setSinkId($('output-device').value);const tone=ctx.createOscillator();tone.frequency.value=440;const level=ctx.createGain();level.gain.value=0.08;tone.connect(level);level.connect(gain);tone.start();tone.stop(ctx.currentTime+.3);});
$('save-runtime').onclick=reportTo('runtime-notice',async()=>{const next={...runtimeConfig};for(const key of ['python_path','source_path','model_path','codec_repo','presets_dir'])next[key]=$('config-'+key).value;next.device=$('runtime-device').value;next.precision=next.device==='cpu'?'fp32':'bf16';next.codec_precision='fp32';next.preload=$('runtime-preload').checked;next.offline=$('runtime-offline').checked;const result=await api('/api/config',jsonRequest('PUT',next));runtimeConfig=next;$('runtime-notice').textContent=result.message;});
$('load-runtime').onclick=reportTo('runtime-notice',async()=>{await api('/api/runtime/load',{method:'POST'});await refresh();});
$('shutdown').onclick=reportTo('runtime-notice',async()=>{stop();await api('/api/shutdown',{method:'POST'});$('runtime-notice').textContent='終了しました。start.batで再起動できます。';});
document.querySelectorAll('[data-manual]').forEach(button=>button.onclick=()=>loadManual(button.dataset.manual));
window.addEventListener('beforeunload',()=>{stream?.getTracks().forEach(track=>track.stop());});
async function initializeUI() {
  try { preferences=await api('/api/preferences');$('speed').value=String(preferences.speed);$('steps').value=String(preferences.steps);$('volume').value=preferences.volume;$('history-enabled').checked=preferences.history_enabled;$('history-limit').value=preferences.history_count;$('history-days').value=preferences.history_days;$('history-mb').value=preferences.history_mb;if(preferences.output_device)$('output-device').append(new Option('保存した出力先',preferences.output_device));$('output-device').value=preferences.output_device;
    preferences.phrases.forEach(addPhrase);preferences.dictionary.forEach(addReading);renderPhrases();historyPolicy();
    if(preferences.history_enabled)history.push(...await api('/api/history'));
    await loadConfigUI();await loadManual('user');
  }catch(e){$('settings-notice').textContent=e.message;}
  showView();renderHistory();await refresh();setInterval(refresh,2000);
}
initializeUI();
