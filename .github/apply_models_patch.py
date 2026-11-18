#!/usr/bin/env python3
"""
apply_models_patch.py (v3) - Sim Radio "MODELS": pick brain / voice models on the fly, 2 fallback slots each,
a model report, and fixes for what the Johannesburg test flight showed.

Run from the REPO ROOT, as the LAST patch (AFTER apply_bush_radio_fix.py):
    python3 .github/apply_models_patch.py

Pause menu > Sim Radio > "Models: ..." gives, for BRAIN and for VOICE:
  * Model       - the one to use (empty = Auto, the built-in list)
  * Fallback 1  - used only if the model fails (empty = none)
  * Fallback 2  - same
  Each slot is picked from a list (known models + whatever your key can see) or typed by hand, so any model id
  can be trialled in flight. If any slot is filled, ONLY the filled slots are used, in that order.
  * Model report - per model: calls that worked / failed and the last error (kept between flights)
  * Reset report and un-bench all

Fixes from the flight log:
  1. A whole MODEL is now rested after it fails (brain AND voice, Auto and chosen): 404 = 6 h, two 503s/timeouts
     in 3 min = 5 min, three 429s in 3 min = 2 min. Before, a dead or overloaded model was retried on every
     transmission with the next key, costing 15-25 s each time (gemini-flash-latest, gemini-2.5-flash).
  2. The Auto brain list now starts with gemini-3.1-flash-lite (the only brain model that answered in the log);
     gemini-2.5-flash is dropped (404 "no longer available to new users"); gemini-flash-latest is last.
  3. Voice timeout now grows with the length of the line (was a flat 35 s / 22 s). Every voice failure in the log
     was a 35-57 s line; the 100-word lines need about a minute to generate.

Voice providers (voice only; the brain stays Gemini): Speechify and Groq (Orpheus). Menu: Models > Voice providers.
Their keys are stored apart from the 5 Gemini keys. In Auto voice mode a provider you gave a key to is tried first, then the
Gemini voices. In the voice slots they appear as speechify:<model> and groq:<model>.
  * Groq limits one request to 200 characters, so a line is cut at sentence ends and the audio pieces are joined.
  * Groq makes you accept the Orpheus terms once in the Groq console before the first call.

Keys: the Bush Radio code already lets brain and voice use all 5 Gemini keys (+ default key), so no key change is needed.

Safe to re-run (MODELS3 marker). If an anchor is missing it STOPS and prints context: paste that log back.
"""
import pathlib
import sys

MARK = "MODELS3"
RADIO = "src/utils/radio.ts"
HELPERS = "src/utils/radioHelpers.ts"


def die(msg, text=None, keywords=()):
    print("\n==================== MODELS PATCH FAILED ====================")
    print(msg)
    if text is not None and keywords:
        shown = 0
        for i, ln in enumerate(text.split("\n")):
            if any(k in ln for k in keywords):
                print("  %5d | %s" % (i + 1, ln.rstrip()[:160]))
                shown += 1
                if shown >= 30:
                    break
    print("\nPaste this whole log back to the model.")
    print("=============================================================")
    sys.exit(1)


def once(text, old, new, label, keywords=()):
    n = text.count(old)
    if n != 1:
        die("Anchor '%s' expected once, found %d times." % (label, n), text,
            keywords or (old.strip().split("\n")[0][:30],))
    return text.replace(old, new)


