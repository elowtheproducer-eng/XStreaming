#!/usr/bin/env python3
"""
apply_brain_patch.py  -  XStreaming "Brain": permanent trip memory, backup, black OLED radio screen,
10-second screenshot batches and sharper frames for Sim Radio.

Run from the REPO ROOT, AFTER apply_radio_patch.py:
    python3 .github/apply_brain_patch.py

What it does
  1. writes src/utils/brain.ts
       - compact permanent memory of every trip and place (stored small, rendered to the model in
         full every turn, with per-place detail the model can ask for or that is pulled in automatically
         when you are somewhere you have been before)
       - backup / restore / share, and the black OLED "radio screen"
  2. writes android/app/src/main/java/com/xstreaming/brain/BrainModule.java + BrainPackage.java
       - backup file in Downloads/XStreamingBackup (survives an app wipe or uninstall), restore picker,
         share sheet, and the black always-on radio-symbol overlay (hold a finger 1.5 s to go back)
  3. registers BrainPackage in MainApplication.java
  4. patches src/utils/radio.ts
       - main frame 1600 px / quality 85 (was 1024 / 75), model timeout 16 s -> 25 s
       - a small screenshot every 10 s, sent as one batch with the next prompt
       - the model now also reports PLACES / LOG / RECALL, which feed the brain
       - new menu entries: "Brain, logbook and backup" and "Black radio screen (OLED)"
  5. writes docs/brain-further-plans.md

Safe to re-run (BRAIN marker). If an anchor is missing it STOPS and prints context: paste that log back.
"""
import pathlib
import re
import sys

JAVA_DIR = "android/app/src/main/java/com/xstreaming/brain"


