#!/usr/bin/env python3
"""
apply_cabin_fix_patch.py  -  XStreaming: fixes the Sim Radio quality patch, then wires Cabin Crew + voice rotation.

Run from the REPO ROOT, AFTER apply_radio_patch.py (which runs apply_brain_patch.py itself):
    python3 .github/apply_cabin_fix_patch.py

What it does, in order
  1. repairs .github/apply_quality_patch.py (its "nerd level 3" anchor never matched, so the quality patch
     never ran: no said.ts, no repeat guard, no talk rules, no key plan)
  2. runs apply_quality_patch.py if it has not been applied yet
  3. runs apply_crew_patch.py if src/utils/crew.ts is missing (writes crew.ts + voiceRotation.ts)
  4. wires src/utils/radio.ts
       - speech: the five TTS models are used IN TURN (voiceRotation), 20 s rest per model+key route
       - word floor: any radio line under 40 words is rewritten once (prompt text raised to 40 as well)
       - Cabin Crew: pressing a command speaks it. "command" kinds and emergencies use the built-in script
         at once (no AI wait); "announce" kinds go to the AI with the screenshot and fall back to the script
       - crew sequence keeps its place (next announcement is highlighted), can be synced from the radio notes
       - radio chatter pauses for the announcement and resumes afterwards (not after an emergency)
       - menu: "Cabin crew announcements" is the 3rd item of the Sim Radio menu; screens are short and
         Back is always near the top, so nothing important sits where the list cannot scroll
       - status screen shows which speech model is next
  5. patches src/pages/NativeStream.tsx: the Sim Radio entry moves to the TOP of the pause menu
  6. patches .github/workflows/build-tilt-apk.yml: one step runs this script after the Sim Radio patch
     (the old separate quality / crew steps are removed so nothing runs twice)

Safe to re-run (CREW marker). If an anchor is missing it STOPS and prints context: paste that log back.
"""
import pathlib
import subprocess
import sys

RADIO = "src/utils/radio.ts"
NATIVE = "src/pages/NativeStream.tsx"
WORKFLOW = ".github/workflows/build-tilt-apk.yml"
QUALITY = ".github/apply_quality_patch.py"
CREW_PATCH = ".github/apply_crew_patch.py"


def die(msg, path=None, text=None, keywords=()):
    print("\n==================== CABIN FIX PATCH FAILED ====================")
    print(msg)
    if path:
        print("File:", path)
    if text is not None and keywords:
        shown = 0
        for i, ln in enumerate(text.split("\n")):
            if any(k in ln for k in keywords):
                print("  %5d | %s" % (i + 1, ln.rstrip()[:160]))
                shown += 1
                if shown >= 40:
                    break
        if shown == 0:
            print("  (no matching lines)")
    print("\nPaste this whole log back to the model.")
    print("================================================================")
    sys.exit(1)


def read(p):
    raw = pathlib.Path(p).read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def write(p, text, crlf=False):
    if crlf:
        text = text.replace("\n", "\r\n")
    pathlib.Path(p).write_bytes(text.encode("utf-8"))


def once(text, find, repl, label, path):
    n = text.count(find)
    if n != 1:
        die("edit '%s': expected exactly 1 match, found %d." % (label, n), path, text,
            (find.strip().split("\n")[0][:30],))
    return text.replace(find, repl, 1)


def between(text, start, end, new, label, path):
    if text.count(start) != 1:
        die("region '%s': start anchor found %d times (expected 1)." % (label, text.count(start)), path, text,
            (start.strip().split("\n")[0][:30],))
    a = text.index(start)
    b = text.find(end, a + len(start))
    if b < 0:
        die("region '%s': end anchor not found." % label, path, text, (end.strip().split("\n")[0][:30],))
    return text[:a] + new + text[b:]


def soft(text, find, repl, label):
    if text.count(find) == 1:
        return text.replace(find, repl, 1)
    print("  note: '%s' not found exactly once, left as it was" % label)
    return text


def run(script):
    print("\nRunning %s ..." % script)
    r = subprocess.run([sys.executable, script])
    if r.returncode != 0:
        print("\n%s failed, see the log above." % script)
        sys.exit(r.returncode)


# ---------------------------------------------------------------------------------------------
# step 1: repair the quality patch anchor
# ---------------------------------------------------------------------------------------------
def fix_quality_patch():
    text, crlf = read(QUALITY)
    lines = text.split("\n")
    hit = False
    for i, ln in enumerate(lines):
        if "text = once(text," in ln and "here is why" in ln:
            good = "    text = once(text, 'and a short \"here is why\".',"
            if ln != good:
                lines[i] = good
                hit = True
    if hit:
        write(QUALITY, "\n".join(lines), crlf)
        print("repaired the 'nerd level 3' anchor in apply_quality_patch.py")
    else:
        print("apply_quality_patch.py anchor already fine")