MEMBERS = r"""  // MODELS3: chosen models (model + 2 fallbacks, brain and voice), per-model report, model-level resting
  private failTimes: Record<string, number[]> = {};
  private voiceTurn = 0;
  getModelSlot(kind: string, i: number): string {
    return storage.getString('radio_' + kind + '_m' + i) || '';
  }
  setModelSlot(kind: string, i: number, m: string) {
    const v = (m || '').trim();
    storage.set('radio_' + kind + '_m' + i, v);
    if (v) {
      // choosing a model on purpose means "try it now"
      delete this.globalModelCooldown[v];
      delete this.failTimes[v];
    }
  }
  private chosenModels(kind: string): string[] {
    const out: string[] = [];
    for (let i = 0; i < 3; i++) {
      const m = this.getModelSlot(kind, i);
      if (m && out.indexOf(m) < 0) {
        out.push(m);
      }
    }
    return out;
  }
  // models that are not resting first, resting ones last (never dropped: a chosen model is still tried)
  private orderByHealth(list: string[]): string[] {
    const now = Date.now();
    const live = list.filter(m => (this.globalModelCooldown[m] || 0) <= now);
    const rest = list.filter(m => (this.globalModelCooldown[m] || 0) > now);
    return live.concat(rest);
  }
  private slotSummary(kind: string): string {
    const c = this.chosenModels(kind);
    return c.length === 0 ? 'auto' : c.map(m => m.replace(/^gemini-/, '')).join(' > ');
  }
  private voiceTimeoutMs(text: string): number {
    const words = text.split(/\s+/).filter(Boolean).length;
    const audioMs = (words / 2.6) * 1000;
    return Math.round(Math.min(80000, Math.max(30000, 15000 + audioMs * 1.1)));
  }
  private modelStats(): Record<string, {ok: number; fail: number; last: string; at: number}> {
    try {
      return JSON.parse(storage.getString('radio_model_stats') || '{}') || {};
    } catch (e) {
      return {};
    }
  }
  private bumpModel(model: string, ok: boolean, err = '') {
    if (!model || model === 'none') {
      return;
    }
    const s = this.modelStats();
    const e = s[model] || {ok: 0, fail: 0, last: '', at: 0};
    if (ok) {
      e.ok += 1;
      this.failTimes[model] = [];
    } else {
      e.fail += 1;
      e.last = err.slice(0, 90);
    }
    e.at = Date.now();
    s[model] = e;
    try {
      storage.set('radio_model_stats', JSON.stringify(s));
    } catch (x) {}
  }
  // reads the radio's own log lines (so it sees brain and voice failures wherever they are produced)
  private trackModels(m: string) {
    try {
      const now = Date.now();
      const f = m.match(/^(brain|voice) fallback from (\S+?)(?: \(key \d+\))?: ([\s\S]*)$/);
      if (f) {
        const model = f[2];
        const err = f[3].replace(/\s+/g, ' ');
        this.bumpModel(model, false, err);
        if (/HTTP 404|no longer available/i.test(err)) {
          this.globalModelCooldown[model] = Math.max(this.globalModelCooldown[model] || 0, now + 6 * 3600 * 1000);
        } else if (/HTTP 5\d\d|timed out|timeout|HTTP 429/i.test(err)) {
          const t = (this.failTimes[model] || []).filter(x => now - x < 3 * 60 * 1000);
          t.push(now);
          this.failTimes[model] = t;
          const is429 = /HTTP 429/.test(err);
          if (t.length >= (is429 ? 3 : 2)) {
            this.globalModelCooldown[model] = Math.max(this.globalModelCooldown[model] || 0, now + (is429 ? 2 : 5) * 60 * 1000);
          }
        }
        return;
      }
      const ok = m.match(/^model=(\S+) voice=(\S+?)(?:#\d+)? /);
      if (ok) {
        this.bumpModel(ok[1], true);
        if (ok[2] !== 'none') {
          this.bumpModel(ok[2], true);
        }
      }
    } catch (e) {}
  }
  private modelChoices(brain: boolean): string[] {
    const base: string[] = brain ? MODEL_CHAIN : TTS_CHAIN;
    const av = (this.available || []).filter(
      m =>
        /gemini/i.test(m) &&
        (brain ? !/tts|image|live|audio|embed|robot|computer|veo|imagen/i.test(m) : /tts/i.test(m)),
    );
    const all: string[] = [];
    const provs = brain
      ? []
      : ['speechify:' + this.getProvOpt('speechify', 'model'), 'groq:' + this.getProvOpt('groq', 'model')];
    for (const m of provs.concat(base, av)) {
      if (all.indexOf(m) < 0) {
        all.push(m);
      }
    }
    return all.slice(0, 16);
  }
  private modelLine(m: string): string {
    const s = this.modelStats()[m];
    const benched = (this.globalModelCooldown[m] || 0) > Date.now();
    const mark = benched ? '(resting) ' : s && s.ok > 0 && s.fail === 0 ? 'OK ' : s && s.fail > s.ok ? 'BAD ' : '';
    return mark + m + (s ? '  [' + s.ok + ' ok, ' + s.fail + ' failed]' : '');
  }
  private modelReportItems(): any[] {
    const s = this.modelStats();
    const names = Object.keys(s).sort((a, b) => s[b].ok - s[a].ok || s[a].fail - s[b].fail);
    if (names.length === 0) {
      return [{id: 'radio:modelinfo', title: 'Nothing recorded yet. Let the radio run a few turns.'}];
    }
    return names.map(m => ({
      id: 'radio:modelinfo',
      title: this.modelLine(m) + (s[m].fail > 0 && s[m].last ? ' | last: ' + s[m].last : ''),
    }));
  }
  private async loadModelList() {
    try {
      const k = this.getApiKey();
      if (k) {
        await this.refreshAvailable(k);
      }
    } catch (e) {}
  }
  // MODELS3: voice-only providers (Speechify, Groq). Their keys are kept apart from the Gemini keys.
  getProvKey(p: string): string {
    return storage.getString('radio_pkey_' + p) || '';
  }
  setProvKey(p: string, k: string) {
    storage.set('radio_pkey_' + p, (k || '').trim());
  }
  getProvOpt(p: string, what: string): string {
    const d: Record<string, string> = {
      speechify_voice: 'george',
      speechify_model: 'simba-3.5',
      groq_voice: 'troy',
      groq_model: 'canopylabs/orpheus-v1-english',
    };
    return storage.getString('radio_popt_' + p + '_' + what) || d[p + '_' + what] || '';
  }
  setProvOpt(p: string, what: string, v: string) {
    storage.set('radio_popt_' + p + '_' + what, (v || '').trim());
  }
  private isProviderModel(m: string): boolean {
    return m.indexOf('speechify:') === 0 || m.indexOf('groq:') === 0;
  }
  private provRouteFor(model: string): {model: string; id: number; key: string; tag: string} | null {
    const p = model.slice(0, model.indexOf(':'));
    const key = this.getProvKey(p);
    if (!key) {
      return null;
    }
    const id = p === 'speechify' ? 101 : 102;
    return {model, id, key, tag: model + '@' + id};
  }
  private providerRoutes(): Array<{model: string; id: number; key: string; tag: string}> {
    const out: Array<{model: string; id: number; key: string; tag: string}> = [];
    for (const p of ['speechify', 'groq']) {
      const r = this.provRouteFor(p + ':' + this.getProvOpt(p, 'model'));
      if (r) {
        out.push(r);
      }
    }
    return out;
  }
  private b64ToBytes(b64: string): Uint8Array {
    const T = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    const lut: Record<string, number> = {};
    for (let i = 0; i < 64; i++) {
      lut[T.charAt(i)] = i;
    }
    const s = b64.replace(/[^A-Za-z0-9+/]/g, '');
    const n = Math.floor((s.length * 3) / 4);
    const out = new Uint8Array(n);
    let o = 0;
    for (let i = 0; i < s.length; i += 4) {
      const a = lut[s.charAt(i)] || 0;
      const b = lut[s.charAt(i + 1)] || 0;
      const c = i + 2 < s.length ? lut[s.charAt(i + 2)] || 0 : 0;
      const d = i + 3 < s.length ? lut[s.charAt(i + 3)] || 0 : 0;
      const v = (a << 18) | (b << 12) | (c << 6) | d;
      if (o < n) {
        out[o++] = (v >> 16) & 255;
      }
      if (o < n) {
        out[o++] = (v >> 8) & 255;
      }
      if (o < n) {
        out[o++] = v & 255;
      }
    }
    return out;
  }
  private bytesToB64(u: Uint8Array): string {
    const T = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    const parts: string[] = [];
    let s = '';
    for (let i = 0; i < u.length; i += 3) {
      const a = u[i];
      const b = i + 1 < u.length ? u[i + 1] : 0;
      const c = i + 2 < u.length ? u[i + 2] : 0;
      const v = (a << 16) | (b << 8) | c;
      s +=
        T.charAt((v >> 18) & 63) +
        T.charAt((v >> 12) & 63) +
        (i + 1 < u.length ? T.charAt((v >> 6) & 63) : '=') +
        (i + 2 < u.length ? T.charAt(v & 63) : '=');
      if (s.length > 8192) {
        parts.push(s);
        s = '';
      }
    }
    parts.push(s);
    return parts.join('');
  }
  // 16-bit PCM out of a WAV file (mono; stereo keeps the left channel). No RIFF header = already raw PCM.
  private wavToPcm(u: Uint8Array, fallbackRate: number): {pcm: Uint8Array; rate: number} {
    const riff = u.length > 44 && u[0] === 0x52 && u[1] === 0x49 && u[2] === 0x46 && u[3] === 0x46;
    if (!riff) {
      return {pcm: u, rate: fallbackRate};
    }
    let rate = fallbackRate;
    let ch = 1;
    let bits = 16;
    let start = 44;
    let len = u.length - 44;
    let pos = 12;
    while (pos + 8 <= u.length) {
      const id = String.fromCharCode(u[pos], u[pos + 1], u[pos + 2], u[pos + 3]);
      const sz = u[pos + 4] + u[pos + 5] * 256 + u[pos + 6] * 65536 + u[pos + 7] * 16777216;
      if (id === 'fmt ') {
        ch = u[pos + 10] + u[pos + 11] * 256;
        rate = u[pos + 12] + u[pos + 13] * 256 + u[pos + 14] * 65536 + u[pos + 15] * 16777216;
        bits = u[pos + 22] + u[pos + 23] * 256;
      } else if (id === 'data') {
        start = pos + 8;
        len = sz > 0 ? Math.min(sz, u.length - start) : u.length - start;
        break;
      }
      pos += 8 + sz + (sz % 2);
    }
    if (bits !== 16) {
      throw new ApiError(0, 'unsupported audio: ' + bits + ' bit');
    }
    const frame = 2 * Math.max(1, ch);
    len -= len % frame;
    if (ch <= 1) {
      return {pcm: u.slice(start, start + len), rate};
    }
    const mono = new Uint8Array(len / ch);
    for (let i = 0, o = 0; i < len; i += frame) {
      mono[o++] = u[start + i];
      mono[o++] = u[start + i + 1];
    }
    return {pcm: mono, rate};
  }
  private async respBytes(resp: any): Promise<Uint8Array> {
    try {
      return new Uint8Array(await resp.arrayBuffer());
    } catch (e) {
      const blob = await resp.blob();
      const url: string = await new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(String(fr.result || ''));
        fr.onerror = () => rej(new Error('could not read audio'));
        fr.readAsDataURL(blob);
      });
      return this.b64ToBytes(url.slice(url.indexOf(',') + 1));
    }
  }
  // cuts a line into pieces of at most max characters, at sentence ends where possible
  private splitSpeech(text: string, max: number): string[] {
    const t = text.replace(/\s+/g, ' ').trim();
    if (t.length <= max) {
      return [t];
    }
    const sentences = t.match(/[^.!?\u2026]+[.!?\u2026]+["')\]]*\s*|[^.!?\u2026]+$/g) || [t];
    const out: string[] = [];
    let cur = '';
    for (const s0 of sentences) {
      let s = s0.trim();
      while (s.length > max) {
        let cut = s.lastIndexOf(' ', max);
        if (cut < max * 0.5) {
          cut = max;
        }
        if (cur) {
          out.push(cur);
          cur = '';
        }
        out.push(s.slice(0, cut).trim());
        s = s.slice(cut).trim();
      }
      if (!s) {
        continue;
      }
      if ((cur + ' ' + s).trim().length > max) {
        if (cur) {
          out.push(cur);
        }
        cur = s;
      } else {
        cur = (cur + ' ' + s).trim();
      }
    }
    if (cur) {
      out.push(cur);
    }
    return out;
  }
  // Speechify (<= 2000 chars a request) and Groq Orpheus (<= 200 chars a request, so long lines are cut and joined)
  private async providerAudio(
    r: {model: string; id: number; key: string; tag: string},
    text: string,
  ): Promise<{data: string; rate: number; ms: number}> {
    const p = r.model.slice(0, r.model.indexOf(':'));
    const model = r.model.slice(p.length + 1);
    const voice = this.getProvOpt(p, 'voice');
    const pieces: Uint8Array[] = [];
    let rate = 24000;
    const chunks = this.splitSpeech(text, p === 'groq' ? 190 : 1800);
    for (const chunk of chunks) {
      if (p === 'speechify') {
        const resp = await this.timedFetch(
          'https://api.speechify.ai/v1/audio/speech',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + r.key},
            body: JSON.stringify({input: chunk, voice_id: voice, model, audio_format: 'pcm'}),
          },
          25000,
        );
        const raw = await resp.text();
        if (!resp.ok) {
          throw new ApiError(resp.status, raw);
        }
        const j: any = JSON.parse(raw);
        if (!j?.audio_data) {
          throw new ApiError(0, 'no audio returned');
        }
        const fmt = String(j.audio_format || 'pcm').toLowerCase();
        if (fmt !== 'pcm' && fmt !== 'wav') {
          throw new ApiError(0, 'unexpected audio format ' + fmt);
        }
        const w = this.wavToPcm(this.b64ToBytes(String(j.audio_data)), 24000);
        rate = w.rate;
        pieces.push(w.pcm);
      } else {
        const resp = await this.timedFetch(
          'https://api.groq.com/openai/v1/audio/speech',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + r.key},
            body: JSON.stringify({model, input: chunk, voice, response_format: 'wav'}),
          },
          20000,
        );
        if (!resp.ok) {
          throw new ApiError(resp.status, await resp.text());
        }
        const w = this.wavToPcm(await this.respBytes(resp), 24000);
        rate = w.rate;
        pieces.push(w.pcm);
      }
    }
    let total = 0;
    for (const b of pieces) {
      total += b.length;
    }
    if (total === 0) {
      throw new ApiError(0, 'no audio returned');
    }
    const all = new Uint8Array(total);
    let o = 0;
    for (const b of pieces) {
      all.set(b, o);
      o += b.length;
    }
    return {data: this.bytesToB64(all), rate, ms: Math.round((total / 2 / rate) * 1000)};
  }
  private async typeProv(kind: string, p: string, what: string, showInput: (o: any) => Promise<any>) {
    const name = p === 'speechify' ? 'Speechify' : 'Groq';
    const isKey = kind === 'pkey';
    const r = await showInput({
      title: name + (isKey ? ' API key' : ' ' + what),
      message: isKey
        ? 'Paste the ' + name + ' API key. It is used for the radio voice only. Empty clears it.'
        : 'The ' + name + ' ' + what + ' id. Empty goes back to the default (' + this.getProvOpt(p, what) + ').',
      hint: isKey ? 'key' : what,
      text: isKey ? this.getProvKey(p) : storage.getString('radio_popt_' + p + '_' + what) || '',
      maxLength: 200,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      const v = String(r.text || '').trim();
      if (isKey) {
        this.setProvKey(p, v);
        toast(v ? name + ' key saved' : name + ' key cleared');
      } else {
        this.setProvOpt(p, what, v);
        toast(v ? 'Saved: ' + v : 'Back to default');
      }
    }
  }

  private async typeModel(kind: string, i: number, showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: (kind === 'brain' ? 'Brain' : 'Voice') + ' model',
      message:
        'The exact Google model id, for example ' +
        (kind === 'brain'
          ? 'gemini-3.1-flash-lite'
          : 'gemini-2.5-flash-preview-tts, speechify:simba-3.5 or groq:canopylabs/orpheus-v1-english') +
        '. Empty clears the slot.',
      hint: 'gemini-...',
      text: this.getModelSlot(kind, i),
      maxLength: 80,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      const v = String(r.text || '').trim().replace(/^models\//, '');
      if (v && !/^[A-Za-z0-9._:\/-]+$/.test(v)) {
        toast('That is not a valid model id', true);
        return;
      }
      this.setModelSlot(kind, i, v);
      toast(v ? 'Saved: ' + v : 'Slot cleared');
    }
  }

"""

