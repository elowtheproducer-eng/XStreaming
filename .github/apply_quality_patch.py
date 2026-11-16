#!/usr/bin/env python3
"""
apply_quality_patch.py  -  Sim Radio QUALITY patch (one shared rule set for EVERY character/preset)

Run from the REPO ROOT, AFTER apply_radio_patch.py (which already runs apply_brain_patch.py):
    python3 .github/apply_quality_patch.py

It also adds a build step for itself to .github/workflows/build-tilt-apk.yml, right after the
"Apply Sim Radio patch" step, so the CI build applies it automatically.

What it does (everything is shared by all characters: Bush Radio, Tour guide, Old bush pilot, ...)
  1. writes src/utils/said.ts
       - TRIP TALK LOG: every fact told this trip is stored and sent back each turn ("ALREADY TOLD"),
         so the radio never repeats a fact but may revisit a place and build on it
       - repeat guard: a line that is too close to an earlier line / fact is rejected and rewritten once
       - polish: removes "here's why", "did you know", questions aimed at the pilot, song/artist names,
         altitude/speed read-outs and aircraft-configuration talk outside their windows, menu chatter
  2. patches src/utils/radio.ts
       - new SHOW RULES: no questions (offers/statements instead), no repeats, natural speech,
         no routine read-outs, one opening music tip (genre + country only), truth rules,
         silent on menus, trip-brief typos corrected silently
       - altitude/speed advice only inside a window (default one tip per 20 min, scenario based)
       - aircraft / configuration talk only in a rare window (first line + one per 40 min)
       - longer lines (no more 15-25 word fragments), new talk segments, no music/trivia-question segments
       - KEY PLAN: Key 1 = brain, Keys 2-4 = voice. Routes are (model, key) pairs with their own cool-downs,
         so a spent voice quota on one project moves on to the next project instead of the phone voice
       - failures escalate (45 s, 90 s, 3 min ... 15 min) so a model with 503s / timeouts stops stealing 25 s per turn
       - dead models removed (2.5 flash: 404), 400 "invalid argument" now retries the other thinking modes
       - menu: More settings > "Talk rules" (tip cooldown, opening music tip, memory), Keys screen relabelled,
         two read-only info screens. Nothing existing is moved or removed.
  3. writes docs/sim-radio-quality.md

Safe to re-run (QUALITY marker). If an anchor is missing it STOPS and prints context: paste that log back.
"""
import pathlib
import sys

MARK = "QUALITY"


def die(msg, path=None, text=None, keywords=()):
    print("\n==================== QUALITY PATCH FAILED ====================")
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
    print("==============================================================")
    sys.exit(1)


def read(p):
    f = pathlib.Path(p)
    if not f.exists():
        die("Missing file: " + p)
    raw = f.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" in raw)