# ---------------------------------------------------------------------------------------------
# step 4: radio.ts wiring
# ---------------------------------------------------------------------------------------------
IMPORTS = """import {
  CREW_CATEGORIES,
  CREW_SYSTEM_PROMPT,
  CrewCommand,
  CrewState,
  crewAfterPress,
  crewCommandsIn,
  crewFind,
  crewInitialState,
  crewNextId,
  crewScript,
  crewShortNote,
  crewStateFromNotes,
  crewUserPrompt,
  crewWordCount,
} from './crew'; // CREW
import {
  RotationState,
  afterSuccess,
  buildVoiceRoutes,
  isTooShort,
  markUsed,
  newRotationState,
  rotationText,
  shortRetryNote,
  wordCount,
} from './voiceRotation'; // CREW
"""

FIELDS = """  private rot: RotationState = newRotationState(); // CREW
  private crewState: CrewState = crewInitialState();
  private crewPressed = 0;
  private crewBusy = false;
"""

VOICE_ROUTES = """  // CREW: the five speech models are used in turn (voiceRotation.ts). Each model+key route rests at least
  // 20 s between uses, benched routes are skipped, and routes still resting are tried last, never dropped.
  private voiceRoutes(): Array<{model: string; id: number; key: string; tag: string}> {
    return buildVoiceRoutes(this.keyPool(VOICE_KEY_IDS), this.cooldown, this.rot, Date.now());
  }

"""

FLOOR = """    if (text && isTooShort(text)) {
      const n = wordCount(text);
      this.log('too short (' + n + ' words), asking once more'); // CREW
      this.dupNote = shortRetryNote(n);
      try {
        const again = this.polish(await this.ask(frame));
        if (again && wordCount(again) > n && !said.duplicateOf(again, this.lastTold)) {
          text = again;
        }
      } catch (e) {
        // keep the short line rather than going silent
      } finally {
        this.dupNote = '';
      }
    }
    return text;
  }
"""