def die(msg, path=None, text=None, keywords=()):
    print("\n==================== BRAIN PATCH FAILED ====================")
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
BRAIN_MODULE = r'''package com.xstreaming.brain;

// BRAIN: backup / restore of the trip brain (Downloads, survives uninstall) + black OLED radio screen

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;

import androidx.annotation.NonNull;

import com.facebook.react.bridge.ActivityEventListener;
import com.facebook.react.bridge.BaseActivityEventListener;
import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

@SuppressLint("NewApi")
public class BrainModule extends ReactContextBaseJavaModule {
    private static final String DIR = "XStreamingBackup";
    private static final int REQ_PICK = 7311;
    private static final int MAX_BYTES = 20 * 1024 * 1024;

    private Promise pickPromise;
    private BlackoutView overlay;
    private boolean dimmed = false;
    private float savedBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE;

    private final ActivityEventListener listener = new BaseActivityEventListener() {
        @Override
        public void onActivityResult(Activity activity, int requestCode, int resultCode, Intent data) {
            if (requestCode != REQ_PICK) return;
            Promise p = pickPromise;
            pickPromise = null;
            if (p == null) return;
            if (resultCode != Activity.RESULT_OK || data == null || data.getData() == null) {
                p.reject("CANCELLED", "cancelled");
                return;
            }
            try (InputStream in = getReactApplicationContext().getContentResolver().openInputStream(data.getData())) {
                p.resolve(readAll(in));
            } catch (Throwable t) {
                p.reject("READ_FAILED", String.valueOf(t.getMessage()));
            }
        }
    };

    public BrainModule(ReactApplicationContext ctx) {
        super(ctx);
        ctx.addActivityEventListener(listener);
    }

    @NonNull
    @Override
    public String getName() {
        return "BrainModule";
    }

    @Override
    public void invalidate() {
        super.invalidate();
        try { getReactApplicationContext().removeActivityEventListener(listener); } catch (Throwable ignored) { }
    }

    // ---------------------------------------------------------------- helpers
    private static String readAll(InputStream in) throws IOException {
        if (in == null) throw new IOException("could not open file");
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) {
            bos.write(buf, 0, n);
            if (bos.size() > MAX_BYTES) throw new IOException("file too large");
        }
        return new String(bos.toByteArray(), StandardCharsets.UTF_8);
    }

    private Uri findDownload(ContentResolver cr, String name) {
        Uri coll = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        String[] proj = {MediaStore.MediaColumns._ID};
        String sel = MediaStore.MediaColumns.DISPLAY_NAME + "=? AND " + MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ?";
        try (Cursor c = cr.query(coll, proj, sel, new String[]{name, Environment.DIRECTORY_DOWNLOADS + "/" + DIR + "%"}, null)) {
            if (c != null && c.moveToFirst()) {
                return ContentUris.withAppendedId(coll, c.getLong(0));
            }
        } catch (Throwable ignored) { }
        return null;
    }

    private Uri writeToDownloads(String name, String text) throws Exception {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            throw new Exception("Backups need Android 10 or newer");
        }
        ContentResolver cr = getReactApplicationContext().getContentResolver();
        byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
        Uri existing = findDownload(cr, name);
        if (existing != null) {
            try (OutputStream os = cr.openOutputStream(existing, "wt")) {
                if (os == null) throw new IOException("no stream");
                os.write(bytes);
                return existing;
            } catch (Exception ignored) {
                // file belongs to an older install: fall through and create a fresh copy
            }
        }
        ContentValues v = new ContentValues();
        v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
        v.put(MediaStore.MediaColumns.MIME_TYPE, "application/json");
        v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/" + DIR);
        Uri created = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
        if (created == null) throw new IOException("could not create the backup file");
        try (OutputStream os = cr.openOutputStream(created, "wt")) {
            if (os == null) throw new IOException("no stream");
            os.write(bytes);
        }
        return created;
    }

    // ---------------------------------------------------------------- backup / restore / share
    @ReactMethod
    public void writeBackup(final String json, final String name, final Promise promise) {
        new Thread(() -> {
            try {
                writeToDownloads(name, json);
                promise.resolve("Downloads/" + DIR + "/" + name);
            } catch (Throwable t) {
                promise.reject("WRITE_FAILED", String.valueOf(t.getMessage()), t);
            }
        }, "BrainBackup").start();
    }

    // silent attempt to read the latest backup (works when this install can still see the old file)
    @ReactMethod
    public void readLatestBackup(final String name, final Promise promise) {
        new Thread(() -> {
            try {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) { promise.resolve(null); return; }
                ContentResolver cr = getReactApplicationContext().getContentResolver();
                Uri uri = findDownload(cr, name);
                if (uri == null) { promise.resolve(null); return; }
                try (InputStream in = cr.openInputStream(uri)) {
                    promise.resolve(readAll(in));
                }
            } catch (Throwable t) {
                promise.resolve(null);
            }
        }, "BrainRead").start();
    }

    // file picker: always works, even after a reinstall
    @ReactMethod
    public void pickBackup(final Promise promise) {
        final Activity a = getCurrentActivity();
        if (a == null) { promise.reject("NO_ACTIVITY", "No activity"); return; }
        if (pickPromise != null) { promise.reject("BUSY", "Already picking a file"); return; }
        pickPromise = promise;
        try {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("*/*");
            a.startActivityForResult(i, REQ_PICK);
        } catch (Throwable t) {
            pickPromise = null;
            promise.reject("PICK_FAILED", String.valueOf(t.getMessage()));
        }
    }

    @ReactMethod
    public void shareBackup(final String json, final String name, final Promise promise) {
        new Thread(() -> {
            try {
                final Uri uri = writeToDownloads(name, json);
                final Activity a = getCurrentActivity();
                if (a == null) { promise.reject("NO_ACTIVITY", "No activity"); return; }
                a.runOnUiThread(() -> {
                    try {
                        Intent send = new Intent(Intent.ACTION_SEND);
                        send.setType("application/json");
                        send.putExtra(Intent.EXTRA_STREAM, uri);
                        send.putExtra(Intent.EXTRA_SUBJECT, "XStreaming brain backup");
                        send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        a.startActivity(Intent.createChooser(send, "Share backup"));
                        promise.resolve(true);
                    } catch (Throwable t) {
                        promise.reject("SHARE_FAILED", String.valueOf(t.getMessage()));
                    }
                });
            } catch (Throwable t) {
                promise.reject("WRITE_FAILED", String.valueOf(t.getMessage()), t);
            }
        }, "BrainShare").start();
    }

    // ---------------------------------------------------------------- black OLED radio screen
    @ReactMethod
    public void showBlackout(final boolean dim, final Promise promise) {
        final Activity a = getCurrentActivity();
        if (a == null) { promise.reject("NO_ACTIVITY", "No activity"); return; }
        a.runOnUiThread(() -> {
            try {
                if (overlay != null) { promise.resolve(true); return; }
                ViewGroup decor = (ViewGroup) a.getWindow().getDecorView();
                overlay = new BlackoutView(a, () -> removeOverlay(a));
                decor.addView(overlay, new ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                if (dim) {
                    WindowManager.LayoutParams lp = a.getWindow().getAttributes();
                    savedBrightness = lp.screenBrightness;
                    lp.screenBrightness = 0.01f;
                    a.getWindow().setAttributes(lp);
                    dimmed = true;
                }
                promise.resolve(true);
            } catch (Throwable t) {
                promise.reject("BLACKOUT_FAILED", String.valueOf(t.getMessage()), t);
            }
        });
    }

    // must run on the UI thread
    private void removeOverlay(Activity a) {
        try {
            if (overlay != null) {
                overlay.stop();
                ViewGroup p = (ViewGroup) overlay.getParent();
                if (p != null) p.removeView(overlay);
                overlay = null;
                if (dimmed) {
                    WindowManager.LayoutParams lp = a.getWindow().getAttributes();
                    lp.screenBrightness = savedBrightness;
                    a.getWindow().setAttributes(lp);
                    dimmed = false;
                }
            }
        } catch (Throwable ignored) { }
    }

    @ReactMethod
    public void hideBlackout() {
        final Activity a = getCurrentActivity();
        if (a == null) return;
        a.runOnUiThread(() -> removeOverlay(a));
    }

    // pure black (OLED pixels off) with a dim radio symbol that drifts a few pixels every 45 s
    private static class BlackoutView extends View {
        private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint hint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF rect = new RectF();
        private final Handler h = new Handler(Looper.getMainLooper());
        private Runnable exit;
        private float d;
        private int step = 0;
        private float sx = 0;
        private float sy = 0;
        private long hintUntil;
        private boolean stopped = false;

        private final Runnable redraw = new Runnable() {
            @Override public void run() { invalidate(); }
        };
        private final Runnable holdExit = new Runnable() {
            @Override public void run() { if (!stopped) exit.run(); }
        };
        private final Runnable shifter = new Runnable() {
            @Override public void run() {
                if (stopped) return;
                final int[][] pts = {{0, 0}, {16, 10}, {-16, 14}, {12, -16}, {-14, -10}};
                step++;
                int[] p = pts[step % pts.length];
                sx = p[0] * d;
                sy = p[1] * d;
                invalidate();
                h.postDelayed(this, 45000);
            }
        };

        BlackoutView(Context c, Runnable exit) {
            super(c);
            this.exit = exit;
            this.d = c.getResources().getDisplayMetrics().density;
            setBackgroundColor(Color.BLACK);
            setClickable(true);
            setFocusable(false);
            setKeepScreenOn(true);
            line.setStyle(Paint.Style.STROKE);
            line.setStrokeWidth(2.5f * d);
            line.setStrokeCap(Paint.Cap.ROUND);
            line.setColor(0xFF3A3A3A);
            dot.setStyle(Paint.Style.FILL);
            dot.setColor(0xFF3A3A3A);
            hint.setColor(0xFF303030);
            hint.setTextSize(14 * d);
            hint.setTextAlign(Paint.Align.CENTER);
            hintUntil = System.currentTimeMillis() + 6000;
            h.postDelayed(shifter, 45000);
            h.postDelayed(redraw, 6100);
        }

        void stop() {
            stopped = true;
            h.removeCallbacksAndMessages(null);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    hintUntil = System.currentTimeMillis() + 3000;
                    invalidate();
                    h.postDelayed(holdExit, 1500);
                    h.postDelayed(redraw, 3100);
                    break;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    h.removeCallbacks(holdExit);
                    break;
                default:
                    break;
            }
            return true;
        }

        @Override
        protected void onDraw(Canvas c) {
            c.drawColor(Color.BLACK);
            float u = d;
            float cx = getWidth() / 2f + sx;
            float cy = getHeight() / 2f + sy;
            // radio body
            rect.set(cx - 80 * u, cy - 45 * u, cx + 80 * u, cy + 50 * u);
            c.drawRoundRect(rect, 14 * u, 14 * u, line);
            // antenna and signal arcs
            float ax = cx + 92 * u;
            float ay = cy - 105 * u;
            c.drawLine(cx + 52 * u, cy - 45 * u, ax, ay, line);
            c.drawCircle(ax, ay, 3.5f * u, dot);
            rect.set(ax - 14 * u, ay - 14 * u, ax + 14 * u, ay + 14 * u);
            c.drawArc(rect, -80, 70, false, line);
            rect.set(ax - 26 * u, ay - 26 * u, ax + 26 * u, ay + 26 * u);
            c.drawArc(rect, -80, 70, false, line);
            // speaker
            c.drawCircle(cx - 38 * u, cy + 5 * u, 28 * u, line);
            c.drawCircle(cx - 38 * u, cy + 5 * u, 15 * u, line);
            c.drawCircle(cx - 38 * u, cy + 5 * u, 4 * u, dot);
            // frequency display and tuning dial
            rect.set(cx + 8 * u, cy - 33 * u, cx + 66 * u, cy - 15 * u);
            c.drawRoundRect(rect, 4 * u, 4 * u, line);
            c.drawCircle(cx + 37 * u, cy + 20 * u, 14 * u, line);
            c.drawLine(cx + 37 * u, cy + 20 * u, cx + 44 * u, cy + 12 * u, line);
            if (System.currentTimeMillis() < hintUntil) {
                c.drawText("hold to return", getWidth() / 2f, getHeight() - 48 * u, hint);
            }
        }
    }
}
'''

