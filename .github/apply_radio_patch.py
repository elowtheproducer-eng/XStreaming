#!/usr/bin/env python3
"""
apply_radio_patch.py  -  XStreaming "Sim Radio": Gemini looks at the stream and talks about it.

Run from the REPO ROOT, AFTER apply_tilt_patch.py and apply_headtrack_patch.py:
    python3 .github/apply_radio_patch.py

What it does
  1. writes android/app/src/main/java/com/xstreaming/radio/RadioModule.java + RadioPackage.java
     (frame grab via PixelCopy, Android text-to-speech, radio click)
  2. registers RadioPackage in MainApplication.java
  3. writes src/utils/radio.ts (Gemini engine, model fallback chain, personas, settings)
  4. patches src/pages/NativeStream.tsx (pause-menu items "Start/Stop Sim Radio" + "Sim Radio settings")

Safe to re-run (RADIO marker). If an anchor is missing it STOPS and prints context: paste that log back.
"""
import pathlib
import re
import sys

MARK = "RADIO"
JAVA_DIR = "android/app/src/main/java/com/xstreaming/radio"


def die(msg, path=None, text=None, keywords=()):
    print("\n==================== RADIO PATCH FAILED ====================")
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
    print("============================================================")
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


# ------------------------------------------------------------------------------------------
# Java
# ------------------------------------------------------------------------------------------
RADIO_MODULE = r'''package com.xstreaming.radio;

// RADIO: frame grab + text-to-speech for Sim Radio

import android.app.Activity;
import android.graphics.Bitmap;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.util.Base64;
import android.view.PixelCopy;
import android.view.Surface;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;

import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class RadioModule extends ReactContextBaseJavaModule {
    private interface Ready { void run(boolean ok); }

    private TextToSpeech tts;
    private boolean ttsReady = false;
    private boolean ttsFailed = false;
    private final List<Ready> waiting = new ArrayList<>();
    private final Map<String, Promise> speakPromises = new ConcurrentHashMap<>();

    public RadioModule(ReactApplicationContext ctx) {
        super(ctx);
    }

    @NonNull
    @Override
    public String getName() {
        return "RadioModule";
    }

    // ---------------------------------------------------------------- frame grab
    @ReactMethod
    public void captureFrame(final int maxWidth, final int quality, final Promise promise) {
        final Activity activity = getCurrentActivity();
        if (activity == null) {
            promise.reject("NO_ACTIVITY", "Current activity is null");
            return;
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            promise.reject("UNSUPPORTED", "PixelCopy needs Android 8+");
            return;
        }
        activity.runOnUiThread(() -> {
            try {
                SurfaceView sv = findActiveSurfaceView(activity.getWindow().getDecorView());
                if (sv == null) {
                    promise.reject("NO_SURFACE", "No active video surface found");
                    return;
                }
                int w = sv.getWidth();
                int h = sv.getHeight();
                Surface surface = sv.getHolder().getSurface();
                if (w <= 1 || h <= 1 || surface == null || !surface.isValid()) {
                    promise.reject("INVALID_SURFACE", "Surface not ready");
                    return;
                }
                int tw = Math.min(maxWidth > 0 ? maxWidth : 768, w);
                int th = Math.max(1, Math.round(h * (tw / (float) w)));
                final Bitmap bmp = Bitmap.createBitmap(tw, th, Bitmap.Config.ARGB_8888);
                final HandlerThread ht = new HandlerThread("RadioPixelCopy");
                ht.start();
                Handler handler = new Handler(ht.getLooper());
                PixelCopy.request(sv, bmp, result -> {
                    try {
                        if (result == PixelCopy.SUCCESS) {
                            ByteArrayOutputStream bos = new ByteArrayOutputStream();
                            bmp.compress(Bitmap.CompressFormat.JPEG, quality > 0 ? quality : 70, bos);
                            promise.resolve(Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP));
                        } else {
                            promise.reject("COPY_FAILED", "PixelCopy failed: " + result);
                        }
                    } catch (Throwable t) {
                        promise.reject("ENCODE_FAILED", String.valueOf(t.getMessage()), t);
                    } finally {
                        bmp.recycle();
                        ht.quitSafely();
                    }
                }, handler);
            } catch (Throwable t) {
                promise.reject("CAPTURE_ERROR", String.valueOf(t.getMessage()), t);
            }
        });
    }

    private SurfaceView findActiveSurfaceView(View root) {
        List<SurfaceView> list = new ArrayList<>();
        collect(root, list);
        SurfaceView selected = null;
        int maxArea = 0;
        for (SurfaceView sv : list) {
            if (!sv.isShown() || sv.getVisibility() != View.VISIBLE || sv.getAlpha() <= 0.1f) continue;
            Surface s = sv.getHolder().getSurface();
            if (s == null || !s.isValid()) continue;
            int w = sv.getWidth();
            int h = sv.getHeight();
            if (w <= 1 || h <= 1) continue;
            if (sv.getClass().getSimpleName().contains("GLSurfaceView") && sv.getAlpha() > 0.5f) return sv;
            int area = w * h;
            if (area > maxArea) {
                maxArea = area;
                selected = sv;
            }
        }
        return selected;
    }

    private void collect(View v, List<SurfaceView> out) {
        if (v == null) return;
        if (v instanceof SurfaceView) out.add((SurfaceView) v);
        if (v instanceof ViewGroup) {
            ViewGroup vg = (ViewGroup) v;
            for (int i = 0; i < vg.getChildCount(); i++) collect(vg.getChildAt(i), out);
        }
    }

    // ---------------------------------------------------------------- text to speech
    private void ensureTts(final Ready cb) {
        new Handler(Looper.getMainLooper()).post(() -> {
            synchronized (waiting) {
                if (ttsReady) { cb.run(true); return; }
                if (ttsFailed) { cb.run(false); return; }
                waiting.add(cb);
                if (tts != null) return;
                tts = new TextToSpeech(getReactApplicationContext(), status -> {
                    List<Ready> copy;
                    synchronized (waiting) {
                        if (status == TextToSpeech.SUCCESS) {
                            try { tts.setLanguage(Locale.getDefault()); } catch (Throwable ignored) { }
                            tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                                @Override public void onStart(String id) { }
                                @Override public void onDone(String id) { finish(id, true); }
                                @Override public void onError(String id) { finish(id, false); }
                                @Override public void onStop(String id, boolean interrupted) { finish(id, false); }
                            });
                            ttsReady = true;
                        } else {
                            ttsFailed = true;
                        }
                        copy = new ArrayList<>(waiting);
                        waiting.clear();
                    }
                    for (Ready r : copy) r.run(ttsReady);
                });
            }
        });
    }

    private void finish(String id, boolean ok) {
        Promise p = speakPromises.remove(id);
        if (p != null) p.resolve(ok);
    }

    @ReactMethod
    public void speak(final String text, final double rate, final double pitch, final Promise promise) {
        ensureTts(ok -> {
            if (!ok || text == null || text.trim().isEmpty()) { promise.resolve(false); return; }
            String t = text.length() > 800 ? text.substring(0, 800) : text;
            String id = "radio_" + System.nanoTime();
            speakPromises.put(id, promise);
            try {
                tts.setSpeechRate((float) (rate > 0 ? rate : 1.0));
                tts.setPitch((float) (pitch > 0 ? pitch : 1.0));
                int r = tts.speak(t, TextToSpeech.QUEUE_FLUSH, null, id);
                if (r != TextToSpeech.SUCCESS) finish(id, false);
            } catch (Throwable e) {
                finish(id, false);
            }
        });
    }

    @ReactMethod
    public void stopSpeaking() {
        new Handler(Looper.getMainLooper()).post(() -> {
            try { if (tts != null && ttsReady) tts.stop(); } catch (Throwable ignored) { }
        });
    }

    @ReactMethod
    public void log(String msg) {
        try { com.xstreaming.HeadLog.i("Radio", msg); } catch (Throwable ignored) { }
    }

    // short "radio keyed" blip before a transmission
    @ReactMethod
    public void click() {
        try {
            final ToneGenerator tg = new ToneGenerator(AudioManager.STREAM_MUSIC, 30);
            tg.startTone(ToneGenerator.TONE_PROP_BEEP2, 90);
            new Handler(Looper.getMainLooper()).postDelayed(tg::release, 400);
        } catch (Throwable ignored) { }
    }

    @Override
    public void invalidate() {
        super.invalidate();
        try { if (tts != null) { tts.stop(); tts.shutdown(); } } catch (Throwable ignored) { }
        tts = null;
        ttsReady = false;
    }
}
'''