CREW_METHODS = """  // ---------- CREW: cabin crew announcements ----------
  crewNextLabel(): string {
    const nid = crewNextId(this.crewState);
    const c = nid ? crewFind(nid) : undefined;
    return c ? c.label : '';
  }

  crewResync(): boolean {
    const s = crewStateFromNotes(this.getNotes());
    if (s) {
      this.crewState = s;
      return true;
    }
    return false;
  }

  crewReset() {
    this.crewState = crewInitialState();
    this.crewPressed = 0;
  }

  // one button press: speak the command, or ask the AI (with the screen) and speak its reply
  async crewPress(cmd: CrewCommand) {
    if (this.crewBusy && !cmd.emergency) {
      toast('Crew: finishing the last announcement');
      return;
    }
    this.crewBusy = true;
    const wasOn = this.on;
    const id = ++this.run;
    try {
      try {
        RadioModule?.stopSpeaking?.();
      } catch (e) {}
      toast('Crew: ' + cmd.label);
      const text = await this.crewText(cmd);
      if (this.run !== id || !text) {
        return;
      }
      this.crewState = crewAfterPress(this.crewState, cmd.id);
      this.crewPressed++;
      try {
        brain.ingest({log: 'Cabin crew: ' + cmd.label}, this.getAircraft());
      } catch (be) {}
      // the three short emergency calls use the phone voice: no network wait at all
      let audio: any = null;
      if (this.getSpeaker() !== 'Phone voice' && !cmd.short_ok) {
        audio = await this.fetchGeminiAudio(text);
      }
      if (this.run !== id) {
        return;
      }
      const ms = audio ? audio.ms : Math.round((crewWordCount(text) / 2.6) * 1000);
      this.log('crew ' + cmd.id + ' voice=' + (audio ? this.lastVoice : 'phone') + ' said=' + text);
      await this.play({text, audio, ms}, id);
    } catch (e: any) {
      this.noteError(e);
    } finally {
      if (this.run === id) {
        this.crewBusy = false;
        // chatter comes back after a normal announcement, not after an emergency
        if (wasOn && this.on && (!cmd.emergency || cmd.id === 'all_clear')) {
          this.loop(++this.run);
        }
      }
    }
  }

  private async crewText(cmd: CrewCommand): Promise<string> {
    // commands and emergencies must start at once: the built-in script is standard PA wording
    if (cmd.kind === 'command' || cmd.emergency) {
      return crewScript(cmd);
    }
    let text = '';
    if (this.getApiKey()) {
      try {
        text = await this.crewAsk(cmd);
      } catch (e: any) {
        this.log('crew: AI failed, using the built-in script: ' + String(e?.message || e));
      }
    }
    return text || crewScript(cmd);
  }

  private async crewAsk(cmd: CrewCommand): Promise<string> {
    await this.refreshAvailable(this.getApiKey());
    const frame: string = await RadioModule.captureFrame(FRAME_W, FRAME_Q);
    const user = crewUserPrompt(cmd, {trip: this.getTrip(), aircraft: this.getAircraft(), notes: this.getNotes()});
    let text = await this.crewRoutes(user, frame);
    if (text && !cmd.short_ok && isTooShort(text)) {
      const n = crewWordCount(text);
      try {
        const again = await this.crewRoutes(user + crewShortNote(n), frame);
        if (again && crewWordCount(again) > n) {
          text = again;
        }
      } catch (e) {}
    }
    return text;
  }

  private async crewRoutes(user: string, frame: string): Promise<string> {
    const skip: Record<string, boolean> = {};
    let tries = 0;
    for (const r of this.brainRoutes()) {
      if (skip[r.model]) {
        continue;
      }
      if (++tries > 3) {
        break;
      }
      try {
        const out = await this.crewGenerate(r.model, r.key, user, frame);
        this.good(r.tag);
        return this.clean(out).replace(/^(?:SAY|ANNOUNCEMENT)\\s*:\\s*/i, '');
      } catch (e: any) {
        if (e instanceof ApiError) {
          if (e.status === 401 || (e.status === 400 && /API key/i.test(e.body))) {
            this.cooldown[r.tag] = Date.now() + 30 * 60 * 1000;
            continue;
          }
          this.bench(r.tag, e);
          if (e.status !== 429 && e.status !== 403) {
            skip[r.model] = true;
          }
        } else {
          this.benchFor(r.tag, 45 * 1000, true);
          skip[r.model] = true;
        }
        this.log('crew fallback from ' + r.model + ' (key ' + r.id + '): ' + String(e?.message || e));
      }
    }
    throw new Error('no model answered');
  }

  private async crewGenerate(model: string, key: string, user: string, frame: string): Promise<string> {
    const parts: any[] = [{text: user}, {inline_data: {mime_type: 'image/jpeg', data: frame}}];
    const modes: any[] = [{thinkingBudget: 0}, {thinkingLevel: 'low'}, null];
    for (let attempt = 0; attempt < 3; attempt++) {
      const mode = Math.min(this.thinkMode[model] || 0, 2);
      const cfg: any = {temperature: 0.8, maxOutputTokens: 1024};
      if (modes[mode]) {
        cfg.thinkingConfig = modes[mode];
      }
      const r = await this.timedFetch(
        API + '/models/' + model + ':generateContent',
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'x-goog-api-key': key},
          body: JSON.stringify({
            systemInstruction: {parts: [{text: CREW_SYSTEM_PROMPT}]},
            contents: [{role: 'user', parts}],
            generationConfig: cfg,
          }),
        },
        this.timeoutFor(model),
      );
      const raw = await r.text();
      if (!r.ok) {
        if (r.status === 400 && !/API key/i.test(raw) && mode < 2) {
          this.thinkMode[model] = mode + 1;
          continue;
        }
        throw new ApiError(r.status, raw);
      }
      let j: any = {};
      try {
        j = JSON.parse(raw);
      } catch (e) {}
      const ps: any[] = j?.candidates?.[0]?.content?.parts || [];
      const text = ps
        .filter(p => typeof p?.text === 'string' && !p.thought)
        .map(p => p.text)
        .join(' ')
        .trim();
      if (!text) {
        throw new ApiError(0, 'empty reply (' + (j?.candidates?.[0]?.finishReason || '?') + ')');
      }
      return text;
    }
    throw new ApiError(0, 'thinking config rejected');
  }

"""

MENU_MAIN = """          {id: 'radio:crew', title: 'Cabin crew announcements'},
"""

