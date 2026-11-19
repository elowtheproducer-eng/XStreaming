#!/usr/bin/env python3
"""
SPFY1 - Sim Radio: Speechify only.

Runs LAST (after apply_keys_patch.py). Changes:
  * Removes the Gemini voice picker (Charon, Fenrir, Orus ...) from BOTH menus
    (the Bush Radio overlay and the in-stream gamepad menu) and wipes the Charon default.
  * Hard-wires the radio voice to Speechify. No Gemini / Groq voice fallbacks, no device TTS.
  * Fixes the silent radio: the log showed "voice_not_found" (HTTP 404). The voice id is now
    looked up in your Speechify workspace (GET /v1/voices) by id or display name; if the saved
    voice is not in your workspace a working one is picked and saved. Model falls back to
    simba-english if the configured model is rejected.
  * Every Speechify failure is written to the Bush Radio log with the real reason.
"""
import re
import sys
from pathlib import Path


def find(path):
    p = Path(path)
    if p.exists():
        return p
    sys.exit("ERROR: missing " + path + " (run this after the other patches, from the repo root)")


def sub(src, old, new, label, count=1):
    n = src.count(old)
    if n != count:
        sys.exit("ERROR [%s]: expected %d match, found %d" % (label, count, n))
    return src.replace(old, new)


def rsub(src, pattern, new, label):
    out, n = re.subn(pattern, lambda m: new, src, count=1, flags=re.S)
    if n != 1:
        sys.exit("ERROR [%s]: pattern not found" % label)
    return out


# ------------------------------------------------------------------ radio.ts
RADIO = find("src/utils/radio.ts")
s = RADIO.read_text()
if "SPFY1" in s:
    print("radio.ts already patched, skipping")