def write(p, text, crlf=False):
    f = pathlib.Path(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    if crlf:
        text = text.replace("\n", "\r\n")
    f.write_bytes(text.encode("utf-8"))


def once(text, find, repl, label, path="src/utils/radio.ts"):
    n = text.count(find)
    if n != 1:
        die("edit '%s': expected exactly 1 match, found %d." % (label, n), path, text,
            (find.strip().split("\n")[0][:30],))
    return text.replace(find, repl, 1)


def between(text, start, end, new, label, include_end=False, path="src/utils/radio.ts"):
    if text.count(start) != 1:
        die("region '%s': start anchor found %d times (expected 1)." % (label, text.count(start)), path, text,
            (start.strip().split("\n")[0][:30],))
    a = text.index(start)
    b = text.find(end, a + len(start))
    if b < 0:
        die("region '%s': end anchor not found after the start anchor." % label, path, text,
            (end.strip().split("\n")[0][:30],))
    if include_end:
        b += len(end)
    return text[:a] + new + text[b:]


# ------------------------------------------------------------------------------------------
# src/utils/said.ts
# ------------------------------------------------------------------------------------------
SAID_TS = r"""// QUALITY: what has already been said this trip, a repeat guard and spoken-text polish.
// Shared by every character, so every preset gets the same quality.
import {storage} from '../store/mmkv';

const K_SAID = 'radio_said_v1';
const STALE_MS = 4 * 3600 * 1000; // a new trip starts after this much silence
const MAX_FACTS = 160;
const MAX_LINES = 40;
const BUDGET = 3200; // characters of the ALREADY TOLD list sent to the model each turn

type Fact = {s: string; f: string; t: number};
type Line = {t: number; w: string; x: string; o: string};
type Store = {u: number; facts: Fact[]; lines: Line[]};

const STOP = new Set(
  (
    'a an the and or but if so of to in on at by for with from as is are was were be been it its this that these those ' +
    'we us our you your he she they them their there here then than too very just also can could will would should do ' +
    'does did have has had not no yes up down out over under about into onto off more most some any all each every one ' +
    'two three four five six seven eight nine ten now like what which who how when where why while still even ever ' +
    'really quite well see look way much many get got make made'
  ).split(' '),
);

const stem = (w: string) => (w.length > 5 ? w.replace(/(?:ing|ed|es|s)$/, '') : w.length > 3 ? w.replace(/s$/, '') : w);

const toWords = (s: string): string[] => {
  const out: string[] = [];
  const seen: Record<string, boolean> = {};
  const parts = String(s || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/);
  for (const p of parts) {
    if (p.length < 3 || STOP.has(p)) {
      continue;
    }
    const w = stem(p);
    if (w.length < 3 || seen[w]) {
      continue;
    }
    seen[w] = true;
    out.push(w);
  }
  return out;
};

const overlap = (a: string[], b: string[]) => {
  const set: Record<string, boolean> = {};
  for (const x of b) {
    set[x] = true;
  }
  let shared = 0;
  for (const x of a) {
    if (set[x]) {
      shared++;
    }
  }
  return {shared, uni: a.length + b.length - shared};
};

const clip = (s: string, n: number) => {
  const x = String(s || '').trim();
  return x.length > n ? x.slice(0, n) : x;
};

const opener = (t: string) =>
  String(t || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 3)
    .join(' ');

// ---------- polish ----------
const SENT = /[^.!?]+[.!?]+["'”’)]*\s*|[^.!?]+$/g;

const FILLER_START: RegExp[] = [
  /^(?:and |but |so |now,? |well,? |okay,? )?(?:here(?:'|’)?s|here is|this is) (?:why|the thing|the kicker|the catch|a fun fact|a fun piece of trivia|a curious bit of trivia|something interesting)[:,.!]?\s*/i,
  /^(?:fun fact|quick fact|trivia time|interesting fact|fun trivia|here(?:'|’)?s a fun one)[:,.!]?\s*/i,
  /^(?:you know|it(?: is|(?:'|’)s) worth (?:noting|remembering|mentioning)|worth noting|i find it (?:incredible|fascinating|remarkable))(?: that)?[,:]?\s*/i,
];
const DYK = /^(?:and |but |so |now,? )?did you know(?: that)?[,:]?\s+/i;
const LISTENER_Q =
  /\byou(?:r|rs|rself)?\b|^(?:ready|shall|should we|want|would|can we|how about|what about|why not|isn(?:'|’)?t|wasn(?:'|’)?t|don(?:'|’)?t|doesn(?:'|’)?t|have|do|does|are|is|will|could)\b/i;
const SONG_NAMED = /["“][^"”]{2,60}["”]\s+(?:by|from)\s+[A-Z]|\b(?:song|track|tune|single|album)\s+(?:called|titled|named)\b/;
const MUSIC_DROP =
  /\b(?:playlist|soundtrack|queue(?:d|ing)? up|put on (?:some|a|the|an)|turn on (?:some|a|the)|listen(?:ing)? to|(?:some|a bit of|a little) (?:music|jazz|city[- ]pop|lo-?fi|tunes)|(?:song|tune|track|album|artist|band) (?:for|that|to)|musical (?:pick|suggestion|accompaniment))\b/i;
const MUSIC_ANY = /\b(?:music|playlist|soundtrack|tunes|city[- ]pop|jazz|lo-?fi|genre|listen(?:ing)? to|put on)\b/i;
const AIRCRAFT_TECH =
  /\b(?:high[- ]wing|low[- ]wing|dihedral|stabili[sz]er|elevator|rudder|aileron|trim tab|vacuum (?:system|pump)|carburet\w*|magneto|yoke|cowl(?:ing)?|airframe|wing configuration|flaps?|throttle|mixture|propeller|rpm|attitude indicator|heading indicator|altimeter|airspeed indicator|gyro\w*|pendulous|self-level\w*)\b/i;
const READOUT_UNIT = /\b(?:feet|knots?|kts|flight level|feet per minute|fpm|miles per hour|mph|rpm)\b/i;
const READOUT_VERB =
  /\b(?:we(?:'|’)re|we are|we(?:'|’)ve|we have|holding|cruising|passing|climbing|descending|levell?ing|maintaining|sitting|steady)\b/i;
const UI_WORDS = /\b(?:settings|interface|menu|pause screen|options screen)\b/i;
const UI_CHATTER = /\b(?:tidy|adjust|tweak|fine-?tun\w*|popped|pop into|moment|digital cockpit|before heading|while you)\b/i;

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

class Said {
  private mem: Store | null = null;

  private load(): Store {
    if (!this.mem) {
      let s: any = null;
      try {
        s = JSON.parse(storage.getString(K_SAID) || 'null');
      } catch (e) {}
      this.mem = s && Array.isArray(s.facts) && Array.isArray(s.lines) ? s : {u: 0, facts: [], lines: []};
    }
    const m = this.mem as Store;
    if (m.u && Date.now() - m.u > STALE_MS) {
      m.facts = [];
      m.lines = [];
      m.u = 0;
    }
    return m;
  }

  private save(s: Store) {
    this.mem = s;
    try {
      storage.set(K_SAID, JSON.stringify(s));
    } catch (e) {}
  }

  begin() {
    this.save(this.load());
  }

  clear() {
    this.save({u: 0, facts: [], lines: []});
  }

  count(): number {
    return this.load().facts.length;
  }

  openers(n: number): string[] {
    const out: string[] = [];
    for (const l of this.load().lines.slice(-n)) {
      if (l.o && out.indexOf(l.o) < 0) {
        out.push(l.o);
      }
    }
    return out;
  }

  // what the model reads every turn
  context(): string {
    const st = this.load();
    if (!st.facts.length) {
      return '\nALREADY TOLD THIS TRIP: nothing yet. Every fact you use goes into TOLD.';
    }
    const groups: Record<string, {n: string; f: string[]; t: number}> = {};
    for (const x of st.facts) {
      const k = (x.s || 'misc').toLowerCase();
      const g = groups[k] || (groups[k] = {n: x.s || 'misc', f: [], t: 0});
      g.f.push(x.f);
      g.t = Math.max(g.t, x.t);
    }
    const order = Object.keys(groups).sort((a, b) => groups[b].t - groups[a].t);
    const lines: string[] = [];
    const rest: string[] = [];
    let used = 0;
    for (const k of order) {
      const g = groups[k];
      const line = g.n + ': ' + g.f.slice(-6).join('; ');
      if (used + line.length > BUDGET) {
        rest.push(g.n);
        continue;
      }
      used += line.length + 1;
      lines.push(line);
    }
    return (
      '\nALREADY TOLD THIS TRIP (never repeat any of these facts, stories or jokes in any wording; you may return to the same place if you bring something NEW):\n' +
      lines.join('\n') +
      (rest.length ? '\nALSO COVERED EARLIER (subjects only): ' + rest.slice(0, 40).join(', ') : '')
    );
  }

  private splitTold(told: string): Array<{s: string; f: string}> {
    const raw = String(told || '').trim();
    if (!raw || /^none\b/i.test(raw)) {
      return [];
    }
    const out: Array<{s: string; f: string}> = [];
    for (const p of raw.split(/\s*;\s*|\n/)) {
      const x = p.trim();
      if (!x || /^none$/i.test(x)) {
        continue;
      }
      const i = x.indexOf(':');
      if (i > 0 && i < 45) {
        out.push({s: clip(x.slice(0, i), 40), f: clip(x.slice(i + 1), 110)});
      } else {
        out.push({s: '', f: clip(x, 110)});
      }
    }
    return out.slice(0, 4);
  }

  // Returns a reason when the new line repeats earlier content, otherwise ''.
  duplicateOf(text: string, told: string): string {
    const st = this.load();
    const w = toWords(text);
    if (w.length >= 8) {
      for (const l of st.lines.slice(-12)) {
        const lw = l.w ? l.w.split(' ') : [];
        if (!lw.length) {
          continue;
        }
        const o = overlap(w, lw);
        const jac = o.shared / Math.max(1, o.uni);
        const ov = o.shared / Math.max(1, Math.min(w.length, lw.length));
        if (jac >= 0.5 || (ov >= 0.7 && o.shared >= 8)) {
          return 'too close to your earlier line starting "' + l.x + '"';
        }
      }
    }
    for (const t of this.splitTold(told)) {
      const fw = toWords(t.f);
      if (fw.length < 3) {
        continue;
      }
      for (const x of st.facts) {
        const xw = toWords(x.f);
        if (xw.length < 3) {
          continue;
        }
        const o = overlap(fw, xw);
        if (o.shared >= 3 && o.shared / Math.min(fw.length, xw.length) >= 0.7) {
          return 'that fact was already told: "' + x.f + '"';
        }
      }
    }
    return '';
  }

  record(text: string, told: string) {
    const st = this.load();
    const now = Date.now();
    let facts = this.splitTold(told);
    if (!facts.length) {
      const first = (String(text || '').match(SENT) || [''])[0].trim();
      if (first) {
        facts = [{s: '', f: clip(first, 100)}];
      }
    }
    for (const f of facts) {
      const dupe = st.facts.some(x => x.f.toLowerCase() === f.f.toLowerCase());
      if (!dupe) {
        st.facts.push({s: f.s, f: f.f, t: now});
      }
    }
    while (st.facts.length > MAX_FACTS) {
      st.facts.shift();
    }
    st.lines.push({
      t: now,
      w: toWords(text).slice(0, 70).join(' '),
      x: String(text || '').split(/\s+/).slice(0, 10).join(' '),
      o: opener(text),
    });
    while (st.lines.length > MAX_LINES) {
      st.lines.shift();
    }
    st.u = now;
    this.save(st);
  }

  mentionsMusic(text: string): boolean {
    return MUSIC_ANY.test(String(text || ''));
  }

  mentionsAircraft(text: string): boolean {
    return AIRCRAFT_TECH.test(String(text || ''));
  }

  // Safety net behind the prompt rules. Works sentence by sentence.
  polish(text: string, o: {music: boolean; advice: boolean; aircraft: boolean}): {text: string; dropped: string[]} {
    const raw = String(text || '').trim();
    if (!raw) {
      return {text: '', dropped: []};
    }
    const parts: string[] = raw.match(SENT) || [raw];
    const out: string[] = [];
    const dropped: string[] = [];
    const seen: Record<string, boolean> = {};
    for (const part of parts) {
      let s = part.trim();
      if (!s) {
        continue;
      }
      for (let i = 0; i < 3; i++) {
        let changed = false;
        for (const rx of FILLER_START) {
          const n = s.replace(rx, '');
          if (n !== s) {
            s = n;
            changed = true;
          }
        }
        if (!changed) {
          break;
        }
      }
      const dyk = s.replace(DYK, '');
      if (dyk !== s) {
        s = dyk.replace(/\?(["'”’)]*)\s*$/, '.$1');
      }
      s = s.replace(/\b(?:here(?:'|’)?s|here is) why[:,]?\s*/gi, '').trim();
      if (!s) {
        continue;
      }
      s = capital(s);
      const n = s.split(/\s+/).length;
      let why = '';
      if (/\?["'”’)]*$/.test(s) && LISTENER_Q.test(s)) {
        why = 'question';
      } else if (SONG_NAMED.test(s)) {
        why = 'song';
      } else if (!o.music && MUSIC_DROP.test(s)) {
        why = 'music';
      } else if (!o.aircraft && AIRCRAFT_TECH.test(s)) {
        why = 'aircraft';
      } else if (!o.advice && n <= 28 && READOUT_UNIT.test(s) && READOUT_VERB.test(s)) {
        why = 'readout';
      } else if (n <= 45 && UI_CHATTER.test(s) && UI_WORDS.test(s)) {
        why = 'settings';
      }
      if (why) {
        dropped.push(why + ': ' + s.slice(0, 50));
        continue;
      }
      const key = s.toLowerCase().replace(/[^a-z0-9]/g, '');
      if (seen[key]) {
        continue;
      }
      seen[key] = true;
      out.push(s);
    }
    return {text: out.join(' ').replace(/\s+/g, ' ').trim(), dropped};
  }
}

const said = new Said();
export default said;
"""

# ------------------------------------------------------------------------------------------
# radio.ts: constants and prompt text
# ------------------------------------------------------------------------------------------
MODEL_CHAIN_NEW = r"""export const MODEL_CHAIN = [
  'gemini-4-hydrogen',
  'gemini-flash-latest',
  'gemini-3.1-flash-lite',
  'gemini-3.5-flash-lite',
  'gemini-flash-lite-latest',
];
"""

TTS_CHAIN_NEW = r"""export const TTS_CHAIN = [
  'gemini-3.8-flash-tts',
  'gemini-3.1-flash-tts-preview',
  'gemini-3.8-flash-lite-tts',
  'gemini-2.5-flash-preview-tts',
];
"""

SEGMENTS_NEW = r"""const SEGMENTS: Array<{t: string; nerd: boolean; air?: boolean}> = [
  {t: 'memory callback: if BRAIN or RECALLED DETAIL shows we have been to or near this place, flown this route or met this situation before, tell the listener what happened or what we learned last time; if nothing matches, do a normal segment instead', nerd: false},
  {t: 'connect two places from BRAIN: say how this place relates to somewhere else we have flown, for example the route between them, a shared history or what we did on the way', nerd: false},
  {t: 'name the exact landmark, town, river, mountain or airfield below or ahead and give ONE surprising fact about it that is not in ALREADY TOLD', nerd: false},
  {t: 'tell a short true piece of local history or a human story tied to this area, ideally about a real person', nerd: false},
  {t: 'colour about the wildlife, terrain, climate or weather typical of this exact region and season', nerd: false},
  {t: 'react to the latest ATC subtitle if one is visible, or to what the pilot is doing right now, with personality; if there is no ATC text, do a different kind of segment', nerd: false},
  {t: 'trip progress as a statement: where we came from, where we are heading, which waypoint from the trip brief comes next and roughly how long until it', nerd: false},
  {t: 'a quick funny observation or bit of banter based on something visible on screen', nerd: false},
  {t: 'a spotter note: tell the listener what will appear in the next few minutes of flight and where to look for it (left, right, ahead), as a statement', nerd: false},
  {t: 'a short legend or story connected to a place we have just passed', nerd: false},
  {t: 'give the pilot two real options from here as statements, each with a direction, a rough distance and one reason to go, then close with something like "fly to whichever one pulls at you"; never phrase it as a question', nerd: false},
  {t: 'set a spotting challenge as a statement (for example "see if you can pick out the red bridge just past the river") and give one detail that makes it easier', nerd: false},
  {t: 'what daily life is like down on the ground in this area right now: sounds, food, customs or work, told as a small scene', nerd: false},
  {t: 'what this exact place looked like a hundred or more years ago, or what was here before, told as a vivid before-and-after', nerd: false},
  {t: 'a nerdy geography, geology, map or place-name fact about this region (why it looks like this, how it formed, why it is called that)', nerd: true},
  {t: 'a bit of aviation, space or engineering history that connects to somewhere near this route', nerd: true},
  {t: 'a nerdy tangent from physics, astronomy, language or technology that this view reminds you of', nerd: true},
  {t: 'ONE nerdy idea about how this aircraft flies or works, only if it ties to what is happening right now', nerd: true, air: true},
];
"""

LENGTHS_NEW = r"""const LENGTHS: Array<{w: number; t: string}> = [
  {w: 0.3, t: 'MEDIUM: about 40 to 65 words'},
  {w: 0.45, t: 'LONG: about 70 to 110 words, take your time and tell it properly'},
  {w: 0.25, t: 'STORY: about 120 to 170 words, a proper little story or explanation with a beginning, a middle and an end'},
];
"""

KEY_SLOTS_NEW = r"""export const KEY_SLOTS: Array<{id: number; model: string; name: string}> = [
  {id: 1, model: 'brain', name: 'BRAIN: Hydrogen, 3.8 Flash, 3.1 Flash Lite'},
  {id: 2, model: 'voice', name: 'VOICE A: every speech voice (spare brain)'},
  {id: 3, model: 'voice', name: 'VOICE B: every speech voice'},
  {id: 4, model: 'voice', name: 'VOICE C: every speech voice'},
];

// QUALITY: which keys each job tries, in order. Key 1 also speaks as a last resort, Key 2 also thinks as a spare.
const BRAIN_KEY_IDS = [1, 2];
const VOICE_KEY_IDS = [2, 3, 4, 1];

const KEY_PLAN: string[] = [
  'Make every key in its OWN Google AI Studio project',
  'Two keys from one project share one quota: no gain',
  'Key 1 = BRAIN (Hydrogen, 3.8 Flash, 3.1 Flash Lite)',
  'Keys 2, 3, 4 = VOICE (the same speech voices on each)',
  'Best voice is used on keys 2, 3, 4 before the next voice',
  'Your log: about 10 spoken lines per voice per project per day',
  'So 3 voice keys is about 90 lines, roughly 2 hours of talk',
  'Key 1 is the last-resort voice, Key 2 the spare brain',
  'Only one key? Put it in Key 1: it does everything',
  'The spare key (menu) is tried last by every job',
];

const RULE_PLAN: string[] = [
  'It never asks you questions: it offers options instead',
  'One music tip at the start: genre and country only',
  'Altitude and speed advice: at most one per cooldown',
  'No routine altitude, speed or aircraft-config chatter',
  'It remembers every fact told this trip, no repeats',
  'It may revisit a place if it adds something new',
  'It stays silent on menu and settings screens',
  'Same rules for every character',
];
"""

FLIGHT_TALK_NEW = r"""const FLIGHT_TALK =
  '\nSHOW RULES. These apply to every character and outrank the character description, which only sets your voice, tone and attitude (not length, topics or these rules).' +
  '\n1 NO QUESTIONS TO THE PILOT. The pilot cannot answer and nothing happens after you stop speaking, so never ask the pilot anything and never wait for a reply (no "ready?", "shall we", "what do you think", "did you know", "have you ever", "how about", "want to", "does that surprise you"). Where you would ask, make a statement or an offer: "From here you can swing left to X, about eight miles, or carry on to Y; fly to whichever one pulls at you." Finish every line on a statement, an observation or a look-ahead, never on a question. A rhetorical question that you answer in the very next sentence is fine, but rarely.' +
  '\n2 NO REPEATS. ALREADY TOLD is everything you have said this trip. Never say a fact, story, comparison or joke from it again in any wording. You MAY talk about the same place again, as often as you like, when you bring something NEW (another angle, another fact, what changed, how it ties to something seen earlier). Prefer a new subject when the view offers one. Do not announce a phase twice (lined up, airborne, climbing, cruising, turning) unless the phase really changed.' +
  '\n3 NATURAL SPEECH. Never use: "here is why", "here\'s why", "did you know", "fun fact", "you know,", "it is worth noting", "worth remembering", "interesting tidbit", "let me tell you", "buckle up". Do not announce that a fact is coming, just say it. Vary how lines start: never begin two lines the same way and avoid starting with "We are", "Cruising", "Passing", "Back in the air" or "Look at". No recap, sign-off or goodbye unless it is the final landing.' +
  '\n4 NO ROUTINE READ-OUTS. Do not state altitude, airspeed, vertical speed, heading or engine numbers as commentary, and do not describe the aircraft configuration, systems or design (wing type, stability, instruments, engine, controls). Only the FLIGHT ADVICE and AIRCRAFT TALK lines of each turn can open these up. A number is also fine when ATC text on screen gives an instruction you are reacting to.' +
  '\n5 MUSIC. Never name a song, album or artist, ever. Music is only allowed when the MUSIC TIP line of the turn says OPEN, and then only as genre plus country or region, in a few words.' +
  '\n6 TRUTH. One fact at a time, only facts about the real place that you are sure of. Do not invent ATC calls (react only to ATC text that is visible), statistics, counts or names. If unsure, choose a different fact.' +
  '\n7 SCREEN. If the screen shows a settings, pause, map, loading or any menu instead of the flight view, say nothing: SAY: SKIP. Never comment on menus, settings or the interface, and never say you are back in the air.' +
  '\n8 BRIEF. The trip brief is typed or dictated by a person and can contain typos or sound-alike mistakes (for example "China" for Chiba, "Jesse" for Messe). Silently match each item to the real place on the route, never repeat the mistake and never treat it as a different place. Follow the waypoints in the order given and mention the next one before you reach it.';

// QUALITY: two extra reply lines, read by the app (TOLD feeds the trip talk log, ADVICE the tip cooldown)
const QUALITY_FORMAT =
  '\nAfter the RECALL line ALWAYS add two final lines in exactly this form:' +
  '\nTOLD: the 1 to 3 facts, stories or jokes you just used in SAY, each written as "Subject: fact in 12 words or fewer", separated by " ; ". NONE if SAY had no new fact.' +
  '\nADVICE: ALT, SPEED, BOTH or NONE, depending on whether SAY contained a recommendation about altitude or speed.';
"""

FIELDS_ADD = r"""  // QUALITY
  private streak: Record<string, number> = {};
  private lastKeyId = 0;
  private adviceAt = 0;
  private aircraftAt = 0;
  private lines = 0;
  private lastTold = '';
  private lastAdv = '';
  private dupNote = '';
"""

SETTINGS_ADD = r"""  // QUALITY: talk rule settings
  getAdviceMin(): number {
    const v = storage.getNumber('radio_adv_min');
    return v === undefined ? 20 : v;
  }
  setAdviceMin(n: number) {
    storage.set('radio_adv_min', n);
  }
  getMusicOn(): boolean {
    const v = storage.getBoolean('radio_music_on');
    return v === undefined ? true : v;
  }
  setMusicOn(v: boolean) {
    storage.set('radio_music_on', v);
  }
"""

KEY_METHODS_NEW = r"""  // QUALITY: Key 1 = brain, Keys 2-4 = voice (see KEY_PLAN). The old "default key" is kept as a spare for every job.
  getApiKey(): string {
    return this.getSlotKey(1) || this.getMainKey() || this.firstSlotKey();
  }
  getMainKey(): string {
    return storage.getString(K_API) || '';
  }
  getSlotKey(id: number): string {
    return storage.getString('radio_key_' + id) || '';
  }
  setSlotKey(id: number, k: string) {
    storage.set('radio_key_' + id, (k || '').trim());
  }
  private firstSlotKey(): string {
    for (const s of KEY_SLOTS) {
      const k = this.getSlotKey(s.id);
      if (k) {
        return k;
      }
    }
    return '';
  }
  // the keys one job may use, in order, one per distinct key text. Spare (default) key last. id 0 = spare.
  private keyPool(ids: number[]): Array<{id: number; key: string}> {
    const out: Array<{id: number; key: string}> = [];
    const seen: Record<string, boolean> = {};
    for (const id of ids) {
      const k = this.getSlotKey(id);
      if (k && !seen[k]) {
        seen[k] = true;
        out.push({id, key: k});
      }
    }
    const d = this.getMainKey();
    if (d && !seen[d]) {
      seen[d] = true;
      out.push({id: 0, key: d});
    }
    if (out.length === 0) {
      const any = this.firstSlotKey();
      if (any) {
        out.push({id: 0, key: any});
      }
    }
    return out;
  }
  private clearCooldownFor(id: number) {
    for (const k of Object.keys(this.cooldown)) {
      if (k.slice(k.lastIndexOf('@') + 1) === String(id)) {
        delete this.cooldown[k];
        delete this.streak[k];
      }
    }
  }
"""

VOICE_REGION_NEW = r"""  // ---------- speaking ----------
  // QUALITY: routes are (voice model, key) pairs. Each pair has its own cool-down, so when one project's daily
  // quota for a voice is spent the next project's quota for the same voice is used before a weaker voice.
  private voiceRoutes(): Array<{model: string; id: number; key: string; tag: string}> {
    const now = Date.now();
    let list = TTS_CHAIN.slice();
    if (this.available) {
      const all = this.available.filter(m => /tts/i.test(m) && !/argon|carbon|-pro-/i.test(m));
      const rank = (m: string) => {
        if (/hydrogen/i.test(m)) {
          return -1;
        }
        const i = TTS_CHAIN.indexOf(m);
        return i >= 0 ? i : 50;
      };
      list = all.sort((x, y) => rank(x) - rank(y));
      if (list.length === 0) {
        list = TTS_CHAIN.slice();
      }
    }
    const pool = this.keyPool(VOICE_KEY_IDS);
    const out: Array<{model: string; id: number; key: string; tag: string}> = [];
    for (const model of list) {
      for (const p of pool) {
        const tag = model + '@' + p.id;
        if ((this.cooldown[tag] || 0) <= now) {
          out.push({model, id: p.id, key: p.key, tag});
        }
      }
    }
    return out;
  }

  private async fetchGeminiAudio(text: string): Promise<any> {
    const skip: Record<string, boolean> = {};
    for (const r of this.voiceRoutes()) {
      if (skip[r.model]) {
        continue;
      }
      try {
        const resp = await this.timedFetch(
          API + '/models/' + r.model + ':generateContent',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'x-goog-api-key': r.key},
            body: JSON.stringify({
              contents: [{parts: [{text}]}],
              generationConfig: {
                responseModalities: ['AUDIO'],
                speechConfig: {
                  voiceConfig: {prebuiltVoiceConfig: {voiceName: this.getSpeaker()}},
                },
              },
            }),
          },
          (this.streak[r.tag] || 0) > 0 ? 20000 : 30000,
        );
        const raw = await resp.text();
        if (!resp.ok) {
          throw new ApiError(resp.status, raw);
        }
        const j: any = JSON.parse(raw);
        const parts: any[] = j?.candidates?.[0]?.content?.parts || [];
        const ap = parts.find(p => p?.inlineData?.data || p?.inline_data?.data);
        const inl = ap?.inlineData || ap?.inline_data;
        if (!inl?.data) {
          throw new ApiError(0, 'no audio returned');
        }
        const mime: string = String(inl.mimeType || inl.mime_type || '');
        const rate = parseInt((mime.match(/rate=(\d+)/) || [])[1] || '24000', 10);
        const bytes = Math.floor((String(inl.data).length * 3) / 4);
        this.lastVoice = r.model + (r.id ? '#' + r.id : '');
        this.good(r.tag);
        return {data: inl.data, rate, ms: Math.round((bytes / 2 / rate) * 1000)};
      } catch (e: any) {
        if (e instanceof ApiError) {
          if (e.status === 401 || (e.status === 400 && /API key/i.test(e.body))) {
            this.cooldown[r.tag] = Date.now() + 30 * 60 * 1000;
          } else {
            this.bench(r.tag, e, true);
            if (e.status !== 429 && e.status !== 403) {
              skip[r.model] = true;
            }
          }
        } else {
          this.benchFor(r.tag, 45 * 1000, true);
          skip[r.model] = true;
        }
        this.log('voice fallback from ' + r.model + ' (key ' + r.id + '): ' + String(e?.message || e));
      }
    }
    return null;
  }

"""

BRAIN_REGION_NEW = r"""  // QUALITY: the brain models in order of preference (unchanged logic), then expanded to (model, key) pairs
  private brainModels(): string[] {
    const hydro = (this.available || []).filter(
      m => /hydrogen/i.test(m) && !/tts|image|live|audio|embed|robot/i.test(m),
    );
    const base = this.available ? MODEL_CHAIN.filter(m => this.available!.includes(m)) : MODEL_CHAIN;
    const merged = hydro.concat(base.filter(m => !hydro.includes(m)));
    return merged.length > 0 ? merged : MODEL_CHAIN;
  }

  private brainRoutes(): Array<{model: string; id: number; key: string; tag: string}> {
    const now = Date.now();
    const pool = this.keyPool(BRAIN_KEY_IDS);
    const all: Array<{model: string; id: number; key: string; tag: string}> = [];
    for (const model of this.brainModels()) {
      for (const p of pool) {
        all.push({model, id: p.id, key: p.key, tag: model + '@' + p.id});
      }
    }
    const ok = all.filter(r => (this.cooldown[r.tag] || 0) <= now);
    if (ok.length > 0) {
      return ok;
    }
    // everything is benched: still try the one that comes back soonest instead of going silent
    const soon = all.slice().sort((a, b) => (this.cooldown[a.tag] || 0) - (this.cooldown[b.tag] || 0))[0];
    return soon ? [soon] : [];
  }

  // QUALITY: short, error-specific cool-downs that GROW when the same pair keeps failing (503, timeouts).
  // A model that keeps timing out used to cost 25 s on every other turn; now it is left alone for longer each time.
  private bench(tag: string, e: ApiError, voice = false) {
    const b = e.body || '';
    let ms = 60 * 1000;
    let esc = false;
    if (e.status === 429) {
      const m = b.match(/retry in ([0-9.]+)s/i);
      const wait = m ? Math.ceil(parseFloat(m[1])) * 1000 + 2000 : 60000;
      ms = /PerDay|per day|daily/i.test(b) ? 6 * 3600 * 1000 : Math.min(120000, Math.max(10000, wait));
    } else if (e.status === 503 || e.status === 500 || e.status === 504) {
      ms = 45 * 1000;
      esc = true;
    } else if (e.status === 404 || e.status === 403) {
      ms = 30 * 60 * 1000;
    } else if (e.status === 400) {
      ms = /not supported|unsupported|invalid model|not found/i.test(b) ? 30 * 60 * 1000 : voice ? 3 * 60 * 1000 : 20 * 60 * 1000;
    } else if (e.status === 0) {
      ms = 30 * 1000;
      esc = true;
    }
    this.benchFor(tag, ms, esc);
  }

  private benchFor(tag: string, ms: number, escalate: boolean) {
    const n = (this.streak[tag] || 0) + 1;
    this.streak[tag] = n;
    const mult = escalate ? Math.pow(2, Math.min(n - 1, 4)) : 1;
    this.cooldown[tag] = Date.now() + Math.min(ms * mult, Math.max(ms, 15 * 60 * 1000));
  }

  private good(tag: string) {
    this.streak[tag] = 0;
    delete this.cooldown[tag];
  }

  private timeoutFor(model: string): number {
    const bad = Object.keys(this.streak).some(k => k.indexOf(model + '@') === 0 && this.streak[k] > 0);
    return bad ? 15000 : 25000;
  }

  // QUALITY: the talk windows. They decide what the radio may bring up this turn.
  private windows() {
    const now = Date.now();
    const mins = this.startedAt ? (now - this.startedAt) / 60000 : 0;
    const advMin = this.getAdviceMin();
    const musicAt = storage.getNumber('radio_music_at') || 0;
    return {
      mins,
      advice: advMin > 0 && mins >= 4 && now - this.adviceAt >= advMin * 60000,
      music: this.getMusicOn() && mins < 8 && now - musicAt > 3 * 3600 * 1000,
      aircraft: this.lines < 2 || (mins >= 12 && now - this.aircraftAt >= 40 * 60000),
    };
  }

  private gates(): string {
    const w = this.windows();
    const op = said.openers(4);
    return (
      (w.music
        ? '\nMUSIC TIP: OPEN. In this line or the next you may give ONE short tip for what kind of music to put on for this flight: genre and country or region only (for example "some Japanese city pop"), never a song, album or artist, a few words and no explanation. After that, never mention music again.'
        : '\nMUSIC TIP: CLOSED. Do not mention music, songs, playlists or listening at all.') +
      (w.advice
        ? '\nFLIGHT ADVICE: OPEN. If this moment fits a scenario (climb-out, levelling off, a sightseeing pass over a landmark or city, descent, approach, final), you may give ONE short recommendation for altitude and/or speed that suits what you see and the aircraft, in plain spoken numbers with a few words of reason, worded as advice ("about fifteen hundred feet would show the towers off nicely"), not as a read-out of the current values. If no scenario fits, say nothing about it and answer ADVICE: NONE.'
        : '\nFLIGHT ADVICE: CLOSED. No altitude, speed, heading or vertical speed numbers at all this turn.') +
      (this.lines < 2
        ? '\nAIRCRAFT TALK: OPEN for this opening only: you may name the aircraft once, nothing technical.'
        : w.aircraft
        ? '\nAIRCRAFT TALK: OPEN (rare). You may mention ONE thing about how the aircraft flies, only if it ties to something happening right now.'
        : '\nAIRCRAFT TALK: CLOSED. Do not mention the aircraft type, its configuration, systems or design at all.') +
      (op.length ? '\nRECENT LINE OPENERS (start this line differently): ' + op.join(' | ') : '')
    );
  }

  private polish(text: string): string {
    if (!text) {
      return '';
    }
    const w = this.windows();
    const r = said.polish(text, {music: w.music, advice: w.advice, aircraft: w.aircraft});
    if (r.dropped.length) {
      this.log('trimmed: ' + r.dropped.join(' | ').slice(0, 300));
    }
    return r.text;
  }

  // ask, polish, and rewrite once if the line repeats something already said
  private async draft(frame: string): Promise<string> {
    let text = this.polish(await this.ask(frame));
    if (text) {
      const why = said.duplicateOf(text, this.lastTold);
      if (why) {
        this.log('repeat blocked: ' + why);
        this.dupNote =
          '\nYOUR LAST DRAFT WAS REJECTED because it repeated earlier content (' + why + '). Write a completely different line about something NEW, using the ALREADY TOLD list.';
        try {
          text = this.polish(await this.ask(frame));
        } finally {
          this.dupNote = '';
        }
        if (text && said.duplicateOf(text, this.lastTold)) {
          text = '';
        }
      }
    }
    return text;
  }

  // called once for every line that is really going to be spoken
  private note(text: string) {
    const w = this.windows();
    said.record(text, this.lastTold);
    this.lines++;
    if (/^(?:alt|speed|both)/i.test(this.lastAdv)) {
      this.adviceAt = Date.now();
    }
    if (w.music && said.mentionsMusic(text)) {
      storage.set('radio_music_at', Date.now());
    }
    if (w.aircraft && this.lines > 2 && said.mentionsAircraft(text)) {
      this.aircraftAt = Date.now();
    }
  }

"""

ASK_REGION_NEW = r"""  private async ask(frame: string): Promise<string> {
    const first = this.getApiKey();
    if (!first) {
      throw new Error('no Gemini API key set');
    }
    await this.refreshAvailable(first);
    const skip: Record<string, boolean> = {};
    let tried = 0;
    for (const r of this.brainRoutes()) {
      if (skip[r.model]) {
        continue;
      }
      tried++;
      try {
        const parsed: any = this.parse(await this.generate(r.model, r.key, frame));
        const {say, state, pause} = parsed;
        try {
          brain.ingest(parsed, this.getAircraft()); // BRAIN
        } catch (be) {
          this.log('brain: ' + String(be));
        }
        this.pauseRatio = pause;
        this.lastModel = r.model;
        this.lastKeyId = r.id;
        this.lastError = '';
        this.lastTold = parsed.told || '';
        this.lastAdv = parsed.advice || '';
        this.good(r.tag);
        if (state) {
          this.setNotes(state);
        }
        if (!say || /^SKIP\b/i.test(say)) {
          return '';
        }
        return say;
      } catch (e: any) {
        if (e instanceof ApiError) {
          if (e.status === 401 || (e.status === 400 && /API key/i.test(e.body))) {
            // a wrong key in one slot must not silence the whole radio
            this.cooldown[r.tag] = Date.now() + 30 * 60 * 1000;
            this.lastError = 'key ' + r.id + ' was rejected by Google';
            this.log(this.lastError);
            continue;
          }
          this.bench(r.tag, e);
          this.lastError = r.model + ' (key ' + r.id + '): ' + e.message;
          if (e.status !== 429 && e.status !== 403) {
            skip[r.model] = true; // a 503, timeout or dead model is not fixed by another key
          }
        } else {
          this.benchFor(r.tag, 45 * 1000, true);
          this.lastError = r.model + ': ' + (e?.name === 'AbortError' ? 'timeout' : String(e?.message || e));
          skip[r.model] = true;
        }
        this.log('brain fallback from ' + r.model + ' (key ' + r.id + '): ' + this.lastError);
      }
    }
    if (tried === 0) {
      throw new Error('all models capped, waiting for quota');
    }
    throw new Error('all models failed. last: ' + this.lastError);
  }

"""

SLOT_PROMPT_NEW = r"""  async promptForSlotKey(id: number, showInput: (o: any) => Promise<any>) {
    const slot = KEY_SLOTS.find(s => s.id === id);
    if (!slot) {
      return;
    }
    const r = await showInput({
      title: 'Key ' + id + ': ' + slot.name,
      message: 'Paste a key from its OWN Google AI Studio project (aistudio.google.com/apikey, Create API key, new project). Keys from the same project share one quota. Leave empty to remove it.',
      hint: 'AIza...',
      text: this.getSlotKey(id),
      maxLength: 200,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      this.setSlotKey(id, r.text || '');
      this.clearCooldownFor(id);
      toast(this.getSlotKey(id) ? 'Key ' + id + ' saved' : 'Key ' + id + ' cleared');
    }
  }

"""

MENU_KEYS_AND_RULES = r"""      } else if (screen === 'keys') {
        items = [
          {id: 'radio:keyplan', title: 'How to use the keys (read me)'},
          {id: 'radio:key', title: 'Spare key (every job tries it last): ' + (this.getMainKey() ? '[set]' : '[empty]')},
        ].concat(
          KEY_SLOTS.map(s => ({
            id: 'radio:slot:' + s.id,
            title: 'Key ' + s.id + ': ' + s.name + (this.getSlotKey(s.id) ? ' [set]' : ' [empty]'),
          })),
        );
        items.push({id: 'radio:back', title: 'Back'});
      } else if (screen === 'keyplan') {
        items = KEY_PLAN.map((t, i) => ({id: 'radio:info:' + i, title: t}));
        items.push({id: 'radio:keys', title: 'Back'});
      } else if (screen === 'rules') {
        const am = this.getAdviceMin();
        items = [
          {id: 'radio:rule:adv', title: 'Altitude and speed tips: ' + (am > 0 ? 'one per ' + am + ' min at most' : 'off') + ' (tap to change)'},
          {id: 'radio:rule:music', title: 'Opening music tip (genre only): ' + (this.getMusicOn() ? 'on' : 'off'), active: this.getMusicOn()},
          {id: 'radio:rule:said', title: 'Trip memory: ' + said.count() + ' facts told this trip (tap to clear)'},
          {id: 'radio:ruleplan', title: 'What the radio will and will not say'},
          {id: 'radio:more', title: 'Back'},
        ];
      } else if (screen === 'ruleplan') {
        items = RULE_PLAN.map((t, i) => ({id: 'radio:info:' + i, title: t}));
        items.push({id: 'radio:rules', title: 'Back'});
"""

MENU_RULE_HANDLERS = r"""      } else if (id === 'radio:rules') {
        screen = 'rules';
      } else if (id === 'radio:ruleplan') {
        screen = 'ruleplan';
      } else if (id === 'radio:keyplan') {
        screen = 'keyplan';
      } else if (id.startsWith('radio:info:')) {
        // read-only line: stay on the same screen
      } else if (id.startsWith('radio:rule:')) {
        const sub = id.slice('radio:rule:'.length);
        if (sub === 'adv') {
          const cur = this.getAdviceMin();
          this.setAdviceMin(cur === 10 ? 20 : cur === 20 ? 30 : cur === 30 ? 0 : 10);
        } else if (sub === 'music') {
          this.setMusicOn(!this.getMusicOn());
        } else if (sub === 'said') {
          said.clear();
          toast('Trip memory cleared');
        }
      } else if (id === 'radio:keys') {
"""

DOC_MD = r"""# Sim Radio quality patch

One rule set, shared by every character (Bush Radio, Tour guide, Old bush pilot, Nature documentary, Race
commentator, Sarcastic co-pilot, ATC). The character only decides voice, tone and attitude.

## What the Tokyo log showed
- Voice stopped at 12:32: every Gemini voice had spent its daily quota on this project (about 10 spoken lines per
  voice, 4 voices, about 40 lines in total). After that the phone voice took over.
- Prep time was 15 to 45 s because gemini-flash-latest (503 / timeouts) was retried every other turn, and dead
  models (2.5 flash: 404, 3.5 flash lite and flash lite latest: 400) were tried again and again.
- Altitude and speed were read out about 25 times, the aircraft design was explained 6 times (high wing, dihedral,
  pendulum stability, trim tab, vacuum system), reclaimed land / Kanto Plain / Skytree damper were told 3 to 5 times.
- Two lines were word for word identical (12:46 and 12:47).
- 14 questions to a pilot who cannot answer, 9 music tips (real artists, several of them wrong for Tokyo),
  3 times "tidying the interface settings" while a menu was open.
- Some facts were wrong (Japan Cup is not run at Nakayama, Tokyo Tower is about 3 m taller than the Eiffel Tower,
  not 13 m, an invented count of corners at the raceway).
- The trip brief said "China city folk museum / China zoological park": that is Chiba, the radio repeated "China".

## What changed
- Trip talk log (src/utils/said.ts): every fact told is stored and sent back as ALREADY TOLD. A repeat is blocked and rewritten once.
- Questions become offers and statements. "Did you know", "here is why" and similar filler are removed.
- Music: one tip at the start, genre and country only, never a song or artist.
- Altitude / speed: advice only, one per 20 minutes by default (More settings > Talk rules: 10 / 20 / 30 / off).
- Aircraft configuration talk: opening line once, then one per 40 minutes at most.
- Menus and settings screens: silence.
- Lines are 40 to 170 words (no more fragments). Takeoff, landing and heavy ATC stay short.
- Keys: Key 1 = brain, Keys 2 to 4 = voice. See the Keys screen ("How to use the keys").
- Failing models are left alone for longer each time instead of costing 25 s every other turn.
"""


# ------------------------------------------------------------------------------------------
def patch_radio_ts():
    p = "src/utils/radio.ts"
    text, crlf = read(p)
    if "from './said'" in text:
        print("radio.ts: already patched")
        return
    if "from './brain'" not in text:
        die("radio.ts has no brain import: run apply_radio_patch.py (it runs apply_brain_patch.py) first.", p, text,
            ("import",))

    # imports + constants
    text = once(text, "import brain from './brain'; // BRAIN\n",
                "import brain from './brain'; // BRAIN\nimport said from './said'; // QUALITY\n", "import")
    text = between(text, "export const MODEL_CHAIN = [\n", "];\n", MODEL_CHAIN_NEW, "MODEL_CHAIN", include_end=True)
    text = between(text, "export const TTS_CHAIN = [\n", "];\n", TTS_CHAIN_NEW, "TTS_CHAIN", include_end=True)
    text = between(text, "const SEGMENTS: Array<{t: string; nerd: boolean}> = [\n", "\n];\n", SEGMENTS_NEW, "SEGMENTS",
                   include_end=True)
    text = once(text, 'and a short \\"here is why\\".',
                "and the reason behind it woven into the same sentence.", "nerd level 3 wording")
    text = between(text, "const LENGTHS: Array<{w: number; t: string}> = [\n", "\n];\n", LENGTHS_NEW, "LENGTHS",
                   include_end=True)
    text = once(text,
                "return LENGTHS[pick].t + '. Never fewer than 15 words. If the pilot is busy (takeoff, landing, heavy ATC) keep it SHORT whatever the band says.';",
                "return LENGTHS[pick].t + '. Never fewer than 25 words. If the pilot is busy (takeoff, landing, heavy ATC) keep it to about 25 to 40 words whatever the band says.';",
                "length text")
    text = between(text, "export const KEY_SLOTS: Array<{id: number; model: string; name: string}> = [\n", "\n];\n",
                   KEY_SLOTS_NEW, "KEY_SLOTS", include_end=True)
    text = between(text, "const FLIGHT_TALK =\n  '", "';\n", FLIGHT_TALK_NEW, "FLIGHT_TALK", include_end=True)

    # fields, settings, key helpers
    text = once(text, "  private lastLen = -1;\n", "  private lastLen = -1;\n" + FIELDS_ADD, "fields")
    text = once(text, "  isOn() {\n    return this.on;\n  }\n", SETTINGS_ADD + "  isOn() {\n    return this.on;\n  }\n",
                "settings")
    text = between(text, "  getApiKey(): string {\n    // BRAIN: the default key", "  setApiKey(k: string) {\n",
                   KEY_METHODS_NEW, "key helpers")

    # lifecycle
    text = once(text,
                "    brain.beginSession(this.getAircraft(), this.getTrip()); // BRAIN\n    this.startBurst();\n",
                "    brain.beginSession(this.getAircraft(), this.getTrip()); // BRAIN\n"
                "    said.begin(); // QUALITY\n    this.adviceAt = 0;\n    this.aircraftAt = 0;\n    this.lines = 0;\n"
                "    this.startBurst();\n", "start")
    text = once(text, "      const lead = Math.min(30000, Math.max(5000, this.latencyEma + 2000));",
                "      const lead = Math.min(45000, Math.max(5000, this.latencyEma + 2000));", "lead cap")

    # produce: draft (ask + polish + repeat guard) and note
    text = once(text, "      const text = await this.ask(frame);\n", "      const text = await this.draft(frame); // QUALITY\n",
                "produce draft")
    text = once(text, "      this.history.push(text);\n", "      this.note(text); // QUALITY\n      this.history.push(text);\n",
                "produce note")

    # voice + brain regions
    text = between(text, "  // ---------- speaking ----------\n  private ttsCandidates(): string[] {",
                   "  // ---------- Gemini (brain) ----------\n", VOICE_REGION_NEW, "voice region")
    text = between(text, "  private candidates(): string[] {", "  private pickSegment(): string {\n",
                   BRAIN_REGION_NEW, "brain region")
    text = once(text,
                "const weights = SEGMENTS.map((s, i) => (i === this.lastSegment ? 0 : s.nerd ? level.weight : 1));",
                "const airOk = this.windows().aircraft;\n"
                "    const weights = SEGMENTS.map((s, i) =>\n"
                "      i === this.lastSegment || (s.air && !airOk) ? 0 : s.nerd ? level.weight : 1,\n    );",
                "segment weights")

    # prompt text
    text = once(text,
                "song recommendations (title and artist only, never lyrics), asides about science, engineering, aviation, geography or language that a curious person would love (as far as the NERD LEVEL allows), light opinions and questions to the pilot.",
                "asides about science, engineering, aviation, geography or language that a curious person would love (as far as the NERD LEVEL allows), light opinions stated as opinions, and real suggestions of where to fly next (as statements, never questions).",
                "conversation rule")
    text = once(text, "(never fewer than 15 words, never padded:", "(never fewer than 25 words, never padded:", "say rule length")
    text = once(text, "      FLIGHT_TALK +\n      brain.formatRules();",
                "      FLIGHT_TALK +\n      brain.formatRules() +\n      QUALITY_FORMAT;", "system tail")
    text = once(text, "      brain.context() +\n",
                "      brain.context() +\n      said.context() +\n      this.gates() +\n", "user gates")
    text = once(text, "      (this.burstNote || '\\nThe image is the screen NOW.');",
                "      (this.burstNote || '\\nThe image is the screen NOW.') +\n      this.dupNote;", "user tail")

    # generate: retry the other thinking styles on ANY 400 that is not a key problem, shorter timeout for sick models
    text = once(text, "if (r.status === 400 && /think/i.test(raw) && mode < 2) {",
                "if (r.status === 400 && !/API key/i.test(raw) && mode < 2) {", "thinking retry")
    text = once(text, "        25000,\n      );\n      const raw = await r.text();",
                "        this.timeoutFor(model),\n      );\n      const raw = await r.text();", "brain timeout")

    # parse: two more fields
    text = once(text, "(STATE|SAY|PAUSE|PLACES|LOG|RECALL)", "(STATE|SAY|PAUSE|PLACES|LOG|RECALL|TOLD|ADVICE)", "parse labels")
    text = once(text, "places: '', log: '', recall: ''};", "places: '', log: '', recall: '', told: '', advice: ''};",
                "parse empty")
    text = once(text, "      recall: keep(f.RECALL),\n    };",
                "      recall: keep(f.RECALL),\n      told: keep(f.TOLD),\n      advice: this.clean(f.ADVICE || ''),\n    };",
                "parse result")

    text = between(text, "  private async ask(frame: string): Promise<string> {", "  statusText(): string {\n",
                   ASK_REGION_NEW, "ask")
    text = once(text, "' | brain: ' + (this.lastModel || 'none yet') +",
                "' | brain: ' + (this.lastModel || 'none yet') + (this.lastKeyId ? ' (key ' + this.lastKeyId + ')' : '') +",
                "status")
    text = between(text, "  async promptForSlotKey(id: number, showInput: (o: any) => Promise<any>) {",
                   "  async promptForTrip(", SLOT_PROMPT_NEW, "slot prompt")

    # menu
    text = once(text, "          {id: 'radio:captions', title: 'Captions', active: this.getCaptions()},\n",
                "          {id: 'radio:captions', title: 'Captions', active: this.getCaptions()},\n"
                "          {id: 'radio:rules', title: 'Talk rules: tips, music, memory'},\n", "menu more")
    text = between(text, "      } else if (screen === 'keys') {\n", "      } else if (screen === 'logbook') {\n",
                   MENU_KEYS_AND_RULES, "menu screens")
    text = once(text, "      } else if (id === 'radio:keys') {\n", MENU_RULE_HANDLERS, "menu handlers")
    text = once(text, "          brain.newTrip();\n", "          brain.newTrip();\n          said.clear(); // QUALITY\n",
                "menu new trip")
    text = once(text, "        this.setNotes('');\n        this.history = [];\n        this.prevFrame = '';\n",
                "        this.setNotes('');\n        this.history = [];\n        said.clear(); // QUALITY\n        this.prevFrame = '';\n",
                "menu forget")

    write(p, text, crlf)
    print("radio.ts: quality rules, trip talk log, key routes and menu added")


def patch_workflow():
    p = ".github/workflows/build-tilt-apk.yml"
    if not pathlib.Path(p).exists():
        print("workflow file not found (%s): add this step yourself after 'Apply Sim Radio patch':" % p)
        print("      - name: Apply Sim Radio quality patch\n        run: python3 .github/apply_quality_patch.py")
        return
    text, crlf = read(p)
    if "apply_quality_patch.py" in text:
        print("workflow: already has the quality step")
        return
    anchor = "      - name: Apply Sim Radio patch\n        run: python3 .github/apply_radio_patch.py\n"
    if text.count(anchor) != 1:
        print("workflow: could not find the 'Apply Sim Radio patch' step. Add this step after it yourself:")
        print("      - name: Apply Sim Radio quality patch\n        run: python3 .github/apply_quality_patch.py")
        return
    text = text.replace(anchor, anchor + "\n      - name: Apply Sim Radio quality patch\n        run: python3 .github/apply_quality_patch.py\n", 1)
    write(p, text, crlf)
    print("workflow: quality step added after the Sim Radio patch")


def main():
    if not pathlib.Path("package.json").exists():
        die("Run this from the repo root (package.json not found).")
    if not pathlib.Path("src/utils/radio.ts").exists():
        die("src/utils/radio.ts not found. Run apply_radio_patch.py first (it also runs apply_brain_patch.py).")
    write("src/utils/said.ts", SAID_TS)
    print("wrote src/utils/said.ts")
    write("docs/sim-radio-quality.md", DOC_MD)
    print("wrote docs/sim-radio-quality.md")
    patch_radio_ts()
    patch_workflow()
    print("\nQUALITY patch OK")


if __name__ == "__main__":
    main()
