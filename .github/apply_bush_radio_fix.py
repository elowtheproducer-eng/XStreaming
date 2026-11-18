#!/usr/bin/env python3
"""
apply_bush_radio_fix.py - Comprehensive fix & upgrade for Bush Radio / Sim Radio
in XStreaming + SQUAWK merged builds.

Run from the REPO ROOT AFTER apply_merge_patch.py:
    python3 .github/apply_bush_radio_fix.py

Fixes & Features:
  1. First-open bottom-right Bush Radio toggle visibility (RN + DecorView/Compose sync).
  2. Efficient 5-key distribution across all 5 API keys & live TTS models (voiceRotation.ts).
  3. Full-screen landscape stream underneath Bush Radio UI + Full Settings access from UI.
  4. Mood & cadence cues passed ONLY once at session start (systemInstruction), never spoken aloud.
  5. Typed "Ask / Talk" question input field inside Bush Radio UI (e.g. "any race tracks around?").
  6. Uninterrupted full playback of long responses (AudioTrack.MODE_STREAM + RIFF chunk parser + play queue).
  7. Complete removal of Android Device Default TTS (TextToSpeech) & 'Phone voice'.
  8. Complete removal & exclusion of gemini-4-hydrogen (/hydrogen/i).
  9. Dedicated Logs button with interactive viewer, Copy, Share, Refresh, and Clear.
"""
import json
import os
import pathlib
import re
import sys

MARK = "BUSH_RADIO_FIX_V1"

JAVA_RADIO_DIR = "android/app/src/main/java/com/xstreaming/radio"
MAIN_ACTIVITY_JAVA = "android/app/src/main/java/com/xstreaming/MainActivity.java"
WORKFLOW_MERGED = ".github/workflows/build-merged-apk.yml"

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

def log(msg):
    print("[bush_radio_fix] " + msg)


def die(msg):
    print("\n==================== BUSH RADIO FIX FAILED ====================")
    print(msg)
    print("================================================================")
    sys.exit(1)


def read_text(path):
    p = pathlib.Path(path)
    raw = p.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), ("\r\n" in raw)


def write_text(path, text, crlf=False):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))


# ------------------------------------------------------------------------------
# 1. Pure TypeScript Helpers (src/utils/radioHelpers.ts)
# ------------------------------------------------------------------------------
RADIO_HELPERS_TS = r"""// BUSH_RADIO_FIX_V1: Pure, testable helpers for 5-key distribution, model filtering,
// cue sanitization, question prompts, and WAV chunk inspection.

export const DEFAULT_SPEAKER = 'Charon';
export const MAX_KEY_SLOTS = 5;

// Free-tier proven vision/brain models (never includes gemini-4-hydrogen)
export const BRAIN_MODEL_CHAIN: string[] = [
  'gemini-flash-latest',
  'gemini-2.5-flash',
  'gemini-3.1-flash-lite',
  'gemini-flash-lite-latest',
  'gemini-2.5-flash-lite',
];

// Working Gemini TTS models (never includes gemini-4-hydrogen or dead 404 endpoints)
export const TTS_MODEL_CHAIN: string[] = [
  'gemini-2.5-flash-preview-tts',
  'gemini-3.1-flash-tts-preview',
];

export const DEAD_TTS_MODELS: RegExp = /3\.8-flash|argon|carbon|-pro-/i;

export function isExcludedModel(model: string): boolean {
  const m = String(model || '').trim();
  if (!m) {
    return true;
  }
  return /hydrogen|argon|carbon|embed|image|live|robot|aqa/i.test(m);
}

export function sanitizeSpeaker(speaker?: string | null): string {
  const s = String(speaker || '').trim();
  if (!s || /^phone\s*voice$/i.test(s) || /device\s*tts/i.test(s)) {
    return DEFAULT_SPEAKER;
  }
  return s;
}

export function filterBrainModels(
  available: string[] | null | undefined,
  fallback: string[] = BRAIN_MODEL_CHAIN,
): string[] {
  const cleanFallback = fallback.filter(
    m => !isExcludedModel(m) && !/tts/i.test(m),
  );
  if (!available || available.length === 0) {
    return cleanFallback;
  }
  const cleanAvailable = available.filter(
    m => !isExcludedModel(m) && !/tts/i.test(m),
  );
  const preferred = cleanFallback.filter(m => cleanAvailable.includes(m));
  if (preferred.length > 0) {
    return preferred;
  }
  const anyGeminiFlash = cleanAvailable.filter(m =>
    /gemini.*flash/i.test(m),
  );
  return anyGeminiFlash.length > 0 ? anyGeminiFlash : cleanFallback;
}

export function filterVoiceModels(
  available: string[] | null | undefined,
  fallback: string[] = TTS_MODEL_CHAIN,
): string[] {
  const cleanFallback = fallback.filter(
    m => /tts/i.test(m) && !isExcludedModel(m) && !DEAD_TTS_MODELS.test(m),
  );
  if (!available || available.length === 0) {
    return cleanFallback;
  }
  const cleanAvailable = available.filter(
    m => /tts/i.test(m) && !isExcludedModel(m) && !DEAD_TTS_MODELS.test(m),
  );
  if (cleanAvailable.length === 0) {
    return cleanFallback;
  }
  const rank = (m: string) => {
    const idx = cleanFallback.indexOf(m);
    return idx >= 0 ? idx : 50;
  };
  return cleanAvailable.slice().sort((a, b) => rank(a) - rank(b));
}

export interface KeyEntry {
  id: number;
  key: string;
}

export function collectKeyPool(
  slotKeys: KeyEntry[],
  spareKey = '',
  externalKeys: string[] = [],
): KeyEntry[] {
  const out: KeyEntry[] = [];
  const seen: Record<string, boolean> = {};

  for (const item of slotKeys) {
    const k = String(item?.key || '').trim();
    if (k && !seen[k]) {
      seen[k] = true;
      out.push({id: item.id, key: k});
    }
  }

  // Merge any external keys synced from native SharedPreferences into free slots or spare IDs
  let extraId = 6;
  for (const raw of externalKeys) {
    const k = String(raw || '').trim();
    if (k && !seen[k]) {
      seen[k] = true;
      out.push({id: extraId++, key: k});
    }
  }

  const sp = String(spareKey || '').trim();
  if (sp && !seen[sp]) {
    seen[sp] = true;
    out.push({id: 0, key: sp});
  }

  return out;
}

const CUE_KEYWORDS =
  /\b(?:warm(?:ly)?|gravelly|cadence|mood|tone|style|voice|whisper(?:ing)?|soft(?:ly)?|hushed|slow(?:ly)?|fast|energetic|deadpan|sarcastic|chuckle|sigh|laugh|gasp|pause|beat|smiling|relaxed|enthusiastic|reverent|radio host|speak like|delivery|pacing|unhurried|amused|bright(?:ly)?|excited|dramatic|calm(?:ly)?|steady|inflection|breathe?)\b/i;

export function stripMoodAndCadenceCues(text: string): string {
  let out = String(text || '');
  if (!out.trim()) {
    return '';
  }

  // Remove explicit labelled cue lines or prefixes like "Mood: ...", "Cadence: ...", "Delivery: ..."
  out = out.replace(
    /(?:^|\n)[ \t]*\**(?:mood|cadence|tone|voice\s*style|style\s*cue|delivery|stage\s*direction)\**\s*:\s*[^\n]*(?:\n|$)/gi,
    ' ',
  );

  // Remove leading "Speak like a ..." directive if accidentally echoed at start of SAY
  out = out.replace(
    /^\s*(?:\*{1,2}|\[|\()?\s*speak\s+like\s+[^.!?\n:]{6,140}(?:\*{1,2}|\]|\))?[:.\-–—]\s*/i,
    '',
  );

  // Remove asterisk stage directions: *chuckles*, *warm radio cadence*, *pauses*
  out = out.replace(/\*([^*\n]{1,90})\*/g, (full, inner) =>
    CUE_KEYWORDS.test(inner) || inner.split(/\s+/).length <= 4 ? ' ' : full,
  );

  // Remove bracketed stage/mood/cadence cues: [warmly], [slow cadence], [pause]
  out = out.replace(/\[([^\]\n]{1,100})\]/g, (full, inner) =>
    CUE_KEYWORDS.test(inner) || inner.split(/\s+/).length <= 6 ? ' ' : full,
  );

  // Remove parenthetical mood/cadence cues ONLY when they match style/delivery keywords
  out = out.replace(/\(([^)\n]{1,100})\)/g, (full, inner) =>
    CUE_KEYWORDS.test(inner) ? ' ' : full,
  );

  // Remove angle-bracket SSML-like or emotion tags: <warm>, <pause>
  out = out.replace(/<[^>\n]{1,40}>/g, ' ');

  return out
    .replace(/\s+([,.;!?])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function buildSessionStyleSystemBlock(
  personaPrompt: string,
  personaStyle: string,
  customMoodCadence = '',
): string {
  const custom = String(customMoodCadence || '').trim();
  const styleDesc = [String(personaStyle || '').trim(), custom]
    .filter(Boolean)
    .join('. ');

  return (
    String(personaPrompt || '').trim() +
    (styleDesc
      ? '\n\nSESSION DELIVERY, MOOD & CADENCE (established once for the whole session — apply internally in word choice and rhythm, and NEVER speak, quote, announce, wrap in brackets/parentheses, or echo any mood, tone, cadence, or stage direction): ' +
        styleDesc
      : '')
  );
}

export function buildQuestionUserPrompt(opts: {
  question: string;
  trip: string;
  aircraft: string;
  notes: string;
  brainContext?: string;
}): string {
  const q = String(opts.question || '').trim();
  return (
    'PILOT QUESTION (DIRECT REQUEST — ANSWER IMMEDIATELY AND COMPLETELY): "' +
    q +
    '"' +
    '\nAIRCRAFT: ' +
    (opts.aircraft || '(read from screen if visible)') +
    '\nTRIP BRIEF: ' +
    (opts.trip || '(none given)') +
    (opts.brainContext || '') +
    '\nNOTEBOOK: ' +
    (opts.notes || '(empty)') +
    '\nINSTRUCTIONS FOR ANSWERING THIS QUESTION:' +
    '\n- Answer the pilot directly based on the current full-resolution landscape screen AND real-world geography/places nearby.' +
    '\n- Ignore any generic "silence on questions" or topic-restriction rules for this turn so you give a helpful, specific, accurate spoken answer.' +
    '\n- Do NOT echo the mood/cadence instructions or stage directions.' +
    '\n- The image attached is the full-screen landscape view NOW.'
  );
}

export function findWavDataRange(bytes: Uint8Array): {
  offset: number;
  length: number;
  sampleRate: number;
} {
  if (!bytes || bytes.length < 12) {
    return {offset: 0, length: bytes ? bytes.length : 0, sampleRate: 24000};
  }
  const isRiff =
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46;
  const isWave =
    bytes[8] === 0x57 &&
    bytes[9] === 0x41 &&
    bytes[10] === 0x56 &&
    bytes[11] === 0x45;

  if (!isRiff || !isWave) {
    return {offset: 0, length: bytes.length, sampleRate: 24000};
  }

  let sampleRate = 24000;
  let pos = 12;
  while (pos + 8 <= bytes.length) {
    const id =
      String.fromCharCode(bytes[pos]) +
      String.fromCharCode(bytes[pos + 1]) +
      String.fromCharCode(bytes[pos + 2]) +
      String.fromCharCode(bytes[pos + 3]);
    const size =
      (bytes[pos + 4] |
        (bytes[pos + 5] << 8) |
        (bytes[pos + 6] << 16) |
        (bytes[pos + 7] << 24)) >>>
      0;

    if (id === 'fmt ' && pos + 8 + 16 <= bytes.length) {
      const sr =
        (bytes[pos + 12] |
          (bytes[pos + 13] << 8) |
          (bytes[pos + 14] << 16) |
          (bytes[pos + 15] << 24)) >>>
        0;
      if (sr >= 8000 && sr <= 192000) {
        sampleRate = sr;
      }
    } else if (id === 'data') {
      const dataOff = pos + 8;
      const avail = Math.max(0, bytes.length - dataOff);
      const len = size > 0 && size <= avail ? size : avail;
      return {offset: dataOff, length: len, sampleRate};
    }

    const padded = size + (size % 2);
    const next = pos + 8 + padded;
    if (next <= pos) {
      break;
    }
    pos = next;
  }

  const fallbackOffset = Math.min(44, bytes.length);
  return {
    offset: fallbackOffset,
    length: Math.max(0, bytes.length - fallbackOffset),
    sampleRate,
  };
}

export function estimateSpeechMsFromBase64(b64: string, sampleRate = 24000): number {
  const s = String(b64 || '').trim();
  if (!s) {
    return 0;
  }
  const pad = s.endsWith('==') ? 2 : s.endsWith('=') ? 1 : 0;
  const rawBytes = Math.max(0, Math.floor((s.length * 3) / 4) - pad);
  const pcmBytes = rawBytes > 44 ? rawBytes - 44 : rawBytes;
  const sr = sampleRate > 0 ? sampleRate : 24000;
  return Math.round((pcmBytes / 2 / sr) * 1000);
}
"""