BRAIN_PACKAGE = r'''package com.xstreaming.brain;

import androidx.annotation.NonNull;

import com.facebook.react.ReactPackage;
import com.facebook.react.bridge.NativeModule;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.uimanager.ViewManager;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class BrainPackage implements ReactPackage {
    @NonNull
    @Override
    public List<NativeModule> createNativeModules(@NonNull ReactApplicationContext ctx) {
        List<NativeModule> m = new ArrayList<>();
        m.add(new BrainModule(ctx));
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
# TypeScript: the brain
# ------------------------------------------------------------------------------------------
BRAIN_TS = r'''// BRAIN: permanent trip memory, backup / restore and the black OLED radio screen.
//
// Storage is deliberately tiny: short keys, places referenced by key, one MMKV string for the core
// and one for the per-place detail ("dossiers"). Everything is kept forever, but what the model reads
// every turn is rendered to a fixed budget (about 6500 characters), so the whole brain is always read
// in one go. Per-place detail is pulled in only when the model asks for it (RECALL) or when you are at
// a place you have visited before.
import {NativeModules, ToastAndroid} from 'react-native';
import {storage} from '../store/mmkv';

const {BrainModule} = NativeModules;

const K_CORE = 'brain_core_v1';
const K_DOS = 'brain_dossier_v1';
const K_LAST_BACKUP = 'brain_last_backup';

const BACKUP_LATEST = 'xstreaming-brain-latest.json';
const TRIP_GAP_S = 4 * 3600; // longer than this between transmissions = a new trip
const AUTO_BACKUP_S = 600; // silent auto-backup at most every 10 minutes
const BUDGET_PLACES = 3600; // characters of PLACES shown to the model each turn
const BUDGET_TRIPS = 2200; // characters of TRIPS shown to the model each turn
const MAX_FACTS = 40; // detail lines kept per place
const MAX_ROUTE = 80; // places remembered per trip

// settings that travel with the backup (the API key deliberately does not)
const SETTING_STR = ['radio_persona', 'radio_speaker', 'radio_trip', 'radio_notebook', 'radio_aircraft'];
const SETTING_NUM = ['radio_gap_min', 'radio_gap_max', 'radio_nerd'];
const SETTING_BOOL = ['radio_captions'];

type Place = {
  k: string; // key (ICAO code in lower case, or the normalised name)
  n: string; // display name
  r: string; // country / region
  v: number; // number of trips it appeared in
  f: number; // first seen (epoch seconds)
  l: number; // start of the latest trip that included it
  o?: number; // start of the trip before that
  t: string; // short lasting facts
  x: Record<string, number>; // flown together with: place key -> times
  c?: string; // ICAO code
};
type Trip = {
  s: number; // start (epoch seconds), also the trip identity
  e: number; // last activity
  a: string; // aircraft
  b: string; // brief
  p: string[]; // route: place keys in order of first appearance
  m: string; // running summary
  z?: number; // 1 = closed
};
type Core = {v: number; places: Record<string, Place>; trips: Trip[]};
type Dossiers = Record<string, string[]>;
type Parsed = {places?: string; log?: string; recall?: string};

const toast = (msg: string, long = false) => {
  try {
    ToastAndroid.show(msg, long ? ToastAndroid.LONG : ToastAndroid.SHORT);
  } catch (e) {}
};

const now = () => Math.floor(Date.now() / 1000);
const iso = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);
const clip = (s: string, n: number) => {
  const x = String(s || '').trim();
  return x.length > n ? x.slice(0, n) : x;
};

const norm = (s: string) => {
  let x = String(s || '').toLowerCase();
  try {
    x = x.normalize('NFD').replace(/[̀-ͯ]/g, '');
  } catch (e) {}
  return x
    .replace(/\b(international|intl|airport|airfield|airstrip|aerodrome|municipal|regional|the)\b/g, ' ')
    .replace(/[^a-z0-9]+/g, '');
};

const addTag = (old: string, tag: string) => {
  const t = clip(tag, 60);
  if (!t) {
    return old;
  }
  if ((old || '').toLowerCase().indexOf(t.toLowerCase()) >= 0) {
    return old;
  }
  let s = old ? old + '; ' + t : t;
  while (s.length > 90 && s.indexOf('; ') > 0) {
    s = s.slice(s.indexOf('; ') + 2);
  }
  return clip(s, 90);
};

const addSummary = (old: string, log: string) => {
  if (!log || (old || '').toLowerCase().indexOf(log.toLowerCase()) >= 0) {
    return old;
  }
  let s = old ? old + '; ' + log : log;
  while (s.length > 240 && s.indexOf('; ') > 0) {
    s = s.slice(s.indexOf('; ') + 2);
  }
  return s.length > 240 ? s.slice(s.length - 240) : s;
};

const noneToEmpty = (s?: string) => {
  const x = String(s || '').trim();
  return /^none\b/i.test(x) ? '' : x;
};

const splitList = (s?: string) =>
  noneToEmpty(s)
    .split(/\s*;\s*|\n/)
    .map(x => x.trim())
    .filter(x => x && !/^none$/i.test(x));

const parsePlaces = (s?: string) => {
  const out: Array<{name: string; code: string; region: string; tag: string}> = [];
  for (const part of splitList(s)) {
    const bits = part.split('|').map(x => x.trim());
    let raw = bits[0] || '';
    let code = '';
    const m = raw.match(/\(([A-Z]{4})\)/);
    if (m) {
      code = m[1];
      raw = raw.replace(m[0], '').trim();
    }
    if (!raw && !code) {
      continue;
    }
    out.push({name: raw || code, code, region: bits[1] || '', tag: bits[2] || ''});
  }
  return out.slice(0, 4);
};

class Brain {
  private core: Core | null = null;
  private dos: Dossiers | null = null;
  private recall: string[] = [];
  private cache = '';
  private dirty = true;
  private lastBackupTry = 0;
  private lastError = '';
  private warned = false;
  private restoring = false;

  // ---------- storage ----------
  private get(): Core {
    if (!this.core) {
      let c: any = null;
      try {
        c = JSON.parse(storage.getString(K_CORE) || 'null');
      } catch (e) {}
      this.core = c && c.places && c.trips ? c : {v: 1, places: {}, trips: []};
    }
    return this.core as Core;
  }

  private getDos(): Dossiers {
    if (!this.dos) {
      let d: any = null;
      try {
        d = JSON.parse(storage.getString(K_DOS) || 'null');
      } catch (e) {}
      this.dos = d && typeof d === 'object' ? d : {};
    }
    return this.dos as Dossiers;
  }

  private save() {
    try {
      storage.set(K_CORE, JSON.stringify(this.get()));
      storage.set(K_DOS, JSON.stringify(this.getDos()));
    } catch (e) {}
    this.dirty = true;
  }

  private nameOf(k: string) {
    const p = this.get().places[k];
    return p ? p.n : k;
  }

