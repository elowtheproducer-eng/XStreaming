#!/usr/bin/env python3
"""
apply_keys_patch.py (KEYS1) - one clean set of key + model settings for BOTH Sim Radio menus.

Run from the REPO ROOT, as the very LAST patch (AFTER apply_models_patch.py):
    python3 .github/apply_keys_patch.py

What it does
------------
Both menus (the native pause menu > Sim Radio, and the Bush Radio panel with the floating button) now show
ONLY these four settings, and nothing else about keys or models:

  1. Voice key    - ONE slot. Paste a Gemini, Speechify or Groq key; the type is detected from the key:
                      AIza...  -> Gemini
                      gsk_...  -> Groq
                      anything else -> Speechify
  2. Brain key    - ONE slot. Gemini only (must start with AIza).
  3. Voice model  - ONE slot. Empty = Auto (built-in list with fallbacks). Typed id, for example
                      Gemini:    gemini-2.5-flash-preview-tts
                      Speechify: simba-3.5
                      Groq:      canopylabs/orpheus-v1-english
                    (the provider comes from the voice key, so you do not type "groq:" or "speechify:").
  4. Brain model  - ONE slot. Empty = Auto (built-in list with fallbacks). Gemini model id.

Removed from both menus: the 5 key slots, the spare/default key, key plan, the Models screen with 3 slots each,
fallback slots, the model picker lists, the model report, the Voice providers screen, and the panel's key chips.
(The old code is left in the file, unreachable, so nothing else breaks.)

Under the hood
--------------
  * Brain key  -> stored as key slot 1.  Used by the brain, and as the Gemini voice fallback.
  * Voice key  -> Gemini: key slot 2.  Groq / Speechify: that provider's key. Only one is active at a time.
  * Key pools now use only those slots (the spare key and the old slots 3-5 are ignored).
  * First run after the update moves your old keys over once: first Gemini key -> Brain, a Speechify/Groq key
    (or else the next Gemini key) -> Voice. Old fallback model slots are dropped.

Safe to re-run (KEYS1 marker). If an anchor is missing it STOPS and prints context: paste that log back.
"""
import pathlib
import sys

MARK = "KEYS1"
RADIO = "src/utils/radio.ts"
OVERLAY = "src/components/BushRadioOverlay.tsx"


def die(msg, text=None, keywords=()):
    print("\n==================== KEYS PATCH FAILED ====================")
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
    print("===========================================================")
    sys.exit(1)


def once(text, old, new, label, keywords=()):
    n = text.count(old)
    if n != 1:
        die("Anchor '%s' expected once, found %d times." % (label, n), text,
            keywords or (old.strip().split("\n")[0][:30],))
    return text.replace(old, new)


def cut_between(text, start, end, new, label):
    a = text.find(start)
    if a < 0 or text.count(start) != 1:
        die("Start anchor '%s' expected once, found %d times." % (label, text.count(start)), text, (start.strip()[:25],))
    b = text.find(end, a)
    if b < 0:
        die("End anchor for '%s' not found after the start anchor." % label, text, (end.strip()[:25],))
    return text[:a] + new + text[b:]