RADIO_PACKAGE = r'''package com.xstreaming.radio;

import androidx.annotation.NonNull;

import com.facebook.react.ReactPackage;
import com.facebook.react.bridge.NativeModule;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.uimanager.ViewManager;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class RadioPackage implements ReactPackage {
    @NonNull
    @Override
    public List<NativeModule> createNativeModules(@NonNull ReactApplicationContext ctx) {
        List<NativeModule> m = new ArrayList<>();
        m.add(new RadioModule(ctx));
        return m;
    }

    @NonNull
    @Override
    public List<ViewManager> createViewManagers(@NonNull ReactApplicationContext ctx) {
        return Collections.emptyList();
    }
}
'''

# ------------------------------------------------------------------------------------------
# TypeScript engine
# ------------------------------------------------------------------------------------------
RADIO_TS = r'''// RADIO: Sim Radio engine. Looks at the stream with Gemini and talks about it.
import {NativeModules, ToastAndroid} from 'react-native';
import {storage} from '../store/mmkv';

const {RadioModule} = NativeModules;

// Best -> worst. First one that is available and not capped is used; on quota / unavailable errors
// it silently drops to the next. Edit this list any time Google renames models.
export const MODEL_CHAIN = [
  'gemini-3.8-flash',
  'gemini-3.7-flash',
  'gemini-3.6-flash',
  'gemini-3.5-flash',
  'gemini-3.5-flash-lite',
  'gemini-3.1-flash-lite',
  'gemini-2.5-flash',
  'gemini-2.5-flash-lite',
  'gemini-flash-latest',
  'gemini-flash-lite-latest',
];

const API = 'https://generativelanguage.googleapis.com/v1beta';
const KEY_API = 'radio_api_key';
const KEY_PERSONA = 'radio_persona';
const KEY_INTERVAL = 'radio_interval';
const KEY_CAPTIONS = 'radio_captions';

export const PERSONAS: Array<{id: string; name: string; prompt: string}> = [
  {
    id: 'bush',
    name: 'Bush Radio host',
    prompt:
      'You are the host of "Bush Radio", a warm, dry-witted radio station for a pilot flying a small plane in a flight simulator. If instruments or a map are readable (altitude, speed, heading, coordinates, airport/waypoint names, terrain labels), use them to work out where the plane is and say something real about that region: geography, wildlife, towns, history, weather. If you are on the ground or in a menu, chat about the airfield or the trip. Stay in character.',
  },
  {
    id: 'guide',
    name: 'Tour guide',
    prompt:
      'You are an enthusiastic tour guide narrating what the player is looking at in a game. Point out landmarks, scenery and interesting details, and add a short fun fact when it fits.',
  },
  {
    id: 'doc',
    name: 'Nature documentary',
    prompt:
      'You are a calm, hushed nature-documentary narrator. Describe what is on screen as if it were wildlife footage: gentle, observant, a little poetic.',
  },
  {
    id: 'sports',
    name: 'Race commentator',
    prompt:
      'You are an excitable motorsport commentator. React to the action on screen: speed, position, corners, close calls, crashes. Short punchy lines.',
  },
  {
    id: 'copilot',
    name: 'Sarcastic co-pilot',
    prompt:
      'You are a sarcastic but loyal co-pilot sitting next to the player. Make dry, funny observations about what they are doing and what is on screen, never mean.',
  },
  {
    id: 'atc',
    name: 'ATC / traffic',
    prompt:
      'You are a friendly air-traffic and traffic-info voice. Give short, professional-sounding calls about what is visible: terrain ahead, airfield, weather, obstacles, plus the occasional advisory.',
  },
];

const INTERVALS = [15, 30, 60, 120];

type Cooldowns = Record<string, number>;

class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super('HTTP ' + status + ' ' + body.slice(0, 160));
    this.status = status;
    this.body = body;
  }
}

const toast = (msg: string) => {
  try {
    ToastAndroid.show(msg, ToastAndroid.SHORT);
  } catch (e) {}
};

class SimRadio {
  private on = false;
  private busy = false;
  private timer: any = null;
  private history: string[] = [];
  private cooldown: Cooldowns = {};
  private available: string[] | null = null;
  private availableAt = 0;
  private lastModel = '';
  private lastError = '';
  private lastErrorToastAt = 0;

  // ---------- settings ----------
  getApiKey(): string {
    return storage.getString(KEY_API) || '';
  }
  setApiKey(k: string) {
    storage.set(KEY_API, (k || '').trim());
  }
  getPersonaId(): string {
    return storage.getString(KEY_PERSONA) || 'bush';
  }
  setPersonaId(id: string) {
    storage.set(KEY_PERSONA, id);
  }
  getInterval(): number {
    return storage.getNumber(KEY_INTERVAL) || 30;
  }
  setInterval(s: number) {
    storage.set(KEY_INTERVAL, s);
  }
  getCaptions(): boolean {
    const v = storage.getBoolean(KEY_CAPTIONS);
    return v === undefined ? true : v;
  }
  setCaptions(v: boolean) {
    storage.set(KEY_CAPTIONS, v);
  }
  isOn() {
    return this.on;
  }

  // ---------- lifecycle ----------
  start() {
    if (this.on) {
      return;
    }
    this.on = true;
    this.schedule(2500);
  }

  stop() {
    this.on = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    try {
      RadioModule?.stopSpeaking?.();
    } catch (e) {}
  }

  private schedule(ms: number) {
    if (!this.on) {
      return;
    }
    if (this.timer) {
      clearTimeout(this.timer);
    }
    this.timer = setTimeout(() => this.tick(false), ms);
  }

  async talkNow() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    await this.tick(true);
  }

  private async tick(force: boolean) {
    if ((!this.on && !force) || this.busy) {
      return;
    }
    this.busy = true;
    try {
      const frame = await RadioModule.captureFrame(768, 70);
      const text = await this.ask(frame);
      this.log('model=' + this.lastModel + ' said=' + (text || '(skip)'));
      if (text && (this.on || force)) {
        this.history.push(text);
        if (this.history.length > 8) {
          this.history.shift();
        }
        if (this.getCaptions()) {
          toast('📻 ' + text);
        }
        RadioModule?.click?.();
        await Promise.race([
          RadioModule?.speak?.(text, 1.0, 0.95),
          new Promise(res =>
            setTimeout(() => {
              RadioModule?.stopSpeaking?.();
              res(false);
            }, 30000),
          ),
        ]);
      }
    } catch (e: any) {
      this.noteError(e);
    } finally {
      this.busy = false;
      this.schedule(this.getInterval() * 1000);
    }
  }

  private log(m: string) {
    try {
      RadioModule?.log?.(m);
    } catch (e) {}
  }

  private noteError(e: any) {
    const msg = String(e?.message || e);
    this.lastError = msg;
    this.log('error: ' + msg);
    const now = Date.now();
    if (/NO_SURFACE|INVALID_SURFACE|NO_ACTIVITY/.test(msg)) {
      return; // stream not showing yet
    }
    if (now - this.lastErrorToastAt > 120000) {
      this.lastErrorToastAt = now;
      toast('Radio: ' + msg.slice(0, 120));
    }
  }

  // ---------- Gemini ----------
  private async refreshAvailable(key: string) {
    if (this.available && Date.now() - this.availableAt < 6 * 3600 * 1000) {
      return;
    }
    try {
      const r = await this.timedFetch(API + '/models?pageSize=200', {
        headers: {'x-goog-api-key': key},
      });
      if (!r.ok) {
        return;
      }
      const j: any = await r.json();
      const names: string[] = (j?.models || [])
        .filter((m: any) =>
          (m?.supportedGenerationMethods || []).includes('generateContent'),
        )
        .map((m: any) => String(m.name || '').replace(/^models\//, ''));
      if (names.length > 0) {
        this.available = names;
        this.availableAt = Date.now();
      }
    } catch (e) {}
  }

  private async timedFetch(url: string, init: any, ms = 15000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, {...init, signal: ctrl.signal});
    } finally {
      clearTimeout(t);
    }
  }

  private candidates(): string[] {
    const now = Date.now();
    const base = this.available
      ? MODEL_CHAIN.filter(m => this.available!.includes(m))
      : MODEL_CHAIN;
    const list = base.length > 0 ? base : MODEL_CHAIN;
    return list.filter(m => (this.cooldown[m] || 0) <= now);
  }

  private setCooldown(model: string, e: ApiError) {
    const b = e.body || '';
    let ms = 60 * 1000;
    if (e.status === 429) {
      ms = /PerDay|per day|daily/i.test(b) ? 6 * 3600 * 1000 : 10 * 60 * 1000;
    } else if (e.status === 404 || e.status === 400) {
      ms = 6 * 3600 * 1000;
    } else if (e.status === 403) {
      ms = 30 * 60 * 1000;
    }
    this.cooldown[model] = Date.now() + ms;
  }

  private buildPrompt(): {system: string; user: string} {
    const persona =
      PERSONAS.find(p => p.id === this.getPersonaId()) || PERSONAS[0];
    const system =
      persona.prompt +
      ' You receive one screenshot from a game stream every so often. Reply with ONLY the words to be spoken aloud: 1 to 3 short sentences, under 45 words, no emojis, no markdown, no stage directions. Do not repeat anything you already said. If the screen is only a loading screen, black, a menu, or essentially unchanged and there is nothing new to say, reply with exactly: SKIP';
    const recent = this.history.slice(-6);
    const user =
      (recent.length
        ? 'Things you already said (do not repeat): ' +
          recent.map(h => '"' + h + '"').join(' | ') +
          '\n'
        : '') + 'Here is the current screen. Say something.';
    return {system, user};
  }

  private async generate(model: string, key: string, frame: string) {
    const {system, user} = this.buildPrompt();
    const r = await this.timedFetch(
      API + '/models/' + model + ':generateContent',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'x-goog-api-key': key},
        body: JSON.stringify({
          systemInstruction: {parts: [{text: system}]},
          contents: [
            {
              role: 'user',
              parts: [
                {text: user},
                {inline_data: {mime_type: 'image/jpeg', data: frame}},
              ],
            },
          ],
          generationConfig: {temperature: 0.9, maxOutputTokens: 1024},
        }),
      },
    );
    const raw = await r.text();
    if (!r.ok) {
      throw new ApiError(r.status, raw);
    }
    let j: any = {};
    try {
      j = JSON.parse(raw);
    } catch (e) {}
    if (j?.promptFeedback?.blockReason) {
      return 'SKIP';
    }
    const parts: any[] = j?.candidates?.[0]?.content?.parts || [];
    const text = parts
      .filter(p => typeof p?.text === 'string' && !p.thought)
      .map(p => p.text)
      .join(' ')
      .trim();
    if (!text) {
      throw new ApiError(0, 'empty reply (' + (j?.candidates?.[0]?.finishReason || '?') + ')');
    }
    return text;
  }

  private clean(t: string) {
    return t
      .replace(/[*_#`>~]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  private async ask(frame: string): Promise<string> {
    const key = this.getApiKey();
    if (!key) {
      throw new Error('no Gemini API key set');
    }
    await this.refreshAvailable(key);
    const tried: string[] = [];
    for (const model of this.candidates()) {
      try {
        const out = this.clean(await this.generate(model, key, frame));
        this.lastModel = model;
        this.lastError = '';
        if (!out || /^SKIP\b/i.test(out)) {
          return '';
        }
        return out;
      } catch (e: any) {
        tried.push(model);
        if (e instanceof ApiError) {
          if (e.status === 401 || (e.status === 400 && /API key/i.test(e.body))) {
            throw new Error('API key rejected by Google');
          }
          this.setCooldown(model, e);
          this.lastError = model + ': ' + e.message;
        } else {
          // timeout / network hiccup on this model: park it briefly and try the next one
          this.cooldown[model] = Date.now() + 90 * 1000;
          this.lastError =
            model + ': ' + (e?.name === 'AbortError' ? 'timeout' : String(e?.message || e));
        }
        this.log('fallback from ' + model + ' -> ' + this.lastError);
      }
    }
    if (tried.length === 0) {
      throw new Error('all models capped, waiting for quota');
    }
    throw new Error('all models failed. last: ' + this.lastError);
  }

  statusText(): string {
    const now = Date.now();
    const capped = Object.keys(this.cooldown).filter(m => this.cooldown[m] > now);
    return (
      (this.on ? 'ON' : 'OFF') +
      ' | model: ' +
      (this.lastModel || 'none yet') +
      (capped.length ? ' | capped: ' + capped.join(', ') : '') +
      (this.lastError ? ' | last error: ' + this.lastError.slice(0, 140) : '')
    );
  }

  // ---------- UI helpers (use the app's native dialogs) ----------
  async promptForKey(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Gemini API key',
      message: 'Free key from aistudio.google.com/apikey',
      hint: 'AIza...',
      text: this.getApiKey(),
      maxLength: 200,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      this.setApiKey(r.text || '');
      this.available = null;
      this.cooldown = {};
      toast(this.getApiKey() ? 'Gemini key saved' : 'Key cleared');
    }
  }

  async openMenu(
    showOptions: (items: any[], o?: any) => Promise<any>,
    showInput: (o: any) => Promise<any>,
  ) {
    const pause = () => new Promise(r => setTimeout(r, 150));
    let screen = 'main';
    for (let guard = 0; guard < 40; guard++) {
      const pid = this.getPersonaId();
      const iv = this.getInterval();
      let items: any[] = [];
      if (screen === 'main') {
        const pname = (PERSONAS.find(p => p.id === pid) || PERSONAS[0]).name;
        items = [
          {id: 'radio:toggle', title: this.on ? 'Stop radio' : 'Start radio', active: this.on},
          {id: 'radio:now', title: 'Talk now'},
          {id: 'radio:voice', title: 'Voice: ' + pname},
          {id: 'radio:interval', title: 'Talk every ' + iv + 's'},
          {id: 'radio:key', title: this.getApiKey() ? 'API key: set' : 'API key: NOT SET'},
          {id: 'radio:captions', title: 'Captions', active: this.getCaptions()},
          {id: 'radio:status', title: 'Status / last error'},
        ];
      } else if (screen === 'voice') {
        items = PERSONAS.map(p => ({id: 'radio:persona:' + p.id, title: p.name, active: p.id === pid}));
        items.push({id: 'radio:back', title: 'Back'});
      } else {
        items = INTERVALS.map(s => ({id: 'radio:interval:' + s, title: 'Every ' + s + ' seconds', active: s === iv}));
        items.push({id: 'radio:back', title: 'Back'});
      }
      const res = await showOptions(items, {});
      if (res?.action !== 'select') {
        return;
      }
      const id: string = String(res.id || '');
      if (id === 'radio:toggle') {
        if (this.on) {
          this.stop();
          toast('Sim Radio off');
        } else {
          if (!this.getApiKey()) {
            await this.promptForKey(showInput);
          }
          if (this.getApiKey()) {
            this.start();
            toast('Sim Radio on');
          }
        }
        return;
      } else if (id === 'radio:now') {
        if (!this.getApiKey()) {
          await this.promptForKey(showInput);
        }
        if (this.getApiKey()) {
          this.talkNow();
        }
        return;
      } else if (id === 'radio:voice') {
        screen = 'voice';
      } else if (id === 'radio:interval') {
        screen = 'interval';
      } else if (id === 'radio:back') {
        screen = 'main';
      } else if (id === 'radio:key') {
        await this.promptForKey(showInput);
      } else if (id === 'radio:captions') {
        this.setCaptions(!this.getCaptions());
      } else if (id === 'radio:status') {
        ToastAndroid.show(this.statusText(), ToastAndroid.LONG);
      } else if (id.startsWith('radio:persona:')) {
        this.setPersonaId(id.slice('radio:persona:'.length));
        this.history = [];
        screen = 'main';
      } else if (id.startsWith('radio:interval:')) {
        this.setInterval(parseInt(id.slice('radio:interval:'.length), 10) || 30);
        screen = 'main';
      }
      await pause();
    }
  }
}

const radio = new SimRadio();
export default radio;
'''

