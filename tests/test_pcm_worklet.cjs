const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function processor(){
  let Klass; const events=[];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/pcm-worklet.js'),'utf8'),{
    AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>events.push(m)}}},
    Float32Array,Int16Array,sampleRate:48000,registerProcessor:(name,value)=>Klass=value
  });
  const p=new Klass({processorOptions:{rate:24000}});
  return {p,events,send:data=>p.port.onmessage({data}),render:()=>{
    const samples=new Float32Array(128);return {samples,active:p.process([],[[samples]])};
  }};
}
test('buffers, resamples across chunks and drains',()=>{
  const {p,events,send,render}=processor();
  assert.ok(render().samples.every(x=>x===0));
  send({type:'pcm',buffer:new Int16Array(2500).fill(8192).buffer});
  assert.equal(render().samples[0],.25);
  send({type:'pcm',buffer:new Int16Array(1000).fill(16384).buffer});send({type:'end'});
  let active=true,blocks=0;while(active && blocks++<100) active=render().active;
  assert.equal(active,false);assert.equal(p.cursor,3500);
  assert.equal(events.filter(x=>x.type==='started').length,1);
  assert.equal(events.filter(x=>x.type==='drained').length,1);
});
test('stop and overflow terminate processing',()=>{
  const s=processor();s.send({type:'stop'});assert.equal(s.render().active,false);
  const f=processor();f.send({type:'pcm',buffer:new Int16Array(24000*30+1).buffer});
  assert.equal(f.render().active,false);assert.equal(f.events[0].type,'error');
});