MENU_SCREENS = """      } else if (screen === 'crew') {
        // CREW: short list, Back near the top, rarely used items last
        const nid = crewNextId(this.crewState);
        const nc = nid ? crewFind(nid) : undefined;
        items = [];
        if (nc) {
          items.push({id: 'radio:crewgo:' + nc.id, title: 'NEXT: ' + nc.label});
        }
        items.push({id: 'radio:back', title: 'Back'});
        const catRow = (c: {id: string; label: string}) => ({
          id: 'radio:crewcat:' + c.id,
          title: c.label + ' (' + crewCommandsIn(c.id).length + ')',
        });
        for (const c of CREW_CATEGORIES.filter(x => x.id === 'emergency')) {
          items.push(catRow(c));
        }
        for (const c of CREW_CATEGORIES.filter(x => x.id !== 'emergency')) {
          items.push(catRow(c));
        }
        items.push({id: 'radio:crewsync', title: 'Sync to flight phase (from radio notes)'});
        items.push({id: 'radio:crewreset', title: 'Start of flight (reset sequence)'});
      } else if (screen.indexOf('crewcat:') === 0) {
        const nid = crewNextId(this.crewState);
        const all = crewCommandsIn(screen.slice('crewcat:'.length));
        const ordered = all.filter(c => c.short_ok).concat(all.filter(c => !c.short_ok));
        items = [{id: 'radio:crew', title: 'Back'}];
        for (const c of ordered) {
          items.push({id: 'radio:crewgo:' + c.id, title: (c.id === nid ? '> ' : '') + c.label, active: c.id === nid});
        }
"""

MENU_HANDLERS = """      } else if (id === 'radio:crew') {
        if (this.crewPressed === 0) {
          this.crewResync();
        }
        screen = 'crew';
      } else if (id.indexOf('radio:crewcat:') === 0) {
        screen = 'crewcat:' + id.slice('radio:crewcat:'.length);
      } else if (id.indexOf('radio:crewgo:') === 0) {
        const cc = crewFind(id.slice('radio:crewgo:'.length));
        if (cc) {
          this.crewPress(cc); // not awaited: the menu closes and the announcement plays
        }
        return;
      } else if (id === 'radio:crewsync') {
        toast(this.crewResync() ? 'Crew position synced to the flight phase' : 'No flight phase in the radio notes yet');
      } else if (id === 'radio:crewreset') {
        this.crewReset();
        toast('Crew sequence is back at the start');
"""


def patch_radio():
    text, crlf = read(RADIO)
    if "// CREW" in text:
        print("radio.ts already wired (CREW marker), skipping")
        return
    p = RADIO
    text = once(text, "import said from './said'; // QUALITY\n", "import said from './said'; // QUALITY\n" + IMPORTS, "imports", p)
    text = once(text, "  private cooldown: Record<string, number> = {};\n",
                "  private cooldown: Record<string, number> = {};\n" + FIELDS, "fields", p)

    # speech: rotation instead of always-best-first
    text = between(text, "  // QUALITY: routes are (voice model, key) pairs.", "  private async fetchGeminiAudio(",
                   VOICE_ROUTES, "voiceRoutes", p)
    text = once(text, "        const resp = await this.timedFetch(\n          API + '/models/' + r.model + ':generateContent',",
                "        markUsed(this.rot, r.tag, Date.now()); // CREW\n"
                "        const resp = await this.timedFetch(\n          API + '/models/' + r.model + ':generateContent',",
                "markUsed", p)
    text = once(text, "        this.lastVoice = r.model + (r.id ? '#' + r.id : '');\n",
                "        this.lastVoice = r.model + (r.id ? '#' + r.id : '');\n        afterSuccess(this.rot, r.model);\n",
                "afterSuccess", p)
    text = once(text, "      (capped.length ? ' | capped: ' + capped.join(', ') : '') +\n",
                "      ' | ' + rotationText(this.rot) +\n      (capped.length ? ' | capped: ' + capped.join(', ') : '') +\n",
                "status", p)

    # word floor
    text = once(text,
                "        if (text && said.duplicateOf(text, this.lastTold)) {\n          text = '';\n        }\n      }\n    }\n    return text;\n  }\n",
                "        if (text && said.duplicateOf(text, this.lastTold)) {\n          text = '';\n        }\n      }\n    }\n" + FLOOR,
                "word floor", p)
    text = soft(text, "never fewer than 25 words, never padded", "never fewer than 40 words, never padded", "SAY rules 25")
    text = soft(text,
                "Never fewer than 25 words. If the pilot is busy (takeoff, landing, heavy ATC) keep it to about 25 to 40 words whatever the band says.",
                "Never fewer than 40 words. If the pilot is busy (takeoff, landing, heavy ATC) keep it to about 40 to 50 words whatever the band says.",
                "length text 25")

    # crew engine
    text = once(text, "  // ---------- UI helpers (the app's native dialogs) ----------\n",
                CREW_METHODS + "  // ---------- UI helpers (the app's native dialogs) ----------\n", "crew methods", p)

    # menu: 3rd item of the main screen, new screens, handlers
    text = once(text, "          {id: 'radio:now', title: 'Talk now'},\n",
                "          {id: 'radio:now', title: 'Talk now'},\n" + MENU_MAIN, "main menu item", p)
    text = once(text, "      } else if (screen === 'voice') {\n", MENU_SCREENS + "      } else if (screen === 'voice') {\n",
                "menu screens", p)
    text = once(text, "      } else if (id === 'radio:voice') {\n        screen = 'voice';\n",
                "      } else if (id === 'radio:voice') {\n        screen = 'voice';\n" + MENU_HANDLERS,
                "menu handlers", p)
    write(p, text, crlf)
    print("radio.ts: speech rotation, word floor, cabin crew engine and menu wired")