VOICE_CHOSEN = r"""    // MODELS3: chosen voice models in the order picked (resting ones last). Gemini models use every key, in turn.
    const nowV = Date.now();
    const chosenV = this.chosenModels('voice');
    if (chosenV.length > 0) {
      const vpool = this.keyPool(VOICE_KEY_IDS);
      const off = vpool.length > 0 ? this.voiceTurn++ % vpool.length : 0;
      const rotated = vpool.slice(off).concat(vpool.slice(0, off));
      const mine: Array<{model: string; id: number; key: string; tag: string}> = [];
      for (const model of this.orderByHealth(chosenV)) {
        if (this.isProviderModel(model)) {
          const pr = this.provRouteFor(model);
          if (pr) {
            mine.push(pr);
          }
          continue;
        }
        for (const p of rotated) {
          mine.push({model, id: p.id, key: p.key, tag: model + '@' + p.id});
        }
      }
      const ready = mine.filter(r => (this.cooldown[r.tag] || 0) <= nowV);
      return ready.length > 0 ? ready : mine;
    }
    // Auto: speech providers whose key you entered come first, then the Gemini voices
    const provR = this.providerRoutes().filter(
      r => (this.cooldown[r.tag] || 0) <= nowV && (this.globalModelCooldown[r.model] || 0) <= nowV,
    );
"""