MEMBERS = r"""  // KEYS1: four settings only - voice key (Gemini / Speechify / Groq, detected), brain key (Gemini), voice model, brain model
  private keysChecked = false;
  private keysReady() {
    if (this.keysChecked) {
      return;
    }
    this.keysChecked = true;
    try {
      if (storage.getString('radio_keys_v2')) {
        return;
      }
      storage.set('radio_keys_v2', '1');
      // one-time move of the old keys: first Gemini key -> brain, speech provider key (or next Gemini key) -> voice
      const legacy: string[] = [];
      const olds = [1, 2, 3, 4, 5].map(i => this.getSlotKey(i)).concat([this.getMainKey()]);
      for (const k of olds) {
        if (k && /^AIza/.test(k) && legacy.indexOf(k) < 0) {
          legacy.push(k);
        }
      }
      if (legacy[0]) {
        this.setSlotKey(1, legacy[0]);
      }
      const sp = this.getProvKey('speechify');
      const gq = this.getProvKey('groq');
      const g2 = legacy.length > 1 ? legacy[1] : '';
      const v = sp || gq || g2;
      const kind = sp ? 'speechify' : gq ? 'groq' : g2 ? 'gemini' : '';
      storage.set('radio_vkey', v);
      storage.set('radio_vkind', kind);
      this.setSlotKey(2, kind === 'gemini' ? v : '');
      this.setProvKey('speechify', kind === 'speechify' ? v : '');
      this.setProvKey('groq', kind === 'groq' ? v : '');
      for (const mk of ['brain', 'voice']) {
        this.setModelSlot(mk, 1, '');
        this.setModelSlot(mk, 2, '');
      }
      const vm = this.getModelSlot('voice', 0);
      if (vm && this.voiceModelKind(vm) !== kind) {
        this.setModelSlot('voice', 0, '');
      }
    } catch (e) {}
  }
  private voiceModelKind(m: string): string {
    return m.indexOf('speechify:') === 0 ? 'speechify' : m.indexOf('groq:') === 0 ? 'groq' : 'gemini';
  }
  voiceKindOf(k: string): string {
    const t = (k || '').trim();
    if (!t) {
      return '';
    }
    if (/^AIza/.test(t)) {
      return 'gemini';
    }
    if (/^gsk_/.test(t)) {
      return 'groq';
    }
    return 'speechify';
  }
  getBrainKey(): string {
    this.keysReady();
    return this.getSlotKey(1);
  }
  setBrainKey(k: string) {
    this.keysReady();
    this.setSlotKey(1, (k || '').trim());
    this.clearCooldownFor(1);
    this.available = null;
  }
  getVoiceKey(): string {
    this.keysReady();
    return storage.getString('radio_vkey') || '';
  }
  getVoiceKind(): string {
    this.keysReady();
    return storage.getString('radio_vkind') || '';
  }
  setVoiceKey(k: string): string {
    this.keysReady();
    const t = (k || '').trim();
    const kind = this.voiceKindOf(t);
    storage.set('radio_vkey', t);
    storage.set('radio_vkind', kind);
    this.setSlotKey(2, kind === 'gemini' ? t : '');
    this.setProvKey('speechify', kind === 'speechify' ? t : '');
    this.setProvKey('groq', kind === 'groq' ? t : '');
    const vm = this.getModelSlot('voice', 0);
    if (vm && this.voiceModelKind(vm) !== kind) {
      this.setVoiceModel('');
    }
    this.clearCooldownFor(2);
    this.clearCooldownFor(101);
    this.clearCooldownFor(102);
    this.available = null;
    return kind;
  }
  getVoiceModel(): string {
    this.keysReady();
    return this.getModelSlot('voice', 0).replace(/^(speechify|groq):/, '');
  }
  setVoiceModel(m: string) {
    this.keysReady();
    const kind = this.getVoiceKind();
    let v = (m || '').trim().replace(/^models\//, '');
    if (v && v.indexOf(':') < 0 && (kind === 'speechify' || kind === 'groq')) {
      v = kind + ':' + v;
    }
    for (let i = 0; i < 3; i++) {
      this.setModelSlot('voice', i, '');
    }
    if (v) {
      this.setModelSlot('voice', 0, v);
    }
  }
  getBrainModel(): string {
    this.keysReady();
    return this.getModelSlot('brain', 0);
  }
  setBrainModel(m: string) {
    this.keysReady();
    const v = (m || '').trim().replace(/^models\//, '');
    for (let i = 0; i < 3; i++) {
      this.setModelSlot('brain', i, '');
    }
    if (v) {
      this.setModelSlot('brain', 0, v);
    }
  }
  private maskKey(k: string): string {
    return k.length > 8 ? '...' + k.slice(-4) : 'set';
  }
  voiceKeyLabel(): string {
    const k = this.getVoiceKey();
    if (!k) {
      return 'not set';
    }
    const names: Record<string, string> = {gemini: 'Gemini', groq: 'Groq', speechify: 'Speechify'};
    return (names[this.getVoiceKind()] || '?') + ' (' + this.maskKey(k) + ')';
  }
  brainKeyLabel(): string {
    const k = this.getBrainKey();
    return k ? 'Gemini (' + this.maskKey(k) + ')' : 'not set';
  }
  voiceModelLabel(): string {
    return this.getVoiceModel() || 'Auto';
  }
  brainModelLabel(): string {
    return this.getBrainModel() || 'Auto';
  }
  async promptForVoiceKey(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Voice key',
      message:
        'Paste a Gemini (AIza...), Groq (gsk_...) or Speechify key. The type is detected from the key. Empty clears it.',
      hint: 'AIza... / gsk_... / Speechify key',
      text: this.getVoiceKey(),
      maxLength: 200,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      const v = String(r.text || '').trim();
      if (/\s/.test(v)) {
        toast('A key cannot contain spaces', true);
        return;
      }
      const kind = this.setVoiceKey(v);
      const names: Record<string, string> = {gemini: 'Gemini', groq: 'Groq', speechify: 'Speechify'};
      toast(v ? 'Voice key saved: ' + (names[kind] || '?') : 'Voice key cleared');
    }
  }
  async promptForBrainKey(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Brain key',
      message: 'Gemini key only (aistudio.google.com/apikey). Empty clears it.',
      hint: 'AIza...',
      text: this.getBrainKey(),
      maxLength: 200,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      const v = String(r.text || '').trim();
      if (v && !/^AIza\S+$/.test(v)) {
        toast('The brain key must be a Gemini key (starts with AIza)', true);
        return;
      }
      this.setBrainKey(v);
      toast(v ? 'Brain key saved' : 'Brain key cleared');
    }
  }
  async promptForVoiceModel(showInput: (o: any) => Promise<any>) {
    const kind = this.getVoiceKind();
    const ex =
      kind === 'groq'
        ? 'canopylabs/orpheus-v1-english'
        : kind === 'speechify'
        ? 'simba-3.5'
        : 'gemini-2.5-flash-preview-tts';
    const r = await showInput({
      title: 'Voice model',
      message:
        'The model id for your voice key' +
        (kind ? '' : ' (set the voice key first)') +
        ', for example ' + ex + '. Empty = Auto.',
      hint: ex,
      text: this.getVoiceModel(),
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
      if (v && !kind) {
        toast('Set the voice key first, then the model', true);
        return;
      }
      if (v && v.indexOf(':') > 0 && this.voiceModelKind(v) !== kind) {
        toast('That model does not match your voice key type', true);
        return;
      }
      this.setVoiceModel(v);
      toast(v ? 'Voice model: ' + this.getVoiceModel() : 'Voice model: Auto');
    }
  }
  async promptForBrainModel(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Brain model',
      message: 'The Gemini model id, for example gemini-3.1-flash-lite. Empty = Auto.',
      hint: 'gemini-...',
      text: this.getBrainModel(),
      maxLength: 80,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      const v = String(r.text || '').trim().replace(/^models\//, '');
      if (v && !/^[A-Za-z0-9._\/-]+$/.test(v)) {
        toast('That is not a valid model id', true);
        return;
      }
      this.setBrainModel(v);
      toast(v ? 'Brain model: ' + v : 'Brain model: Auto');
    }
  }
"""