# ------------------------------------------------------------------------------
# 2. 5-Key Distributed Voice Rotation (src/utils/voiceRotation.ts)
# ------------------------------------------------------------------------------
VOICE_ROTATION_TS = r"""// BUSH_RADIO_FIX_V1: True 5-key + multi-model TTS distributor (excludes gemini-4-hydrogen)
import {TTS_MODEL_CHAIN, isExcludedModel, DEAD_TTS_MODELS} from './radioHelpers';

export const VOICE_MODELS: string[] = TTS_MODEL_CHAIN.slice();

export const VOICE_ROUTE_GAP_MS = 12000;
export const MIN_WORDS = 40;
export const RETRY_WORDS = 45;

export interface VoiceKey {
  id: number;
  key: string;
}

export interface VoiceRoute {
  model: string;
  id: number;
  key: string;
  tag: string;
}

export interface RotationState {
  nextIndex: number;
  keyCursor: number;
  lastUsedAt: Record<string, number>;
  lastKeyUsedAt: Record<number, number>;
  totalSuccess: number;
}

function safeIndex(idx: number, len: number): number {
  if (len <= 0) return 0;
  const raw = Number.isFinite(idx) ? Math.trunc(idx) : 0;
  return ((raw % len) + len) % len;
}

export function newRotationState(): RotationState {
  return {
    nextIndex: 0,
    keyCursor: 0,
    lastUsedAt: {},
    lastKeyUsedAt: {},
    totalSuccess: 0,
  };
}

function usableModels(models?: string[]): string[] {
  const src = models && models.length > 0 ? models : VOICE_MODELS;
  const filtered = src.filter(
    m => /tts/i.test(m) && !isExcludedModel(m) && !DEAD_TTS_MODELS.test(m),
  );
  return filtered.length > 0 ? filtered : VOICE_MODELS.slice();
}

/**
 * Distributes TTS requests evenly across ALL available API keys (1..5 + spare)
 * and working non-hydrogen TTS models.
 *
 * Unlike the legacy model-major loop that repeatedly exhausted a single key/model pair,
 * this interleaves the key ring round-robin (advancing keyCursor after each call) so
 * consecutive spoken lines spread evenly across all 5 projects/keys.
 */
export function buildVoiceRoutes(
  keys: VoiceKey[],
  cooldown: Record<string, number>,
  state: RotationState,
  now: number,
  models?: string[],
  globalModelCooldown: Record<string, number> = {},
): VoiceRoute[] {
  const keyList = (keys || []).filter(k => k && String(k.key || '').trim().length > 0);
  if (keyList.length === 0) {
    return [];
  }

  const allModels = usableModels(models);
  const healthyModels = allModels.filter(m => (globalModelCooldown[m] || 0) <= now);
  const candidateModels = healthyModels.length > 0 ? healthyModels : allModels;

  const kLen = keyList.length;
  const kStart = safeIndex(state.keyCursor || 0, kLen);

  // Order keys starting at keyCursor, then by least-recently-used key timestamp
  const rotatedKeys = Array.from({length: kLen}, (_, i) => ({
    k: keyList[(kStart + i) % kLen],
    rotOrder: i,
    keyUsedAt: state.lastKeyUsedAt[keyList[(kStart + i) % kLen].id] || 0,
  })).sort((a, b) => {
    if (a.keyUsedAt !== b.keyUsedAt) {
      return a.keyUsedAt - b.keyUsedAt;
    }
    return a.rotOrder - b.rotOrder;
  });

  const mLen = candidateModels.length;
  const mStart = safeIndex(state.nextIndex || 0, mLen);
  const rotatedModels = Array.from(
    {length: mLen},
    (_, i) => candidateModels[(mStart + i) % mLen],
  );

  // Diagonal / balanced interleaving across all 5 keys and models:
  // Layer 0 uses primary key for this turn on model[mStart], then spreads remaining
  // keys across models BEFORE falling back to resting/benched pairs.
  const ready: VoiceRoute[] = [];
  const resting: VoiceRoute[] = [];
  const seenTag: Record<string, boolean> = {};

  for (let mOff = 0; mOff < rotatedModels.length; mOff++) {
    const model = rotatedModels[mOff];
    for (let kOff = 0; kOff < rotatedKeys.length; kOff++) {
      // Shift key index by mOff so fallback model picks a different key cleanly too
      const key = rotatedKeys[(kOff + mOff) % rotatedKeys.length].k;
      const tag = model + '@' + key.id;
      if (seenTag[tag]) continue;
      seenTag[tag] = true;
      if ((cooldown[tag] || 0) > now) {
        continue;
      }
      const route: VoiceRoute = {model, id: key.id, key: key.key, tag};
      const usedAt = Math.max(
        state.lastUsedAt[tag] || 0,
        state.lastKeyUsedAt[key.id] || 0,
      );
      if (usedAt > 0 && now - usedAt < VOICE_ROUTE_GAP_MS) {
        resting.push(route);
      } else {
        ready.push(route);
      }
    }
  }

  return ready.concat(resting);
}

export function markUsed(
  state: RotationState,
  tag: string,
  now: number,
  keyId?: number,
): void {
  state.lastUsedAt[tag] = now;
  if (typeof keyId === 'number' && Number.isFinite(keyId)) {
    state.lastKeyUsedAt[keyId] = now;
  } else {
    const at = tag.lastIndexOf('@');
    if (at >= 0) {
      const parsed = parseInt(tag.slice(at + 1), 10);
      if (Number.isFinite(parsed)) {
        state.lastKeyUsedAt[parsed] = now;
      }
    }
  }
}

export function afterSuccess(
  state: RotationState,
  model: string,
  keyId?: number,
  keyCount = 5,
): {used: string; next: string; nextKeyCursor: number} {
  state.totalSuccess = (state.totalSuccess || 0) + 1;
  const idx = VOICE_MODELS.indexOf(model);
  if (idx !== -1) {
    state.nextIndex = (idx + 1) % VOICE_MODELS.length;
  } else {
    state.nextIndex = ((state.nextIndex || 0) + 1) % VOICE_MODELS.length;
  }
  const denom = Math.max(1, keyCount);
  state.keyCursor = ((state.keyCursor || 0) + 1) % denom;
  if (typeof keyId === 'number' && Number.isFinite(keyId)) {
    state.lastKeyUsedAt[keyId] = Date.now();
  }
  const safeIdx = safeIndex(state.nextIndex, VOICE_MODELS.length);
  return {
    used: model,
    next: VOICE_MODELS[safeIdx],
    nextKeyCursor: state.keyCursor,
  };
}

export function rotationText(state: RotationState, activeKeys = 0): string {
  const safeIdx = safeIndex(state.nextIndex, VOICE_MODELS.length);
  return (
    'voice rotation: model=' +
    VOICE_MODELS[safeIdx] +
    ' keySlotCursor=' +
    ((state.keyCursor || 0) + 1) +
    (activeKeys > 0 ? '/' + activeKeys : '')
  );
}

export function wordCount(text: string): number {
  const trimmed = String(text || '').trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).filter(Boolean).length;
}

export function isTooShort(text: string): boolean {
  const count = wordCount(text);
  if (count === 0) return false;
  return count < MIN_WORDS;
}

export function shortRetryNote(words: number): string {
  return (
    '\nYOUR LAST DRAFT WAS TOO SHORT (' +
    words +
    ' words). Write at least ' +
    RETRY_WORDS +
    ' words.'
  );
}
"""