SCREENS = r"""      } else if (screen === 'models') {
        // MODELS3
        items = [
          {id: 'radio:slots:brain', title: 'Brain: ' + this.slotSummary('brain')},
          {id: 'radio:slots:voice', title: 'Voice: ' + this.slotSummary('voice')},
          {id: 'radio:vprov', title: 'Voice providers (Speechify, Groq)'},
          {id: 'radio:modelreport', title: 'Model report (what worked, what failed)'},
          {id: 'radio:modelreset', title: 'Reset report and un-bench all models'},
          {id: 'radio:back', title: 'Back'},
        ];
      } else if (screen === 'vprov') {
        items = [];
        for (const pv of ['speechify', 'groq']) {
          const nm = pv === 'speechify' ? 'Speechify' : 'Groq';
          items.push({id: 'radio:pkey:' + pv, title: nm + ' key: ' + (this.getProvKey(pv) ? 'set' : 'not set')});
          items.push({id: 'radio:popt:' + pv + ':voice', title: nm + ' voice: ' + this.getProvOpt(pv, 'voice')});
          items.push({id: 'radio:popt:' + pv + ':model', title: nm + ' model: ' + this.getProvOpt(pv, 'model')});
        }
        items.push({id: 'radio:models', title: 'Back'});
      } else if (screen.indexOf('slots:') === 0) {
        const kind = screen.slice('slots:'.length);
        const label = kind === 'brain' ? 'Brain' : 'Voice';
        items = [];
        for (let i = 0; i < 3; i++) {
          const cur = this.getModelSlot(kind, i);
          const name = i === 0 ? label + ' model' : label + ' fallback ' + i;
          items.push({id: 'radio:slot:' + kind + ':' + i, title: name + ': ' + (cur || (i === 0 ? 'Auto' : 'empty'))});
        }
        items.push({id: 'radio:slotsclear:' + kind, title: 'Clear all (back to Auto)'});
        items.push({id: 'radio:models', title: 'Back'});
      } else if (screen.indexOf('pick:') === 0) {
        const pp = screen.split(':');
        const kind = pp[1];
        const idx = parseInt(pp[2], 10) || 0;
        const cur = this.getModelSlot(kind, idx);
        items = [
          {
            id: 'radio:set:' + kind + ':' + idx + ':',
            title: idx === 0 ? 'Auto (use the built-in list)' : 'Empty (no fallback)',
            active: !cur,
          },
        ];
        for (const m of this.modelChoices(kind === 'brain')) {
          items.push({id: 'radio:set:' + kind + ':' + idx + ':' + m, title: this.modelLine(m), active: m === cur});
        }
        items.push({id: 'radio:typemodel:' + kind + ':' + idx, title: 'Type a model name...'});
        items.push({id: 'radio:slots:' + kind, title: 'Back'});
      } else if (screen === 'modelreport') {
        items = this.modelReportItems();
        items.push({id: 'radio:models', title: 'Back'});
"""