MENU_ITEMS = (
    "          {id: 'radio:vkey', title: 'Voice key: ' + this.voiceKeyLabel()},\n"
    "          {id: 'radio:bkey', title: 'Brain key: ' + this.brainKeyLabel()},\n"
    "          {id: 'radio:vmodel', title: 'Voice model: ' + this.voiceModelLabel()},\n"
    "          {id: 'radio:bmodel', title: 'Brain model: ' + this.brainModelLabel()},\n"
)

HANDLERS = r"""      } else if (id === 'radio:vkey') {
        await this.promptForVoiceKey(showInput);
      } else if (id === 'radio:bkey') {
        await this.promptForBrainKey(showInput);
      } else if (id === 'radio:vmodel') {
        await this.promptForVoiceModel(showInput);
      } else if (id === 'radio:bmodel') {
        await this.promptForBrainModel(showInput);
"""

PANEL = r"""                {/* KEYS1: the only key and model settings */}
                <Text style={styles.sectionLabel}>Keys & Models</Text>
                <TouchableOpacity
                  onPress={async () => {
                    await radio.promptForVoiceKey(showInput);
                    radio.refreshUi?.();
                  }}
                  style={styles.wideRowBtn}>
                  <Text style={styles.wideRowTxt}>
                    Voice key (Gemini / Speechify / Groq): {radio.voiceKeyLabel()}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={async () => {
                    await radio.promptForBrainKey(showInput);
                    radio.refreshUi?.();
                  }}
                  style={styles.wideRowBtn}>
                  <Text style={styles.wideRowTxt}>
                    Brain key (Gemini): {radio.brainKeyLabel()}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={async () => {
                    await radio.promptForVoiceModel(showInput);
                    radio.refreshUi?.();
                  }}
                  style={styles.wideRowBtn}>
                  <Text style={styles.wideRowTxt}>
                    Voice model: {radio.voiceModelLabel()}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={async () => {
                    await radio.promptForBrainModel(showInput);
                    radio.refreshUi?.();
                  }}
                  style={styles.wideRowBtn}>
                  <Text style={styles.wideRowTxt}>
                    Brain model: {radio.brainModelLabel()}
                  </Text>
                </TouchableOpacity>

"""