  // ---------- trips ----------
  private current(aircraft: string, brief: string): Trip {
    const c = this.get();
    const t = now();
    let tr = c.trips[c.trips.length - 1];
    if (!tr || tr.z || t - tr.e > TRIP_GAP_S) {
      tr = {s: t, e: t, a: clip(aircraft, 40), b: clip(brief, 80), p: [], m: ''};
      c.trips.push(tr);
    } else {
      if (aircraft && !tr.a) {
        tr.a = clip(aircraft, 40);
      }
      if (brief && !tr.b) {
        tr.b = clip(brief, 80);
      }
    }
    return tr;
  }

  beginSession(aircraft: string, brief: string) {
    try {
      this.current(aircraft, brief);
      this.save();
      this.autoRestore();
    } catch (e) {}
  }

  endSession() {
    try {
      const c = this.get();
      const tr = c.trips[c.trips.length - 1];
      if (tr) {
        tr.e = now();
      }
      this.save();
      this.maybeBackup(true);
    } catch (e) {}
  }

  newTrip() {
    const c = this.get();
    const tr = c.trips[c.trips.length - 1];
    if (tr) {
      tr.z = 1;
    }
    this.save();
    this.maybeBackup(true);
  }

  // ---------- places ----------
  private find(name: string, code: string): Place | null {
    const c = this.get();
    const kc = code ? code.toLowerCase() : '';
    if (kc && c.places[kc]) {
      return c.places[kc];
    }
    const nn = norm(name);
    if (!nn && !kc) {
      return null;
    }
    let best: Place | null = null;
    for (const k in c.places) {
      const p = c.places[k];
      if (kc && p.c === kc) {
        return p;
      }
      const pn = norm(p.n);
      if (!pn || !nn) {
        continue;
      }
      if (pn === nn) {
        return p;
      }
      const a = pn.length < nn.length ? pn : nn;
      const b = pn.length < nn.length ? nn : pn;
      if (a.length >= 6 && b.indexOf(a) === 0 && !best) {
        best = p;
      }
    }
    return best;
  }

  private bump(p: Place, k: string) {
    p.x[k] = (p.x[k] || 0) + 1;
    const keys = Object.keys(p.x);
    if (keys.length > 8) {
      keys.sort((a, b) => p.x[a] - p.x[b]);
      delete p.x[keys[0]];
    }
  }

  private touch(it: {name: string; code: string; region: string; tag: string}, trip: Trip): Place | null {
    const c = this.get();
    let p = this.find(it.name, it.code);
    if (!p) {
      const k = it.code ? it.code.toLowerCase() : norm(it.name);
      if (!k) {
        return null;
      }
      p = {k, n: clip(it.name, 40), r: clip(it.region, 24), v: 0, f: now(), l: trip.s, t: '', x: {}};
      c.places[k] = p;
    }
    if (it.code && !p.c) {
      p.c = it.code.toLowerCase();
    }
    if (!p.r && it.region) {
      p.r = clip(it.region, 24);
    }
    if (it.tag) {
      p.t = addTag(p.t, it.tag);
    }
    if (trip.p.indexOf(p.k) < 0) {
      const prev = trip.p.slice(-3);
      trip.p.push(p.k);
      if (trip.p.length > MAX_ROUTE) {
        trip.p.shift();
      }
      if (p.v > 0) {
        p.o = p.l;
      }
      p.l = trip.s;
      p.v += 1;
      for (const q of prev) {
        const o = c.places[q];
        if (o && o !== p) {
          this.bump(p, o.k);
          this.bump(o, p.k);
        }
      }
    }
    return p;
  }

  private addFact(k: string, text: string) {
    const d = this.getDos();
    const arr = d[k] || (d[k] = []);
    const body = clip(text, 120);
    if (arr.some(x => x.slice(7).toLowerCase() === body.toLowerCase())) {
      return;
    }
    arr.push(iso(now()).slice(2).replace(/-/g, '') + ' ' + body);
    while (arr.length > MAX_FACTS) {
      arr.shift();
    }
  }

  // Called once per radio turn with what the model reported.
  ingest(p: Parsed, aircraft: string) {
    const trip = this.current(aircraft, '');
    const touched: Place[] = [];
    for (const it of parsePlaces(p && p.places)) {
      const pl = this.touch(it, trip);
      if (pl && touched.indexOf(pl) < 0) {
        touched.push(pl);
      }
    }
    const log = clip(noneToEmpty(p && p.log), 160);
    if (log) {
      trip.m = addSummary(trip.m, log);
      if (touched[0]) {
        this.addFact(touched[0].k, log);
      }
    }
    trip.e = now();
    // detail for next turn: what the model asked for + where we are now if we have been here before
    const keys: string[] = [];
    for (const name of splitList(p && p.recall)) {
      const f = this.find(name, '');
      if (f && keys.indexOf(f.k) < 0) {
        keys.push(f.k);
      }
    }
    for (const t of touched.slice(0, 2)) {
      if (t.v > 1 && keys.indexOf(t.k) < 0) {
        keys.push(t.k);
      }
    }
    this.recall = keys.slice(0, 3);
    this.save();
    this.maybeBackup(false);
  }

  // ---------- what the model reads ----------
  formatRules(): string {
    return (
      '\nMEMORY: the BRAIN block in each turn is your permanent memory of every past trip. Read all of it. When where we are now, the route, an airport, the aircraft or the situation matches something in it, say so naturally ("we have been here before, last time we..."), but only when BRAIN or RECALLED DETAIL really says so. Never invent past visits.' +
      '\nAfter the PAUSE line ALWAYS add three more lines in exactly this form:' +
      '\nPLACES: up to 4 real places we are at, near or approaching right now, nearest first, each written "Name (ICAO code if it is an airport)|Country or region|optional lasting tip of at most 10 words", separated by " ; ". Reuse the exact spelling from BRAIN for places it already lists. NONE if you cannot tell.' +
      '\nLOG: one genuinely new, lasting fact worth keeping in the logbook (a landing, a first visit, a notable event, a chosen destination, a milestone), 25 words max. NONE if nothing new.' +
      '\nRECALL: up to 2 place names from BRAIN whose detailed history you would like to see next turn (for example when this looks like somewhere we have been before). NONE if not needed.'
    );
  }

