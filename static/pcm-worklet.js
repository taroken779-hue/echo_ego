/* Bounded per-utterance PCM storage; continuous fractional resampling across chunks. */
class EchoPCM extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.rate = options.processorOptions.rate;
    this.samples = new Float32Array(this.rate * 30);
    this.written = 0; this.cursor = 0; this.started = false; this.ended = false; this.stopped = false;
    this.port.onmessage = ({data}) => {
      if (data.type === 'stop') { this.stopped = true; return; }
      if (data.type === 'end') { this.ended = true; return; }
      if (data.type === 'pcm') {
        const input = new Int16Array(data.buffer);
        if (this.written + input.length > this.samples.length) { this.port.postMessage({type:'error'}); this.stopped = true; return; }
        for (const v of input) this.samples[this.written++] = v / 32768;
      }
    };
  }
  process(inputs, outputs) {
    const output = outputs[0][0];
    if (this.stopped) return false;
    if (!this.started && (this.written >= this.rate * .1 || this.ended)) {
      this.started = true; this.port.postMessage({type:'started'});
    }
    if (!this.started) return true;
    const step = this.rate / sampleRate;
    for (let i = 0; i < output.length; i++) {
      const at = Math.floor(this.cursor);
      if (at >= this.written || (!this.ended && at + 1 >= this.written)) break;
      const a = this.samples[at], b = this.samples[Math.min(at + 1, this.written - 1)];
      output[i] = a + (b - a) * (this.cursor - at);
      this.cursor += step;
    }
    if (this.ended && this.cursor >= this.written) {
      this.port.postMessage({type:'drained'}); return false;
    }
    return true;
  }
}
registerProcessor('echo-pcm', EchoPCM);