def patch_radio():
    p = pathlib.Path(RADIO)
    if not p.exists():
        die("src/utils/radio.ts not found. Run the other patches first.")
    t = p.read_text(encoding="utf-8")
    if MARK in t:
        print("radio.ts: KEYS patch already applied.")
        return
    if "MODELS3" not in t:
        die("The models patch (MODELS3) is not in radio.ts. Run apply_models_patch.py first.")

    # key pools: brain = slot 1, voice = slot 2 then slot 1 (Gemini voice fallback uses the brain key)
    t = once(t, "const BRAIN_KEY_IDS = [1, 2, 3, 4, 5];\n", "const BRAIN_KEY_IDS = [1]; // KEYS1\n",
             "BRAIN_KEY_IDS", ("BRAIN_KEY_IDS",))
    t = once(t, "const VOICE_KEY_IDS = [1, 2, 3, 4, 5];\n", "const VOICE_KEY_IDS = [2, 1]; // KEYS1\n",
             "VOICE_KEY_IDS", ("VOICE_KEY_IDS",))

    # getApiKey: the brain key only
    t = once(t,
             "    return this.atcKeys.brain[0] || this.getSlotKey(1) || this.getMainKey() || this.firstSlotKey() || this.atcKeys.voice[0] || '';\n",
             "    this.keysReady(); // KEYS1\n    return this.getSlotKey(1);\n",
             "getApiKey()", ("getApiKey",))

    # keyPool: only the slots asked for (no spare key, no external keys)
    t = once(t,
             "    const slotList = ids.map(id => ({id, key: this.getSlotKey(id)}));\n"
             "    const pool = collectKeyPool(slotList, this.getMainKey(), this.externalKeys);\n"
             "    if (pool.length === 0) {\n"
             "      const any = this.firstSlotKey();\n"
             "      if (any) pool.push({id: 0, key: any});\n"
             "    }\n"
             "    return pool;\n",
             "    this.keysReady(); // KEYS1\n"
             "    const slotList = ids.map(id => ({id, key: this.getSlotKey(id)}));\n"
             "    return collectKeyPool(slotList, '', []);\n",
             "keyPool()", ("keyPool",))

    # old single-key prompts now open the brain key prompt (used by start / talk now / the panel)
    t = once(t,
             "  async promptForKey(showInput: (o: any) => Promise<any>) {\n",
             "  async promptForKey(showInput: (o: any) => Promise<any>) {\n"
             "    return this.promptForBrainKey(showInput); // KEYS1\n"
             "  }\n"
             "  async promptForKeyOld(showInput: (o: any) => Promise<any>) {\n",
             "promptForKey()", ("promptForKey",))
    t = once(t,
             "  async promptForSlotKey(id: number, showInput: (o: any) => Promise<any>) {\n",
             "  async promptForSlotKey(id: number, showInput: (o: any) => Promise<any>) {\n"
             "    return this.promptForBrainKey(showInput); // KEYS1\n"
             "  }\n"
             "  async promptForSlotKeyOld(id: number, showInput: (o: any) => Promise<any>) {\n",
             "promptForSlotKey()", ("promptForSlotKey",))

    # key count shown in status / badge: brain + voice = 2
    t = once(t,
             "  keysSetCount(): number {\n    let n = 0;\n",
             "  keysSetCount(): number {\n"
             "    return (this.getBrainKey() ? 1 : 0) + (this.getVoiceKey() ? 1 : 0); // KEYS1\n"
             "  }\n"
             "  private keysSetCountOld(): number {\n    let n = 0;\n",
             "keysSetCount()", ("keysSetCount",))
    t = once(t, "' | keys: ' + this.keysSetCount() + '/5' +\n", "' | keys: ' + this.keysSetCount() + '/2' +\n",
             "status keys text", ("keys: ",))

    # no more auto-copying of SQUAWK keys into the slots: just run the one-time move of the old keys
    t = once(t,
             "  async syncExternalKeys() {\n    try {\n",
             "  async syncExternalKeys() {\n"
             "    this.keysReady(); // KEYS1\n"
             "    this.emitUi();\n"
             "  }\n"
             "  async syncExternalKeysOld() {\n    try {\n",
             "syncExternalKeys()", ("syncExternalKeys",))

    # new members (before log())
    t = once(t,
             "  private log(m: string) {\n    this.trackModels(m); // MODELS3\n",
             MEMBERS + "  private log(m: string) {\n    this.trackModels(m); // MODELS3\n",
             "log()", ("private log",))

    # native menu: main screen shows the four settings; the Models item and the key items are gone
    t = once(t,
             "          {id: 'radio:keys', title: 'API keys (' + (KEY_SLOTS.filter(s => this.getSlotKey(s.id)).length + (this.getMainKey() ? 1 : 0)) + ' of ' + (KEY_SLOTS.length + 1) + ' set)'},\n",
             MENU_ITEMS, "main menu: API keys item", ("radio:keys",))
    t = once(t,
             "          {id: 'radio:models', title: 'Models: brain ' + this.slotSummary('brain') + ' | voice ' + this.slotSummary('voice')},\n",
             "", "main menu: Models item", ("radio:models",))
    t = once(t,
             "          {id: 'radio:key', title: this.getMainKey() ? 'Default API key: set' : 'Default API key: not set'},\n"
             "          {id: 'radio:keys', title: 'Keys per model (' + KEY_SLOTS.filter(s => this.getSlotKey(s.id)).length + ' of ' + KEY_SLOTS.length + ' set)'},\n",
             "", "more menu: key items", ("Default API key",))

    # handlers for the four items
    t = once(t, "      } else if (id === 'radio:models') {\n",
             HANDLERS + "      } else if (id === 'radio:models') {\n",
             "menu handlers", ("radio:models",))

    p.write_text(t, encoding="utf-8")
    print("radio.ts: voice key / brain key / voice model / brain model added; old key and model screens removed from the native menu")


def patch_overlay():
    p = pathlib.Path(OVERLAY)
    if not p.exists():
        print("BushRadioOverlay.tsx not found: panel left as is (the native menu is done).")
        return
    t = p.read_text(encoding="utf-8")
    if MARK in t:
        print("BushRadioOverlay.tsx: KEYS patch already applied.")
        return
    t = once(t, "import radio, {KEY_SLOTS, PERSONAS, SPEAKERS} from '../utils/radio';\n",
             "import radio, {PERSONAS, SPEAKERS} from '../utils/radio';\n", "overlay import", ("KEY_SLOTS",))
    t = once(t, "{snap.keysSet}/5 keys", "{snap.keysSet}/2 keys", "panel badge", ("keys",))
    t = cut_between(t, "                {/* 5 API Keys + Spare */}\n", "                {/* Character */}\n",
                    PANEL, "panel key chips")
    p.write_text(t, encoding="utf-8")
    print("BushRadioOverlay.tsx: key chips replaced by the four settings")


def main():
    patch_radio()
    patch_overlay()
    print("\nKEYS patch OK")


main()
