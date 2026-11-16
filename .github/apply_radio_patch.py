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

// Vision/brain models, best -> worst (free-tier ones only; Argon/Carbon are paid). Unavailable / capped / timing out => next one.
export const MODEL_CHAIN = [
  'gemini-4-hydrogen',
  'gemini-3.5-flash-lite',
  'gemini-flash-latest',
  'gemini-flash-lite-latest',
  'gemini-3.1-flash-lite',
  'gemini-2.5-flash',
  'gemini-2.5-flash-lite',
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
const K_GAP_MIN = 'radio_gap_min';
const K_GAP_MAX = 'radio_gap_max';
const K_CAPTIONS = 'radio_captions';
const K_SPEAKER = 'radio_speaker';
const K_TRIP = 'radio_trip';
const K_NOTES = 'radio_notebook';
const K_NERD = 'radio_nerd';
const K_AIRCRAFT = 'radio_aircraft';

export const PERSONAS: Array<{id: string; name: string; prompt: string; style: string}> = [
  {
    id: 'bush',
    name: 'Bush Radio host',
    style:
      'Speak like a warm, slightly gravelly, relaxed late-night radio host with dry humour, natural pacing and small pauses',
    prompt:
      'You are the host of "Bush Radio", a late-night station for a pilot flying around the world. You are warm, dry-witted, curious and a little cheeky, and you love local stories, geography, wildlife and aviation history. You are talking to ONE listener, the pilot, like an old friend.',
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

const SEGMENTS: Array<{t: string; nerd: boolean}> = [
  {t: 'name the exact landmark, town, river, mountain or airfield below or ahead and give ONE surprising fact about it', nerd: false},
  {t: 'tell a short true piece of local history or a human story tied to this area', nerd: false},
  {t: 'colour about the wildlife, terrain, climate or weather typical of this exact region and altitude', nerd: false},
  {t: 'react to the latest ATC subtitle or what the pilot is doing right now, with personality', nerd: false},
  {t: 'trip progress: where we came from, where we are heading, what comes next on the route', nerd: false},
  {t: 'a quick funny observation or bit of banter based on something visible on screen', nerd: false},
  {t: 'tell the listener what to look out for in the next few minutes of flight', nerd: false},
  {t: 'a short legend or story connected to a place we have just passed', nerd: false},
  {t: 'recommend ONE real song (title and artist, never quote lyrics) that suits this place, this time of day or this mood of flying, and say why in a sentence or two', nerd: false},
  {t: 'a nerdy aside about how THIS aircraft works or flies (aerodynamics, lift, engine, instruments, handling quirks of its actual type) explained so it is genuinely fun', nerd: true},
  {t: 'a nerdy geography, geology, map or place-name fact about this region (why it looks like this, how it formed, why it is called that)', nerd: true},
  {t: 'a bit of aviation, space or engineering history that connects to somewhere near this route', nerd: true},
  {t: 'a fun "did you know" or a tiny trivia question to the pilot that you then answer yourself after a beat', nerd: true},
  {t: 'chat the way real radio hosts do: a light opinion, a "what would you do" question to the pilot, or a thought about flying at this time of day', nerd: false},
  {t: 'a nerdy tangent from physics, astronomy, language or technology that this view reminds you of', nerd: true},
];

const NERD_LEVELS: Array<{id: number; name: string; weight: number; directive: string}> = [
  {id: 1, name: '1 - Casual (stories, banter, no science)', weight: 0,
    directive: 'Keep it light and plain: stories, places, people, banter and music. No technical explanations or jargon at all.'},
  {id: 2, name: '2 - A little nerdy', weight: 0.35,
    directive: 'Mostly everyday talk. Now and then one simple, friendly science or tech fact, explained in a sentence.'},
  {id: 3, name: '3 - Nerdy (default)', weight: 1,
    directive: 'Nerdy but friendly: enjoy explaining how things work, with one clear, surprising fact at a time and a short "here is why".'},
  {id: 4, name: '4 - Properly nerdy', weight: 2,
    directive: 'Properly nerdy: go a layer deeper than most people would. Name the mechanism or effect, give real numbers, and add the history of the idea, always explained clearly so a curious person follows it.'},
  {id: 5, name: '5 - Full professor', weight: 3.5,
    directive: 'Full nerd: expert-level tangents, precise terminology (defined in passing), real figures, and surprising connections between fields. The listener loves rabbit holes. Still talk like a person on the radio, never like a lecture.'},
];

const GAP_MINS = [2, 4, 8, 15, 30];
const GAP_MAXS = [15, 30, 60, 120, 240];

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
  private run = 0;
  private latencyEma = 9000;
  private thinkMode: Record<string, number> = {};
  private pauseRatio = 0.4;

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
  getGapMin(): number {
    return storage.getNumber(K_GAP_MIN) || 4;
  }
  getGapMax(): number {
    return Math.max(storage.getNumber(K_GAP_MAX) || 40, this.getGapMin());
  }
  setGapMin(s: number) {
    storage.set(K_GAP_MIN, s);
  }
  setGapMax(s: number) {
    storage.set(K_GAP_MAX, s);
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
  getNerd(): number {
    const v = storage.getNumber(K_NERD);
    return v && v >= 1 && v <= 5 ? v : 3;
  }
  setNerd(n: number) {
    storage.set(K_NERD, n);
  }
  getAircraft(): string {
    return storage.getString(K_AIRCRAFT) || '';
  }
  setAircraft(s: string) {
    storage.set(K_AIRCRAFT, (s || '').trim());
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
    const id = ++this.run;
    this.loop(id);
  }

  stop() {
    this.on = false;
    this.run++;
    try {
      RadioModule?.stopSpeaking?.();
    } catch (e) {}
  }

  async talkNow() {
    try {
      RadioModule?.stopSpeaking?.();
    } catch (e) {}
    const id = ++this.run;
    if (this.on) {
      this.loop(id);
      return;
    }
    const p = await this.produce(id);
    if (p) {
      await this.play(p, id);
    }
  }

  private sleep(ms: number) {
    return new Promise<void>(res => setTimeout(res, Math.max(0, ms)));
  }

  private log(m: string) {
    try {
      RadioModule?.log?.(m);
    } catch (e) {}
  }

  // The next line is looked at, written and voiced WHILE the current one is still playing, timed so
  // it is ready the moment the pause after the current line ends. A fresh screenshot is taken
  // then, so a long line simply delays the next screenshot (dynamic timing).
  private async loop(id: number) {
    let next: Promise<any> = this.produce(id);
    while (this.on && this.run === id) {
      const prepared = await next;
      if (!this.on || this.run !== id) {
        return;
      }
      if (!prepared) {
        await this.sleep(Math.min(15000, Math.max(3000, this.getGapMin() * 1000)));
        next = this.produce(id);
        continue;
      }
      const gap = prepared.pause;
      const lead = Math.min(30000, Math.max(5000, this.latencyEma + 2000));
      const startNextIn = Math.max(0, prepared.ms + gap - lead);
      next = this.sleep(startNextIn).then(() =>
        this.on && this.run === id ? this.produce(id) : null,
      );
      await this.play(prepared, id);
      if (!this.on || this.run !== id) {
        return;
      }
      await this.sleep(gap);
    }
  }

  private async produce(id: number): Promise<any> {
    const t0 = Date.now();
    try {
      const frame: string = await RadioModule.captureFrame(1024, 75);
      const text = await this.ask(frame);
      this.prevFrame = frame;
      this.prevFrameAt = Date.now();
      if (!text) {
        this.log('model=' + this.lastModel + ' said=(skip)');
        return null;
      }
      if (this.run !== id) {
        return null;
      }
      this.history.push(text);
      if (this.history.length > 8) {
        this.history.shift();
      }
      let audio: any = null;
      if (this.getSpeaker() !== 'Phone voice') {
        audio = await this.fetchGeminiAudio(text);
      }
      const words = text.split(/\s+/).length;
      const ms = audio ? audio.ms : Math.round((words / 2.6) * 1000);
      // dynamic pause: the model suggests short/medium/long, nudged by how long the line was, plus jitter
      const pmin = this.getGapMin() * 1000;
      const pmax = Math.max(pmin, this.getGapMax() * 1000);
      let ratio = this.pauseRatio + (ms > 40000 ? 0.15 : ms < 8000 ? -0.1 : 0) + (Math.random() - 0.5) * 0.2;
      ratio = Math.min(1, Math.max(0, ratio));
      const pause = Math.round(pmin + (pmax - pmin) * ratio);
      const lat = Date.now() - t0;
      this.latencyEma = Math.round(this.latencyEma * 0.6 + lat * 0.4);
      this.log(
        'model=' + this.lastModel + ' voice=' + (audio ? this.lastVoice : 'phone') +
          ' prep=' + lat + 'ms speech=' + ms + 'ms pause=' + pause + 'ms said=' + text,
      );
      return {text, audio, ms, pause};
    } catch (e: any) {
      this.noteError(e);
      return null;
    }
  }

  private async play(p: any, id: number) {
    if (this.run !== id) {
      return;
    }
    if (this.getCaptions()) {
      toast('📻 ' + p.text);
    }
    RadioModule?.click?.();
    if (p.audio) {
      const t0 = Date.now();
      let ok = false;
      try {
        ok = await RadioModule.playPcm(p.audio.data, p.audio.rate);
      } catch (e) {}
      // phone voice only if the Gemini audio failed to start at all (never over audio that played)
      if (ok || Date.now() - t0 > 1500 || this.run !== id) {
        return;
      }
    }
    await Promise.race([
      RadioModule?.speak?.(p.text, 1.0, 0.92),
      this.sleep(p.ms * 1.6 + 15000).then(() => {
        RadioModule?.stopSpeaking?.();
        return false;
      }),
    ]);
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
  private ttsCandidates(): string[] {
    const now = Date.now();
    let list = TTS_CHAIN.slice();
    if (this.available) {
      const all = this.available.filter(m => /tts/i.test(m) && !/argon|carbon/i.test(m));
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
    return list.filter(m => (this.cooldown[m] || 0) <= now);
  }

  private async fetchGeminiAudio(text: string): Promise<any> {
    const key = this.getApiKey();
    for (const model of this.ttsCandidates()) {
      try {
        const r = await this.timedFetch(
          API + '/models/' + model + ':generateContent',
          {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'x-goog-api-key': key},
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
          30000,
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
        const bytes = Math.floor((String(inl.data).length * 3) / 4);
        this.lastVoice = model;
        return {data: inl.data, rate, ms: Math.round((bytes / 2 / rate) * 1000)};
      } catch (e: any) {
        if (e instanceof ApiError) {
          this.setCooldown(model, e);
        } else {
          this.cooldown[model] = Date.now() + 3 * 60 * 1000;
        }
        this.log('voice fallback from ' + model + ': ' + String(e?.message || e));
      }
    }
    return null;
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
    const hydro = (this.available || []).filter(
      m => /hydrogen/i.test(m) && !/tts|image|live|audio|embed|robot/i.test(m),
    );
    const base = this.available ? MODEL_CHAIN.filter(m => this.available!.includes(m)) : MODEL_CHAIN;
    const merged = hydro.concat(base.filter(m => !hydro.includes(m)));
    const list = merged.length > 0 ? merged : MODEL_CHAIN;
    return list.filter(m => (this.cooldown[m] || 0) <= now);
  }

  private setCooldown(model: string, e: ApiError) {
    const b = e.body || '';
    let ms = 3 * 60 * 1000;
    if (e.status === 503 || e.status === 500 || e.status === 504) {
      ms = 5 * 60 * 1000;
    } else if (e.status === 429) {
      ms = /PerDay|per day|daily/i.test(b) ? 6 * 3600 * 1000 : 10 * 60 * 1000;
    } else if (e.status === 404 || e.status === 400) {
      ms = 6 * 3600 * 1000;
    } else if (e.status === 403) {
      ms = 30 * 60 * 1000;
    }
    this.cooldown[model] = Date.now() + ms;
  }

  private pickSegment(): string {
    const level = NERD_LEVELS.find(n => n.id === this.getNerd()) || NERD_LEVELS[2];
    const weights = SEGMENTS.map((s, i) => (i === this.lastSegment ? 0 : s.nerd ? level.weight : 1));
    const total = weights.reduce((x, y) => x + y, 0);
    let r = Math.random() * total;
    let pick = 0;
    for (let i = 0; i < weights.length; i++) {
      r -= weights[i];
      if (r <= 0) {
        pick = i;
        break;
      }
    }
    this.lastSegment = pick;
    return SEGMENTS[pick].t;
  }

  private buildPrompt(hasPrev: boolean): {system: string; user: string} {
    const persona = PERSONAS.find(p => p.id === this.getPersonaId()) || PERSONAS[0];
    const system =
      persona.prompt +
      '\n\nYou are both the brain and the voice of the show. Each turn you get the current screen from the game stream' +
      (hasPrev ? ' (plus an earlier screen so you can see movement)' : '') +
      ', the trip brief, your running notebook and your recent lines.' +
      '\nAIRCRAFT RULE: the aircraft can change from flight to flight. Never assume a type. Identify it from the AIRCRAFT and TRIP BRIEF lines and from anything visible (HUD, instrument panel, aircraft name or registration, ATC callsign). If the screen contradicts the brief, trust the screen and carry the correct type in your notebook. If you genuinely cannot tell, say "the aircraft" without naming a type. Keep any technical or handling talk true to the actual aircraft.' +
      '\nREAD ALL ON-SCREEN TEXT carefully: HUD and instrument readouts, map, place-name and UI banners, waypoint and airport identifiers, ATC subtitles and callsigns. From these, work out exactly where the aircraft is and what is below, ahead and nearby, then use your world knowledge to talk about the REAL place: its landmarks, rivers, towns, mountains, history, wildlife and culture. If you cannot justify a place from the screen or notebook, hedge once ("looks like...") instead of inventing.' +
      '\nReply in EXACTLY this format:' +
      '\nSTATE: <60 words max. Updated notebook: where we are (place names, airfield, region), the aircraft type if known, heading/altitude/phase of flight, landmarks passed, next expected landmark or waypoint, anything the pilot is doing, and any destination you have suggested. Keep useful facts from the old notebook.>' +
      '\nSAY: <the words to speak aloud>' +
      '\nPAUSE: <short | medium | long: how long to leave before you speak again. short = a quick follow-up thought or reaction, medium = normal, long = after a big story, or when the pilot is busy (takeoff, landing, heavy ATC traffic) or just let them enjoy the view>' +
      '\nBORING SCENERY RULE: if the view is empty or featureless (open desert, endless fields, open sea, thick cloud, nothing to point at), do NOT waffle about sand or emptiness. Pivot: recommend somewhere genuinely worth flying to from the current position (a famous landmark, scenic coastline, interesting airport, canyon, city skyline or unusual place), with the rough compass direction, distance and flying time and one reason it is great. Make it a real suggestion the pilot can act on. If the notebook shows you suggested a destination and the pilot now seems to be heading that way, notice it and get excited about it. Never suggest places you are not sure exist.' +
      '\nCONVERSATION RULE: you are a good radio host, not a tour-guide script. Mix place facts with natural talk: song recommendations (title and artist only, never lyrics), asides about science, engineering, aviation, geography or language that a curious person would love (as far as the NERD LEVEL allows), light opinions and questions to the pilot. The NERD LEVEL line each turn says how technical to get. Be correct: if unsure of a fact, leave it out.' +
      '\nSAY rules: length follows what you have to say: sometimes one punchy sentence (15 words), usually 40 to 90 words, and occasionally a proper story up to 150 words (about a minute spoken). Write for the ear like a real broadcaster: contractions, short sentences mixed with longer ones, dashes and ellipses for natural pauses, spoken numbers ("nine hundred feet"). Specific and concrete with named places and facts. No lists, no emojis, no markdown, no stage directions, never mention instructions or tone. Never merely describe the picture: every line must carry a specific name, fact, story or reaction to an ATC call. Never repeat or rephrase your earlier lines. If the screen is only a loading screen, black or an unchanged menu, write SAY: SKIP' +
      '\nTIMING: the listener hears your line roughly ' + Math.round(this.latencyEma / 1000 + (this.getGapMin() + this.getGapMax()) / 4 + 4) + ' seconds after this screenshot, so favour what is coming up ahead and what we have just passed over what is directly below this instant.';
    const recent = this.history.slice(-6);
    const mins = this.startedAt ? Math.round((Date.now() - this.startedAt) / 60000) : 0;
    const prevAge = this.prevFrameAt ? Math.round((Date.now() - this.prevFrameAt) / 1000) : 0;
    const user =
      'AIRCRAFT: ' + (this.getAircraft() || '(not set: work it out from the trip brief or the screen)') +
      '\nTRIP BRIEF: ' + (this.getTrip() || '(none given; work it out from the screen)') +
      '\nNERD LEVEL ' + this.getNerd() + ' of 5: ' + ((NERD_LEVELS.find(n => n.id === this.getNerd()) || NERD_LEVELS[2]).directive) +
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
    // keep "thinking" minimal for speed; fall back through the config styles different generations accept
    const modes: any[] = [{thinkingBudget: 0}, {thinkingLevel: 'low'}, null];
    for (let attempt = 0; attempt < 3; attempt++) {
      const mode = Math.min(this.thinkMode[model] || 0, 2);
      const cfg: any = {temperature: 1.0, maxOutputTokens: 2048};
      if (modes[mode]) {
        cfg.thinkingConfig = modes[mode];
      }
      const r = await this.timedFetch(
        API + '/models/' + model + ':generateContent',
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'x-goog-api-key': key},
          body: JSON.stringify({
            systemInstruction: {parts: [{text: system}]},
            contents: [{role: 'user', parts}],
            generationConfig: cfg,
          }),
        },
        16000,
      );
      const raw = await r.text();
      if (!r.ok) {
        if (r.status === 400 && /think/i.test(raw) && mode < 2) {
          this.thinkMode[model] = mode + 1;
          continue;
        }
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
    throw new ApiError(0, 'thinking config rejected');
  }

  private clean(t: string) {
    return t
      .replace(/[*_#`~]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  private parse(out: string): {say: string; state: string; pause: number} {
    const m = out.match(/STATE:\s*([\s\S]*?)\s*SAY:\s*([\s\S]*?)(?:\s*PAUSE:\s*(\w+))?\s*$/i);
    const pr = (w?: string) => {
      const k = String(w || '').toLowerCase();
      return k === 'short' ? 0.08 : k === 'long' ? 0.92 : 0.45;
    };
    if (m) {
      return {state: this.clean(m[1]), say: this.clean(m[2]), pause: pr(m[3])};
    }
    return {state: '', say: this.clean(out.replace(/^SAY:\s*/i, '')), pause: 0.45};
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
        const {say, state, pause} = this.parse(await this.generate(model, key, frame));
        this.pauseRatio = pause;
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
          this.cooldown[model] = Date.now() + 3 * 60 * 1000;
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
      ' | prep ' + Math.round(this.latencyEma / 1000) + 's | voice: ' + (this.getSpeaker() === 'Phone voice' ? 'phone' : this.lastVoice || 'none yet') +
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
      message: 'Route, legs, stops, goals, what you are up to today. The radio uses this every time. (The aircraft has its own setting.)',
      hint: 'e.g. world tour, leg 3 of 12, sightseeing around the coast',
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

  async promptForAircraft(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Aircraft',
      message: 'What you are flying right now. Leave empty to let the radio work it out from the screen.',
      hint: 'e.g. type, make, livery or registration',
      text: this.getAircraft(),
      maxLength: 80,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      this.setAircraft(r.text || '');
      toast(this.getAircraft() ? 'Aircraft saved' : 'Aircraft cleared (auto)');
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
      const gmin = this.getGapMin();
      const gmax = this.getGapMax();
      const spk = this.getSpeaker();
      let items: any[] = [];
      if (screen === 'main') {
        const pname = (PERSONAS.find(p => p.id === pid) || PERSONAS[0]).name;
        items = [
          {id: 'radio:toggle', title: this.on ? 'Stop radio' : 'Start radio', active: this.on},
          {id: 'radio:now', title: 'Talk now'},
          {id: 'radio:voice', title: 'Character: ' + pname},
          {id: 'radio:speaker', title: 'Voice: ' + spk},
          {id: 'radio:nerd', title: 'Nerd level: ' + this.getNerd() + ' of 5'},
          {id: 'radio:tripair', title: 'Trip and aircraft'},
          {id: 'radio:more', title: 'More settings'},
        ];
      } else if (screen === 'voice') {
        items = PERSONAS.map(p => ({id: 'radio:persona:' + p.id, title: p.name, active: p.id === pid}));
        items.push({id: 'radio:back', title: 'Back'});
      } else if (screen === 'nerd') {
        const nl = this.getNerd();
        items = NERD_LEVELS.map(n => ({id: 'radio:nerdlvl:' + n.id, title: n.name, active: n.id === nl}));
        items.push({id: 'radio:back', title: 'Back'});
      } else if (screen === 'tripair') {
        items = [
          {id: 'radio:trip', title: this.getTrip() ? 'Trip brief: set' : 'Trip brief: not set'},
          {id: 'radio:aircraft', title: this.getAircraft() ? 'Aircraft: ' + this.getAircraft().slice(0, 30) : 'Aircraft: auto-detect'},
          {id: 'radio:back', title: 'Back'},
        ];
      } else if (screen === 'speaker') {
        items = SPEAKERS.map(s => ({id: 'radio:spk:' + s.id, title: s.name, active: s.id === spk}));
        items.push({id: 'radio:back', title: 'Back'});
      } else if (screen === 'gapmin') {
        items = GAP_MINS.map(s => ({id: 'radio:gmin:' + s, title: 'Shortest pause: ' + s + ' seconds', active: s === gmin}));
        items.push({id: 'radio:more', title: 'Back'});
      } else if (screen === 'gapmax') {
        items = GAP_MAXS.map(s => ({id: 'radio:gmax:' + s, title: 'Longest pause: ' + s + ' seconds', active: s === gmax}));
        items.push({id: 'radio:more', title: 'Back'});
      } else {
        items = [
          {id: 'radio:gapmin', title: 'Shortest pause: ' + gmin + 's'},
          {id: 'radio:gapmax', title: 'Longest pause: ' + gmax + 's'},
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
      } else if (id === 'radio:gapmin') {
        screen = 'gapmin';
      } else if (id === 'radio:gapmax') {
        screen = 'gapmax';
      } else if (id === 'radio:more') {
        screen = 'more';
      } else if (id === 'radio:back') {
        screen = 'main';
      } else if (id === 'radio:nerd') {
        screen = 'nerd';
      } else if (id === 'radio:tripair') {
        screen = 'tripair';
      } else if (id === 'radio:aircraft') {
        await this.promptForAircraft(showInput);
      } else if (id.startsWith('radio:nerdlvl:')) {
        this.setNerd(parseInt(id.slice('radio:nerdlvl:'.length), 10) || 3);
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
      } else if (id.startsWith('radio:gmin:')) {
        this.setGapMin(parseInt(id.slice('radio:gmin:'.length), 10) || 4);
        screen = 'more';
      } else if (id.startsWith('radio:gmax:')) {
        this.setGapMax(parseInt(id.slice('radio:gmax:'.length), 10) || 40);
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