# ------------------------------------------------------------------------------------------
# NativeStream.tsx edits
# ------------------------------------------------------------------------------------------
CASES = r'''      // RADIO ---- Sim Radio
      case 'radioMenu': {
        try {
          GamepadManager.setCurrentScreen('');
          resumeGamepadNavigation();
          await radio.openMenu(showNativeOptionsDialog, showNativeInputDialog);
        } catch (err: any) {
          ToastAndroid.show(err?.message || 'Radio error', ToastAndroid.SHORT);
        } finally {
          GamepadManager.setCurrentScreen('stream');
          suspendGamepadNavigation();
        }
        break;
      }
'''

ITEMS = r'''
      // RADIO
      items.push({
        id: 'radioMenu',
        title: radio.isOn() ? '📻 Sim Radio (ON)' : '📻 Sim Radio',
        active: radio.isOn(),
      });'''


def patch_main_application():
    p = "android/app/src/main/java/com/xstreaming/MainApplication.java"
    text, crlf = read(p)
    if "RadioPackage" in text:
        print("MainApplication.java: already patched")
        return
    m = re.search(r"\n([ \t]*)packages\.add\(new ScreenshotPackage\(\)\);", text)
    if not m:
        die("Could not find 'packages.add(new ScreenshotPackage());'", p, text, ("packages.add", "Package"))
    ins = "\n%s// RADIO\n%spackages.add(new com.xstreaming.radio.RadioPackage());" % (m.group(1), m.group(1))
    text = text[: m.end()] + ins + text[m.end():]
    write(p, text, crlf)
    print("MainApplication.java: RadioPackage registered")