# ------------------------------------------------------------------------------
# 3. Native Java RadioModule.java (MODE_STREAM PCM, No Device TTS, Full Logs, Keys, Landscape)
# ------------------------------------------------------------------------------
RADIO_MODULE_JAVA = r"""package com.xstreaming.radio;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ActivityInfo;
import android.graphics.Bitmap;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Base64;
import android.view.PixelCopy;
import android.view.Surface;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;

import androidx.annotation.NonNull;

import com.facebook.react.bridge.Arguments;
import com.facebook.react.bridge.Promise;
import com.facebook.react.bridge.ReactApplicationContext;
import com.facebook.react.bridge.ReactContextBaseJavaModule;
import com.facebook.react.bridge.ReactMethod;
import com.facebook.react.bridge.WritableArray;
import com.facebook.react.modules.core.DeviceEventManagerModule;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileWriter;
import java.io.RandomAccessFile;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

/**
 * BUSH_RADIO_FIX_V1:
 *  - Device TextToSpeech completely removed (Gemini TTS PCM only).
 *  - AudioTrack.MODE_STREAM with RIFF 'data' chunk parser + tail silence padding so long responses NEVER cut off.
 *  - Persistent radiolog.txt with getLogs / clearLogs / shareLogs.
 *  - SharedPreferences scanner for cross-syncing 5 API keys from :atc/SQUAWK UI.
 *  - Landscape fullscreen + first-open stream overlay notification helpers.
 */
public class RadioModule extends ReactContextBaseJavaModule {
    public static final String ACTION_STREAM_STATE = "com.xstreaming.ACTION_STREAM_STATE";
    private static final String LOG_FILE = "radiolog.txt";
    private static final long MAX_LOG_BYTES = 500 * 1024;
    private static final int READ_LOG_CHARS = 120000;

    private final Object playLock = new Object();
    private final Object logLock = new Object();
    private final AtomicLong playSeq = new AtomicLong(0);
    private volatile AudioTrack currentTrack;
    private volatile boolean stopRequested = false;
    private volatile boolean streamActive = false;

    private File radioLogFile;
    private final SimpleDateFormat logFmt = new SimpleDateFormat("HH:mm:ss.SSS", Locale.US);

    public RadioModule(ReactApplicationContext ctx) {
        super(ctx);
        try {
            radioLogFile = new File(ctx.getFilesDir(), LOG_FILE);
            if (radioLogFile.exists() && radioLogFile.length() > MAX_LOG_BYTES) {
                radioLogFile.delete();
            }
            appendLog("I", "RadioModule", "initialized (DeviceTTS=disabled, AudioMode=STREAM)");
        } catch (Throwable ignored) {}
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
                int tw = Math.min(maxWidth > 0 ? maxWidth : 1280, w);
                int th = Math.max(1, Math.round(h * (tw / (float) w)));
                final Bitmap bmp = Bitmap.createBitmap(tw, th, Bitmap.Config.ARGB_8888);
                final HandlerThread ht = new HandlerThread("RadioPixelCopy");
                ht.start();
                Handler handler = new Handler(ht.getLooper());
                PixelCopy.request(sv, bmp, result -> {
                    try {
                        if (result == PixelCopy.SUCCESS) {
                            ByteArrayOutputStream bos = new ByteArrayOutputStream();
                            bmp.compress(Bitmap.CompressFormat.JPEG, quality > 0 ? quality : 75, bos);
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

    // ---------------------------------------------------------------- WAV / PCM streaming playback
    private static int readLeInt(byte[] b, int off) {
        return (b[off] & 0xFF)
                | ((b[off + 1] & 0xFF) << 8)
                | ((b[off + 2] & 0xFF) << 16)
                | ((b[off + 3] & 0xFF) << 24);
    }

    private static int[] parseWavData(byte[] raw, int defaultRate) {
        int rate = defaultRate > 0 ? defaultRate : 24000;
        if (raw.length >= 12
                && raw[0] == 'R' && raw[1] == 'I' && raw[2] == 'F' && raw[3] == 'F'
                && raw[8] == 'W' && raw[9] == 'A' && raw[10] == 'V' && raw[11] == 'E') {
            int pos = 12;
            while (pos + 8 <= raw.length) {
                int c0 = raw[pos] & 0xFF, c1 = raw[pos + 1] & 0xFF, c2 = raw[pos + 2] & 0xFF, c3 = raw[pos + 3] & 0xFF;
                long size = readLeInt(raw, pos + 4) & 0xFFFFFFFFL;
                if (c0 == 'f' && c1 == 'm' && c2 == 't' && c3 == ' ' && pos + 24 <= raw.length) {
                    int sr = readLeInt(raw, pos + 12);
                    if (sr >= 8000 && sr <= 192000) rate = sr;
                } else if (c0 == 'd' && c1 == 'a' && c2 == 't' && c3 == 'a') {
                    int off = pos + 8;
                    int avail = Math.max(0, raw.length - off);
                    int len = (size > 0 && size <= avail) ? (int) size : avail;
                    return new int[]{off, len, rate};
                }
                long next = pos + 8L + size + (size & 1L);
                if (next <= pos || next > raw.length) break;
                pos = (int) next;
            }
            int off = Math.min(44, raw.length);
            return new int[]{off, Math.max(0, raw.length - off), rate};
        }
        return new int[]{0, raw.length, rate};
    }

    /**
     * Plays raw 16-bit mono PCM (or WAV) via AudioTrack.MODE_STREAM.
     * Guaranteed not to truncate long clips and drains cleanly through the final frame.
     */
    @ReactMethod
    public void playPcm(final String b64, final int sampleRate, final Promise promise) {
        final long mySeq = playSeq.incrementAndGet();
        stopRequested = false;

        new Thread(() -> {
            synchronized (playLock) {
                AudioTrack track = null;
                AudioManager am = (AudioManager) getReactApplicationContext().getSystemService(Context.AUDIO_SERVICE);
                AudioFocusRequest focusReq = null;
                try {
                    if (stopRequested || playSeq.get() != mySeq) {
                        promise.resolve(false);
                        return;
                    }
                    byte[] decoded = Base64.decode(b64, Base64.DEFAULT);
                    int[] wav = parseWavData(decoded, sampleRate);
                    int off = wav[0];
                    int len = wav[1] & ~1; // even byte count for 16-bit PCM
                    int rate = wav[2];
                    if (len < 2) {
                        appendLog("W", "PCM", "skipped empty buffer");
                        promise.resolve(false);
                        return;
                    }

                    int minBuf = AudioTrack.getMinBufferSize(
                            rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    int bufBytes = Math.max(minBuf * 4, 32768);

                    AudioAttributes attrs = new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build();

                    if (am != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        focusReq = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                                .setAudioAttributes(attrs)
                                .build();
                        am.requestAudioFocus(focusReq);
                    }

                    track = new AudioTrack.Builder()
                            .setAudioAttributes(attrs)
                            .setAudioFormat(new AudioFormat.Builder()
                                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                                    .setSampleRate(rate)
                                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                                    .build())
                            .setBufferSizeInBytes(bufBytes)
                            .setTransferMode(AudioTrack.MODE_STREAM)
                            .build();

                    currentTrack = track;
                    track.play();

                    int totalFrames = len / 2;
                    long expectedMs = (totalFrames * 1000L) / rate;
                    appendLog("I", "PCM", "start seq=" + mySeq + " frames=" + totalFrames + " rate=" + rate + " expectedMs=" + expectedMs);

                    int written = 0;
                    int chunkSize = 16384;
                    while (written < len && !stopRequested && playSeq.get() == mySeq) {
                        int n = Math.min(chunkSize, len - written);
                        int res = track.write(decoded, off + written, n, AudioTrack.WRITE_BLOCKING);
                        if (res <= 0) break;
                        written += res;
                    }

                    // Write ~240ms tail silence so AudioFlinger/Bluetooth flushes every last word
                    if (!stopRequested && playSeq.get() == mySeq) {
                        int padBytes = ((rate / 4) * 2) & ~1;
                        byte[] silence = new byte[Math.min(padBytes, 16384)];
                        track.write(silence, 0, silence.length, AudioTrack.WRITE_BLOCKING);
                        int padFrames = silence.length / 2;
                        int targetFrames = totalFrames + (padFrames / 2);

                        int lastHead = -1;
                        long lastProgressMs = System.currentTimeMillis();
                        long hardDeadline = System.currentTimeMillis() + expectedMs + 30000L;

                        while (!stopRequested && playSeq.get() == mySeq
                                && System.currentTimeMillis() < hardDeadline
                                && track.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) {
                            int head = track.getPlaybackHeadPosition();
                            if (head >= targetFrames) break;
                            if (head > lastHead) {
                                lastHead = head;
                                lastProgressMs = System.currentTimeMillis();
                            } else if (System.currentTimeMillis() - lastProgressMs > 8000L) {
                                appendLog("W", "PCM", "head stalled at " + head + "/" + targetFrames);
                                break;
                            }
                            Thread.sleep(40);
                        }
                    }

                    boolean completedNormally = !stopRequested && playSeq.get() == mySeq;
                    appendLog("I", "PCM", "done seq=" + mySeq + " completed=" + completedNormally);
                    promise.resolve(completedNormally);
                } catch (Throwable t) {
                    appendLog("E", "PCM", "playback failed: " + t.getMessage());
                    promise.resolve(false);
                } finally {
                    try {
                        if (track != null) {
                            track.pause();
                            track.flush();
                            track.stop();
                            track.release();
                        }
                    } catch (Throwable ignored) {}
                    if (currentTrack == track) currentTrack = null;
                    try {
                        if (am != null && focusReq != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                            am.abandonAudioFocusRequest(focusReq);
                        }
                    } catch (Throwable ignored) {}
                }
            }
        }, "RadioPcmStream").start();
    }

    @ReactMethod
    public void stopSpeaking() {
        stopRequested = true;
        playSeq.incrementAndGet();
        try {
            AudioTrack t = currentTrack;
            currentTrack = null;
            if (t != null) {
                t.pause();
                t.flush();
                t.stop();
            }
        } catch (Throwable ignored) {}
    }

    // ---------------------------------------------------------------- orientation & first-open overlay bridge
    @ReactMethod
    public void forceLandscapeFullscreen() {
        final Activity activity = getCurrentActivity();
        if (activity == null) return;
        activity.runOnUiThread(() -> {
            try {
                activity.setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    WindowManager.LayoutParams lp = activity.getWindow().getAttributes();
                    lp.layoutInDisplayCutoutMode =
                            WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
                    activity.getWindow().setAttributes(lp);
                }
                int flags = View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY;
                activity.getWindow().getDecorView().setSystemUiVisibility(flags);
            } catch (Throwable t) {
                appendLog("W", "Orientation", "forceLandscape failed: " + t.getMessage());
            }
        });
    }

    @ReactMethod
    public void notifyStreamOpened(final boolean open) {
        streamActive = open;
        appendLog("I", "StreamState", "open=" + open);
        final Activity activity = getCurrentActivity();
        if (activity != null) {
            activity.runOnUiThread(() -> {
                try {
                    Intent it = new Intent(ACTION_STREAM_STATE);
                    it.setPackage(activity.getPackageName());
                    it.putExtra("open", open);
                    activity.sendBroadcast(it);

                    // Bring any native :atc overlay toggle to top immediately on first open
                    ViewGroup decor = (ViewGroup) activity.getWindow().getDecorView();
                    bringOverlayViewsToFront(decor);
                } catch (Throwable ignored) {}
            });
        }
    }

    private void bringOverlayViewsToFront(View v) {
        if (v == null) return;
        Object tag = v.getTag();
        String tagStr = tag != null ? String.valueOf(tag).toLowerCase(Locale.US) : "";
        String clsStr = v.getClass().getName().toLowerCase(Locale.US);
        if (tagStr.contains("radio") || tagStr.contains("atc") || tagStr.contains("bush")
                || clsStr.contains("composeview")) {
            v.setVisibility(View.VISIBLE);
            v.bringToFront();
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                v.setElevation(100f);
            }
        }
        if (v instanceof ViewGroup) {
            ViewGroup vg = (ViewGroup) v;
            for (int i = 0; i < vg.getChildCount(); i++) {
                bringOverlayViewsToFront(vg.getChildAt(i));
            }
        }
    }

    // ---------------------------------------------------------------- cross-sync 5 API keys from SharedPreferences
    @ReactMethod
    public void getAtcKeys(final Promise promise) {
        try {
            Set<String> keys = new LinkedHashSet<>();
            Context ctx = getReactApplicationContext();
            File spDir = new File(ctx.getApplicationInfo().dataDir, "shared_prefs");
            File[] files = spDir.listFiles();
            if (files != null) {
                for (File f : files) {
                    if (!f.getName().endsWith(".xml")) continue;
                    String prefName = f.getName().substring(0, f.getName().length() - 4);
                    SharedPreferences sp = ctx.getSharedPreferences(prefName, Context.MODE_PRIVATE);
                    for (Map.Entry<String, ?> entry : sp.getAll().entrySet()) {
                        Object val = entry.getValue();
                        if (val instanceof String) {
                            String s = ((String) val).trim();
                            if (s.startsWith("AIza") && s.length() >= 30 && s.length() <= 120) {
                                keys.add(s);
                            }
                        }
                    }
                }
            }
            WritableArray arr = Arguments.createArray();
            for (String k : keys) arr.pushString(k);
            promise.resolve(arr);
        } catch (Throwable t) {
            promise.resolve(Arguments.createArray());
        }
    }

    // ---------------------------------------------------------------- persistent radiolog.txt + HeadLog bridge
    private void appendLog(String lvl, String tag, String msg) {
        String line = logFmt.format(new Date()) + " " + lvl + "/" + tag + ": " + msg;
        try { com.xstreaming.HeadLog.i("Radio", msg); } catch (Throwable ignored) {}
        synchronized (logLock) {
            if (radioLogFile == null) return;
            try (FileWriter fw = new FileWriter(radioLogFile, true)) {
                fw.write(line + "\n");
            } catch (Throwable ignored) {}
        }
    }

    @ReactMethod
    public void log(String msg) {
        appendLog("I", "Radio", msg);
    }

    private String readLogsInternal() {
        synchronized (logLock) {
            if (radioLogFile == null || !radioLogFile.exists()) {
                return "(no Bush Radio logs recorded yet)";
            }
            try (RandomAccessFile f = new RandomAccessFile(radioLogFile, "r")) {
                long len = f.length();
                long start = Math.max(0, len - READ_LOG_CHARS);
                f.seek(start);
                byte[] buf = new byte[(int) (len - start)];
                f.readFully(buf);
                return new String(buf, "UTF-8");
            } catch (Throwable t) {
                return "(log read failed: " + t.getMessage() + ")";
            }
        }
    }

    @ReactMethod
    public void getLogs(final Promise promise) {
        promise.resolve(readLogsInternal());
    }

    @ReactMethod
    public void clearLogs(final Promise promise) {
        synchronized (logLock) {
            try {
                if (radioLogFile != null && radioLogFile.exists()) {
                    radioLogFile.delete();
                }
            } catch (Throwable ignored) {}
        }
        appendLog("I", "RadioModule", "logs cleared by user");
        promise.resolve(true);
    }

    @ReactMethod
    public void shareLogs(final Promise promise) {
        final Activity activity = getCurrentActivity();
        if (activity == null) {
            promise.resolve(false);
            return;
        }
        final String text = readLogsInternal();
        activity.runOnUiThread(() -> {
            try {
                ClipboardManager cm = (ClipboardManager) activity.getSystemService(Context.CLIPBOARD_SERVICE);
                if (cm != null) {
                    cm.setPrimaryClip(ClipData.newPlainText("bush_radio_log", text));
                }
                Intent it = new Intent(Intent.ACTION_SEND);
                it.setType("text/plain");
                it.putExtra(Intent.EXTRA_SUBJECT, "Bush Radio Debug Logs");
                it.putExtra(Intent.EXTRA_TEXT, text);
                activity.startActivity(Intent.createChooser(it, "Share Bush Radio Logs"));
                promise.resolve(true);
            } catch (Throwable t) {
                appendLog("E", "LogShare", "share failed: " + t.getMessage());
                promise.resolve(false);
            }
        });
    }

    // short "radio keyed" blip before a transmission
    @ReactMethod
    public void click() {
        try {
            final ToneGenerator tg = new ToneGenerator(AudioManager.STREAM_MUSIC, 25);
            tg.startTone(ToneGenerator.TONE_PROP_BEEP2, 85);
            new Handler(Looper.getMainLooper()).postDelayed(tg::release, 350);
        } catch (Throwable ignored) {}
    }

    @Override
    public void invalidate() {
        stopSpeaking();
        super.invalidate();
    }
}
"""

