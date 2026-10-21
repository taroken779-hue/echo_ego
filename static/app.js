const $ = id => document.getElementById(id);
let ctx, source, controller;
let generation = 0, localBusy = false, remoteBusy = false;
let ready = false, composing = false, playing = false, playingItemId = null;
let serverMessage = '接続しています…', phase = 'loading', deletedItems = [];
let preferences = {}, voiceItems = [], queue = [], prepared = [], synthesizing = false, activeJob = null, gain;
const history = [];
let clientId = sessionStorage.echoClient || (sessionStorage.echoClient = crypto.randomUUID());
let submissionChain = Promise.resolve();
let engineStates = {}, operationError = '', omniReferenceReady = false;
function engineName(engine) { return engineStates[engine]?.label || engine || '音声モデル'; }
function jobProgress(job) {
  const name = engineName(job.payload.engine);
  return ({queued:'発話待ち', translating:'英語に翻訳中', waiting_engine:`${name}を準備中 · エンジンの切り替え・モデルの読み込みを待っています`, synthesizing:`${name}で音声を生成中`})[job.state] || `${name}への発話を受け付けています`;
}
function selectedEngine() { return preferences.model_id || ''; }
function currentCapabilities() { return engineStates[selectedEngine()] || {}; }
const labels = {age_middle_male:'男性・落ち着いた声',age_middle_female:'女性・落ち着いた声',age_young_male:'男性・若い声',age_young_female:'女性・若い声',age_senior_male:'男性・年配の声',age_senior_female:'女性・年配の声',age_child_male:'男の子の声',age_child_female:'女の子の声',narrator:'ナレーター'};
const dateFormat = new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'});
function canSpeak() { return ready && Boolean($('voice').value) && omniReferenceReady && queue.length + prepared.length < 8; }
function seconds(ms) { return (ms / 1000).toFixed(2); }
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '/static/icons.svg#' + name); svg.append(use);
  return svg;
}
function updateStatus() {
  const loadingEngine = Object.keys(engineStates).find(key => engineStates[key].phase === 'loading');
  const progress = activeJob ? jobProgress(activeJob) : '';
  const loadingMessage = loadingEngine ? `${engineName(loadingEngine)}を準備中 · モデルを読み込んでいます` : '';
  const message = operationError || (phase === 'error' ? serverMessage : '') || (playing ? `再生中${progress ? ' · ' + progress : ''}` : progress || loadingMessage || (remoteBusy ? '音声の処理中' : serverMessage));
  $('status').textContent = message + (queue.length + prepared.length ? ` · 待ち ${queue.length + prepared.length}件` : '');
  $('status').dataset.state = operationError || phase === 'error' ? 'error' : localBusy || playing || loadingEngine || remoteBusy ? 'busy' : 'normal';
  $('speak').disabled = !canSpeak();
  $('stop').disabled = !localBusy && !remoteBusy && !playing && !queue.length && !prepared.length;
  if ($('queue-list')) renderQueue();
  document.querySelectorAll('[data-text]').forEach(b => b.disabled = !canSpeak());
}
function showView() {
  const view = ['speak','history','voices','settings','guide'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'speak';
  for (const name of ['speak','history','voices','settings','guide']) {
    $(name + '-view').hidden = name !== view;
    $('nav-' + name).removeAttribute('aria-current');
  }
  $('nav-' + view).setAttribute('aria-current', 'page');
  if (view === 'speak') $('text').focus();
  document.title = 'Echo Ego — ' + {speak:'発話',history:'履歴',voices:'声の管理',settings:'設定',guide:'マニュアル'}[view];
}
async function refresh() {
  try {
    const r = await fetch('/api/status');
    if (!r.ok) throw Error('接続できません');
    const s = await r.json();
    const engines = await (await fetch('/api/v2/engines')).json();
    engineStates = engines; renderModelControls();
    const selected = engines[selectedEngine()], name = engineName(selectedEngine());
    ready = Boolean(selected?.installed) && Boolean(selected?.languages?.includes($('speech-mode').value === 'ja_to_en' ? 'en' : 'ja')); remoteBusy = s.busy; phase = selected?.phase || 'idle';
    serverMessage = !ready ? `${name}は未導入です` : phase === 'error' ? `${name}の準備に失敗しました。環境設定を確認してください` : phase === 'loading' ? `${name}を準備中 · モデルを読み込んでいます` : phase === 'ready' ? `${name}のモデル準備完了 · ${selected?.reference?.required ? '発話には声の参照設定も必要です' : '発話できます'}` : `${name}を選択中 · 次の発話時にエンジンを切り替え・準備します`;
    $('model').textContent = `${name} · ${(selected?.device || '').toUpperCase()} · ${engines[selectedEngine()]?.message || '未準備'}`;
    voiceItems = s.voices;
    const old = $('voice').value;
    const signature = JSON.stringify([s.voices, selectedEngine()]);
    if ($('voice').dataset.signature !== signature) {
      $('voice').replaceChildren();
      const favorites = selected?.reference?.required === false
        ? [{id:'builtin:default',name:'モデル標準の声',favorite:false}]
        : s.voices.filter(v => v.favorite);
      for (const v of favorites) {
        const o = document.createElement('option'); o.value = v.id;
        o.textContent = (v.favorite ? '★ ' : '') + (labels[v.name] || v.name);
        $('voice').append(o);
      }
      $('voice').value = favorites.some(v => v.id === old) ? old : favorites.some(v => v.id === preferences.voice) ? preferences.voice : favorites[0]?.id || '';
      $('voice').disabled = !favorites.length;
      $('voice').dataset.signature = signature;
      renderVoices();
    }
    await updateVoiceNotice();
    if (ready && omniReferenceReady && phase === 'ready') serverMessage = `${name}の準備完了 · 発話できます`;
    else if (selected?.installed && !selected?.languages?.includes($('speech-mode').value === 'ja_to_en' ? 'en' : 'ja')) serverMessage = `${name}は選択した発話言語に対応していません`;
    if (!$('voice').value) serverMessage = 'お気に入りの声がありません · 「声」ページで登録してください';
    else if (!omniReferenceReady && phase !== 'error' && phase !== 'loading') serverMessage = '選択モデル用の声の参照設定が必要です · 「声」ページを確認してください';
  } catch (e) {
    ready = false; phase = 'error'; serverMessage = 'サーバーへ接続できません';
  }
  updateStatus();
}
async function updateVoiceNotice() {
  const voice = $('voice').value, engine = selectedEngine();
  omniReferenceReady = false;
  const notice = $('voice-availability');
  if (!voice) { notice.textContent = 'お気に入りの声がありません。「声」ページでお気に入りにチェックを入れて保存してください。'; return; }
  if (currentCapabilities().reference?.required === false) { omniReferenceReady = true; notice.textContent = '選択モデルは参照音声なしで発話できます。'; return; }
  notice.textContent = '選択モデル用の声の設定を確認しています…';
  try {
    const ref = await api('/api/v2/voices/' + encodeURIComponent(voice) + '/reference?model_id=' + encodeURIComponent(engine));
    if ($('voice').value !== voice || selectedEngine() !== engine) return;
    omniReferenceReady = ref.model_id === engine && ref.valid_for_model === true;
    notice.textContent = omniReferenceReady ? '選択モデル用の参照設定あり。参照区間と文字起こしが一致しているか「声」ページで確認できます。' : 'この声は選択モデル用の設定が必要です。「声」ページの「区間と文字を自動入力」で下書きを作り、確認して保存してください。';
  } catch { if ($('voice').value === voice) notice.textContent = '選択モデル用の設定を確認できません。「声」ページを確認してください。'; }
}
async function audioContext() {
  if (!ctx) { ctx = new AudioContext(); gain = ctx.createGain(); gain.connect(ctx.destination); }
  gain.gain.value = preferences.volume ?? .8;
  if (preferences.output_device && ctx.setSinkId && ctx.sinkId !== preferences.output_device) {
    try { await ctx.setSinkId(preferences.output_device); } catch { $('message').textContent = '保存した出力先を使えません。標準の出力先に戻します。'; preferences.output_device = ''; await ctx.setSinkId(''); }
  }
  await ctx.resume(); return ctx;
}
function stopPlayback() {
  if (source) { source.onended = null; try { source.stop(); } catch {} source = null; }
  playing = false; playingItemId = null;
}
function stop() {
  const oldClient = clientId; clientId = crypto.randomUUID(); sessionStorage.echoClient = clientId;
  fetch('/api/v2/clients/' + oldClient + '/cancel', {method:'POST'}).catch(()=>{});
  generation++; controller?.abort(); controller = null;
  $('record-preview').pause();
  if (!$('voices-view').hidden) $('voice-notice').textContent = '音声の再生を停止しました。';
  queue = []; prepared = []; activeJob = null;
  stopPlayback(); localBusy = false;
  $('message').textContent = '停止しました。処理中の音声は再生しません。';
  updateStatus(); refresh();
}
function play(buffer, itemId = null) {
  stopPlayback();
  const node = ctx.createBufferSource(); node.buffer = buffer; node.connect(gain);
  source = node; playing = true; playingItemId = itemId;
  node.onended = () => { if (source === node) { source = null; playing = false; playingItemId = null; updateStatus(); pumpPlayback(); } };
  node.start();
  const started = performance.now();
  updateStatus();
  return started;
}
async function replay(item) {
  stop(); const token = generation;
  try { await audioContext(); await loadItemAudio(item); if (token !== generation) return; play(item.buffer, item.id); }
  catch { $('history-notice-text').textContent = '音声を再生できませんでした。'; $('history-notice').hidden = false; $('undo').hidden = true; }
  refresh();
}
function release(items) { items.forEach(item => { if (item.url?.startsWith('blob:')) URL.revokeObjectURL(item.url); }); }
function renderHistory() {
  $('history').replaceChildren();
  $('empty').hidden = history.length > 0;
  $('history-count').textContent = history.length;
  $('clear').disabled = history.length === 0;
  for (const item of history) {
    const row = document.createElement('article'); row.className = 'entry';
    const top = document.createElement('div'); top.className = 'entry-top';
    const time = document.createElement('time'); time.dateTime = item.generatedAt; time.textContent = dateFormat.format(new Date(item.generatedAt)) + ' 生成';
    const voice = document.createElement('span'); voice.className = 'entry-voice'; voice.textContent = item.voice;
    top.append(time, voice);
    const p = document.createElement('p'); p.textContent = item.text;
    if (item.translated_text) { const translation = document.createElement('p'); translation.lang = 'en'; translation.textContent = item.translated_text; top.append(translation); }
    if (item.speech_text && !item.translated_text && item.speech_text !== item.text) { const reading = document.createElement('small'); reading.textContent = '読み：' + item.speech_text; top.append(reading); }
    const bottom = document.createElement('div'); bottom.className = 'entry-bottom';
    const timing = document.createElement('small'); timing.textContent = `再生開始 ${seconds(item.timing.total)}秒 · 生成 ${seconds(item.timing.synthesis)}秒`;
    const b = document.createElement('button'); b.append(icon('play'), document.createTextNode('再生')); b.onclick = () => replay(item); b.setAttribute('aria-label', item.text + 'を再生');
    const a = document.createElement('a'); a.href = item.url || `/api/history/${item.id}/audio`; a.download = `echo-ego-${item.generatedAt.replace(/[:.]/g, '-')}.wav`; a.append(icon('download'), document.createTextNode('WAV保存'));
    const d = document.createElement('button'); d.className = 'delete'; d.append(icon('delete'), document.createTextNode('削除')); d.onclick = () => deleteHistory([item.id]); d.setAttribute('aria-label', item.text + 'の履歴を削除');
    bottom.append(timing, b, a, d); row.append(top, p, bottom); $('history').append(row);
  }
}
async function deleteHistory(ids) {
  const selected = history.filter(item => ids.includes(item.id));
  if (!selected.length) return;
  release(deletedItems); deletedItems = selected;
  for (const item of selected) {
    try { if (preferences.history_enabled) await loadItemAudio(item); } catch {}
    item.deleted = true;
    if (preferences.history_enabled) item.deleteTask = api('/api/history/' + item.id, {method:'DELETE'}).catch(showHistoryError);
  }
  if (selected.some(item => item.id === playingItemId)) stopPlayback();
  for (let i = history.length - 1; i >= 0; i--) if (ids.includes(history[i].id)) history.splice(i, 1);
  $('history-notice-text').textContent = `${selected.length}件の履歴を削除しました。`;
  $('history-notice').hidden = false; $('undo').hidden = false;
  renderHistory(); updateStatus();
}
function undoDeletion() {
  for (const item of deletedItems) { item.deleted = false; persistItem(item); }
  history.push(...deletedItems); deletedItems = [];
  history.sort((a, b) => new Date(b.generatedAt) - new Date(a.generatedAt));
  release(history.splice(preferences.history_enabled ? preferences.history_count : 10));
  $('history-notice-text').textContent = '履歴を元に戻しました。'; $('undo').hidden = true;
  renderHistory();
}
function addHistory(text, buffer, blob, timing, voice, generatedAt, metadata = {}) {
  const item = {...metadata,id:crypto.randomUUID(), text, buffer, blob, timing, voice, generatedAt, url:URL.createObjectURL(blob)};
  history.unshift(item); release(history.splice(preferences.history_enabled ? preferences.history_count : 10)); renderHistory();
  persistItem(item);
  return item.id;
}
async function speak(useCache = false, overrides = {}) {
  if (!canSpeak()) return;
  const text = overrides.text ?? $('text').value;
  if (!text.trim() || Array.from(text).length > 160) { $('message').textContent = '1〜160文字で入力してください'; return; }
  const engine = selectedEngine();
  const payload = {text,voice_id:$('voice').value,mode:$('speech-mode').value,engine,speed:Number($('speed').value),
    engine_settings:modelSettings(),
    client_id:clientId,request_id:crypto.randomUUID(),use_phrase_cache:useCache === true,...overrides};
  const token = generation, start = performance.now(), voiceName = $('voice').selectedOptions[0]?.textContent;
  await audioContext(); if (token !== generation || !canSpeak()) return;
  const job = {id:crypto.randomUUID(),payload,voiceName,start,token};
  queue.push(job);
  job.submission = submissionChain.catch(()=>{}).then(async()=> {
    if (token !== generation) throw Error('取消済み');
    const response = await fetch('/api/v2/speech-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const value = await response.json();
    if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : '入力内容を確認してください');
    job.serverId = value.id;
    if (token !== generation || job.cancelled) { await fetch('/api/v2/speech-jobs/'+value.id,{method:'DELETE'}); throw Error('取消済み'); }
    return value;
  });
  submissionChain = job.submission.catch(()=>{});
  // Attach rejection handler immediately, including while another job is playing.
  job.submission.catch(()=>{});
  $('message').textContent = '発話を受け付けています。'; updateStatus(); pumpSynthesis();
}
async function pumpSynthesis() {
  if (synthesizing || !queue.length) return;
  const job = queue.shift(), {payload,token,start} = job;
  synthesizing = true; localBusy = true; activeJob = job; operationError = ''; updateStatus();
  try {
    let result = await job.submission;
    while (!['ready','failed','cancelled'].includes(result.state)) {
      if (token !== generation || job.cancelled) return;
      job.state = result.state;
      $('message').textContent = jobProgress(job); updateStatus();
      result = await api('/api/v2/speech-jobs/'+job.serverId+'?after_state='+encodeURIComponent(result.state)+'&wait_ms=1000');
    }
    if (result.state === 'failed') throw Error(result.error.message);
    if (result.state === 'cancelled' || token !== generation || job.cancelled) return;
    const response = await fetch('/api/v2/speech-jobs/'+job.serverId+'/audio');
    if (!response.ok) throw Error('音声を取得できませんでした');
    const bytes = await response.arrayBuffer(),received = performance.now()-start;
    const buffer = await ctx.decodeAudioData(bytes.slice(0)); if (token !== generation || job.cancelled) return;
    const snapshot = result.snapshot;
    prepared.push({...job,bytes,buffer,received,metadata:{speech_text:snapshot.speech_text,translated_text:snapshot.translated_text,engine:snapshot.engine,reading_revision:snapshot.reading_revision,model_identity:snapshot.model,voice_revision:snapshot.voice_revision,translation_identity:snapshot.translation_identity,generation_settings:snapshot.settings},
      first:Number(response.headers.get('X-First-Signal-Ms')),generatedAt:response.headers.get('X-Generated-At'),synthesis:Number(response.headers.get('X-Synthesis-Ms')),cached:response.headers.get('X-Cached')==='1'});
    pumpPlayback();
  } catch(e) { if (token === generation && !job.cancelled) { operationError = e.message; $('message').textContent = e.message; } }
  finally { synthesizing = false;localBusy = false;activeJob = null;updateStatus();pumpSynthesis(); }
}
function pumpPlayback() {
    if (playing || !prepared.length) return;
    const job = prepared.shift(); if (job.token !== generation) { pumpPlayback(); return; }
    const {buffer, start, first, generatedAt, received, bytes, payload, voiceName, synthesis, cached} = job;
    const total = play(buffer) - start;
    $('total').innerHTML = seconds(total) + '<small> 秒</small>';
    $('received').innerHTML = seconds(received) + '<small> 秒</small>';
    $('silence').innerHTML = (first < 0 ? '検出なし' : seconds(first)) + '<small> 秒</small>';
    const output = (ctx.outputLatency || 0) * 1000;
    $('message').textContent = (cached ? '生成済みの音声を使用。' : '') + (first >= 0 ? `先頭の音までの目安：${seconds(total + first + output)}秒（出力機器の遅延は推定）` : '音声の信号を検出できませんでした。');
    $('translated-text').hidden = !job.metadata?.translated_text; $('translated-text').textContent = job.metadata?.translated_text || '';
    if (!payload.audition) playingItemId = addHistory(payload.text, buffer, new Blob([bytes], {type:'audio/wav'}), {total,received,synthesis}, voiceName, generatedAt, job.metadata);
    updateStatus();
}
$('speak').onclick = () => speak().catch(e => $('message').textContent = e.message); $('stop').onclick = stop;
$('text').addEventListener('compositionstart', () => composing = true);
$('text').addEventListener('compositionend', () => composing = false);
$('text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !composing && e.keyCode !== 229) { e.preventDefault(); if (!e.repeat) speak().catch(error => $('message').textContent = error.message); } });
$('text').addEventListener('input', () => $('count').textContent = `${Array.from($('text').value).length} / 160`);
window.addEventListener('hashchange', showView);
$('clear').onclick = () => deleteHistory(history.map(item => item.id));
$('undo').onclick = undoDeletion;
$('upload-button').onclick = () => $('upload').click();
$('upload').onchange = async () => {
  const file = $('upload').files[0]; if (!file) return;
  const data = new FormData(); data.append('file', file); $('message').textContent = '声を登録しています…'; $('upload-button').disabled = true;
  try {
    const r = await fetch('/api/voices', {method:'POST', body:data}); const v = await r.json(); if (!r.ok) throw Error(v.detail);
    await refresh(); $('voice').value = v.id; await rememberSpeechSettings(); $('message').textContent = '自分の声を登録しました。最初の発話は準備の分だけ長くなります。';
  } catch (e) { $('message').textContent = e.message; }
  finally { $('upload').value = ''; $('upload-button').disabled = false; }
};
window.addEventListener('keydown', e => { if (e.key === 'Escape') { stop(); } if (e.altKey && /^[1-9]$/.test(e.key) && !e.isComposing && !e.repeat) { e.preventDefault(); triggerPhrase(Number(e.key) - 1); } });

$('speech-mode').onchange = async () => { operationError = ''; await rememberSpeechSettings(); await refresh(); };
$('reading-check').onclick = async () => {
  try { const result = await api('/api/v2/reading-preview',jsonRequest('POST',{text:$('text').value,mode:$('speech-mode').value,use_dictionary:true}));
    $('reading-preview').textContent = $('speech-mode').value === 'ja' ? '読み上げる文：'+result.speech_text : result.warnings.join(' ');
  } catch(e) { $('reading-preview').textContent = e.message; }
};