  private render(): string {
    const c = this.get();
    const keys = Object.keys(c.places);
    if (!keys.length && !c.trips.length) {
      return '';
    }
    const total = c.trips.length;
    const years: Record<string, number> = {};
    const tl: string[] = [];
    let used = 0;
    for (let i = total - 1; i >= 0; i--) {
      const t = c.trips[i];
      const age = total - 1 - i;
      const route = t.p.map(k => this.nameOf(k)).join('>');
      let line = '';
      if (age < 8) {
        line = '#' + (i + 1) + ' ' + iso(t.s) + ' ' + (t.a ? t.a + ' ' : '') + route + (t.m ? ' "' + t.m + '"' : '');
      } else if (age < 20) {
        line = '#' + (i + 1) + ' ' + iso(t.s) + ' ' + clip(route, 100);
      }
      if (!line || used + line.length > BUDGET_TRIPS) {
        const y = iso(t.s).slice(0, 4);
        years[y] = (years[y] || 0) + 1;
        continue;
      }
      used += line.length + 1;
      tl.push(line);
    }
    tl.reverse();
    const ranked = keys.map(k => c.places[k]).sort((a, b) => b.v - a.v || b.l - a.l);
    const pl: string[] = [];
    let pu = 0;
    let omitted = 0;
    for (const p of ranked) {
      const links = Object.keys(p.x)
        .sort((a, b) => p.x[b] - p.x[a])
        .slice(0, 3)
        .map(k => this.nameOf(k))
        .join(',');
      const line = p.n + '|' + p.r + '|' + p.v + '|' + p.t + (links ? '|~' + links : '');
      if (pu + line.length > BUDGET_PLACES) {
        omitted++;
        continue;
      }
      pu += line.length + 1;
      pl.push(line);
    }
    const older = Object.keys(years)
      .sort()
      .map(y => y + ': ' + years[y] + ' trips')
      .join(', ');
    return (
      '\nBRAIN (permanent memory of ALL past trips; read all of it every turn):' +
      '\nPLACES name|region|trips visited|lasting facts|~often flown with:\n' +
      pl.join('\n') +
      (omitted ? '\n(+' + omitted + ' minor places are stored; name one in RECALL to read it)' : '') +
      '\nTRIPS #number date aircraft route "summary", oldest first:\n' +
      tl.join('\n') +
      (older ? '\nOLDER TRIPS NOT LISTED: ' + older : '')
    );
  }

  private recallText(): string {
    if (!this.recall.length) {
      return '';
    }
    const c = this.get();
    const d = this.getDos();
    const parts: string[] = [];
    for (const k of this.recall) {
      const p = c.places[k];
      if (!p) {
        continue;
      }
      const facts = (d[k] || []).slice(-8).join(' / ');
      const links = Object.keys(p.x)
        .sort((a, b) => p.x[b] - p.x[a])
        .slice(0, 5)
        .map(x => this.nameOf(x))
        .join(', ');
      parts.push(
        p.n + ' (' + p.v + ' trips, first seen ' + iso(p.f) + (p.o ? ', previous visit ' + iso(p.o) : ', no earlier trip') + '): ' +
          (facts || 'no extra detail') + (links ? ' | flown with: ' + links : ''),
      );
    }
    return parts.length
      ? '\nRECALLED DETAIL (full history for places you asked about or that match where we are now):\n' + parts.join('\n')
      : '';
  }

  context(): string {
    if (this.dirty) {
      this.cache = this.render();
      this.dirty = false;
    }
    const base = this.cache || '\nBRAIN: empty. This is the first recorded trip; start building the memory with PLACES and LOG.';
    return base + this.recallText();
  }

  // ---------- logbook (menu) ----------
  stats() {
    const c = this.get();
    return {trips: c.trips.length, places: Object.keys(c.places).length};
  }

  logbookItems(): Array<{id: string; title: string}> {
    const c = this.get();
    const out: Array<{id: string; title: string}> = [];
    for (let i = c.trips.length - 1; i >= 0 && out.length < 30; i--) {
      const t = c.trips[i];
      const names = t.p.map(k => this.nameOf(k));
      const route =
        names.length > 2
          ? names[0] + ' > ' + names[names.length - 1] + ' (' + names.length + ' places)'
          : names.join(' > ') || 'no places yet';
      out.push({id: 'radio:b:t:' + (i + 1), title: '#' + (i + 1) + ' ' + iso(t.s) + ' ' + route});
    }
    if (!out.length) {
      out.push({id: 'radio:brain', title: 'Logbook is empty so far'});
    }
    return out;
  }

  tripText(n: number): string {
    const t = this.get().trips[n - 1];
    if (!t) {
      return 'Trip not found';
    }
    return (
      '#' + n + ' ' + iso(t.s) + (t.a ? ' ' + t.a : '') + ': ' +
      (t.p.map(k => this.nameOf(k)).join(' > ') || 'no places') + (t.m ? ' | ' + t.m : '')
    );
  }

  statusText(): string {
    const c = this.get();
    const kb = Math.round((JSON.stringify(c).length + JSON.stringify(this.getDos()).length) / 1024);
    const lb = storage.getNumber(K_LAST_BACKUP);
    return (
      'Brain: ' + c.trips.length + ' trips, ' + Object.keys(c.places).length + ' places, ' + kb + ' KB stored, ' +
      this.render().length + ' characters read by the model each turn | last backup: ' + (lb ? iso(lb) : 'never') +
      ' (Downloads/XStreamingBackup)' + (this.lastError ? ' | ' + this.lastError : '')
    );
  }

  // ---------- backup / restore ----------
  private exportJson(): string {
    const settings: any = {};
    for (const k of SETTING_STR) {
      const v = storage.getString(k);
      if (v !== undefined) {
        settings[k] = v;
      }
    }
    for (const k of SETTING_NUM) {
      const v = storage.getNumber(k);
      if (v !== undefined) {
        settings[k] = v;
      }
    }
    for (const k of SETTING_BOOL) {
      const v = storage.getBoolean(k);
      if (v !== undefined) {
        settings[k] = v;
      }
    }
    return JSON.stringify({app: 'xstreaming-brain', v: 1, ts: now(), core: this.get(), dos: this.getDos(), settings});
  }

  async backupNow(manual: boolean): Promise<string> {
    if (!BrainModule || !BrainModule.writeBackup) {
      return 'Backup is not available in this build';
    }
    try {
      const json = this.exportJson();
      const where = await BrainModule.writeBackup(json, BACKUP_LATEST);
      if (manual) {
        await BrainModule.writeBackup(json, 'xstreaming-brain-' + iso(now()) + '.json');
      }
      storage.set(K_LAST_BACKUP, now());
      this.lastError = '';
      return 'Backed up ' + Math.max(1, Math.round(json.length / 1024)) + ' KB to ' + where;
    } catch (e: any) {
      this.lastError = 'backup failed: ' + String((e && e.message) || e).slice(0, 80);
      return 'Backup failed: ' + String((e && e.message) || e);
    }
  }

  private maybeBackup(force: boolean) {
    const t = now();
    if (!force && t - this.lastBackupTry < AUTO_BACKUP_S) {
      return;
    }
    this.lastBackupTry = t;
    this.backupNow(false).then(m => {
      if (/failed/i.test(m)) {
        toast(m, true);
      }
    });
  }

  async share(): Promise<string> {
    if (!BrainModule || !BrainModule.shareBackup) {
      return 'Sharing is not available in this build';
    }
    try {
      await BrainModule.shareBackup(this.exportJson(), BACKUP_LATEST);
      return 'Pick where to send the backup';
    } catch (e: any) {
      return 'Share failed: ' + String((e && e.message) || e);
    }
  }