# ------------------------------------------------------------------------------
# 4. Bush Radio Floating Overlay UI (src/components/BushRadioOverlay.tsx)
# ------------------------------------------------------------------------------
BUSH_RADIO_OVERLAY_TSX = r"""// BUSH_RADIO_FIX_V1: Full-featured Bush Radio floating UI over full-screen landscape stream
import React from 'react';
import {
  Keyboard,
  Modal,
  NativeModules,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  ToastAndroid,
  TouchableOpacity,
  View,
} from 'react-native';
import radio, {KEY_SLOTS, PERSONAS, SPEAKERS} from '../utils/radio';
import brain from '../utils/brain';
import said from '../utils/said';
import {
  suspendGamepadNavigation,
  resumeGamepadNavigation,
} from '../utils/useGamepadNavigation';

const {GamepadManager} = NativeModules;

type Props = {
  showOptions: (items: any[], o?: any) => Promise<any>;
  showInput: (o: any) => Promise<any>;
};

export default function BushRadioOverlay({showOptions, showInput}: Props) {
  const [snap, setSnap] = React.useState(() => radio.getUiSnapshot());
  const [panelOpen, setPanelOpen] = React.useState(false);
  const [tab, setTab] = React.useState<'controls' | 'settings'>('controls');
  const [question, setQuestion] = React.useState('');
  const [logsOpen, setLogsOpen] = React.useState(false);
  const [logsText, setLogsText] = React.useState('');

  React.useEffect(() => {
    const unsub = radio.subscribeUi(s => setSnap(s));
    radio.syncExternalKeys?.().catch?.(() => {});
    return unsub;
  }, []);

  const refreshLogs = React.useCallback(async () => {
    const txt = await radio.getLogsText();
    setLogsText(txt || '(no logs yet)');
  }, []);

  const openLogs = React.useCallback(async () => {
    setLogsOpen(true);
    await refreshLogs();
  }, [refreshLogs]);

  const handleToggleRadio = React.useCallback(async () => {
    if (snap.on) {
      radio.stop();
      ToastAndroid.show('Bush Radio stopped', ToastAndroid.SHORT);
      return;
    }
    await radio.syncExternalKeys?.();
    if (!radio.hasAnyKey()) {
      await radio.promptForSlotKey(1, showInput);
    }
    if (radio.hasAnyKey()) {
      radio.start();
      ToastAndroid.show('Bush Radio ON AIR', ToastAndroid.SHORT);
    } else {
      setPanelOpen(true);
      setTab('settings');
      ToastAndroid.show('Add a Gemini API key in Settings first', ToastAndroid.LONG);
    }
  }, [snap.on, showInput]);

  const handleAsk = React.useCallback(async () => {
    const q = question.trim();
    if (!q) {
      ToastAndroid.show('Type a question first', ToastAndroid.SHORT);
      return;
    }
    Keyboard.dismiss();
    await radio.syncExternalKeys?.();
    if (!radio.hasAnyKey()) {
      setPanelOpen(true);
      setTab('settings');
      ToastAndroid.show('Add a Gemini API key first', ToastAndroid.SHORT);
      return;
    }
    setQuestion('');
    await radio.askQuestion(q);
  }, [question]);

  const handleTalkNow = React.useCallback(async () => {
    await radio.syncExternalKeys?.();
    if (!radio.hasAnyKey()) {
      setPanelOpen(true);
      setTab('settings');
      ToastAndroid.show('Add a Gemini API key first', ToastAndroid.SHORT);
      return;
    }
    radio.talkNow();
  }, []);

  const openClassicMenu = React.useCallback(async () => {
    try {
      GamepadManager?.setCurrentScreen?.('');
      resumeGamepadNavigation();
      await radio.openMenu(showOptions, showInput);
    } finally {
      GamepadManager?.setCurrentScreen?.('stream');
      suspendGamepadNavigation();
    }
  }, [showOptions, showInput]);

  const pauseMinOpts = [2, 4, 8, 15, 30];
  const pauseMaxOpts = [15, 30, 60, 120, 240];
  const advOpts = [0, 10, 20, 30];

  return (
    <View style={styles.root} pointerEvents="box-none" collapsable={false}>
      {/* Always-mounted bottom-right toggle button (guaranteed visible on first open) */}
      <View style={styles.fabRow} pointerEvents="box-none">
        <TouchableOpacity
          activeOpacity={0.85}
          onPress={() => {
            setPanelOpen(v => !v);
            radio.refreshUi?.();
          }}
          onLongPress={handleToggleRadio}
          style={[
            styles.fab,
            snap.on ? styles.fabOn : styles.fabOff,
            snap.speaking && styles.fabSpeaking,
          ]}>
          <Text style={styles.fabText}>
            {snap.on
              ? snap.speaking
                ? '📻 ON AIR •'
                : '📻 Radio ON'
              : '📻 Bush Radio'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Expandable Floating Panel over Full-Screen Landscape Stream */}
      {panelOpen && (
        <View style={styles.panelWrap} pointerEvents="box-none">
          <View style={styles.panel}>
            {/* Header */}
            <View style={styles.header}>
              <View style={styles.headerLeft}>
                <View style={[styles.dot, snap.on ? styles.dotOn : styles.dotOff]} />
                <Text style={styles.title}>Bush Radio</Text>
                <Text style={styles.badge}>
                  {snap.keysSet}/5 keys
                </Text>
              </View>
              <View style={styles.tabRow}>
                <TouchableOpacity
                  onPress={() => setTab('controls')}
                  style={[styles.tabBtn, tab === 'controls' && styles.tabBtnActive]}>
                  <Text style={styles.tabTxt}>Radio</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => setTab('settings')}
                  style={[styles.tabBtn, tab === 'settings' && styles.tabBtnActive]}>
                  <Text style={styles.tabTxt}>All Settings</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={openLogs} style={styles.tabBtn}>
                  <Text style={styles.tabTxt}>Logs</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => setPanelOpen(false)}
                  style={styles.closeBtn}>
                  <Text style={styles.closeTxt}>✕</Text>
                </TouchableOpacity>
              </View>
            </View>

            {tab === 'controls' ? (
              <ScrollView
                style={styles.bodyScroll}
                keyboardShouldPersistTaps="handled"
                nestedScrollEnabled>
                {/* Live status strip */}
                <Text style={styles.statusLine} numberOfLines={2}>
                  Brain: {snap.lastModel || 'ready'} | Voice: {snap.speaker}
                  {snap.lastVoice ? ' (' + snap.lastVoice + ')' : ''}
                </Text>

                {!!snap.lastError && (
                  <Text style={styles.errLine} numberOfLines={2}>
                    Last note: {snap.lastError}
                  </Text>
                )}

                {!!snap.lastCaption && (
                  <View style={styles.captionBox}>
                    <Text style={styles.captionTxt}>{snap.lastCaption}</Text>
                  </View>
                )}

                {/* Ask / Talk Input Field */}
                <Text style={styles.sectionLabel}>Ask the voice (uses live full-screen view):</Text>
                <View style={styles.askRow}>
                  <TextInput
                    style={styles.askInput}
                    value={question}
                    onChangeText={setQuestion}
                    placeholder="e.g. any race tracks around?"
                    placeholderTextColor="#8B949E"
                    returnKeyType="send"
                    onFocus={() => {
                      try {
                        GamepadManager?.setCurrentScreen?.('');
                      } catch (e) {}
                    }}
                    onBlur={() => {
                      try {
                        GamepadManager?.setCurrentScreen?.('stream');
                      } catch (e) {}
                    }}
                    onSubmitEditing={handleAsk}
                  />
                  <TouchableOpacity
                    onPress={handleAsk}
                    disabled={snap.asking}
                    style={[styles.askBtn, snap.asking && styles.btnDisabled]}>
                    <Text style={styles.askBtnTxt}>
                      {snap.asking ? '...' : 'Ask'}
                    </Text>
                  </TouchableOpacity>
                </View>

                {/* Primary action buttons */}
                <View style={styles.btnGrid}>
                  <TouchableOpacity
                    onPress={handleToggleRadio}
                    style={[
                      styles.actionBtn,
                      snap.on ? styles.stopBtn : styles.startBtn,
                    ]}>
                    <Text style={styles.actionBtnTxt}>
                      {snap.on ? 'Stop Radio' : 'Start Radio'}
                    </Text>
                  </TouchableOpacity>

                  <TouchableOpacity onPress={handleTalkNow} style={styles.actionBtn}>
                    <Text style={styles.actionBtnTxt}>Talk Now</Text>
                  </TouchableOpacity>

                  <TouchableOpacity onPress={openLogs} style={styles.actionBtn}>
                    <Text style={styles.actionBtnTxt}>Logs</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    onPress={() => setTab('settings')}
                    style={styles.actionBtn}>
                    <Text style={styles.actionBtnTxt}>Settings</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    onPress={() => brain.showBlackout()}
                    style={styles.actionBtn}>
                    <Text style={styles.actionBtnTxt}>OLED Black</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    onPress={openClassicMenu}
                    style={styles.actionBtn}>
                    <Text style={styles.actionBtnTxt}>Crew / Menu</Text>
                  </TouchableOpacity>
                </View>
              </ScrollView>
            ) : (
              <ScrollView
                style={styles.bodyScroll}
                keyboardShouldPersistTaps="handled"
                nestedScrollEnabled>
                {/* 5 API Keys + Spare */}
                <Text style={styles.sectionLabel}>
                  API Keys ({snap.keysSet}/5 configured — TTS rotates across all keys)
                </Text>
                <View style={styles.chipWrap}>
                  {KEY_SLOTS.map(slot => {
                    const set = !!radio.getSlotKey(slot.id);
                    return (
                      <TouchableOpacity
                        key={slot.id}
                        onPress={async () => {
                          await radio.promptForSlotKey(slot.id, showInput);
                          radio.refreshUi?.();
                        }}
                        style={[styles.chip, set && styles.chipActive]}>
                        <Text style={styles.chipTxt}>
                          Key {slot.id} {set ? '✓' : '+'}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                  <TouchableOpacity
                    onPress={async () => {
                      await radio.promptForKey(showInput);
                      radio.refreshUi?.();
                    }}
                    style={[styles.chip, !!radio.getMainKey() && styles.chipActive]}>
                    <Text style={styles.chipTxt}>
                      Spare {radio.getMainKey() ? '✓' : '+'}
                    </Text>
                  </TouchableOpacity>
                </View>

                {/* Character */}
                <Text style={styles.sectionLabel}>Character</Text>
                <View style={styles.chipWrap}>
                  {PERSONAS.map(p => (
                    <TouchableOpacity
                      key={p.id}
                      onPress={() => {
                        radio.setPersonaId(p.id);
                        radio.refreshUi?.();
                      }}
                      style={[
                        styles.chip,
                        snap.personaId === p.id && styles.chipActive,
                      ]}>
                      <Text style={styles.chipTxt}>{p.name}</Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {/* Voice (Gemini only, Device TTS removed) */}
                <Text style={styles.sectionLabel}>Gemini Voice</Text>
                <View style={styles.chipWrap}>
                  {SPEAKERS.map(s => (
                    <TouchableOpacity
                      key={s.id}
                      onPress={() => {
                        radio.setSpeaker(s.id);
                        radio.refreshUi?.();
                      }}
                      style={[
                        styles.chip,
                        snap.speaker === s.id && styles.chipActive,
                      ]}>
                      <Text style={styles.chipTxt}>{s.id}</Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {/* Session-start Mood & Cadence */}
                <Text style={styles.sectionLabel}>
                  Session Mood & Cadence (sent once at session start, never spoken aloud)
                </Text>
                <TouchableOpacity
                  onPress={async () => {
                    await radio.promptForMoodCadence(showInput);
                    radio.refreshUi?.();
                  }}
                  style={styles.wideRowBtn}>
                  <Text style={styles.wideRowTxt}>
                    Mood / Cadence:{' '}
                    {snap.moodCadence || '(use character default)'}
                  </Text>
                </TouchableOpacity>

                {/* Nerd Level */}
                <Text style={styles.sectionLabel}>Nerd Level: {snap.nerd} / 5</Text>
                <View style={styles.chipWrap}>
                  {[1, 2, 3, 4, 5].map(lvl => (
                    <TouchableOpacity
                      key={lvl}
                      onPress={() => {
                        radio.setNerd(lvl);
                        radio.refreshUi?.();
                      }}
                      style={[styles.chip, snap.nerd === lvl && styles.chipActive]}>
                      <Text style={styles.chipTxt}>Level {lvl}</Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {/* Pause Min / Max */}
                <Text style={styles.sectionLabel}>
                  Pause Range: {snap.gapMin}s – {snap.gapMax}s
                </Text>
                <View style={styles.chipWrap}>
                  {pauseMinOpts.map(sec => (
                    <TouchableOpacity
                      key={'min' + sec}
                      onPress={() => {
                        radio.setGapMin(sec);
                        radio.refreshUi?.();
                      }}
                      style={[styles.chip, snap.gapMin === sec && styles.chipActive]}>
                      <Text style={styles.chipTxt}>Min {sec}s</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <View style={styles.chipWrap}>
                  {pauseMaxOpts.map(sec => (
                    <TouchableOpacity
                      key={'max' + sec}
                      onPress={() => {
                        radio.setGapMax(sec);
                        radio.refreshUi?.();
                      }}
                      style={[styles.chip, snap.gapMax === sec && styles.chipActive]}>
                      <Text style={styles.chipTxt}>Max {sec}s</Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {/* Trip, Aircraft & Talk Rules */}
                <Text style={styles.sectionLabel}>Trip, Aircraft & Talk Rules</Text>
                <View style={styles.chipWrap}>
                  <TouchableOpacity
                    onPress={async () => {
                      await radio.promptForTrip(showInput);
                      radio.refreshUi?.();
                    }}
                    style={[styles.chip, !!snap.trip && styles.chipActive]}>
                    <Text style={styles.chipTxt}>
                      Trip Brief {snap.trip ? '✓' : '(set)'}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={async () => {
                      await radio.promptForAircraft(showInput);
                      radio.refreshUi?.();
                    }}
                    style={[styles.chip, !!snap.aircraft && styles.chipActive]}>
                    <Text style={styles.chipTxt}>
                      Aircraft: {snap.aircraft || 'Auto'}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => {
                      radio.setCaptions(!snap.captions);
                      radio.refreshUi?.();
                    }}
                    style={[styles.chip, snap.captions && styles.chipActive]}>
                    <Text style={styles.chipTxt}>
                      Captions: {snap.captions ? 'ON' : 'OFF'}
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => {
                      radio.setMusicOn(!snap.musicOn);
                      radio.refreshUi?.();
                    }}
                    style={[styles.chip, snap.musicOn && styles.chipActive]}>
                    <Text style={styles.chipTxt}>
                      Music Tip: {snap.musicOn ? 'ON' : 'OFF'}
                    </Text>
                  </TouchableOpacity>
                  {advOpts.map(m => (
                    <TouchableOpacity
                      key={'adv' + m}
                      onPress={() => {
                        radio.setAdviceMin(m);
                        radio.refreshUi?.();
                      }}
                      style={[styles.chip, snap.adviceMin === m && styles.chipActive]}>
                      <Text style={styles.chipTxt}>
                        Advice: {m === 0 ? 'OFF' : m + 'm'}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {/* Memory & Diagnostics */}
                <Text style={styles.sectionLabel}>Memory, Crew & Diagnostics</Text>
                <View style={styles.chipWrap}>
                  <TouchableOpacity
                    onPress={() => {
                      said.clear();
                      ToastAndroid.show('Trip memory cleared', ToastAndroid.SHORT);
                    }}
                    style={styles.chip}>
                    <Text style={styles.chipTxt}>Clear Memory</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => {
                      radio.clearNotebook();
                      ToastAndroid.show('Notebook cleared', ToastAndroid.SHORT);
                    }}
                    style={styles.chip}>
                    <Text style={styles.chipTxt}>Forget Notebook</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={async () => {
                      ToastAndroid.show(await brain.backupNow(true), ToastAndroid.LONG);
                    }}
                    style={styles.chip}>
                    <Text style={styles.chipTxt}>Backup Brain</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={openLogs} style={styles.chip}>
                    <Text style={styles.chipTxt}>View Logs</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={openClassicMenu} style={styles.chip}>
                    <Text style={styles.chipTxt}>Full Menu / Crew</Text>
                  </TouchableOpacity>
                </View>
              </ScrollView>
            )}
          </View>
        </View>
      )}

      {/* Dedicated Bush Radio Log Viewer Modal */}
      <Modal
        visible={logsOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setLogsOpen(false)}>
        <View style={styles.logBackdrop}>
          <View style={styles.logModal}>
            <View style={styles.logHeader}>
              <Text style={styles.title}>Bush Radio Debug Logs</Text>
              <TouchableOpacity
                onPress={() => setLogsOpen(false)}
                style={styles.closeBtn}>
                <Text style={styles.closeTxt}>✕</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.logActions}>
              <TouchableOpacity onPress={refreshLogs} style={styles.logBtn}>
                <Text style={styles.logBtnTxt}>Refresh</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={async () => {
                  await radio.shareLogs();
                }}
                style={[styles.logBtn, styles.startBtn]}>
                <Text style={styles.logBtnTxt}>Copy & Share Logs</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={async () => {
                  await radio.clearLogs();
                  await refreshLogs();
                }}
                style={[styles.logBtn, styles.stopBtn]}>
                <Text style={styles.logBtnTxt}>Clear</Text>
              </TouchableOpacity>
            </View>
            <ScrollView style={styles.logScroll}>
              <Text selectable style={styles.logMono}>
                {logsText}
              </Text>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 99999,
    elevation: 99,
  },
  fabRow: {
    position: 'absolute',
    right: 14,
    bottom: 14,
    zIndex: 99999,
    elevation: 99,
  },
  fab: {
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: 8,
    borderWidth: 1,
  },
  fabOff: {
    backgroundColor: 'rgba(18, 22, 30, 0.88)',
    borderColor: '#4B5563',
  },
  fabOn: {
    backgroundColor: 'rgba(16, 110, 62, 0.94)',
    borderColor: '#34D399',
  },
  fabSpeaking: {
    borderColor: '#FBBF24',
  },
  fabText: {
    color: '#F9FAFB',
    fontSize: 13,
    fontWeight: '700',
  },
  panelWrap: {
    position: 'absolute',
    right: 14,
    bottom: 62,
    width: 420,
    maxWidth: '92%',
    maxHeight: '80%',
    zIndex: 99999,
    elevation: 99,
  },
  panel: {
    backgroundColor: 'rgba(13, 17, 23, 0.94)',
    borderColor: '#30363D',
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
    maxHeight: '100%',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#21262D',
    paddingBottom: 6,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  dotOn: {backgroundColor: '#3FB950'},
  dotOff: {backgroundColor: '#6E7681'},
  title: {
    color: '#F0F6FC',
    fontSize: 14,
    fontWeight: '700',
    marginRight: 6,
  },
  badge: {
    color: '#9CDCFE',
    fontSize: 11,
    fontWeight: '600',
  },
  tabRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tabBtn: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    marginLeft: 4,
    backgroundColor: '#21262D',
  },
  tabBtnActive: {
    backgroundColor: '#1F6FEB',
  },
  tabTxt: {
    color: '#F0F6FC',
    fontSize: 11,
    fontWeight: '600',
  },
  closeBtn: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    marginLeft: 6,
  },
  closeTxt: {
    color: '#8B949E',
    fontSize: 15,
    fontWeight: '700',
  },
  bodyScroll: {
    maxHeight: 270,
  },
  statusLine: {
    color: '#8B949E',
    fontSize: 11,
    marginBottom: 4,
  },
  errLine: {
    color: '#F85149',
    fontSize: 11,
    marginBottom: 6,
  },
  captionBox: {
    backgroundColor: 'rgba(33, 38, 45, 0.8)',
    borderRadius: 6,
    padding: 7,
    marginBottom: 8,
  },
  captionTxt: {
    color: '#E6EDF3',
    fontSize: 12,
    lineHeight: 16,
  },
  sectionLabel: {
    color: '#9CA3AF',
    fontSize: 11,
    fontWeight: '700',
    marginTop: 6,
    marginBottom: 4,
  },
  askRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  askInput: {
    flex: 1,
    backgroundColor: '#161B22',
    borderWidth: 1,
    borderColor: '#30363D',
    borderRadius: 6,
    color: '#F0F6FC',
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 12,
    marginRight: 6,
  },
  askBtn: {
    backgroundColor: '#1F6FEB',
    borderRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  askBtnTxt: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '700',
  },
  btnDisabled: {
    opacity: 0.5,
  },
  btnGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 2,
  },
  actionBtn: {
    backgroundColor: '#21262D',
    borderWidth: 1,
    borderColor: '#30363D',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  startBtn: {
    backgroundColor: '#238636',
    borderColor: '#2EA043',
  },
  stopBtn: {
    backgroundColor: '#B62324',
    borderColor: '#F85149',
  },
  actionBtnTxt: {
    color: '#F0F6FC',
    fontSize: 12,
    fontWeight: '600',
  },
  chipWrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 5,
    marginBottom: 4,
  },
  chip: {
    backgroundColor: '#161B22',
    borderWidth: 1,
    borderColor: '#30363D',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  chipActive: {
    backgroundColor: '#1F6FEB',
    borderColor: '#58A6FF',
  },
  chipTxt: {
    color: '#E6EDF3',
    fontSize: 11,
    fontWeight: '600',
  },
  wideRowBtn: {
    backgroundColor: '#161B22',
    borderWidth: 1,
    borderColor: '#30363D',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginBottom: 4,
  },
  wideRowTxt: {
    color: '#E6EDF3',
    fontSize: 11,
  },
  logBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.72)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 16,
  },
  logModal: {
    width: '92%',
    height: '86%',
    backgroundColor: '#0D1117',
    borderWidth: 1,
    borderColor: '#30363D',
    borderRadius: 10,
    padding: 12,
  },
  logHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  logActions: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 8,
  },
  logBtn: {
    backgroundColor: '#21262D',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  logBtnTxt: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '600',
  },
  logScroll: {
    flex: 1,
    backgroundColor: '#010409',
    borderRadius: 6,
    padding: 8,
  },
  logMono: {
    color: '#C9D1D9',
    fontSize: 10.5,
    fontFamily: 'monospace',
  },
});
"""