else:
    # 1. no Gemini voice list
    s = rsub(s, r"export const SPEAKERS: Array<\{id: string; name: string\}> = \[.*?\n\];",
             "export const SPEAKERS: Array<{id: string; name: string}> = []; // SPFY1: Gemini voices removed", "SPEAKERS")

    # 2. getSpeaker / setSpeaker now mean the Speechify voice
    s = sub(s,
            """  getSpeaker(): string {
    const raw = storage.getString(K_SPEAKER);
    const clean = sanitizeSpeaker(raw);
    if (raw && raw !== clean) storage.set(K_SPEAKER, clean);
    return clean;
  }
  setSpeaker(s: string) {
    storage.set(K_SPEAKER, sanitizeSpeaker(s));
    this.emitUi();
  }""",
            """  getSpeaker(): string {
    return this.getProvOpt('speechify', 'voice'); // SPFY1
  }
  setSpeaker(s: string) {
    this.setProvOpt('speechify', 'voice', s);
    this.emitUi();
  }""", "speaker")

    # 3. main loop: always speak through Speechify (the Charon gate is gone)
    s = sub(s,
            "      const useAtc = Boolean(ATC) && this.getVoiceEngine() === 'atc';\n"
            "      if (this.getVoiceKey() || (!useAtc && this.getSpeaker() !== 'Charon')) { // KEYS1\n",
            "      if (true) { // SPFY1: Speechify only\n", "mainloop")
    s = sub(s, "skipped playback: no Gemini audio available (Device TTS disabled)",
            "skipped playback: no Speechify audio (check the Speechify key / voice)", "skipmsg")

    # 4. voice key is always a Speechify key
    s = rsub(s, r"  voiceKindOf\(k: string\): string \{.*?\n  getBrainKey\(\): string \{",
             "  voiceKindOf(k: string): string {\n    return (k || '').trim() ? 'speechify' : ''; // SPFY1\n  }\n  getBrainKey(): string {",
             "voiceKindOf")
    s = sub(s,
            """  getVoiceKey(): string {
    this.keysReady();
    return storage.getString('radio_vkey') || '';
  }
  getVoiceKind(): string {
    this.keysReady();
    return storage.getString('radio_vkind') || '';
  }""",
            """  getVoiceKey(): string {
    this.keysReady();
    const sp = this.getProvKey('speechify');
    if (sp) {
      return sp;
    }
    const v = storage.getString('radio_vkey') || '';
    return /^(AIza|gsk_)/.test(v) ? '' : v; // an old Gemini / Groq voice key is not usable
  }
  getVoiceKind(): string {
    return this.getVoiceKey() ? 'speechify' : ''; // SPFY1
  }""", "voicekey")
    s = sub(s, "    const kind = sp.kind || this.voiceKindOf(t);\n",
            "    const kind = t ? 'speechify' : ''; // SPFY1: whatever is pasted is a Speechify key\n"
            "    this.spfyVoices = null;\n    this.spfyForce = false;\n", "setvoicekey")
    s = sub(s, "  private keysChecked = false;\n",
            "  private keysChecked = false;\n"
            "  // SPFY1 Speechify voice lookup\n"
            "  private spfyVoices: Array<{id: string; name: string; en: boolean}> | null = null;\n"
            "  private spfyVoicesAt = 0;\n"
            "  private spfyForce = false;\n", "fields")

    # 5. key / voice prompts
    s = rsub(s, r"message:\n        'Paste a Gemini, Groq \(gsk_\.\.\.\) or Speechify key\.[^\n]*',",
             "message: 'Paste your Speechify API key. Empty clears it.',", "keymsg")
    s = sub(s, "hint: 'AIza... / gsk_... / Speechify key',", "hint: 'Speechify API key',", "keyhint")
    s = sub(s,
            """  voiceNameLabel(): string {
    const k = this.getVoiceKind();
    return k === 'groq' || k === 'speechify' ? this.getProvOpt(k, 'voice') : this.getSpeaker();
  }
  isProviderVoice(): boolean {
    const k = this.getVoiceKind();
    return k === 'groq' || k === 'speechify';
  }""",
            """  voiceNameLabel(): string {
    return this.getProvOpt('speechify', 'voice'); // SPFY1
  }
  isProviderVoice(): boolean {
    return true; // SPFY1
  }""", "voicelabel")
    s = sub(s,
            """    const k = this.getVoiceKind();
    if (k !== 'groq' && k !== 'speechify') {
      return;
    }
    const def = k === 'groq' ? 'troy' : 'george';""",
            """    const k = 'speechify'; // SPFY1
    const def = 'george';""", "voicename")
    s = sub(s, "message: 'The voice id, for example ' + def + '. Empty = default (' + def + ').',",
            "message: 'Speechify voice id or name from your workspace (for example ' + def + '). If it is not found, the radio picks a working voice by itself.',",
            "voicenamemsg")

    # 6. Speechify request uses the resolved voice id
    s = sub(s, "    const voice = this.getProvOpt(p, 'voice');\n    const pieces: Uint8Array[] = [];",
            "    const voice = p === 'speechify' ? await this.spfyVoiceFor(r.key) : this.getProvOpt(p, 'voice');\n"
            "    const pieces: Uint8Array[] = [];", "provaudio")

    # 6b. Speechify audio: ask for wav (unambiguous), accept l16/pcm replies too
    s = sub(s, "body: JSON.stringify({input: chunk, voice_id: voice, model, audio_format: 'pcm'}),",
            "body: JSON.stringify({input: chunk, voice_id: voice, model, audio_format: 'wav'}),", "spfy-wav")
    s = sub(s,
            """        const fmt = String(j.audio_format || 'pcm').toLowerCase();
        if (fmt !== 'pcm' && fmt !== 'wav') {
          throw new ApiError(0, 'unexpected audio format ' + fmt);
        }
        const w = this.wavToPcm(this.b64ToBytes(String(j.audio_data)), 24000);""",
            """        const fmt = String(j.audio_format || 'wav').toLowerCase();
        const fr = parseInt((fmt.match(/rate=(\\d+)/) || [])[1] || '24000', 10) || 24000;
        const bytes = this.b64ToBytes(String(j.audio_data));
        const isRiff = bytes.length > 44 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46;
        let w: {pcm: Uint8Array; rate: number};
        if (isRiff) {
          w = this.wavToPcm(bytes, fr);
        } else if (/^l16/.test(fmt)) {
          // L16 is big-endian by definition: swap to little-endian for playback
          const sw = new Uint8Array(bytes.length - (bytes.length % 2));
          for (let i = 0; i < sw.length; i += 2) {
            sw[i] = bytes[i + 1];
            sw[i + 1] = bytes[i];
          }
          w = {pcm: sw, rate: fr};
        } else if (/pcm|raw/.test(fmt)) {
          w = {pcm: bytes, rate: fr};
        } else {
          throw new ApiError(0, 'unexpected audio format ' + fmt);
        }""", "spfy-format")

    # 7. the speech function itself: Speechify only
    new_fetch = r'''  // SPFY1: ask Speechify which voices this key can use, match the saved voice by id or display name
  private async spfyVoiceFor(key: string): Promise<string> {
    const wanted = this.getProvOpt('speechify', 'voice') || 'george';
    const force = this.spfyForce;
    this.spfyForce = false;
    try {
      if (force || !this.spfyVoices || Date.now() - this.spfyVoicesAt > 3600 * 1000) {
        const resp = await this.timedFetch(
          'https://api.speechify.ai/v1/voices',
          {headers: {Authorization: 'Bearer ' + key}},
          15000,
        );
        const raw = await resp.text();
        if (!resp.ok) {
          this.log('Speechify voice list HTTP ' + resp.status + ': ' + raw.slice(0, 200));
        } else {
          const j: any = JSON.parse(raw);
          const arr: any[] = Array.isArray(j) ? j : j?.voices || j?.data || j?.items || [];
          this.spfyVoices = arr
            .map((v: any) => ({
              id: String(v?.id || v?.voice_id || ''),
              name: String(v?.display_name || v?.name || ''),
              en: JSON.stringify(v || {}).toLowerCase().indexOf('"en') >= 0,
            }))
            .filter(v => v.id);
          this.spfyVoicesAt = Date.now();
          this.log('Speechify voices available: ' + this.spfyVoices.length);
          this.log('Speechify voice names: ' + this.spfyVoices.map(v => v.name || v.id).join(', '));
        }
      }
    } catch (e: any) {
      this.log('Speechify voice list failed: ' + String(e?.message || e));
    }
    const list = this.spfyVoices || [];
    if (list.length === 0) {
      return wanted;
    }
    const w = wanted.toLowerCase();
    const hit =
      list.find(v => v.id.toLowerCase() === w) ||
      list.find(v => v.name.toLowerCase() === w) ||
      list.find(v => v.name.toLowerCase().indexOf(w) === 0);
    if (hit) {
      return hit.id;
    }
    const pick = list.find(v => v.en) || list[0];
    this.log('Speechify voice "' + wanted + '" is not in your workspace, using "' + (pick.name || pick.id) + '" (' + pick.id + ')');
    this.setProvOpt('speechify', 'voice', pick.id);
    this.emitUi();
    return pick.id;
  }

  // SPFY1: the only speech path. Speechify, nothing else.
  private async fetchGeminiAudio(text: string): Promise<any> {
    const cleanSpeech = stripMoodAndCadenceCues(text);
    if (!cleanSpeech) return null;
    const key = this.getVoiceKey();
    if (!key) {
      this.log('voice: no Speechify key set (Voice key in the radio menu)');
      return null;
    }
    let m = this.getVoiceModel();
    if (!m || /gemini|orpheus|groq/i.test(m)) {
      m = this.getProvOpt('speechify', 'model');
    }
    const models = [m];
    if (m !== 'simba-3.0') models.push('simba-3.0'); // simba-english is retired
    for (const model of models) {
      const route = {model: 'speechify:' + model, id: 101, key, tag: 'speechify:' + model + '@101'};
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const pa = await this.providerAudio(route, cleanSpeech);
          this.lastVoice = route.model;
          this.log('TTS ok ' + route.model + ' voice=' + this.getProvOpt('speechify', 'voice') + ' ms=' + pa.ms);
          this.emitUi();
          return pa;
        } catch (e: any) {
          const body = String(e?.body || e?.message || e);
          this.log('Speechify ' + model + ' failed (try ' + (attempt + 1) + '): ' + String(e?.message || e).slice(0, 300));
          if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
            toast('Speechify key was rejected', true);
            return null;
          }
          if (/voice/i.test(body) && attempt === 0) {
            this.spfyForce = true; // reload the voice list and re-pick
            continue;
          }
          if (e instanceof ApiError && e.status === 429 && attempt === 0) {
            await this.sleep(3000);
            continue;
          }
          break;
        }
      }
    }
    return null;
  }
'''
    s = rsub(s, r"  private async fetchGeminiAudio\(text: string\): Promise<any> \{.*?(?=\n  // ---------- Gemini \(brain\) ----------)",
             new_fetch, "fetch")

    # 8. gamepad menu: no speaker list, Speechify-only provider screen
    s = sub(s,
            """        if (this.isProviderVoice()) {
          await this.promptForVoiceName(showInput);
        } else {
          screen = 'speaker';
        }""",
            "        await this.promptForVoiceName(showInput);", "menu-speaker")
    s = rsub(s, r"      \} else if \(screen === 'speaker'\) \{\n        items = SPEAKERS\.map\([^\n]*\n        items\.push\(\{id: 'radio:back', title: 'Back'\}\);\n(?=      \} else if \(screen === 'gapmin'\))",
             "", "menu-speaker-screen")
    s = sub(s,
            """      } else if (id.startsWith('radio:spk:')) {
        this.setSpeaker(id.slice('radio:spk:'.length));
        screen = 'main';
""", "", "menu-spk")
    s = sub(s, "{id: 'radio:vprov', title: 'Voice providers (Speechify, Groq)'}",
            "{id: 'radio:vprov', title: 'Speechify (key, voice, model)'}", "menu-vprov-title")
    s = sub(s, "for (const pv of ['speechify', 'groq']) {", "for (const pv of ['speechify']) {", "menu-vprov")
    s = sub(s, ": ['speechify:' + this.getProvOpt('speechify', 'model'), 'groq:' + this.getProvOpt('groq', 'model')];",
            ": ['speechify:' + this.getProvOpt('speechify', 'model')];", "choices-provs")
    s = sub(s, "for (const m of provs.concat(base, av)) {", "for (const m of brain ? provs.concat(base, av) : provs) {", "choices-voice")
    s = s.replace("export const SPEAKERS", "// SPFY1\nexport const SPEAKERS", 1)
    RADIO.write_text(s)
    print("radio.ts: Speechify only, Gemini voices removed, voice lookup added")

# ------------------------------------------------------------------ radioHelpers.ts
H = find("src/utils/radioHelpers.ts")
h = H.read_text()
if "export const DEFAULT_SPEAKER = 'Charon';" in h:
    h = h.replace("export const DEFAULT_SPEAKER = 'Charon';", "export const DEFAULT_SPEAKER = 'george';")
    H.write_text(h)
    print("radioHelpers.ts: Charon default removed")

# ------------------------------------------------------------------ overlay (menu 1)
O = find("src/components/BushRadioOverlay.tsx")
o = O.read_text()
if "SPEAKERS" in o:
    o = sub(o, "import radio, {PERSONAS, SPEAKERS} from '../utils/radio';",
            "import radio, {PERSONAS} from '../utils/radio';", "overlay-import")
    o = rsub(o, r"\n[ ]*\{/\* Voice \(Gemini only, Device TTS removed\) \*/\}.*?(?=\n[ ]*\{/\* Session-start)",
             "", "overlay-chips")
    o = sub(o, "Voice key (Gemini / Speechify / Groq): ", "Voice key (Speechify): ", "overlay-label")
    O.write_text(o)
    print("BushRadioOverlay.tsx: Gemini voice picker removed")

print("SPEECHIFY-ONLY PATCH OK")