HANDLERS = r"""      } else if (id === 'radio:models') {
        screen = 'models';
      } else if (id === 'radio:vprov') {
        screen = 'vprov';
      } else if (id.indexOf('radio:pkey:') === 0) {
        await this.typeProv('pkey', id.slice('radio:pkey:'.length), 'key', showInput);
        screen = 'vprov';
      } else if (id.indexOf('radio:popt:') === 0) {
        const pt = id.slice('radio:popt:'.length).split(':');
        await this.typeProv('popt', pt[0], pt[1], showInput);
        screen = 'vprov';
      } else if (id.indexOf('radio:slots:') === 0) {
        screen = id.slice('radio:'.length);
      } else if (id.indexOf('radio:slotsclear:') === 0) {
        const k = id.slice('radio:slotsclear:'.length);
        for (let i = 0; i < 3; i++) {
          this.setModelSlot(k, i, '');
        }
        toast('Back to Auto');
        screen = 'slots:' + k;
      } else if (id.indexOf('radio:slot:') === 0) {
        await this.loadModelList();
        screen = 'pick:' + id.slice('radio:slot:'.length);
      } else if (id.indexOf('radio:set:') === 0) {
        const sp = id.slice('radio:set:'.length).split(':');
        this.setModelSlot(sp[0], parseInt(sp[1], 10) || 0, sp.slice(2).join(':'));
        screen = 'slots:' + sp[0];
      } else if (id.indexOf('radio:typemodel:') === 0) {
        const tp = id.slice('radio:typemodel:'.length).split(':');
        await this.typeModel(tp[0], parseInt(tp[1], 10) || 0, showInput);
        screen = 'slots:' + tp[0];
      } else if (id === 'radio:modelreport') {
        screen = 'modelreport';
      } else if (id === 'radio:modelreset') {
        storage.set('radio_model_stats', '{}');
        this.globalModelCooldown = {};
        this.failTimes = {};
        this.cooldown = {};
        this.streak = {};
        toast('Model report cleared, all models un-benched');
        screen = 'models';
"""