  async restore(): Promise<string> {
    if (!BrainModule || !BrainModule.pickBackup) {
      return 'Restore is not available in this build';
    }
    try {
      const txt: string = await BrainModule.pickBackup();
      return this.importJson(txt);
    } catch (e: any) {
      const m = String((e && (e.code || e.message)) || e);
      return /CANCEL/i.test(m) ? 'Restore cancelled' : 'Restore failed: ' + m;
    }
  }

  private mergeTags(a: string, b: string) {
    let out = a;
    for (const seg of (b || '').split('; ')) {
      out = addTag(out, seg);
    }
    return out;
  }

  private importJson(txt: string): string {
    let j: any = null;
    try {
      j = JSON.parse(txt);
    } catch (e) {}
    if (!j || j.app !== 'xstreaming-brain' || !j.core || !j.core.places || !j.core.trips) {
      return 'That file is not an XStreaming brain backup';
    }
    const a = this.get();
    const b: Core = j.core;
    for (const k in b.places) {
      const q = b.places[k];
      const p = a.places[k];
      if (!p) {
        a.places[k] = q;
        continue;
      }
      p.v = Math.max(p.v, q.v);
      p.f = Math.min(p.f, q.f);
      p.l = Math.max(p.l, q.l);
      p.o = Math.max(p.o || 0, q.o || 0) || undefined;
      p.t = this.mergeTags(p.t, q.t);
      if (!p.r) {
        p.r = q.r;
      }
      if (!p.c && q.c) {
        p.c = q.c;
      }
      for (const x in q.x) {
        p.x[x] = Math.max(p.x[x] || 0, q.x[x]);
      }
    }
    const idx: Record<number, number> = {};
    a.trips.forEach((t, i) => {
      idx[t.s] = i;
    });
    for (const t of b.trips) {
      const i = idx[t.s];
      if (i === undefined) {
        a.trips.push(t);
      } else if (t.p.length > a.trips[i].p.length || t.m.length > a.trips[i].m.length) {
        a.trips[i] = t;
      }
    }
    a.trips.sort((x, y) => x.s - y.s);
    const d = this.getDos();
    const bd: Dossiers = j.dos || {};
    for (const k in bd) {
      const arr = d[k] || (d[k] = []);
      for (const line of bd[k]) {
        if (arr.indexOf(line) < 0) {
          arr.push(line);
        }
      }
      arr.sort();
      while (arr.length > MAX_FACTS) {
        arr.shift();
      }
    }
    // settings: only fill in what is not set yet, never overwrite your current choices
    const s = j.settings || {};
    for (const k of SETTING_STR) {
      if (typeof s[k] === 'string' && storage.getString(k) === undefined) {
        storage.set(k, s[k]);
      }
    }
    for (const k of SETTING_NUM) {
      if (typeof s[k] === 'number' && storage.getNumber(k) === undefined) {
        storage.set(k, s[k]);
      }
    }
    for (const k of SETTING_BOOL) {
      if (typeof s[k] === 'boolean' && storage.getBoolean(k) === undefined) {
        storage.set(k, s[k]);
      }
    }
    this.save();
    return 'Restored: ' + a.trips.length + ' trips, ' + Object.keys(a.places).length + ' places';
  }

  // empty brain on a fresh install: quietly try the last backup, otherwise point at the Restore button
  private async autoRestore() {
    const c = this.get();
    if (this.restoring || this.warned || Object.keys(c.places).length > 0 || c.trips.length > 1) {
      return;
    }
    this.restoring = true;
    try {
      const txt: any = BrainModule && BrainModule.readLatestBackup ? await BrainModule.readLatestBackup(BACKUP_LATEST) : null;
      if (txt) {
        toast(this.importJson(String(txt)) + ' (automatic)', true);
      } else {
        toast('Brain is empty. Had a backup? Sim Radio > Brain, logbook and backup > Restore.', true);
      }
    } catch (e) {
    } finally {
      this.restoring = false;
      this.warned = true;
    }
  }

  // ---------- black OLED radio screen ----------
  async showBlackout() {
    try {
      await BrainModule.showBlackout(true);
      toast('Black radio screen on. Hold a finger on the screen for 1.5 s to go back.', true);
    } catch (e: any) {
      toast('Could not show the black screen: ' + String((e && e.message) || e), true);
    }
  }

  hideBlackout() {
    try {
      if (BrainModule && BrainModule.hideBlackout) {
        BrainModule.hideBlackout();
      }
    } catch (e) {}
  }
}

const brain = new Brain();
export default brain;
'''

FURTHER_PLANS = r'''# Brain / radio: further plans

Things that were left out on purpose, or only partly done, with the reason.

## Done in the brain patch
- Permanent memory of every trip and place (src/utils/brain.ts). The model reads the whole compact brain every turn.
- Backup file in Downloads/XStreamingBackup (survives an app wipe or uninstall), restore picker, share sheet.
- Black OLED radio screen. The stream keeps running underneath it; hold a finger on the screen for 1.5 s to go back.
- A small screenshot every 10 s, sent as one batch with the next prompt.

## Not done (yet)
- **True screen-off radio.** Turning the display fully off would let Android throttle the app and the stream.
  The black screen keeps the stream alive instead. A foreground service with a wake lock could allow a real
  screen-off mode, but it needs a new notification channel and a manifest change.
- **Model-triggered lookups (function calling).** The model currently "opens the brain" through the RECALL line,
  which is answered on the next turn. Real Gemini function calling would answer in the same turn but costs one
  extra round trip per lookup.
- **Per-image resolution.** The 10 s screenshots are sent at 512 px and the main frame at 1600 px. Gemini 3 models
  accept a per-image resolution hint; it is not used because support differs between the free-tier models.