# ------------------------------------------------------------------------------
# Patchers for Base RN + Java Files
# ------------------------------------------------------------------------------

def patch_radio_module_java():
    p = os.path.join(JAVA_RADIO_DIR, "RadioModule.java")
    write_text(p, RADIO_MODULE_JAVA)
    log("wrote upgraded " + p)


def patch_said_ts():
    p = "src/utils/said.ts"
    if not pathlib.Path(p).exists():
        log("WARNING: " + p + " not found, skipping said.ts patch")
        return
    text, crlf = read_text(p)
    if MARK in text:
        log("said.ts already patched")
        return

    if "from './radioHelpers'" not in text:
        text = (
            "// " + MARK + "\n" +
            "import {stripMoodAndCadenceCues} from './radioHelpers';\n" +
            text
        )

    # Expand polish signature to support {isAnswer?: boolean} and strip mood/cadence cues
    text = re.sub(
        r"polish\(\s*text:\s*string,\s*o:\s*\{\s*music:\s*boolean;\s*advice:\s*boolean;\s*aircraft:\s*boolean(?:;\s*isAnswer\?:\s*boolean)?\s*\}\s*\)",
        "polish(text: string, o: {music: boolean; advice: boolean; aircraft: boolean; isAnswer?: boolean})",
        text,
    )
    text = text.replace(
        "const raw = String(text || '').trim();",
        "const raw = stripMoodAndCadenceCues(String(text || '').trim());",
    )
    text = text.replace(
        "if (/\\?[\"'”’)]*$/.test(s) && LISTENER_Q.test(s)) {",
        "if (!o.isAnswer && /\\?[\"'”’)]*$/.test(s) && LISTENER_Q.test(s)) {",
    )
    text = text.replace(
        "} else if (!o.music && MUSIC_DROP.test(s)) {",
        "} else if (!o.isAnswer && !o.music && MUSIC_DROP.test(s)) {",
    )
    text = text.replace(
        "} else if (!o.aircraft && AIRCRAFT_TECH.test(s)) {",
        "} else if (!o.isAnswer && !o.aircraft && AIRCRAFT_TECH.test(s)) {",
    )
    text = text.replace(
        "} else if (!o.advice && n <= 28 && READOUT_UNIT.test(s) && READOUT_VERB.test(s)) {",
        "} else if (!o.isAnswer && !o.advice && n <= 28 && READOUT_UNIT.test(s) && READOUT_VERB.test(s)) {",
    )
    write_text(p, text, crlf)
    log("patched " + p)


def replace_ts_block(text, signature_regex, new_block):
    """Replace a TS class method or top-level declaration cleanly by brace counting."""
    m = re.search(signature_regex, text, re.MULTILINE)
    if not m:
        return text, False
    start = m.start()
    body_brace = re.search(r"\{[ \t]*(?:\n|$)", text[m.start():])
    if body_brace:
        brace = m.start() + body_brace.start()
    else:
        brace = text.find("{", m.end() - 1)
    if brace < 0:
        return text, False
    depth = 0
    in_str = None
    esc = False
    i = brace
    while i < len(text):
        ch = text[i]
        if esc:
            esc = False
        elif in_str:
            if ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(text) and text[end] in (" ", "\t"):
                        end += 1
                    if end < len(text) and text[end] == "\n":
                        end += 1
                    return text[:start] + new_block + "\n" + text[end:], True
        i += 1
    return text, False