# ---------------------------------------------------------------------------------------------
# step 5: Sim Radio entry to the top of the pause menu
# ---------------------------------------------------------------------------------------------
OLD_ENTRY = """      // RADIO
      items.push({
        id: 'radioMenu',
        title: radio.isOn() ? '\U0001F4FB Sim Radio (ON)' : '\U0001F4FB Sim Radio',
        active: radio.isOn(),
      });
"""

NEW_ENTRY = """      // CREWPOS: first item, the pause menu cannot always scroll down to the bottom
      items.push({
        id: 'radioMenu',
        title: radio.isOn() ? '\U0001F4FB Sim Radio and Cabin Crew (ON)' : '\U0001F4FB Sim Radio and Cabin Crew',
        active: radio.isOn(),
      });
"""


def patch_native():
    text, crlf = read(NATIVE)
    if "// CREWPOS" in text:
        print("NativeStream.tsx already patched (CREWPOS), skipping")
        return
    p = NATIVE
    text = once(text, OLD_ENTRY, "", "old radio entry", p)
    anchor = "    if (connectState === CONNECTED) {\n      ensureSessionStartTime();\n"
    text = once(text, anchor, anchor + NEW_ENTRY, "top of pause menu", p)
    write(p, text, crlf)
    print("NativeStream.tsx: Sim Radio entry is now the first pause-menu item")


# ---------------------------------------------------------------------------------------------
# step 6: workflow
# ---------------------------------------------------------------------------------------------
def patch_workflow():
    p = pathlib.Path(WORKFLOW)
    if not p.exists():
        print("workflow not found, skipped")
        return
    text, crlf = read(WORKFLOW)
    lines = text.split("\n")
    out = []
    i = 0
    added = False
    have = "apply_cabin_fix_patch.py" in text
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        drop = (s.startswith("- name: Apply Sim Radio quality patch") or s.startswith("- name: Apply Cabin Crew patch")
                or s.startswith("- name: Apply Cabin Crew fixes"))
        if drop:
            # remove this step: its name line, its run line and one blank line after it
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("- name:"):
                i += 1
            if i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(ln)
        if s == "run: python3 .github/apply_radio_patch.py" and not added:
            indent = ln[: len(ln) - len(ln.lstrip())]
            base = indent[:-2] if len(indent) >= 2 else indent
            out.append("")
            out.append(base + "- name: Apply Cabin Crew fixes and wiring")
            out.append(indent + "run: python3 .github/apply_cabin_fix_patch.py")
            added = True
        i += 1
    if not added:
        if have:
            print("workflow already has the step")
            return
        die("could not find the 'Apply Sim Radio patch' run line in the workflow.", WORKFLOW, text, ("apply_radio",))
    write(WORKFLOW, "\n".join(out), crlf)
    print("workflow: one 'Apply Cabin Crew fixes and wiring' step after the Sim Radio patch")


def main():
    if not pathlib.Path("package.json").exists():
        die("Run this from the repo root (package.json not found).")
    if not pathlib.Path(RADIO).exists():
        die("src/utils/radio.ts not found. Run apply_radio_patch.py first.")
    fix_quality_patch()
    qtext, _ = read(RADIO)
    if "import said from './said'; // QUALITY" not in qtext:
        run(QUALITY)
    else:
        print("quality patch already applied")
    if not pathlib.Path("src/utils/crew.ts").exists() or not pathlib.Path("src/utils/voiceRotation.ts").exists():
        run(CREW_PATCH)
    else:
        print("crew.ts and voiceRotation.ts already present")
    patch_radio()
    patch_native()
    patch_workflow()
    print("\nCABIN FIX PATCH OK")


if __name__ == "__main__":
    main()