def patch_native_stream():
    p = "src/pages/NativeStream.tsx"
    text, crlf = read(p)
    if "RADIO" in text:
        print("NativeStream.tsx: already patched")
        return
    kw = ("takeScreenshot", "screenshot", "isRecording")

    # 1. import
    anchor = "import screenshot from '../utils/screenshot';"
    if text.count(anchor) != 1:
        die("Expected exactly one screenshot import line.", p, text, kw)
    text = text.replace(anchor, anchor + "\nimport radio from '../utils/radio'; // RADIO")

    # 2. unmount cleanup
    anchor = "  const [isRecording, setIsRecording] = React.useState(false);\n"
    if text.count(anchor) != 1:
        die("Expected exactly one isRecording useState line.", p, text, kw)
    text = text.replace(
        anchor,
        anchor + "\n  // RADIO: stop the radio when leaving the stream screen\n  React.useEffect(() => {\n    return () => {\n      radio.stop();\n    };\n  }, []);\n",
    )

    # 3. menu items (after the Take Screenshot item)
    pat = re.compile(r"(      items\.push\(\{\s*id: 'takeScreenshot',\s*title: t\('Take Screenshot'\),\s*\}\);)")
    ms = list(pat.finditer(text))
    if len(ms) != 1:
        die("Expected exactly one 'takeScreenshot' menu item, found %d." % len(ms), p, text, kw)
    text = text[: ms[0].end()] + ITEMS + text[ms[0].end():]

    # 4. switch cases (before case 'takeScreenshot')
    anchor = "      case 'takeScreenshot': {"
    if text.count(anchor) != 1:
        die("Expected exactly one case 'takeScreenshot'.", p, text, kw)
    text = text.replace(anchor, CASES + anchor)

    write(p, text, crlf)
    print("NativeStream.tsx: radio menu + cases added")


def main():
    if not pathlib.Path("package.json").exists():
        die("Run this from the repo root (package.json not found).")
    write(JAVA_DIR + "/RadioModule.java", RADIO_MODULE)
    write(JAVA_DIR + "/RadioPackage.java", RADIO_PACKAGE)
    print("wrote Java classes")
    write("src/utils/radio.ts", RADIO_TS)
    print("wrote src/utils/radio.ts")
    patch_main_application()
    patch_native_stream()
    print("\nRADIO patch OK")


main()