def patch_radio_ts():
    p = "src/utils/radio.ts"
    if not pathlib.Path(p).exists():
        die("src/utils/radio.ts not found.")
    text, crlf = read_text(p)
    if MARK in text:
        log("radio.ts already patched")
        return

    # 1. Import radioHelpers + DeviceEventEmitter if useful
    helper_import = (
        "// " + MARK + "\n"
        "import {\n"
        "  BRAIN_MODEL_CHAIN,\n"
        "  DEFAULT_SPEAKER,\n"
        "  TTS_MODEL_CHAIN,\n"
        "  buildQuestionUserPrompt,\n"
        "  buildSessionStyleSystemBlock,\n"
        "  collectKeyPool,\n"
        "  estimateSpeechMsFromBase64,\n"
        "  filterBrainModels,\n"
        "  filterVoiceModels,\n"
        "  sanitizeSpeaker,\n"
        "  stripMoodAndCadenceCues,\n"
        "} from './radioHelpers';\n"
    )
    if "from './radioHelpers'" not in text:
        text = helper_import + text

    # 2. Remove 'gemini-4-hydrogen' and hydrogen checks completely
    text = text.replace("'gemini-4-hydrogen',", "")
    text = text.replace("'gemini-4-hydrogen'", "'gemini-flash-latest'")
    text = re.sub(
        r"export const MODEL_CHAIN\s*=\s*\[[\s\S]*?\];",
        "export const MODEL_CHAIN = BRAIN_MODEL_CHAIN.slice();",
        text,
        count=1,
    )
    text = re.sub(
        r"export const TTS_CHAIN\s*=\s*\[[\s\S]*?\];",
        "export const TTS_CHAIN = TTS_MODEL_CHAIN.slice();",
        text,
        count=1,
    )

    # 3. Remove Phone voice from SPEAKERS
    text = re.sub(r"[ \t]*\{id:\s*'Phone voice'[^\n]*\},\n?", "", text)

    # 4. Expand KEY_SLOTS to all 5 keys + update BRAIN_KEY_IDS / VOICE_KEY_IDS / KEY_PLAN
    key_slots_5 = (
        "export const KEY_SLOTS: Array<{id: number; model: string; name: string}> = [\n"
        "  {id: 1, model: 'brain', name: 'Key 1: Brain & Voice rotation'},\n"
        "  {id: 2, model: 'voice', name: 'Key 2: Voice & Brain rotation'},\n"
        "  {id: 3, model: 'voice', name: 'Key 3: Voice & Brain rotation'},\n"
        "  {id: 4, model: 'voice', name: 'Key 4: Voice & Brain rotation'},\n"
        "  {id: 5, model: 'voice', name: 'Key 5: Voice & Brain rotation'},\n"
        "];\n"
        "const BRAIN_KEY_IDS = [1, 2, 3, 4, 5];\n"
        "const VOICE_KEY_IDS = [1, 2, 3, 4, 5];"
    )
    text = re.sub(
        r"export const KEY_SLOTS:[\s\S]*?(?:const VOICE_KEY_IDS\s*=\s*\[[^\]]*\];)",
        key_slots_5,
        text,
        count=1,
    )
    if "BRAIN_KEY_IDS = [1, 2, 3, 4, 5]" not in text:
        text = re.sub(
            r"export const KEY_SLOTS:[\s\S]*?\];",
            key_slots_5,
            text,
            count=1,
        )
    text = re.sub(
        r"const KEY_PLAN:\s*string\[\]\s*=\s*\[[\s\S]*?\];",
        "const KEY_PLAN: string[] = [\n"
        "  'Make each of Keys 1-5 in its OWN Google AI Studio project',\n"
        "  'Keys from the same project share one quota: separate projects = 5x quota',\n"
        "  'Voice TTS rotates evenly across all 5 configured keys every spoken turn',\n"
        "  'Brain also rotates across all 5 keys if a key hits quota',\n"
        "  'Gemini Hydrogen and Device Phone TTS are disabled cleanly',\n"
        "];",
        text,
        count=1,
    )

    # 5. Add new runtime state fields inside SimRadio class
    fields_inject = (
        "  private globalModelCooldown: Record<string, number> = {};\n"
        "  private sessionStyleHeader = '';\n"
        "  private brainKeyCursor = 0;\n"
        "  private externalKeys: string[] = [];\n"
        "  private playChain: Promise<void> = Promise.resolve();\n"
        "  private isSpeakingNow = false;\n"
        "  private isAskingNow = false;\n"
        "  private lastCaption = '';\n"
        "  private memLogs: string[] = [];\n"
        "  private uiListeners: Set<(s: any) => void> = new Set();\n"
    )
    text = re.sub(
        r"(class SimRadio\s*\{\n)",
        r"\1" + fields_inject,
        text,
        count=1,
    )

    # 6. Upgrade log() to capture into memory + emit UI updates + write native radiolog
    new_log_fn = (
        "  private log(m: string) {\n"
        "    const ts = new Date().toISOString().slice(11, 23);\n"
        "    const line = ts + ' ' + m;\n"
        "    this.memLogs.push(line);\n"
        "    if (this.memLogs.length > 250) this.memLogs.shift();\n"
        "    try { RadioModule?.log?.(m); } catch (e) {}\n"
        "  }"
    )
    text, ok = replace_ts_block(text, r"^[ \t]*private\s+log\([^)]*\)[ \t]*\{[ \t]*$", new_log_fn)
    if not ok:
        die("Could not replace log() in src/utils/radio.ts")

    # 7. Sanitize getSpeaker / setSpeaker (remove 'Phone voice')
    text, ok = replace_ts_block(
        text,
        r"^[ \t]*getSpeaker\(\)\s*:\s*string[ \t]*\{[ \t]*$",
        "  getSpeaker(): string {\n"
        "    const raw = storage.getString(K_SPEAKER);\n"
        "    const clean = sanitizeSpeaker(raw);\n"
        "    if (raw && raw !== clean) storage.set(K_SPEAKER, clean);\n"
        "    return clean;\n"
        "  }",
    )
    if not ok:
        die("Could not replace getSpeaker() in src/utils/radio.ts")
    text, ok = replace_ts_block(
        text,
        r"^[ \t]*setSpeaker\([^)]*\)[ \t]*\{[ \t]*$",
        "  setSpeaker(s: string) {\n"
        "    storage.set(K_SPEAKER, sanitizeSpeaker(s));\n"
        "    this.emitUi();\n"
        "  }",
    )
    if not ok:
        die("Could not replace setSpeaker() in src/utils/radio.ts")

    # 8. Ensure keyPool reads all 5 slots + synced native keys
    new_keypool_fn = (
        "  private keyPool(ids: number[]): Array<{id: number; key: string}> {\n"
        "    const slotList = ids.map(id => ({id, key: this.getSlotKey(id)}));\n"
        "    const pool = collectKeyPool(slotList, this.getMainKey(), this.externalKeys);\n"
        "    if (pool.length === 0) {\n"
        "      const any = this.firstSlotKey();\n"
        "      if (any) pool.push({id: 0, key: any});\n"
        "    }\n"
        "    return pool;\n"
        "  }"
    )
    text, ok = replace_ts_block(text, r"^[ \t]*private\s+keyPool\([^)]*\)[^\n]*\{[ \t]*$", new_keypool_fn)
    if not ok:
        die("Could not replace keyPool() in src/utils/radio.ts")

    # 9. Replace brainModels() and brainRoutes() to EXCLUDE hydrogen completely & rotate all 5 keys
    new_brain_models = (
        "  private brainModels(): string[] {\n"
        "    const now = Date.now();\n"
        "    const list = filterBrainModels(this.available, MODEL_CHAIN);\n"
        "    const healthy = list.filter(m => (this.globalModelCooldown[m] || 0) <= now);\n"
        "    return healthy.length > 0 ? healthy : list;\n"
        "  }"
    )
    text, ok = replace_ts_block(text, r"^[ \t]*private\s+brainModels\(\)[^\n]*\{[ \t]*$", new_brain_models)
    if not ok:
        die("Could not replace brainModels() in src/utils/radio.ts")

    new_brain_routes = (
        "  private brainRoutes(): Array<{model: string; id: number; key: string; tag: string}> {\n"
        "    const now = Date.now();\n"
        "    const pool = this.keyPool(BRAIN_KEY_IDS);\n"
        "    if (pool.length === 0) return [];\n"
        "    const kOff = this.brainKeyCursor % pool.length;\n"
        "    const rotPool = pool.slice(kOff).concat(pool.slice(0, kOff));\n"
        "    this.brainKeyCursor = (this.brainKeyCursor + 1) % Math.max(1, pool.length);\n"
        "    const all: Array<{model: string; id: number; key: string; tag: string}> = [];\n"
        "    for (const model of this.brainModels()) {\n"
        "      for (const p of rotPool) {\n"
        "        all.push({model, id: p.id, key: p.key, tag: model + '@' + p.id});\n"
        "      }\n"
        "    }\n"
        "    const ok = all.filter(r => (this.cooldown[r.tag] || 0) <= now);\n"
        "    if (ok.length > 0) return ok;\n"
        "    const soon = all.slice().sort((a, b) => (this.cooldown[a.tag] || 0) - (this.cooldown[b.tag] || 0))[0];\n"
        "    return soon ? [soon] : [];\n"
        "  }"
    )
    text, ok = replace_ts_block(text, r"^[ \t]*private\s+brainRoutes\(\)[^\n]*\{[ \t]*$", new_brain_routes)
    if not ok:
        die("Could not replace brainRoutes() in src/utils/radio.ts")

    # 10. Replace voiceRoutes() and fetchGeminiAudio() to distribute cleanly across 5 keys & never speak cues
    new_voice_routes = (
        "  private voiceRoutes(): Array<{model: string; id: number; key: string; tag: string}> {\n"
        "    const models = filterVoiceModels(this.available, TTS_CHAIN);\n"
        "    return buildVoiceRoutes(\n"
        "      this.keyPool(VOICE_KEY_IDS),\n"
        "      this.cooldown,\n"
        "      this.rot,\n"
        "      Date.now(),\n"
        "      models,\n"
        "      this.globalModelCooldown,\n"
        "    );\n"
        "  }"
    )
    text, ok = replace_ts_block(text, r"^[ \t]*private\s+voiceRoutes\(\)[^\n]*\{[ \t]*$", new_voice_routes)
    if not ok:
        die("Could not replace voiceRoutes() in src/utils/radio.ts")

    new_fetch_audio = (
        "  private async fetchGeminiAudio(text: string): Promise<any> {\n"
        "    const cleanSpeech = stripMoodAndCadenceCues(text);\n"
        "    if (!cleanSpeech) return null;\n"
        "    const poolSize = Math.max(1, this.keyPool(VOICE_KEY_IDS).length);\n"
        "    const skip: Record<string, boolean> = {};\n"
        "    const speaker = sanitizeSpeaker(this.getSpeaker());\n"
        "    for (const r of this.voiceRoutes()) {\n"
        "      if (skip[r.model]) continue;\n"
        "      try {\n"
        "        markUsed(this.rot, r.tag, Date.now(), r.id);\n"
        "        const resp = await this.timedFetch(\n"
        "          API + '/models/' + r.model + ':generateContent',\n"
        "          {\n"
        "            method: 'POST',\n"
        "            headers: {'Content-Type': 'application/json', 'x-goog-api-key': r.key},\n"
        "            body: JSON.stringify({\n"
        "              contents: [{parts: [{text: cleanSpeech}]}],\n"
        "              generationConfig: {\n"
        "                responseModalities: ['AUDIO'],\n"
        "                speechConfig: {\n"
        "                  voiceConfig: {prebuiltVoiceConfig: {voiceName: speaker}},\n"
        "                },\n"
        "              },\n"
        "            }),\n"
        "          },\n"
        "          (this.streak[r.tag] || 0) > 0 ? 22000 : 35000,\n"
        "        );\n"
        "        const raw = await resp.text();\n"
        "        if (!resp.ok) throw new ApiError(resp.status, raw);\n"
        "        const j: any = JSON.parse(raw);\n"
        "        const parts: any[] = j?.candidates?.[0]?.content?.parts || [];\n"
        "        const ap = parts.find(p => p?.inlineData?.data || p?.inline_data?.data);\n"
        "        const inl = ap?.inlineData || ap?.inline_data;\n"
        "        if (!inl?.data) throw new ApiError(0, 'no audio returned');\n"
        "        const mime: string = String(inl.mimeType || inl.mime_type || '');\n"
        "        const rate = parseInt((mime.match(/rate=(\\d+)/) || [])[1] || '24000', 10);\n"
        "        const ms = estimateSpeechMsFromBase64(String(inl.data), rate);\n"
        "        this.lastVoice = r.model + (r.id ? '#' + r.id : '#spare');\n"
        "        this.good(r.tag);\n"
        "        afterSuccess(this.rot, r.model, r.id, poolSize);\n"
        "        this.log('TTS ok ' + this.lastVoice + ' speaker=' + speaker + ' ms=' + ms);\n"
        "        this.emitUi();\n"
        "        return {data: inl.data, rate, ms};\n"
        "      } catch (e: any) {\n"
        "        if (e instanceof ApiError) {\n"
        "          if (e.status === 401 || (e.status === 400 && /API key/i.test(e.body))) {\n"
        "            this.cooldown[r.tag] = Date.now() + 30 * 60 * 1000;\n"
        "          } else {\n"
        "            this.bench(r.tag, e, true);\n"
        "            if (e.status === 404 || (e.status === 400 && /not found|not supported|unsupported/i.test(e.body))) {\n"
        "              this.globalModelCooldown[r.model] = Date.now() + 30 * 60 * 1000;\n"
        "              skip[r.model] = true;\n"
        "            } else if (e.status !== 429 && e.status !== 403) {\n"
        "              skip[r.model] = true;\n"
        "            }\n"
        "          }\n"
        "        } else {\n"
        "          this.benchFor(r.tag, 45 * 1000, true);\n"
        "          skip[r.model] = true;\n"
        "        }\n"
        "        this.log('voice fallback from ' + r.model + ' (key ' + r.id + '): ' + String(e?.message || e));\n"
        "      }\n"
        "    }\n"
        "    return null;\n"
        "  }"
    )
    text, _ = replace_ts_block(text, r"^[ \t]*private\s+async\s+fetchGeminiAudio\([^)]*\)[^{]*\{", new_fetch_audio)

    # 11. Rewrite play() to NEVER invoke Device TTS and NEVER truncate long responses
    new_play_fn = (
        "  private async play(p: any, id: number) {\n"
        "    const runPlay = async () => {\n"
        "      if (this.run !== id) return;\n"
        "      const spokenText = stripMoodAndCadenceCues(String(p?.text || ''));\n"
        "      if (!spokenText && !p?.audio) return;\n"
        "      this.lastCaption = spokenText;\n"
        "      this.isSpeakingNow = true;\n"
        "      this.emitUi();\n"
        "      try {\n"
        "        if (this.getCaptions() && spokenText) {\n"
        "          toast('📻 ' + spokenText, true);\n"
        "        }\n"
        "        RadioModule?.click?.();\n"
        "        if (p?.audio?.data) {\n"
        "          await RadioModule.playPcm(p.audio.data, p.audio.rate || 24000);\n"
        "        } else {\n"
        "          this.log('skipped playback: no Gemini audio available (Device TTS disabled)');\n"
        "        }\n"
        "      } catch (e: any) {\n"
        "        this.log('play error: ' + String(e?.message || e));\n"
        "      } finally {\n"
        "        this.isSpeakingNow = false;\n"
        "        this.emitUi();\n"
        "      }\n"
        "    };\n"
        "    this.playChain = this.playChain.then(runPlay, runPlay);\n"
        "    await this.playChain;\n"
        "  }"
    )
    text, _ = replace_ts_block(text, r"^[ \t]*private\s+async\s+play\([^)]*\)\s*\{", new_play_fn)

    # 12. Ensure talkNow & crewPress do NOT cut off an ongoing transmission abruptly, and remove Phone voice check
    text = re.sub(
        r"if\s*\(\s*this\.getSpeaker\(\)\s*!==\s*'Phone voice'\s*(?:&&\s*!cmd\.short_ok)?\s*\)\s*\{",
        "if (true) {",
        text,
    )
    text = text.replace(
        "audio ? this.lastVoice : 'phone'",
        "audio ? this.lastVoice : 'none'",
    )
    text = text.replace(
        "  async talkNow() {\n    try {\n      RadioModule?.stopSpeaking?.();\n    } catch (e) {}",
        "  async talkNow() {\n    this.log('talkNow pressed');",
    )
    text = text.replace(
        "      try {\n        RadioModule?.stopSpeaking?.();\n      } catch (e) {}\n      toast('Crew: ' + cmd.label);",
        "      toast('Crew: ' + cmd.label);",
    )

    # 13. Session-start Mood & Cadence directive in systemInstruction ONLY
    text = re.sub(
        r"const persona = PERSONAS\.find[^\n]+\n\s*const system =",
        "const persona = PERSONAS.find(p => p.id === this.getPersonaId()) || PERSONAS[0];\n"
        "    if (!this.sessionStyleHeader) {\n"
        "      this.sessionStyleHeader = buildSessionStyleSystemBlock(persona.prompt, persona.style, this.getMoodCadence());\n"
        "    }\n"
        "    const system =",
        text,
        count=1,
    )
    text = text.replace(
        "persona.prompt +",
        "this.sessionStyleHeader +",
    )
    # Remove any accidental per-turn style reminder inside user prompt
    text = re.sub(
        r"\n[^\n]*(?:persona\.style|MOOD|CADENCE)[^\n]*\+",
        "\n",
        text,
    )

    # Reset sessionStyleHeader on start() and persona change
    text = text.replace(
        "this.startedAt = Date.now();",
        "this.startedAt = Date.now();\n    const _p = PERSONAS.find(x => x.id === this.getPersonaId()) || PERSONAS[0];\n    this.sessionStyleHeader = buildSessionStyleSystemBlock(_p.prompt, _p.style, this.getMoodCadence());\n    this.emitUi();",
        1,
    )
    text = text.replace(
        "this.setPersonaId(id.slice('radio:persona:'.length));",
        "this.setPersonaId(id.slice('radio:persona:'.length));\n        this.sessionStyleHeader = '';",
    )

    # 14. Clean buildPrompt / refreshAvailable to never leak hydrogen
    text = text.replace(
        ".map((m: any) => String(m.name || '').replace(/^models\\//, ''));",
        ".map((m: any) => String(m.name || '').replace(/^models\\//, '')).filter((m: string) => !/hydrogen/i.test(m));",
    )

    # 15. Strip cues inside clean() and produce()
    text = text.replace(
        "return t\n      .replace(/[*_#`~]/g, '')",
        "return stripMoodAndCadenceCues(t)\n      .replace(/[*_#`~]/g, '')",
    )

    # 16. Add Ask Question, Logs, Mood/Cadence settings, SyncExternalKeys, UI Snapshot/Subscribe helpers before statusText()
    extra_methods = """
  // ---------- BUSH_RADIO_FIX_V1: Mood/Cadence, Question Answering, Logs & UI Sync ----------
  getMoodCadence(): string {
    return storage.getString('radio_mood_cadence') || '';
  }
  setMoodCadence(s: string) {
    storage.set('radio_mood_cadence', (s || '').trim());
    this.sessionStyleHeader = '';
    this.emitUi();
  }
  async promptForMoodCadence(showInput: (o: any) => Promise<any>) {
    const r = await showInput({
      title: 'Session Mood & Cadence',
      message: 'Set once at session start so the AI keeps this tone all flight without reading cues out loud.',
      hint: 'e.g. calm late-night radio host, dry humour, unhurried pace',
      text: this.getMoodCadence(),
      maxLength: 240,
      confirmText: 'Save',
      cancelText: 'Cancel',
    });
    if (r?.action === 'confirm') {
      this.setMoodCadence(r.text || '');
      toast('Session mood & cadence saved');
    }
  }
  clearNotebook() {
    this.setNotes('');
    this.history = [];
    this.prevFrame = '';
    said.clear();
    this.emitUi();
  }
  hasAnyKey(): boolean {
    return this.keyPool(BRAIN_KEY_IDS).length > 0;
  }
  keysSetCount(): number {
    let n = 0;
    for (const s of KEY_SLOTS) {
      if (this.getSlotKey(s.id)) n++;
    }
    if (this.getMainKey() && n < KEY_SLOTS.length) n++;
    return Math.min(5, Math.max(n, this.keyPool(BRAIN_KEY_IDS).length));
  }
  async syncExternalKeys() {
    try {
      const arr: string[] = (await RadioModule?.getAtcKeys?.()) || [];
      if (Array.isArray(arr) && arr.length > 0) {
        this.externalKeys = arr.map(x => String(x || '').trim()).filter(Boolean);
        // Auto-populate empty slots 1..5 if discovered from :atc SharedPreferences
        const used: Record<string, boolean> = {};
        for (let i = 1; i <= 5; i++) {
          const k = this.getSlotKey(i);
          if (k) used[k] = true;
        }
        for (const k of this.externalKeys) {
          if (used[k]) continue;
          for (let i = 1; i <= 5; i++) {
            if (!this.getSlotKey(i)) {
              this.setSlotKey(i, k);
              used[k] = true;
              break;
            }
          }
        }
        this.emitUi();
      }
    } catch (e) {}
  }
  getUiSnapshot() {
    const pid = this.getPersonaId();
    const pname = (PERSONAS.find(p => p.id === pid) || PERSONAS[0]).name;
    return {
      on: this.on,
      speaking: this.isSpeakingNow,
      asking: this.isAskingNow,
      lastCaption: this.lastCaption,
      lastModel: this.lastModel,
      lastVoice: this.lastVoice,
      lastError: this.lastError,
      personaId: pid,
      personaName: pname,
      speaker: this.getSpeaker(),
      nerd: this.getNerd(),
      gapMin: this.getGapMin(),
      gapMax: this.getGapMax(),
      captions: this.getCaptions(),
      musicOn: this.getMusicOn(),
      adviceMin: this.getAdviceMin(),
      trip: this.getTrip(),
      aircraft: this.getAircraft(),
      moodCadence: this.getMoodCadence(),
      keysSet: this.keysSetCount(),
    };
  }
  subscribeUi(fn: (s: any) => void): () => void {
    this.uiListeners.add(fn);
    try { fn(this.getUiSnapshot()); } catch (e) {}
    return () => {
      this.uiListeners.delete(fn);
    };
  }
  refreshUi() {
    this.emitUi();
  }
  private emitUi() {
    const snap = this.getUiSnapshot();
    this.uiListeners.forEach(fn => {
      try { fn(snap); } catch (e) {}
    });
  }
  async getLogsText(): Promise<string> {
    let nativeLog = '';
    try {
      nativeLog = (await RadioModule?.getLogs?.()) || '';
    } catch (e) {}
    const mem = this.memLogs.join('\\n');
    return [nativeLog, mem ? '\\n--- Session Buffer ---\\n' + mem : ''].filter(Boolean).join('\\n');
  }
  async clearLogs() {
    this.memLogs = [];
    try { await RadioModule?.clearLogs?.(); } catch (e) {}
    ToastAndroid.show('Bush Radio logs cleared', ToastAndroid.SHORT);
  }
  async shareLogs() {
    try {
      const ok = await RadioModule?.shareLogs?.();
      if (ok) {
        ToastAndroid.show('Logs copied & share sheet opened', ToastAndroid.SHORT);
        return;
      }
    } catch (e) {}
    toast('Logs: ' + this.memLogs.slice(-8).join(' | '), true);
  }
  async askQuestion(questionText: string) {
    const q = String(questionText || '').trim();
    if (!q) return;
    if (this.isAskingNow) {
      toast('Still answering your previous question...');
      return;
    }
    this.isAskingNow = true;
    const id = ++this.run;
    const wasOn = this.on;
    this.emitUi();
    this.log('question asked: ' + q);
    try {
      await this.syncExternalKeys();
      const first = this.getApiKey();
      if (!first) throw new Error('No Gemini API key set');
      await this.refreshAvailable(first);
      const frame: string = await RadioModule.captureFrame(1600, 85);
      const persona = PERSONAS.find(p => p.id === this.getPersonaId()) || PERSONAS[0];
      if (!this.sessionStyleHeader) {
        this.sessionStyleHeader = buildSessionStyleSystemBlock(persona.prompt, persona.style, this.getMoodCadence());
      }
      const system =
        this.sessionStyleHeader +
        '\\nYou are answering a direct question from the pilot mid-flight.' +
        '\\nReply in EXACTLY this format:' +
        '\\nSTATE: <updated concise flight/place notes>' +
        '\\nSAY: <clear, warm, specific spoken answer to the pilot question, 40-120 words, no stage directions, no mood/cadence cues>' +
        '\\nPAUSE: medium';
      const user = buildQuestionUserPrompt({
        question: q,
        trip: this.getTrip(),
        aircraft: this.getAircraft(),
        notes: this.getNotes(),
        brainContext: brain.context(),
      });
      let answerSay = '';
      const skip: Record<string, boolean> = {};
      for (const r of this.brainRoutes()) {
        if (skip[r.model]) continue;
        try {
          const resp = await this.timedFetch(
            API + '/models/' + r.model + ':generateContent',
            {
              method: 'POST',
              headers: {'Content-Type': 'application/json', 'x-goog-api-key': r.key},
              body: JSON.stringify({
                systemInstruction: {parts: [{text: system}]},
                contents: [{role: 'user', parts: [{text: user}, {inline_data: {mime_type: 'image/jpeg', data: frame}}]}],
                generationConfig: {temperature: 0.75, maxOutputTokens: 1536},
              }),
            },
            25000,
          );
          const raw = await resp.text();
          if (!resp.ok) throw new ApiError(resp.status, raw);
          const j: any = JSON.parse(raw);
          const ps: any[] = j?.candidates?.[0]?.content?.parts || [];
          const outText = ps.filter(p => typeof p?.text === 'string' && !p.thought).map(p => p.text).join(' ').trim();
          const parsed: any = this.parse(outText);
          this.lastModel = r.model;
          this.lastKeyId = r.id;
          this.lastError = '';
          this.good(r.tag);
          if (parsed.state) this.setNotes(parsed.state);
          const polished = said.polish(parsed.say || outText, {
            music: true,
            advice: true,
            aircraft: true,
            isAnswer: true,
          }).text;
          answerSay = stripMoodAndCadenceCues(polished);
          if (answerSay) break;
        } catch (e: any) {
          if (e instanceof ApiError) {
            this.bench(r.tag, e);
            if (e.status !== 429 && e.status !== 403) skip[r.model] = true;
          } else {
            this.benchFor(r.tag, 45 * 1000, true);
            skip[r.model] = true;
          }
          this.log('question fallback ' + r.model + ': ' + String(e?.message || e));
        }
      }
      if (!answerSay) throw new Error('Could not generate answer right now');
      const audio = await this.fetchGeminiAudio(answerSay);
      this.log('question answer voice=' + (audio ? this.lastVoice : 'none') + ' said=' + answerSay);
      await this.play({text: answerSay, audio, ms: audio ? audio.ms : 10000}, id);
    } catch (e: any) {
      this.noteError(e);
    } finally {
      this.isAskingNow = false;
      this.emitUi();
      if (wasOn && this.on && this.run === id) {
        this.loop(++this.run);
      }
    }
  }
"""
    text = text.replace(
        "  statusText(): string {",
        extra_methods + "\n  statusText(): string {",
        1,
    )
    text, _ = replace_ts_block(
        text,
        r"^[ \t]*statusText\(\)\s*:\s*string\s*\{",
        "  statusText(): string {\n"
        "    const now = Date.now();\n"
        "    const capped = Object.keys(this.cooldown).filter(m => this.cooldown[m] > now);\n"
        "    return (\n"
        "      (this.on ? 'ON' : 'OFF') +\n"
        "      ' | keys: ' + this.keysSetCount() + '/5' +\n"
        "      ' | brain: ' + (this.lastModel || 'none yet') + (this.lastKeyId ? ' (key ' + this.lastKeyId + ')' : '') +\n"
        "      ' | prep ' + Math.round(this.latencyEma / 1000) + 's | voice: ' + this.getSpeaker() +\n"
        "      (this.lastVoice ? ' (' + this.lastVoice + ')' : '') +\n"
        "      ' | ' + rotationText(this.rot, this.keysSetCount()) +\n"
        "      (capped.length ? ' | capped: ' + capped.join(', ') : '') +\n"
        "      (this.lastError ? ' | last error: ' + this.lastError.slice(0, 140) : '')\n"
        "    );\n"
        "  }",
    )

    # Also update main native menu to include Ask Question, Session Mood & Cadence, and View/Share Logs
    text = text.replace(
        "{id: 'radio:now', title: 'Talk now'},",
        "{id: 'radio:now', title: 'Talk now'},\n          {id: 'radio:ask', title: 'Ask a question (type)'},\n          {id: 'radio:logs', title: 'View / share Bush Radio logs'},",
    )
    text = text.replace(
        "{id: 'radio:captions', title: 'Captions', active: this.getCaptions()},",
        "{id: 'radio:mood', title: 'Mood & cadence (session start)'},\n          {id: 'radio:captions', title: 'Captions', active: this.getCaptions()},",
    )
    text = text.replace(
        "} else if (id === 'radio:now') {",
        "} else if (id === 'radio:ask') {\n"
        "        const r = await showInput({title: 'Ask Bush Radio', message: 'Ask anything about what is on screen or nearby:', hint: 'e.g. any race tracks around?', text: '', maxLength: 200, confirmText: 'Ask', cancelText: 'Cancel'});\n"
        "        if (r?.action === 'confirm' && r.text) { this.askQuestion(r.text); }\n"
        "        return;\n"
        "      } else if (id === 'radio:logs') {\n"
        "        await this.shareLogs();\n"
        "      } else if (id === 'radio:mood') {\n"
        "        await this.promptForMoodCadence(showInput);\n"
        "      } else if (id === 'radio:now') {",
    )

    # Update loop stop() to notify UI subscribers
    text = text.replace(
        "    this.on = false;\n    this.run++;",
        "    this.on = false;\n    this.run++;\n    this.emitUi();",
        1,
    )

    write_text(p, text, crlf)
    log("patched " + p)