def main():
    p = pathlib.Path(RADIO)
    if not p.exists():
        die("src/utils/radio.ts not found. Run the other patches first.")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("MODELS patch already applied.")
        return
    if "// MODELS" in text:
        die("An older MODELS patch is already in radio.ts. Start from a clean checkout (the workflow does).")

    text = once(text, "  private log(m: string) {\n",
                MEMBERS + "  private log(m: string) {\n    this.trackModels(m); // MODELS3\n",
                "log()", ("private log",))
    text = once(text,
                "  private brainModels(): string[] {\n    const now = Date.now();\n",
                "  private brainModels(): string[] {\n    const now = Date.now();\n"
                "    // MODELS3: chosen models first, in the order picked; empty = Auto\n"
                "    const chosenB = this.chosenModels('brain');\n"
                "    if (chosenB.length > 0) {\n"
                "      return this.orderByHealth(chosenB);\n"
                "    }\n",
                "brainModels()", ("brainModels",))
    text = once(text,
                "    const models = filterVoiceModels(this.available, TTS_CHAIN);\n",
                VOICE_CHOSEN + "    const models = filterVoiceModels(this.available, TTS_CHAIN);\n",
                "voiceRoutes()", ("voiceRoutes", "filterVoiceModels"))
    text = once(text,
                "    return buildVoiceRoutes(\n      this.keyPool(VOICE_KEY_IDS),\n",
                "    return provR.concat(buildVoiceRoutes(\n      this.keyPool(VOICE_KEY_IDS),\n",
                "voiceRoutes() return", ("buildVoiceRoutes",))
    text = once(text,
                "      this.globalModelCooldown,\n    );\n  }\n\n  private async fetchGeminiAudio",
                "      this.globalModelCooldown,\n    ));\n  }\n\n  private async fetchGeminiAudio",
                "voiceRoutes() end", ("fetchGeminiAudio",))
    text = once(text,
                "        markUsed(this.rot, r.tag, Date.now(), r.id);\n",
                "        markUsed(this.rot, r.tag, Date.now(), r.id);\n"
                "        if (this.isProviderModel(r.model)) {\n"
                "          // MODELS3: Speechify / Groq voice\n"
                "          const pa = await this.providerAudio(r, cleanSpeech);\n"
                "          this.lastVoice = r.model + '#' + r.id;\n"
                "          this.good(r.tag);\n"
                "          afterSuccess(this.rot, r.model, r.id, poolSize);\n"
                "          this.log('TTS ok ' + this.lastVoice + ' ms=' + pa.ms);\n"
                "          this.emitUi();\n"
                "          return pa;\n"
                "        }\n",
                "voice provider branch", ("markUsed(this.rot",))
    text = once(text,
                "          (this.streak[r.tag] || 0) > 0 ? 22000 : 35000,\n",
                "          this.voiceTimeoutMs(cleanSpeech), // MODELS3: longer lines need longer to generate\n",
                "voice timeout", ("22000", "35000"))
    text = once(text, "          {id: 'radio:more', title: 'More settings'},\n",
                "          {id: 'radio:models', title: 'Models: brain ' + this.slotSummary('brain') + ' | voice ' + this.slotSummary('voice')},\n"
                "          {id: 'radio:more', title: 'More settings'},\n", "main menu item", ("radio:more",))
    text = once(text, "      } else if (screen === 'voice') {\n", SCREENS + "      } else if (screen === 'voice') {\n",
                "menu screens", ("screen === 'voice'",))
    text = once(text, "      } else if (id === 'radio:voice') {\n", HANDLERS + "      } else if (id === 'radio:voice') {\n",
                "menu handlers", ("radio:voice",))
    p.write_text(text, encoding="utf-8")
    print("radio.ts: model slots, picker menu, report, model-level resting, length-based voice timeout added")

    h = pathlib.Path(HELPERS)
    if h.exists():
        ht = h.read_text(encoding="utf-8")
        old = ("  'gemini-flash-latest',\n  'gemini-2.5-flash',\n  'gemini-3.1-flash-lite',\n"
               "  'gemini-flash-lite-latest',\n  'gemini-2.5-flash-lite',\n")
        if ht.count(old) == 1:
            new = ("  'gemini-3.1-flash-lite',\n  'gemini-flash-lite-latest',\n  'gemini-2.5-flash-lite',\n"
                   "  'gemini-flash-latest',\n")
            h.write_text(ht.replace(old, new), encoding="utf-8")
            print("radioHelpers.ts: Auto brain list now starts with gemini-3.1-flash-lite; 2.5-flash dropped (404)")
        else:
            print("radioHelpers.ts: brain list differs from expected, left as is")

    wf = pathlib.Path(".github/workflows/build-merged-apk.yml")
    if wf.exists():
        w = wf.read_text(encoding="utf-8")
        if "apply_models_patch.py" not in w:
            anchor = "      - name: Save diff of all patches\n"
            if w.count(anchor) == 1:
                step = ("      - name: Apply Sim Radio model picker\n"
                        "        run: python3 .github/apply_models_patch.py\n\n")
                wf.write_text(w.replace(anchor, step + anchor), encoding="utf-8")
                print("workflow: model picker step added (note: commit the workflow file with this step in it)")
    print("\nMODELS patch OK")


main()
