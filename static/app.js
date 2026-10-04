const $ = id => document.getElementById(id);
let ctx, source, controller;
let generation = 0, localBusy = false, remoteBusy = false;
let ready = false, composing = false, playing = false, playingItemId = null;
let serverMessage = '接続しています…', phase = 'loading', deletedItems = [];
let preferences = {}, voiceItems = [], queue = [], prepared = [], synthesizing = false, activeJob = null, gain;
const history = [];
const labels = {age_middle_male:'男性・落ち着いた声',age_middle_female:'女性・落ち着いた声',age_young_male:'男性・若い声',age_young_female:'女性・若い声',age_senior_male:'男性・年配の声',age_senior_female:'女性・年配の声',age_child_male:'男の子の声',age_child_female:'女の子の声',narrator:'ナレーター'};
const dateFormat = new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23'});
function canSpeak() { return ready && queue.length + prepared.length < 8; }
function seconds(ms) { return (ms / 1000).toFixed(2); }
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '/static/icons.svg#' + name); svg.append(use);
  return svg;
}
function updateStatus() {
  $('status').textContent = (playing ? '再生中' : localBusy ? '音声を生成中' : remoteBusy ? '音声の処理中' : serverMessage) + (queue.length + prepared.length ? ` · 待ち ${queue.length + prepared.length}件` : '');
  $('status').dataset.state = phase === 'error' ? 'error' : 'normal';
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
    ready = s.phase === 'ready'; remoteBusy = s.busy; phase = s.phase; serverMessage = s.message;
    $('model').textContent = `${s.model} · ${s.precision} · ${s.device.toUpperCase()} · ${ready ? '常駐中' : '準備中'}${ready && !s.watermark ? ' · 音声透かし未読込（setupで修復）' : ''}`;
    voiceItems = s.voices;
    const old = $('voice').value;
    const signature = JSON.stringify(s.voices);
    if ($('voice').dataset.signature !== signature) {
      $('voice').replaceChildren();
      for (const v of s.voices) {
        const o = document.createElement('option'); o.value = v.id;
        o.textContent = (v.favorite ? '★ ' : '') + (labels[v.name] || v.name);
        $('voice').append(o);
      }
      $('voice').value = s.voices.some(v => v.id === old) ? old : s.voices.some(v => v.id === preferences.voice) ? preferences.voice : s.voices[0]?.id;
      $('voice').dataset.signature = signature;
      renderVoices();
    }
  } catch (e) {
    ready = false; phase = 'error'; serverMessage = 'サーバーへ接続できません';
  }
  updateStatus();
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
function addHistory(text, buffer, blob, timing, voice, generatedAt) {
  const item = {id:crypto.randomUUID(), text, buffer, blob, timing, voice, generatedAt, url:URL.createObjectURL(blob)};
  history.unshift(item); release(history.splice(preferences.history_enabled ? preferences.history_count : 10)); renderHistory();
  persistItem(item);
  return item.id;
}
async function speak(useCache = false) {
  if (!canSpeak()) return;
  const text = $('text').value.trim();
  if (!text) { $('message').textContent = '文を入力してください'; return; }
  const payload = {text, voice:$('voice').value, steps:Number($('steps').value), speed:Number($('speed').value), use_cache:useCache === true};
  const voiceName = $('voice').selectedOptions[0]?.textContent;
  const token = generation, start = performance.now(); await audioContext(); if (token !== generation || !canSpeak()) return;
  queue.push({id:crypto.randomUUID(), payload, voiceName, start, token:generation});
  $('message').textContent = '発話を受け付けました。'; updateStatus(); pumpSynthesis();
}
async function pumpSynthesis() {
  if (synthesizing || !queue.length) return;
  const job = queue.shift(), {payload, token, start} = job;
  synthesizing = true; localBusy = true; activeJob = job; updateStatus();
  const abort = new AbortController(); controller = abort;
  try {
    let r;
    do {
      if (token !== generation) return;
      r = await fetch('/api/speech', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload), signal:abort.signal});
      if (r.status === 409) await new Promise(resolve => setTimeout(resolve, 250));
    } while (r.status === 409 && performance.now() - start < 60000);
    if (!r.ok) { const err = await r.json(); throw Error(typeof err.detail === 'string' ? err.detail : '入力内容を確認してください'); }
    const bytes = await r.arrayBuffer(), received = performance.now() - start;
    const buffer = await ctx.decodeAudioData(bytes.slice(0)); if (token !== generation) return;
    prepared.push({...job, bytes, buffer, received, first:Number(r.headers.get('X-First-Signal-Ms')), generatedAt:r.headers.get('X-Generated-At') || new Date().toISOString(), synthesis:Number(r.headers.get('X-Synthesis-Ms')), cached:r.headers.get('X-Cached') === '1'});
    pumpPlayback();
  } catch (e) {
    if (token === generation && e.name !== 'AbortError') $('message').textContent = e.message;
  } finally {
    synthesizing = false; localBusy = false; activeJob = null;
    if (controller === abort) controller = null;
    updateStatus(); pumpSynthesis();
  }
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
    playingItemId = addHistory(payload.text, buffer, new Blob([bytes], {type:'audio/wav'}), {total,received,synthesis}, voiceName, generatedAt);
    updateStatus();
}
$('speak').onclick = () => speak().catch(e => $('message').textContent = e.message); $('stop').onclick = stop;
$('text').addEventListener('compositionstart', () => composing = true);
$('text').addEventListener('compositionend', () => composing = false);
$('text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !composing && e.keyCode !== 229) { e.preventDefault(); if (!e.repeat) speak().catch(error => $('message').textContent = error.message); } });
$('text').addEventListener('input', () => $('count').textContent = `${$('text').value.length} / 160`);
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
