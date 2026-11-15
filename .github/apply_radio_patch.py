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
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
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

    private volatile AudioTrack currentTrack;

    // plays raw 16-bit mono PCM (Gemini voice), resolves true when finished
    @ReactMethod
    public void playPcm(final String b64, final int sampleRate, final Promise promise) {
        new Thread(() -> {
            AudioTrack track = null;
            try {
                byte[] data = Base64.decode(b64, Base64.DEFAULT);
                int off = 0;
                if (data.length > 44 && data[0] == 'R' && data[1] == 'I' && data[2] == 'F' && data[3] == 'F') off = 44;
                int len = data.length - off;
                if (len < 2) { promise.resolve(false); return; }
                int rate = sampleRate > 0 ? sampleRate : 24000;
                int frames = len / 2;
                track = new AudioTrack.Builder()
                        .setAudioAttributes(new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build())
                        .setAudioFormat(new AudioFormat.Builder()
                                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                .setSampleRate(rate)
                                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                                .build())
                        .setBufferSizeInBytes(len)
                        .setTransferMode(AudioTrack.MODE_STATIC)
                        .build();
                track.write(data, off, len);
                currentTrack = track;
                track.play();
                long deadline = System.currentTimeMillis() + (frames * 1000L / rate) + 3000;
                while (System.currentTimeMillis() < deadline && currentTrack == track
                        && track.getPlayState() == AudioTrack.PLAYSTATE_PLAYING
                        && track.getPlaybackHeadPosition() < frames - 200) {
                    Thread.sleep(40);
                }
                Thread.sleep(150);
                promise.resolve(true);
            } catch (Throwable t) {
                promise.resolve(false);
            } finally {
                try { if (track != null) { track.stop(); track.release(); } } catch (Throwable ignored) { }
                if (currentTrack == track) currentTrack = null;
            }
        }, "RadioPcm").start();
    }

    @ReactMethod
    public void stopSpeaking() {
        try {
            AudioTrack t = currentTrack;
            currentTrack = null;
            if (t != null) t.stop();
        } catch (Throwable ignored) { }
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
RADIO_TS = r'''// RADIO: Sim Radio engine. Watches the stream with Gemini, keeps a running trip notebook, and talks.
import {NativeModules, ToastAndroid} from 'react-native';
import {storage} from '../store/mmkv';

const {RadioModule} = NativeModules;

// Vision/brain models, best -> worst. Unavailable / capped / timing out => next one.
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

// Natural-voice (speech) models, best -> worst. If all fail the phone's own voice is used.
export const TTS_CHAIN = [
  'gemini-3.8-flash-tts',
  'gemini-3.1-flash-tts-preview',
  'gemini-2.5-flash-preview-tts',
];

export const SPEAKERS: Array<{id: string; name: string}> = [
  {id: 'Charon', name: 'Charon (deep, informative)'},
  {id: 'Fenrir', name: 'Fenrir (excitable)'},
  {id: 'Orus', name: 'Orus (firm)'},
  {id: 'Puck', name: 'Puck (upbeat)'},
  {id: 'Kore', name: 'Kore (firm, female)'},
  {id: 'Aoede', name: 'Aoede (breezy, female)'},
  {id: 'Zephyr', name: 'Zephyr (bright, female)'},
  {id: 'Algenib', name: 'Algenib (gravelly)'},
  {id: 'Phone voice', name: 'Phone voice (offline)'},
];

const API = 'https://generativelanguage.googleapis.com/v1beta';
const K_API = 'radio_api_key';
const K_PERSONA = 'radio_persona';
const K_INTERVAL = 'radio_interval';
const K_CAPTIONS = 'radio_captions';
const K_SPEAKER = 'radio_speaker';
const K_TRIP = 'radio_trip';
const K_NOTES = 'radio_notebook';

export const PERSONAS: Array<{id: string; name: string; prompt: string; style: string}> = [
  {
    id: 'bush',
    name: 'Bush Radio host',
    style:
      'Speak like a warm, slightly gravelly, relaxed late-night radio host with dry humour, natural pacing and small pauses',
    prompt:
      'You are the host of "Bush Radio", a late-night station for a pilot flying a small bush plane around the world. You are warm, dry-witted, curious and a little cheeky, and you love local stories, geography, wildlife and aviation history. You are talking to ONE listener, the pilot, like an old friend.',
  },
  {
    id: 'storyteller',
    name: 'Old bush pilot',
    style: 'Speak like a weathered old bush pilot telling stories, unhurried, gravelly and amused',
    prompt:
      'You are an old, retired bush pilot riding along on the radio, full of true stories, hard-won flying wisdom and opinions about every airstrip and landscape. Tie what you see to real aviation history, real regions and real flying lessons. Facts must be correct; the telling can be colourful.',
  },
  {
    id: 'guide',
    name: 'Tour guide',
    style: 'Speak like an enthusiastic, friendly tour guide, clear and bright',
    prompt:
      'You are an enthusiastic expert tour guide narrating the flight. Name landmarks, rivers, towns, mountains and what makes them interesting, with one surprising fact at a time.',
  },
  {
    id: 'doc',
    name: 'Nature documentary',
    style: 'Speak in a calm, hushed, reverent nature-documentary narrator voice',
    prompt:
      'You are a calm, hushed nature-documentary narrator. Describe the land, wildlife, climate and human history below as if it were a documentary, with poetic but concrete detail.',
  },
  {
    id: 'sports',
    name: 'Race commentator',
    style: 'Speak like an excited motorsport commentator, fast and punchy',
    prompt:
      'You are an excitable motorsport commentator. React to the action: speed, position, corners, close calls, crashes, the road or track and the location. Short punchy energy.',
  },
  {
    id: 'copilot',
    name: 'Sarcastic co-pilot',
    style: 'Speak like a dry, sarcastic but affectionate co-pilot, deadpan',
    prompt:
      'You are a sarcastic but loyal co-pilot sitting next to the pilot. You notice real details of where we are and what is happening, and make dry funny remarks, never mean.',
  },
  {
    id: 'atc',
    name: 'ATC / traffic',
    style: 'Speak like a calm professional air-traffic controller with a friendly edge',
    prompt:
      'You are a friendly air-traffic and traffic-information voice. Give professional-sounding calls about terrain ahead, airfields, weather and obstacles, with the odd advisory about what is coming up on the route.',
  },
];

const SEGMENTS = [
  'name the exact landmark, town, river, mountain or airfield below or ahead and give ONE surprising fact about it',
  'tell a short true piece of local history or a human story tied to this area',
  'colour about the wildlife, terrain, climate or weather typical of this exact region and altitude',
  'react to the latest ATC subtitle or what the pilot is doing right now, with personality',
  'trip progress: where we came from, where we are heading, what comes next on the route',
  'a quick funny observation or bit of banter based on something visible on screen',
  'tell the listener what to look out for in the next few minutes of flight',
  'a short legend or story connected to a place we have just passed',
];

const INTERVALS = [10, 15, 30, 60, 120];

class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super('HTTP ' + status + ' ' + body.slice(0, 160));
    this.status = status;
    this.body = body;
  }
}

const toast = (msg: string, long = false) => {
  try {
    ToastAndroid.show(msg, long ? ToastAndroid.LONG : ToastAndroid.SHORT);
  } catch (e) {}
};

class SimRadio {
  private on = false;
  private busy = false;
  private timer: any = null;
  private history: string[] = [];
  private cooldown: Record<string, number> = {};
  private available: string[] | null = null;
  private availableAt = 0;
  private lastModel = '';
  private lastVoice = '';
  private lastError = '';
  private lastErrorToastAt = 0;
  private prevFrame = '';
  private prevFrameAt = 0;
  private lastSegment = -1;
  private startedAt = 0;

  // ---------- settings ----------
  getApiKey(): string {
    return storage.getString(K_API) || '';
  }
  setApiKey(k: string) {
    storage.set(K_API, (k || '').trim());
  }
  getPersonaId(): string {
    return storage.getString(K_PERSONA) || 'bush';
  }
  setPersonaId(id: string) {
    storage.set(K_PERSONA, id);
  }
  getInterval(): number {
    return storage.getNumber(K_INTERVAL) || 15;
  }
  setInterval(s: number) {
    storage.set(K_INTERVAL, s);
  }
  getCaptions(): boolean {
    const v = storage.getBoolean(K_CAPTIONS);
    return v === undefined ? true : v;
  }
  setCaptions(v: boolean) {
    storage.set(K_CAPTIONS, v);
  }
  getSpeaker(): string {
    return storage.getString(K_SPEAKER) || 'Charon';
  }
  setSpeaker(s: string) {
    storage.set(K_SPEAKER, s);
  }
  getTrip(): string {
    return storage.getString(K_TRIP) || '';
  }
  setTrip(s: string) {
    storage.set(K_TRIP, (s || '').trim());
  }
  getNotes(): string {
    return storage.getString(K_NOTES) || '';
  }
  setNotes(s: string) {
    storage.set(K_NOTES, (s || '').slice(0, 900));
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
    this.startedAt = Date.now();
    this.prevFrame = '';
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

  private log(m: string) {
    try {
      RadioModule?.log?.(m);
    } catch (e) {}
  }

  private async tick(force: boolean) {
    if ((!this.on && !force) || this.busy) {
      return;
    }
    this.busy = true;
    try {
      const frame: string = await RadioModule.captureFrame(1024, 75);
      const text = await this.ask(frame);
      this.prevFrame = frame;
      this.prevFrameAt = Date.now();
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
        await this.say(text);
      }
    } catch (e: any) {
      this.noteError(e);
    } finally {
      this.busy = false;
      this.schedule(this.getInterval() * 1000);
    }
  }

  private noteError(e: any) {
    const msg = String(e?.message || e);
    this.lastError = msg;
    this.log('error: ' + msg);
    if (/NO_SURFACE|INVALID_SURFACE|NO_ACTIVITY/.test(msg)) {
      return;
    }
    const now = Date.now();
    if (now - this.lastErrorToastAt > 120000) {
      this.lastErrorToastAt = now;
      toast('Radio: ' + msg.slice(0, 120));
    }
  }

  // ---------- speaking ----------
  private async say(text: string) {
    let spoken = false;
    if (this.getSpeaker() !== 'Phone voice') {
      try {
        spoken = await Promise.race([
          this.speakGemini(text),
          new Promise<boolean>(res => setTimeout(() => res(false), 45000)),
        ]);
      } catch (e: any) {
        this.log('gemini voice failed: ' + String(e?.message || e));
      }
    }
    if (!spoken) {
      await Promise.race([
        RadioModule?.speak?.(text, 1.0, 0.92),
        new Promise(res =>
          setTimeout(() => {
            RadioModule?.stopSpeaking?.();
            res(false);
          }, 30000),
        ),
      ]);
    }
  }

  private ttsCandidates(): string[] {
    const now = Date.now();
    let list = TTS_CHAIN.slice();
    if (this.available) {
      const have = TTS_CHAIN.filter(m => this.available!.includes(m));
      const extra = this.available
        .filter(m => /tts/i.test(m) && !TTS_CHAIN.includes(m))
        .sort()
        .reverse();
      list = have.concat(extra);
      if (list.length === 0) {
        list = TTS_CHAIN.slice();
      }
    }
    return list.filter(m => (this.cooldown[m] || 0) <= now);
  }

  private async speakGemini(text: string): Promise<boolean> {
    const key = this.getApiKey();
    const persona = PERSONAS.find(p => p.id === this.getPersonaId()) || PERSONAS[0];
    for (const model of this.ttsCandidates()) {
      try {
        const r = await this.timedFetch(
          API + '/models/' + model + ':generateContent',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'x-goog-api-key': key},
            body: JSON.stringify({
              contents: [{parts: [{text: persona.style + ': ' + text}]}],
              generationConfig: {
                responseModalities: ['AUDIO'],
                speechConfig: {
                  voiceConfig: {prebuiltVoiceConfig: {voiceName: this.getSpeaker()}},
                },
              },
            }),
          },
          25000,
        );
        const raw = await r.text();
        if (!r.ok) {
          throw new ApiError(r.status, raw);
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
        const ok = await RadioModule.playPcm(inl.data, rate);
        this.lastVoice = model;
        return !!ok;
      } catch (e: any) {
        if (e instanceof ApiError) {
          this.setCooldown(model, e);
        } else {
          this.cooldown[model] = Date.now() + 90 * 1000;
        }
        this.log('voice fallback from ' + model + ': ' + String(e?.message || e));
      }
    }
    return false;
  }

  // ---------- Gemini (brain) ----------
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
        .filter((m: any) => (m?.supportedGenerationMethods || []).includes('generateContent'))
        .map((m: any) => String(m.name || '').replace(/^models\//, ''));
      if (names.length > 0) {
        this.available = names;
        this.availableAt = Date.now();
      }
    } catch (e) {}
  }

  private async timedFetch(url: string, init: any, ms = 20000) {
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
    const base = this.available ? MODEL_CHAIN.filter(m => this.available!.includes(m)) : MODEL_CHAIN;
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

  private pickSegment(): string {
    let i = Math.floor(Math.random() * SEGMENTS.length);
    if (i === this.lastSegment) {
      i = (i + 1) % SEGMENTS.length;
    }
    this.lastSegment = i;
    return SEGMENTS[i];
  }

  private buildPrompt(hasPrev: boolean): {system: string; user: string} {
    const persona = PERSONAS.find(p => p.id === this.getPersonaId()) || PERSONAS[0];
    const system =
      persona.prompt +
      '\n\nYou are both the brain and the voice of the show. Each turn you get the current screen from the game stream' +
      (hasPrev ? ' (plus an earlier screen so you can see movement)' : '') +
      ', the trip brief, your running notebook and your recent lines.' +
      '\nREAD ALL ON-SCREEN TEXT carefully: HUD and instrument readouts, map, place-name and UI banners, waypoint and airport identifiers, ATC subtitles and callsigns. From these, work out exactly where the aircraft is and what is below, ahead and nearby, then use your world knowledge to talk about the REAL place: its landmarks, rivers, towns, mountains, history, wildlife and culture. If you cannot justify a place from the screen or notebook, hedge once ("looks like...") instead of inventing.' +
      '\nReply in EXACTLY this format:' +
      '\nSTATE: <60 words max. Updated notebook: where we are (place names, airfield, region), heading/altitude/phase of flight, landmarks passed, next expected landmark or waypoint, anything the pilot is doing. Keep useful facts from the old notebook.>' +
      '\nSAY: <the words to speak aloud>' +
      '\nSAY rules: 45 to 75 words, conversational, specific and concrete with named places and facts, varied rhythm, no lists, no emojis, no markdown, no stage directions. Never merely describe the picture: every line must carry a specific name, fact, story or reaction to an ATC call. Never repeat or rephrase your earlier lines. If the screen is only a loading screen, black or an unchanged menu, write SAY: SKIP';
    const recent = this.history.slice(-6);
    const mins = this.startedAt ? Math.round((Date.now() - this.startedAt) / 60000) : 0;
    const prevAge = this.prevFrameAt ? Math.round((Date.now() - this.prevFrameAt) / 1000) : 0;
    const user =
      'TRIP BRIEF: ' + (this.getTrip() || '(none given; work it out from the screen)') +
      '\nNOTEBOOK: ' + (this.getNotes() || '(empty, first transmission)') +
      '\nON AIR FOR: ' + mins + ' min' +
      (recent.length ? '\nYOUR RECENT LINES (do not repeat): ' + recent.map(h => '"' + h + '"').join(' | ') : '') +
      '\nSEGMENT FOR THIS TURN: ' + this.pickSegment() +
      (hasPrev ? '\nThe first image is about ' + prevAge + ' seconds ago, the second is NOW.' : '\nThe image is the screen NOW.');
    return {system, user};
  }

  private async generate(model: string, key: string, frame: string) {
    const hasPrev = !!this.prevFrame;
    const {system, user} = this.buildPrompt(hasPrev);
    const parts: any[] = [{text: user}];
    if (hasPrev) {
      parts.push({inline_data: {mime_type: 'image/jpeg', data: this.prevFrame}});
    }
    parts.push({inline_data: {mime_type: 'image/jpeg', data: frame}});
    const r = await this.timedFetch(
      API + '/models/' + model + ':generateContent',
      {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'x-goog-api-key': key},
        body: JSON.stringify({
          systemInstruction: {parts: [{text: system}]},
          contents: [{role: 'user', parts}],
          generationConfig: {temperature: 1.0, maxOutputTokens: 2048},
        }),
      },
      25000,
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
      return 'STATE:\nSAY: SKIP';
    }
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

  private clean(t: string) {
    return t
      .replace(/[*_#`~]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  private parse(out: string): {say: string; state: string} {
    const m = out.match(/STATE:\s*([\s\S]*?)\s*SAY:\s*([\s\S]*)$/i);
    if (m) {
      return {state: this.clean(m[1]), say: this.clean(m[2])};
    }
    return {state: '', say: this.clean(out.replace(/^SAY:\s*/i, ''))};
  }

  private async ask(frame: string): Promise<string> {
    const key = this.getApiKey();
    if (!key) {
      throw new Error('no Gemini API key set');
    }
    await this.refreshAvailable(key);
    let tried = 0;
    for (const model of this.candidates()) {
      tried++;
      try {
        const {say, state} = this.parse(await this.generate(model, key, frame));
        this.lastModel = model;
        this.lastError = '';
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
            throw new Error('API key rejected by Google');
          }
          this.setCooldown(model, e);
          this.lastError = model + ': ' + e.message;
        } else {
          this.cooldown[model] = Date.now() + 90 * 1000;
          this.lastError = model + ': ' + (e?.name === 'AbortError' ? 'timeout' : String(e?.message || e));
        }
        this.log('fallback from ' + model + ' -> ' + this.lastError);
      }
    }
    if (tried === 0) {
      throw new Error('all models capped, waiting for quota');
    }
    throw new Error('all models failed. last: ' + this.lastError);
  }

  statusText(): string {
    const now = Date.now();
    const capped = Object.keys(this.cooldown).filter(m => this.cooldown[m] > now);
    return (
      (this.on ? 'ON' : 'OFF') +
      ' | brain: ' + (this.lastModel || 'none yet') +
      ' | voice: ' + (this.getSpeaker() === 'Phone voice' ? 'phone' : this.lastVoice || 'none yet') +
      (capped.length ? ' | capped: ' + capped.join(', ') : '') +
      (this.lastError ? ' | last error: ' + this.lastError.slice(0, 140) : '')
    );
  }

  // ---------- UI helpers (the app's native dialogs) ----------
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

  async promptForTrip(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Trip brief',
      message: 'Who/what/where: aircraft, route, legs, stops, goals. The radio uses this every time.',
      hint: 'e.g. Bonanza G36 world tour, FALA loop, leg 3: FALA to FACT',
      text: this.getTrip(),
      maxLength: 500,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      this.setTrip(r.text || '');
      toast('Trip brief saved');
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
      const spk = this.getSpeaker();
      let items: any[] = [];
      if (screen === 'main') {
        const pname = (PERSONAS.find(p => p.id === pid) || PERSONAS[0]).name;
        items = [
          {id: 'radio:toggle', title: this.on ? 'Stop radio' : 'Start radio', active: this.on},
          {id: 'radio:now', title: 'Talk now'},
          {id: 'radio:voice', title: 'Character: ' + pname},
          {id: 'radio:speaker', title: 'Voice: ' + spk},
          {id: 'radio:trip', title: this.getTrip() ? 'Trip brief: set' : 'Trip brief: not set'},
          {id: 'radio:more', title: 'More settings'},
        ];
      } else if (screen === 'voice') {
        items = PERSONAS.map(p => ({id: 'radio:persona:' + p.id, title: p.name, active: p.id === pid}));
        items.push({id: 'radio:back', title: 'Back'});
      } else if (screen === 'speaker') {
        items = SPEAKERS.map(s => ({id: 'radio:spk:' + s.id, title: s.name, active: s.id === spk}));
        items.push({id: 'radio:back', title: 'Back'});
      } else if (screen === 'interval') {
        items = INTERVALS.map(s => ({id: 'radio:interval:' + s, title: 'Every ' + s + ' seconds', active: s === iv}));
        items.push({id: 'radio:back', title: 'Back'});
      } else {
        items = [
          {id: 'radio:interval', title: 'Talk every ' + iv + 's'},
          {id: 'radio:key', title: this.getApiKey() ? 'API key: set' : 'API key: NOT SET'},
          {id: 'radio:captions', title: 'Captions', active: this.getCaptions()},
          {id: 'radio:forget', title: 'Forget trip notebook'},
          {id: 'radio:status', title: 'Status / last error'},
          {id: 'radio:back', title: 'Back'},
        ];
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
      } else if (id === 'radio:speaker') {
        screen = 'speaker';
      } else if (id === 'radio:interval') {
        screen = 'interval';
      } else if (id === 'radio:more') {
        screen = 'more';
      } else if (id === 'radio:back') {
        screen = 'main';
      } else if (id === 'radio:trip') {
        await this.promptForTrip(showInput);
      } else if (id === 'radio:key') {
        await this.promptForKey(showInput);
      } else if (id === 'radio:captions') {
        this.setCaptions(!this.getCaptions());
      } else if (id === 'radio:forget') {
        this.setNotes('');
        this.history = [];
        this.prevFrame = '';
        toast('Notebook cleared');
      } else if (id === 'radio:status') {
        toast(this.statusText(), true);
      } else if (id.startsWith('radio:persona:')) {
        this.setPersonaId(id.slice('radio:persona:'.length));
        this.history = [];
        screen = 'main';
      } else if (id.startsWith('radio:spk:')) {
        this.setSpeaker(id.slice('radio:spk:'.length));
        screen = 'main';
      } else if (id.startsWith('radio:interval:')) {
        this.setInterval(parseInt(id.slice('radio:interval:'.length), 10) || 15);
        screen = 'more';
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
      case 'toggleStreamMute': {
        if (audioGain === 0) {
          handleAudioGainChange(muteRestoreGainRef.current || 1);
        } else {
          muteRestoreGainRef.current = audioGain;
          handleAudioGainChange(0);
        }
        break;
      }
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
      });
      items.push({
        id: 'toggleStreamMute',
        title: audioGain === 0 ? '🔊 Unmute stream sound' : '🔇 Mute stream sound',
        active: audioGain === 0,
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
        anchor + "\n  // RADIO: stop the radio when leaving the stream screen\n  const muteRestoreGainRef = React.useRef(1);\n  React.useEffect(() => {\n    return () => {\n      radio.stop();\n    };\n  }, []);\n",
    )

    # 3. menu items (after the Take Screenshot item)
    pat = re.compile(r"(      items\.push\(\{\s*id: 'takeScreenshot',\s*title: t\('Take Screenshot'\),\s*\}\);)")
    ms = list(pat.finditer(text))
    if len(ms) != 1:
        die("Expected exactly one 'takeScreenshot' menu item, found %d." % len(ms), p, text, kw)
    text = text[: ms[0].end()] + ITEMS + text[ms[0].end():]

    # 3b. add handleAudioGainChange to the menu callback's dependency list
    dep = "    audioGain,\n    connectState,\n    handleCloseModal,\n"
    if text.count(dep) != 1:
        die("Could not find the menu callback dependency list.", p, text, ("audioGain", "connectState"))
    text = text.replace(dep, "    audioGain,\n    handleAudioGainChange,\n    connectState,\n    handleCloseModal,\n")

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