def patch_native_portrait_and_stream():
    # 1. Force NativePortraitStreamScreen to run landscape fullscreen cleanly
    np_path = "src/pages/NativePortraitStream.tsx"
    if pathlib.Path(np_path).exists():
        text, crlf = read_text(np_path)
        if MARK not in text:
            text = (
                "// " + MARK + ": Force full-screen landscape underneath Bush Radio UI\n"
                "import React from 'react';\n"
                "import {NativeStreamScreenBase} from './NativeStream';\n\n"
                "function NativePortraitStreamScreen(props: any) {\n"
                "  return <NativeStreamScreenBase {...props} portraitMode={false} />;\n"
                "}\n\n"
                "export default NativePortraitStreamScreen;\n"
            )
            write_text(np_path, text, crlf)
            log("patched " + np_path + " (forced landscape)")

    # 2. Patch Home.tsx & Cloud.tsx if they route to NativePortraitStream
    for page in ("src/pages/Home.tsx", "src/pages/Cloud.tsx"):
        if pathlib.Path(page).exists():
            t, c = read_text(page)
            if "NativePortraitStream" in t and MARK not in t:
                t = "// " + MARK + "\n" + t.replace("'NativePortraitStream'", "'NativeStream'")
                write_text(page, t, c)
                log("patched " + page + " (NativePortraitStream -> NativeStream)")

    # 3. Patch NativeStream.tsx
    p = "src/pages/NativeStream.tsx"
    if not pathlib.Path(p).exists():
        die(p + " not found.")
    text, crlf = read_text(p)
    if MARK in text:
        log("NativeStream.tsx already patched")
        return

    # Imports
    if "BushRadioOverlay" not in text:
        text = text.replace(
            "import radio from '../utils/radio'; // RADIO",
            "import radio from '../utils/radio'; // RADIO\nimport BushRadioOverlay from '../components/BushRadioOverlay'; // " + MARK,
            1,
        )
        if "BushRadioOverlay" not in text:
            text = re.sub(
                r"(import screenshot from '\.\./utils/screenshot';)",
                r"\1\nimport radio from '../utils/radio';\nimport BushRadioOverlay from '../components/BushRadioOverlay'; // " + MARK,
                text,
                count=1,
            )

    # Ensure settings initializes synchronously on mount so quickMenu & overlay show immediately on 1st open
    text = text.replace(
        "const [settings, setSettings] = React.useState<any>({});",
        "const [settings, setSettings] = React.useState<any>(() => getSettings());",
    )

    # Coerce portraitMode prop to false so stream is always full-screen landscape
    text = text.replace(
        "  portraitMode = false,\n}: NativeStreamScreenProps) {",
        "  portraitMode: _ignoredPortraitMode = false,\n}: NativeStreamScreenProps) {\n  const portraitMode = false; // " + MARK,
        1,
    )

    # Lock landscape immediately (0ms) + notify native RadioModule on mount & AppState resume
    text = text.replace(
        "    orientationLockTimer.current = setTimeout(() => {",
        "    try { Orientation.lockToLandscape(); FullScreenManager?.immersiveModeOn?.(); NativeModules.RadioModule?.forceLandscapeFullscreen?.(); NativeModules.RadioModule?.notifyStreamOpened?.(true); } catch (e) {}\n    orientationLockTimer.current = setTimeout(() => {",
        1,
    )
    text = text.replace(
        "    }, 500);",
        "      try { Orientation.lockToLandscape(); NativeModules.RadioModule?.forceLandscapeFullscreen?.(); NativeModules.RadioModule?.notifyStreamOpened?.(true); } catch (e) {}\n    }, 150);",
        1,
    )

    # Ensure unmount notifies stream closed
    text = text.replace(
        "      radio.stop();",
        "      radio.stop();\n      try { NativeModules.RadioModule?.notifyStreamOpened?.(false); } catch (e) {}",
    )

    # Add BushRadioOverlay to rendered tree above the stream player (both portrait fallback and main return)
    if "<BushRadioOverlay" not in text:
        text = text.replace(
            "      {renderMenu()}\n    </View>",
            "      {renderMenu()}\n      {!isInPictureInPicture && (\n        <BushRadioOverlay\n          showOptions={showNativeOptionsDialog}\n          showInput={showNativeInputDialog}\n        />\n      )}\n    </View>",
            1,
        )

    write_text(p, text, crlf)
    log("patched " + p)