- **Pictures in the backup.** Left out as requested. The brain is text only (a few hundred KB after years of flying).
- **Cloud sync.** The share button sends the backup to Drive or email by hand. Automatic sync would need a sign-in.
- **API key in the backup.** Deliberately excluded because the file sits in Downloads where other apps can read it.
'''


# ------------------------------------------------------------------------------------------
# radio.ts edits
# ------------------------------------------------------------------------------------------
CONSTS = r"""
// BRAIN: picture sizes and the 10-second screenshot batch
const FRAME_W = 1600; // main frame width (was 1024). Output is capped by the stream's own resolution.
const FRAME_Q = 85; // JPEG quality of the main frame (was 75)
const BURST_W = 512; // width of the small 10-second screenshots
const BURST_Q = 60;
const BURST_EVERY_MS = 10000;
const BURST_KEEP = 36; // about 6 minutes of history
const BURST_SEND = 8; // at most this many small screenshots go with each prompt
const BURST_MAX_AGE_MS = 6 * 60 * 1000;"""

SEGMENT_ADD = r"""  {t: 'memory callback: if BRAIN or RECALLED DETAIL shows we have been to or near this place, flown this route or met this situation before, tell the listener what happened or what we learned last time; if nothing matches, do a normal segment instead', nerd: false},
  {t: 'connect two places from BRAIN: say how this place relates to somewhere else we have flown, for example the route between them, a shared history or what we did on the way', nerd: false},
"""

FIELDS = r"""  private pauseRatio = 0.4;
  // BRAIN: 10-second screenshot batch
  private burst: Array<{t: number; d: string}> = [];
  private activeBurst: Array<{t: number; d: string}> = [];
  private burstTimer: any = null;
  private burstBusy = false;
  private burstNote = '';
"""

BURST_METHODS = r"""  // BRAIN: a small screenshot every 10 s, sent as one batch with the next prompt
  private startBurst() {
    this.stopBurst();
    this.burst = [];
    this.burstTimer = setInterval(async () => {
      if (this.burstBusy || !this.on) {
        return;
      }
      this.burstBusy = true;
      try {
        const d: string = await RadioModule.captureFrame(BURST_W, BURST_Q);
        const last = this.burst[this.burst.length - 1];
        if (d && (!last || last.d !== d)) {
          this.burst.push({t: Date.now(), d});
        }
        while (this.burst.length > BURST_KEEP) {
          this.burst.shift();
        }
      } catch (e) {
      } finally {
        this.burstBusy = false;
      }
    }, BURST_EVERY_MS);
  }

  private stopBurst() {
    if (this.burstTimer) {
      clearInterval(this.burstTimer);
      this.burstTimer = null;
    }
    this.burst = [];
  }

  // everything captured since the last prompt, thinned to BURST_SEND frames spread over the whole gap
  private drainBurst(): Array<{t: number; d: string}> {
    const cutoff = Date.now() - BURST_MAX_AGE_MS;
    const all = this.burst.filter(b => b.t >= cutoff);
    this.burst = [];
    if (all.length <= BURST_SEND) {
      return all;
    }
    const out: Array<{t: number; d: string}> = [];
    for (let i = 0; i < BURST_SEND; i++) {
      out.push(all[Math.round((i * (all.length - 1)) / (BURST_SEND - 1))]);
    }
    return out;
  }

  private sleep(ms: number) {"""

GENERATE_OLD = r"""    const hasPrev = !!this.prevFrame;
    const {system, user} = this.buildPrompt(hasPrev);
    const parts: any[] = [{text: user}];
    if (hasPrev) {
      parts.push({inline_data: {mime_type: 'image/jpeg', data: this.prevFrame}});
    }
    parts.push({inline_data: {mime_type: 'image/jpeg', data: frame}});
"""

GENERATE_NEW = r"""    // BRAIN: the batch of small earlier screenshots, then the sharp one from right now
    const burst =
      this.activeBurst.length > 0
        ? this.activeBurst
        : this.prevFrame
        ? [{t: this.prevFrameAt, d: this.prevFrame}]
        : [];
    const hasPrev = burst.length > 0;
    const nowMs = Date.now();
    this.burstNote = hasPrev
      ? '\nThe first ' + burst.length + ' image(s) are smaller screenshots from earlier, oldest first, taken about ' +
        burst.map(b => Math.max(0, Math.round((nowMs - b.t) / 1000)) + 's').join(', ') +
        ' ago, so you can follow the movement and what changed. The LAST image is the sharp full-size screen NOW: read all text from it.'
      : '\nThe image is the screen NOW.';
    const {system, user} = this.buildPrompt(hasPrev);
    const parts: any[] = [{text: user}];
    for (const b of burst) {
      parts.push({inline_data: {mime_type: 'image/jpeg', data: b.d}});
    }
    parts.push({inline_data: {mime_type: 'image/jpeg', data: frame}});
"""

PARSE_START = "  private parse(out: string): {say: string; state: string; pause: number} {\n"
PARSE_END = "    return {state: '', say: this.clean(out.replace(/^SAY:\\s*/i, '')), pause: 0.45};\n  }\n"

PARSE_NEW = r"""  // BRAIN: label-based parser. Fields: STATE, SAY, PAUSE, PLACES, LOG, RECALL (the last three feed the brain)
  private parse(out: string): any {
    const re = /(?:^|\n)[ \t]*\**(STATE|SAY|PAUSE|PLACES|LOG|RECALL)\**[ \t]*:[ \t]*/gi;
    const marks: Array<{k: string; s: number; e: number}> = [];
    let m: RegExpExecArray | null = re.exec(out);
    while (m) {
      marks.push({k: m[1].toUpperCase(), s: m.index, e: re.lastIndex});
      m = re.exec(out);
    }
    const f: Record<string, string> = {};
    for (let i = 0; i < marks.length; i++) {
      const end = i + 1 < marks.length ? marks[i + 1].s : out.length;
      if (f[marks[i].k] === undefined) {
        f[marks[i].k] = out.slice(marks[i].e, end);
      }
    }
    const pr = (w?: string) => {
      const k = String(w || '').toLowerCase();
      return k.indexOf('short') === 0 ? 0.08 : k.indexOf('long') === 0 ? 0.92 : 0.45;
    };
    const keep = (s?: string) => String(s || '').replace(/[*`#]/g, '').trim();
    if (f.SAY === undefined) {
      return {state: '', say: this.clean(out), pause: 0.45, places: '', log: '', recall: ''};
    }
    return {
      state: this.clean(f.STATE || ''),
      say: this.clean(f.SAY),
      pause: pr(this.clean(f.PAUSE || '').split(' ')[0]),
      places: keep(f.PLACES),
      log: this.clean(f.LOG || ''),
      recall: keep(f.RECALL),
    };
  }
"""

MENU_MAIN = r"""          {id: 'radio:tripair', title: 'Trip and aircraft'},
          {id: 'radio:brain', title: 'Brain, logbook and backup'},
          {id: 'radio:oled', title: 'Black radio screen (OLED)'},
"""

MENU_SCREENS = r"""      } else if (screen === 'brain') {
        const st = brain.stats();
        items = [
          {id: 'radio:b:trips', title: 'Logbook: ' + st.trips + ' trips, ' + st.places + ' places (tap to read)'},
          {id: 'radio:b:newtrip', title: 'End this trip, next one starts fresh'},
          {id: 'radio:b:backup', title: 'Back up everything now'},
          {id: 'radio:b:share', title: 'Share backup (Drive, email...)'},
          {id: 'radio:b:restore', title: 'Restore from a backup file'},
          {id: 'radio:b:status', title: 'Brain size and last backup'},
          {id: 'radio:back', title: 'Back'},
        ];
      } else if (screen === 'logbook') {
        items = brain.logbookItems();
        items.push({id: 'radio:brain', title: 'Back'});
      } else if (screen === 'tripair') {
"""

MENU_HANDLERS = r"""      } else if (id === 'radio:brain') {
        screen = 'brain';
      } else if (id === 'radio:oled') {
        await brain.showBlackout();
        return;
      } else if (id.startsWith('radio:b:')) {
        const sub = id.slice('radio:b:'.length);
        if (sub === 'trips') {
          screen = 'logbook';
        } else if (sub.startsWith('t:')) {
          toast(brain.tripText(parseInt(sub.slice(2), 10) || 0), true);
        } else if (sub === 'newtrip') {
          brain.newTrip();
          toast('Trip closed. The next transmission starts a new trip.', true);
        } else if (sub === 'backup') {
          toast(await brain.backupNow(true), true);
        } else if (sub === 'share') {
          toast(await brain.share(), true);
        } else if (sub === 'restore') {
          toast(await brain.restore(), true);
        } else if (sub === 'status') {
          toast(brain.statusText(), true);
        }
      } else if (id.startsWith('radio:nerdlvl:')) {
"""


def once(text, find, repl, label):
    n = text.count(find)
    if n != 1:
        die("radio.ts edit '%s': expected exactly 1 match, found %d." % (label, n),
            "src/utils/radio.ts", text, (find.strip().split("\n")[0][:30],))
    return text.replace(find, repl, 1)


def patch_radio_ts():
    p = "src/utils/radio.ts"
    text, crlf = read(p)
    if "from './brain'" in text:
        print("radio.ts: already patched")
        return

    # 1. import
    text = once(text, "import {storage} from '../store/mmkv';\n",
                "import {storage} from '../store/mmkv';\nimport brain from './brain'; // BRAIN\n", "import")
    # 2. constants
    text = once(text, "const GAP_MAXS = [15, 30, 60, 120, 240];",
                "const GAP_MAXS = [15, 30, 60, 120, 240];" + CONSTS, "constants")
    # 3. extra talk segments that use the memory
    text = once(text, "const SEGMENTS: Array<{t: string; nerd: boolean}> = [\n",
                "const SEGMENTS: Array<{t: string; nerd: boolean}> = [\n" + SEGMENT_ADD, "segments")
    # 4. fields
    text = once(text, "  private pauseRatio = 0.4;\n", FIELDS, "fields")
    # 5. start / stop
    text = once(text, "    this.startedAt = Date.now();\n    this.prevFrame = '';\n",
                "    this.startedAt = Date.now();\n    this.prevFrame = '';\n"
                "    brain.beginSession(this.getAircraft(), this.getTrip()); // BRAIN\n"
                "    this.startBurst();\n", "start")
    text = once(text, "  stop() {\n    this.on = false;\n    this.run++;\n",
                "  stop() {\n    this.on = false;\n    this.run++;\n"
                "    this.stopBurst(); // BRAIN\n    brain.endSession();\n    brain.hideBlackout();\n", "stop")
    # 6. burst helpers (inserted before sleep())
    text = once(text, "  private sleep(ms: number) {", BURST_METHODS, "burst methods")
    # 7. sharper main frame + collect the batch
    text = once(text, "      const frame: string = await RadioModule.captureFrame(1024, 75);",
                "      this.activeBurst = this.drainBurst(); // BRAIN\n"
                "      const frame: string = await RadioModule.captureFrame(FRAME_W, FRAME_Q);", "main frame")
    # 8. prompt: wording, rules, brain block, image description
    text = once(text, "' (plus an earlier screen so you can see movement)'",
                "' (plus a batch of earlier screenshots so you can see movement)'", "prompt wording")
    text = once(text, "directly below this instant.';",
                "directly below this instant.' +\n      brain.formatRules();", "prompt rules")
    text = once(text, "      '\\nNOTEBOOK: ' + (this.getNotes() || '(empty, first transmission)') +",
                "      brain.context() +\n      '\\nNOTEBOOK: ' + (this.getNotes() || '(empty, first transmission)') +",
                "prompt brain block")
    text = once(text,
                "      (hasPrev ? '\\nThe first image is about ' + prevAge + ' seconds ago, the second is NOW.' : '\\nThe image is the screen NOW.');",
                "      (this.burstNote || '\\nThe image is the screen NOW.');", "prompt images")
    # 9. send the batch + a little more time for the bigger request
    text = once(text, GENERATE_OLD, GENERATE_NEW, "generate images")
    text = once(text, "        16000,\n", "        25000,\n", "model timeout")
    # 10. feed the brain from every reply
    text = once(text,
                "        const {say, state, pause} = this.parse(await this.generate(model, key, frame));\n",
                "        const parsed: any = this.parse(await this.generate(model, key, frame));\n"
                "        const {say, state, pause} = parsed;\n"
                "        try {\n          brain.ingest(parsed, this.getAircraft()); // BRAIN\n"
                "        } catch (be) {\n          this.log('brain: ' + String(be));\n        }\n", "ingest")
    # 11. new parser (replaces the old one)
    a = text.find(PARSE_START)
    b = text.find(PARSE_END)
    if a < 0 or b < 0 or text.count(PARSE_START) != 1 or text.count(PARSE_END) != 1 or b < a:
        die("Could not find the old parse() method to replace.", p, text, ("parse(", "SAY:"))
    text = text[:a] + PARSE_NEW + text[b + len(PARSE_END):]
    # 12. menu
    text = once(text, "          {id: 'radio:tripair', title: 'Trip and aircraft'},\n", MENU_MAIN, "menu main")
    text = once(text, "      } else if (screen === 'tripair') {\n", MENU_SCREENS, "menu screens")
    text = once(text, "      } else if (id.startsWith('radio:nerdlvl:')) {\n", MENU_HANDLERS, "menu handlers")

    write(p, text, crlf)
    print("radio.ts: burst, hi-res frames, brain feed and menu added")


def patch_main_application():
    p = "android/app/src/main/java/com/xstreaming/MainApplication.java"
    text, crlf = read(p)
    if "BrainPackage" in text:
        print("MainApplication.java: already patched")
        return
    m = re.search(r"\n([ \t]*)packages\.add\(new com\.xstreaming\.radio\.RadioPackage\(\)\);", text)
    if not m:
        die("Could not find the RadioPackage line (run apply_radio_patch.py first).", p, text,
            ("packages.add", "Package"))
    ins = "\n%s// BRAIN\n%spackages.add(new com.xstreaming.brain.BrainPackage());" % (m.group(1), m.group(1))
    text = text[: m.end()] + ins + text[m.end():]
    write(p, text, crlf)
    print("MainApplication.java: BrainPackage registered")


def main():
    if not pathlib.Path("package.json").exists():
        die("Run this from the repo root (package.json not found).")
    if not pathlib.Path("src/utils/radio.ts").exists():
        die("src/utils/radio.ts not found. Run apply_radio_patch.py first.")
    write(JAVA_DIR + "/BrainModule.java", BRAIN_MODULE)
    write(JAVA_DIR + "/BrainPackage.java", BRAIN_PACKAGE)
    print("wrote Java classes")
    write("src/utils/brain.ts", BRAIN_TS)
    print("wrote src/utils/brain.ts")
    write("docs/brain-further-plans.md", FURTHER_PLANS)
    print("wrote docs/brain-further-plans.md")
    patch_main_application()
    patch_radio_ts()
    print("\nBRAIN patch OK")


if __name__ == "__main__":
    main()