def patch_main_activity_java():
    if not pathlib.Path(MAIN_ACTIVITY_JAVA).exists():
        return
    text, crlf = read_text(MAIN_ACTIVITY_JAVA)
    if MARK in text:
        return
    # Ensure window focus & configuration changes re-affirm native overlay z-order if :atc added DecorView overlays
    if "onWindowFocusChanged" not in text:
        target = "  @Override\n  protected void onUserLeaveHint()"
        hook = (
            "  // " + MARK + "\n"
            "  @Override\n"
            "  public void onWindowFocusChanged(boolean hasFocus) {\n"
            "    super.onWindowFocusChanged(hasFocus);\n"
            "    if (hasFocus) {\n"
            "      try {\n"
            "        android.view.ViewGroup dv = (android.view.ViewGroup) getWindow().getDecorView();\n"
            "        for (int i = 0; i < dv.getChildCount(); i++) {\n"
            "          android.view.View ch = dv.getChildAt(i);\n"
            "          String nm = ch.getClass().getName();\n"
            "          Object tg = ch.getTag();\n"
            "          if (nm.contains(\"ComposeView\") || (tg != null && String.valueOf(tg).toLowerCase().contains(\"radio\"))) {\n"
            "            ch.setVisibility(android.view.View.VISIBLE);\n"
            "            ch.bringToFront();\n"
            "          }\n"
            "        }\n"
            "      } catch (Throwable ignored) {}\n"
            "    }\n"
            "  }\n\n" + target
        )
        if target in text:
            text = text.replace(target, hook, 1)
            write_text(MAIN_ACTIVITY_JAVA, text, crlf)
            log("patched " + MAIN_ACTIVITY_JAVA)


# ------------------------------------------------------------------------------
# Part C: Dynamic Post-Merge Scanner for :atc / apply_merge_patch.py Artifacts
# ------------------------------------------------------------------------------

def scan_and_fix_merged_tree():
    """
    Scans all .kt, .java, .ts, .tsx files across src/, android/atc/, atc_src/, android/app/
    created or modified by apply_merge_patch.py, fixing:
      - gemini-4-hydrogen references everywhere
      - Device TextToSpeech / 'Phone voice' inside Bush Radio / Sim Radio code
      - Portrait locks / NativePortraitStream on stream open
      - Mood/cadence prepending into TTS payloads
      - First-open bottom-right overlay visibility/z-order issues
    """
    scan_roots = ["src", "android/app/src", "android/atc", "atc_src"]
    patched_files = []

    for root in scan_roots:
        rp = pathlib.Path(root)
        if not rp.exists():
            continue
        for p in rp.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in (".kt", ".java", ".ts", ".tsx"):
                continue
            # Skip already canonically rewritten files & node_modules
            norm = p.as_posix()
            if "node_modules" in norm or norm.endswith("radioHelpers.ts") or norm.endswith("voiceRotation.ts") or norm.endswith("BushRadioOverlay.tsx") or norm.endswith("RadioModule.java"):
                continue

            try:
                text, crlf = read_text(p)
            except Exception:
                continue

            orig = text
            is_radio_related = bool(re.search(r"bush\s*radio|sim\s*radio|radiomodule|fetchgeminiaudio|voiceroutes", text, re.I))

            # 1. Remove gemini-4-hydrogen anywhere in the merged app
            if "gemini-4-hydrogen" in text:
                text = text.replace('"gemini-4-hydrogen"', '"gemini-flash-latest"')
                text = text.replace("'gemini-4-hydrogen'", "'gemini-flash-latest'")
                text = text.replace("gemini-4-hydrogen", "gemini-flash-latest")

            # Remove any explicit hydrogen priority filter in model selectors
            if "hydrogen" in text.lower() and (is_radio_related or "MODEL_CHAIN" in text or "TTS_CHAIN" in text or ":generateContent" in text):
                text = re.sub(
                    r"(?:if\s*\([^)]*hydrogen[^)]*\)\s*\{[^}]*return\s+-1;?\s*\})",
                    "if (/hydrogen/i.test(m)) { return 999; }",
                    text,
                )
                text = text.replace(
                    'if (it.contains("hydrogen", ignoreCase = true))',
                    'if (false && it.contains("hydrogen", ignoreCase = true))',
                )

            # 2. Remove Phone voice / Device TextToSpeech fallback in Bush Radio files
            if is_radio_related or norm.endswith("crew.ts"):
                if "Phone voice" in text:
                    text = text.replace("'Phone voice'", "'Charon'").replace('"Phone voice"', '"Charon"')
                # Disable Kotlin/Java TextToSpeech fallback inside Bush Radio / Sim Radio files cleanly
                if p.suffix == ".kt" and "TextToSpeech" in text:
                    text = re.sub(
                        r"\b\w+(?:\s*\?)?\.speak\s*\([^;\n{}]+\)",
                        "run { /* " + MARK + ": device TTS removed */ 0 }",
                        text,
                    )
                elif p.suffix == ".java" and "TextToSpeech" in text:
                    text = re.sub(
                        r"\b\w+\.speak\s*\([^;{}]+\)",
                        "0 /* " + MARK + ": device TTS removed */",
                        text,
                    )

            # 3. Force Landscape Fullscreen when 'Open Stream' / stream view runs in merged code
            if "open stream" in text.lower() or "openstream" in text.lower() or "startstream" in text.lower():
                if "SCREEN_ORIENTATION_PORTRAIT" in text or "SCREEN_ORIENTATION_USER_PORTRAIT" in text:
                    text = text.replace("SCREEN_ORIENTATION_PORTRAIT", "SCREEN_ORIENTATION_SENSOR_LANDSCAPE")
                    text = text.replace("SCREEN_ORIENTATION_USER_PORTRAIT", "SCREEN_ORIENTATION_SENSOR_LANDSCAPE")
                if "lockToPortrait()" in text:
                    text = text.replace("lockToPortrait()", "lockToLandscape()")
                if "'NativePortraitStream'" in text or '"NativePortraitStream"' in text:
                    text = text.replace("'NativePortraitStream'", "'NativeStream'").replace('"NativePortraitStream"', '"NativeStream"')

            # 4. Prevent merged Kotlin/Compose code from prepending mood/cadence text directly to Gemini TTS speech text
            if is_radio_related and p.suffix == ".kt":
                # If a TTS call concatenates mood/cadence/style before the spoken text, neutralize concatenation
                text = re.sub(
                    r'\b(val|var)\s+(\w*(?:ttsPrompt|speechInput|ttsText|voiceText|spokenText)\w*)\s*=\s*"[^"]*\$\{?(?:mood|cadence|style|delivery)[^"]*"\s*\+\s*',
                    r'\1 \2 = /* ' + MARK + ': cues stay in systemInstruction */ ',
                    text,
                    flags=re.I,
                )

            # 5. Ensure any :atc Kotlin DecorView / ComposeView overlay triggered by stream state doesn't skip first open
            if p.suffix == ".kt" and ("DecorView" in text or "window.decorView" in text) and ("radio" in text.lower() or "overlay" in text.lower()):
                if "registerReceiver" not in text and "ACTION_STREAM_STATE" not in text and "onActivityResumed" in text:
                    # Ensure attaching brings view to front & sets high elevation (idempotent)
                    text = re.sub(
                        r"(decor(?:View)?\.addView\(([^,)]+)[^)]*\))(?!.*bringToFront)",
                        r"\1; try { \2.bringToFront(); \2.elevation = 100f } catch (_: Throwable) {}",
                        text,
                    )

            if text != orig:
                write_text(p, text, crlf)
                patched_files.append(norm)

    if patched_files:
        log("dynamic scanner updated " + str(len(patched_files)) + " files: " + ", ".join(patched_files))
    else:
        log("dynamic scanner completed (no extra merge patterns needed adjustment)")


# ------------------------------------------------------------------------------
# Main Entrypoint
# ------------------------------------------------------------------------------

def main():
    if not pathlib.Path("package.json").exists():
        die("Run this script from the repository root (package.json not found).")

    write_text("src/utils/radioHelpers.ts", RADIO_HELPERS_TS)
    log("wrote src/utils/radioHelpers.ts")

    write_text("src/utils/voiceRotation.ts", VOICE_ROTATION_TS)
    log("wrote src/utils/voiceRotation.ts")

    write_text("src/components/BushRadioOverlay.tsx", BUSH_RADIO_OVERLAY_TSX)
    log("wrote src/components/BushRadioOverlay.tsx")

    patch_radio_module_java()
    patch_said_ts()
    patch_radio_ts()
    patch_native_portrait_and_stream()
    patch_main_activity_java()
    scan_and_fix_merged_tree()

    log("BUSH RADIO FIX COMPLETE")


if __name__ == "__main__":
    main()
