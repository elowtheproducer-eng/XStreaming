#!/usr/bin/env python3
"""
apply_headtrack_patch.py  -  XStreaming camera head-tracking (spec v5, Tier 1 + core Tier 2)

Run from the REPO ROOT, AFTER .github/apply_tilt_patch.py:
    python3 .github/apply_headtrack_patch.py

What it does
  1. writes 7 new Java classes into android/app/src/main/java/com/xstreaming/
  2. patches SensorModule.java (new @ReactMethods, recenter/stopSensor hooks, sendEvent made public)
  3. patches sensor.ts + settingStore.ts (3rd sensor mode "Head tracking" + settings)
  4. patches NativeStream.tsx (start head tracking, menu items)
  5. patches AndroidManifest.xml, android/app/build.gradle, proguard-rules.pro (CAMERA, CameraX, MediaPipe, R8 keep)
  6. makes sure minSdk >= 24 and compileSdk >= 34 (CameraX 1.3.x / MediaPipe need that)

Safe to re-run: every patched file gets a HEADTRACK marker and is skipped the second time.
If an anchor can't be found the script STOPS and prints the surrounding lines so you can paste
that output back to the model.  Nothing is half-written: each file is written only after all of
its edits succeeded.
"""
import pathlib
import re
import sys

JAVA_DIR = "android/app/src/main/java/com/xstreaming"
MARK = "HEADTRACK"

# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------

def die(msg, path=None, text=None, keywords=()):
    print("\n==================== HEADTRACK PATCH FAILED ====================")
    print(msg)
    if path:
        print("File:", path)
    if text is not None and keywords:
        lines = text.split("\n")
        shown = 0
        print("\nLines in that file that mention the things I was looking for:")
        for i, ln in enumerate(lines):
            if any(k in ln for k in keywords):
                print("  %5d | %s" % (i + 1, ln.rstrip()[:160]))
                shown += 1
                if shown >= 40:
                    print("  ... (truncated)")
                    break
        if shown == 0:
            print("  (none found)")
    print("\nPaste this whole log back to the model so it can adjust the anchor.")
    print("================================================================")
    sys.exit(1)


ORIG = {}  # path -> original text, so failure diagnostics show the file as it really is


def read(path_str):
    p = pathlib.Path(path_str)
    if not p.exists():
        die("Missing file (is the tilt patch applied / are you in the repo root?): " + path_str)
    raw = p.read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n")
    ORIG[path_str] = text
    return text, ("\r\n" in raw)


def write(path_str, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    pathlib.Path(path_str).write_bytes(text.encode("utf-8"))


def one(text, pattern, path, what, keywords=(), flags=0):
    """Return the single regex match or die."""
    ms = list(re.finditer(pattern, text, flags))
    if len(ms) != 1:
        die("Expected exactly 1 match for [%s] but found %d." % (what, len(ms)), path, ORIG.get(path, text), keywords)
    return ms[0]


def splice(text, start, end, new):
    return text[:start] + new + text[end:]


def new_file(path_str, content):
    p = pathlib.Path(path_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
    print("  created", path_str)


# ----------------------------------------------------------------------------------------------
# 1. new Java sources
# ----------------------------------------------------------------------------------------------
JAVA = {}
JAVA['HeadConfig'] = r'''package com.xstreaming;

import com.facebook.react.bridge.ReadableMap;
import com.facebook.react.bridge.ReadableType;

/**
 * Head-tracking config. JS passes the settings-store values WITHOUT the "head_" prefix and in raw slider units;
 * unit conversion happens here so JS needs no maths. Keys that are absent keep their current value
 * (so updateHeadTrack({flick_gain: 25}) changes only that one thing).
 */
public final class HeadConfig {
    public int camera = 0;               // 0 front, 1 rear
    public int output_mode = 0;          // 0 Hold (absolute), 1 Flick (virtual mouse)
    public int flick_preset = 1;         // 0 Precise, 1 Balanced, 2 Snappy, 3 Spin
    public double flick_gain = 0.020;    // raw/1000. Scales the preset gain (20 = preset as is)
    public int flick_glide = 4;          // 1..10 -> payout tau 0.04..0.15 s (4 ~ 0.07). Scales preset tau
    public double flick_deadzone = 14.0; // vLo, deg/s
    public double flick_accel = 0.30;    // raw/100. Scales preset accel (30 = preset as is)
    public double flick_band = 2.5;      // raw/2, degrees
    public boolean flick_pitch = true;
    public boolean auto_zoom = true;
    public boolean sync_infer = true;
    public boolean raw_landmarks = false;
    public double yaw_range = 35.0;      // deg for full X (both sides)
    public double pitch_up_range = 18.0;
    public double pitch_down_range = 22.0;
    public double deadzone_x = 1.5;      // raw/2, degrees
    public double deadzone_y = 2.0;      // raw/2, degrees
    public double expo_x = 1.4;          // raw/10
    public double expo_y = 1.2;          // raw/10
    public int smoothing = 5;            // 0..10, Hold only
    public double prediction_ms = 15.0;  // extra look-ahead on top of pipeline compensation
    public double game_deadzone = 0.08;  // raw/100
    public boolean invert_x = false;
    public boolean invert_y = false;
    public int cam_rotation = -1;        // -1 none, else extra rotation 0/90/180/270
    public int fps = 0;                  // 0 Auto, 30, 60
    public int resolution = 0;           // 0: 640x480, 1: 1280x720
    public boolean haptics = true;
    public double outer_cap = 0.95;      // raw/100
    public boolean neutral_creep = true;
    public int delegate = 0;             // 0 Auto(GPU->CPU fallback), 1 GPU, 2 CPU
    public boolean multi_face = false;
    public boolean diag_overlay = false;

    public HeadConfig copy() {
        HeadConfig c = new HeadConfig();
        c.camera = camera; c.output_mode = output_mode; c.flick_preset = flick_preset; c.flick_gain = flick_gain;
        c.flick_glide = flick_glide; c.flick_deadzone = flick_deadzone; c.flick_accel = flick_accel;
        c.flick_band = flick_band; c.flick_pitch = flick_pitch; c.auto_zoom = auto_zoom; c.sync_infer = sync_infer;
        c.raw_landmarks = raw_landmarks; c.yaw_range = yaw_range; c.pitch_up_range = pitch_up_range;
        c.pitch_down_range = pitch_down_range; c.deadzone_x = deadzone_x; c.deadzone_y = deadzone_y;
        c.expo_x = expo_x; c.expo_y = expo_y; c.smoothing = smoothing; c.prediction_ms = prediction_ms;
        c.game_deadzone = game_deadzone; c.invert_x = invert_x; c.invert_y = invert_y;
        c.cam_rotation = cam_rotation; c.fps = fps; c.resolution = resolution; c.haptics = haptics;
        c.outer_cap = outer_cap; c.neutral_creep = neutral_creep; c.delegate = delegate;
        c.multi_face = multi_face; c.diag_overlay = diag_overlay;
        return c;
    }

    /** Returns a new config = this + whatever keys are present in the map. */
    public HeadConfig merged(ReadableMap m) {
        HeadConfig c = copy();
        if (m == null) return c;
        c.camera = (int) num(m, "camera", c.camera);
        c.output_mode = (int) num(m, "output_mode", c.output_mode);
        c.flick_preset = (int) clampD(num(m, "flick_preset", c.flick_preset), 0, 3);
        c.flick_gain = num(m, "flick_gain", c.flick_gain * 1000.0) / 1000.0;
        c.flick_glide = (int) clampD(num(m, "flick_glide", c.flick_glide), 1, 10);
        c.flick_deadzone = num(m, "flick_deadzone", c.flick_deadzone);
        c.flick_accel = num(m, "flick_accel", c.flick_accel * 100.0) / 100.0;
        c.flick_band = num(m, "flick_band", c.flick_band * 2.0) / 2.0;
        c.flick_pitch = num(m, "flick_pitch", c.flick_pitch ? 1 : 0) != 0;
        c.auto_zoom = num(m, "auto_zoom", c.auto_zoom ? 1 : 0) != 0;
        c.sync_infer = num(m, "sync_infer", c.sync_infer ? 1 : 0) != 0;
        c.raw_landmarks = num(m, "raw_landmarks", c.raw_landmarks ? 1 : 0) != 0;
        c.yaw_range = num(m, "yaw_range", c.yaw_range);
        c.pitch_up_range = num(m, "pitch_up_range", c.pitch_up_range);
        c.pitch_down_range = num(m, "pitch_down_range", c.pitch_down_range);
        c.deadzone_x = num(m, "deadzone_x", c.deadzone_x * 2.0) / 2.0;
        c.deadzone_y = num(m, "deadzone_y", c.deadzone_y * 2.0) / 2.0;
        c.expo_x = num(m, "expo_x", c.expo_x * 10.0) / 10.0;
        c.expo_y = num(m, "expo_y", c.expo_y * 10.0) / 10.0;
        c.smoothing = (int) clampD(num(m, "smoothing", c.smoothing), 0, 10);
        c.prediction_ms = num(m, "prediction_ms", c.prediction_ms);
        c.game_deadzone = num(m, "game_deadzone", c.game_deadzone * 100.0) / 100.0;
        c.invert_x = num(m, "invert_x", c.invert_x ? 1 : 0) != 0;
        c.invert_y = num(m, "invert_y", c.invert_y ? 1 : 0) != 0;
        c.cam_rotation = (int) num(m, "cam_rotation", c.cam_rotation);
        c.fps = (int) num(m, "fps", c.fps);
        c.resolution = (int) num(m, "resolution", c.resolution);
        c.haptics = num(m, "haptics", c.haptics ? 1 : 0) != 0;
        c.outer_cap = num(m, "outer_cap", c.outer_cap * 100.0) / 100.0;
        c.neutral_creep = num(m, "neutral_creep", c.neutral_creep ? 1 : 0) != 0;
        c.delegate = (int) num(m, "delegate", c.delegate);
        c.multi_face = num(m, "multi_face", c.multi_face ? 1 : 0) != 0;
        c.diag_overlay = num(m, "diag_overlay", c.diag_overlay ? 1 : 0) != 0;
        // sanity clamps so a bad slider can never produce NaN / divide-by-zero downstream
        c.yaw_range = clampD(c.yaw_range, 10, 90);
        c.pitch_up_range = clampD(c.pitch_up_range, 5, 60);
        c.pitch_down_range = clampD(c.pitch_down_range, 5, 60);
        c.outer_cap = clampD(c.outer_cap, 0.5, 1.0);
        c.game_deadzone = clampD(c.game_deadzone, 0.0, 0.4);
        c.expo_x = clampD(c.expo_x, 0.5, 4.0);
        c.expo_y = clampD(c.expo_y, 0.5, 4.0);
        return c;
    }

    public static HeadConfig fromMap(ReadableMap m) { return new HeadConfig().merged(m); }

    private static double clampD(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

    /** Reads a number whether JS sent a number, a boolean or a numeric string. */
    private static double num(ReadableMap m, String key, double def) {
        try {
            if (!m.hasKey(key) || m.isNull(key)) return def;
            ReadableType t = m.getType(key);
            if (t == ReadableType.Number) return m.getDouble(key);
            if (t == ReadableType.Boolean) return m.getBoolean(key) ? 1.0 : 0.0;
            if (t == ReadableType.String) return Double.parseDouble(m.getString(key));
        } catch (Exception ignored) {}
        return def;
    }
}
'''

JAVA['HeadFilters'] = r'''package com.xstreaming;

/** Pure math (no Android imports). Filters for head tracking. */
public final class HeadFilters {
    private HeadFilters() {}

    public static double clamp(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

    public static double smoothstep(double e0, double e1, double x) {
        double t = clamp((x - e0) / (e1 - e0), 0.0, 1.0);
        return t * t * (3.0 - 2.0 * t);
    }

    /** Constant-velocity Kalman with discrete white-noise-acceleration Q, adaptive agility and Huber update. */
    public static final class Kalman1D {
        public double x, v, p00 = 100, p01 = 0, p11 = 100, sa = 350;
        public boolean init = false;
        public long maneuverUntilNs = 0;

        public void reset(double z, double r) {
            x = z; v = 0; p00 = r; p01 = 0; p11 = 400; init = true; maneuverUntilNs = 0;
        }

        /** saRest/saMove: acceleration std (deg/s^2) at rest / in motion. Lower saRest = smoother at rest. */
        public void predict(double dt, double saRest, double saMove, long nowNs) {
            dt = clamp(dt, 0.001, 0.1);
            double f = smoothstep(10.0, 60.0, Math.abs(v));
            sa = saRest + (saMove - saRest) * f;
            if (nowNs < maneuverUntilNs) sa *= 2.0;
            x += v * dt;
            double s2 = sa * sa, dt2 = dt * dt, dt3 = dt2 * dt, dt4 = dt2 * dt2;
            double n00 = p00 + dt * (2 * p01 + dt * p11) + s2 * dt4 / 4.0;
            double n01 = p01 + dt * p11 + s2 * dt3 / 2.0;
            double n11 = p11 + s2 * dt2;
            p00 = n00; p01 = n01; p11 = n11;
        }

        public void update(double z, double r, long nowNs) {
            double y = z - x;
            double s = p00 + r;
            double nis = (y * y) / Math.max(1e-9, s);
            if (nis > 9.0) maneuverUntilNs = nowNs + 150_000_000L;
            double rEff = (nis <= 4.0) ? r : r * nis / 4.0;   // Huber-like: huge outliers get ~0 influence
            double sEff = p00 + rEff;
            double k0 = p00 / sEff, k1 = p01 / sEff;
            x += k0 * y; v += k1 * y;
            double n00 = (1 - k0) * p00, n01 = (1 - k0) * p01, n11 = p11 - k1 * p01;
            p00 = n00; p01 = n01; p11 = n11;
        }
    }

    public static final class OneEuro {
        public double minCut = 1.2, beta = 4.0, dCut = 1.0;
        private double xp, dxp;
        private boolean init;
        public void reset() { init = false; xp = 0; dxp = 0; }
        private static double alpha(double fc, double dt) {
            double tau = 1.0 / (2.0 * Math.PI * fc);
            return 1.0 / (1.0 + tau / Math.max(1e-5, dt));
        }
        public double filter(double x, double dt) {
            if (dt <= 0) return x;
            if (!init) { init = true; xp = x; dxp = 0; return x; }
            double dx = (x - xp) / dt, ad = alpha(dCut, dt);
            dxp = ad * dx + (1 - ad) * dxp;
            double af = alpha(minCut + beta * Math.abs(dxp), dt);
            xp = af * x + (1 - af) * xp;
            return xp;
        }
    }

    /** Freezes the angle when the head is still; releases instantly on real motion. */
    public static final class StillnessGate {
        private boolean engaged;
        private double hold;
        private long stillSince;
        public void reset() { engaged = false; hold = 0; stillSince = 0; }
        public double filter(double theta, double omega, long nowNs) {
            double speed = Math.abs(omega);
            if (engaged) {
                if (Math.abs(theta - hold) > 1.2 || speed > 10.0) { engaged = false; stillSince = 0; return theta; }
                return hold;
            }
            if (speed < 3.0 && Math.abs(theta - hold) < 0.8) {
                if (stillSince == 0) stillSince = nowNs;
                else if (nowNs - stillSince > 150_000_000L) { engaged = true; hold = theta; return hold; }
            } else {
                stillSince = 0;
                hold = theta;   // keep the reference near the current angle so "moved < 0.8 deg" is meaningful
            }
            return theta;
        }
    }

    /** Spike catcher in stick space. maxRate in stick units per second. */
    public static final class SlewLimiter {
        private double last; private boolean init; private final double maxRate;
        public SlewLimiter(double maxRatePerSec) { maxRate = maxRatePerSec; }
        public void reset() { init = false; last = 0; }
        public double filter(double target, double dt) {
            if (!init) { init = true; last = target; return target; }
            if (dt <= 0) return last;
            double m = maxRate * dt;
            last += clamp(target - last, -m, m);
            return last;
        }
    }
}
'''

JAVA['HeadPoseMath'] = r'''package com.xstreaming;

/** Pure math (no Android imports): MediaPipe 4x4 matrix -> neutral-relative yaw/pitch/roll. */
public final class HeadPoseMath {
    private HeadPoseMath() {}

    public static double clamp(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }

    /** Reads the 3x3 rotation out of a 16-float matrix, auto-detecting row- vs column-major, then orthonormalises. */
    public static double[][] extractRotation(float[] m) {
        // Translation lives in (3,7,11) for row-major, (12,13,14) for column-major.
        double rowT = Math.abs(m[3]) + Math.abs(m[7]) + Math.abs(m[11]);
        double colT = Math.abs(m[12]) + Math.abs(m[13]) + Math.abs(m[14]);
        boolean col = colT > rowT;
        double[][] r = new double[3][3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                r[i][j] = col ? m[j * 4 + i] : m[i * 4 + j];
        return orthonormalize(r);
    }

    public static double[][] orthonormalize(double[][] m) {
        double[] c0 = {m[0][0], m[1][0], m[2][0]};
        double[] c1 = {m[0][1], m[1][1], m[2][1]};
        c0 = normalize(c0);
        double d = dot(c0, c1);
        c1 = new double[]{c1[0] - d * c0[0], c1[1] - d * c0[1], c1[2] - d * c0[2]};
        c1 = normalize(c1);
        double[] c2 = cross(c0, c1);               // right-handed, det = +1
        return new double[][]{
            {c0[0], c1[0], c2[0]},
            {c0[1], c1[1], c2[1]},
            {c0[2], c1[2], c2[2]}};
    }

    public static double[] normalize(double[] v) {
        double n = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
        if (n < 1e-12) return new double[]{1, 0, 0};
        return new double[]{v[0] / n, v[1] / n, v[2] / n};
    }
    public static double dot(double[] a, double[] b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
    public static double[] cross(double[] a, double[] b) {
        return new double[]{a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
    }
    public static double[][] transpose(double[][] m) {
        double[][] o = new double[3][3];
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) o[i][j] = m[j][i];
        return o;
    }
    public static double[][] multiply(double[][] a, double[][] b) {
        double[][] o = new double[3][3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                o[i][j] = a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j];
        return o;
    }
    public static double[][] identity() { return new double[][]{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}; }

    /** Element-wise mean of n rotations, re-orthonormalised (fine for the small spread seen at rest). */
    public static double[][] meanRotation(double[][][] ring, int n) {
        double[][] s = new double[3][3];
        for (int k = 0; k < n; k++)
            for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) s[i][j] += ring[k][i][j];
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) s[i][j] /= Math.max(1, n);
        return orthonormalize(s);
    }

    /**
     * P = Rn^T * R (head rotation about its own neutral axes), P' = B^T P B, then YXZ decomposition.
     * yaw/pitch are independent of roll by construction. Returns degrees {yaw, pitch, roll}.
     * Convention (before invert flags): yaw>0 right, pitch>0 up, roll>0 right ear to shoulder.
     */
    public static double[] decompose(double[][] r, double[][] rn, double[][] b, double[] out) {
        double[][] p = multiply(transpose(rn), r);
        double[][] pp = multiply(multiply(transpose(b), p), b);
        double yaw = Math.toDegrees(Math.atan2(pp[0][2], pp[2][2]));
        double pitch = -Math.toDegrees(Math.asin(clamp(pp[1][2], -1.0, 1.0)));
        double roll = Math.toDegrees(Math.atan2(pp[1][0], pp[1][1]));
        out[0] = yaw; out[1] = pitch; out[2] = roll;
        return out;
    }
}
'''

JAVA['HeadMapper'] = r'''package com.xstreaming;

/** Pure math: head angle (deg, neutral-relative) -> stick value in [-1, 1] for Hold mode. */
public final class HeadMapper {
    private HeadMapper() {}

    /**
     * rangePos/rangeNeg: degrees for full stick on the + / - side. dz: deadzone (deg).
     * expo: >1 = finer control near centre. gameDz: the game's own inner deadzone (0..0.3) that we skip over.
     */
    public static double shape(double theta, double rangePos, double rangeNeg,
                               double dz, double expo, double gameDz, boolean wasActive) {
        double r = theta >= 0 ? rangePos : rangeNeg;
        double a = Math.abs(theta);
        double thr = wasActive ? dz * 0.7 : dz;      // hysteresis so the edge doesn't flicker
        if (a <= thr) return 0.0;
        double span = Math.max(0.1, 0.97 * r - dz);  // reach full stick at 97% of range
        double v = Math.max(0.0, Math.min(1.0, (a - dz) / span));
        v = Math.pow(v, expo);
        double out = gameDz + (1.0 - gameDz) * v;
        return Math.copySign(out, theta);
    }
}
'''

JAVA['HeadFlick'] = r'''package com.xstreaming;

/** Pure math: Flick ("virtual mouse") = outward-only ratchet + debt payout (spec 10.4) + neutral creep (10.2b). */
public final class HeadFlick {
    private HeadFlick() {}

    // Presets: Precise, Balanced, Snappy, Spin (X-axis gain in stick-seconds per head degree, payout tau, accel)
    public static final double[] PRESET_GAIN  = {0.012, 0.020, 0.030, 0.045};
    public static final double[] PRESET_TAU   = {0.05, 0.07, 0.06, 0.10};
    public static final double[] PRESET_ACCEL = {0.15, 0.30, 0.40, 0.30};

    public static final class FlickCfg {
        public double gain = 0.020;      // stick-s per head degree. Up = turns more per head degree.
        public double tauPay = 0.07;     // payout smoothing (s). Up = floatier, down = snappier.
        public double uMax = 0.95;       // stick cap
        public double Smax = 0.90;       // cap on stored glide (stick-seconds)
        public double band = 2.5;        // neutral band (deg). Up = more forgiving return overshoot.
        public double hOut = 1.6;        // zig-zag hysteresis, outward->return turning point (deg)
        public double hUp = 2.5;         // zig-zag hysteresis, return->outward (deg)
        public double vLo = 14.0;        // motion gate low (deg/s). Up = less creep at rest.
        public double vHi = 45.0;        // motion gate high (deg/s)
        public double vSign = 8.0;       // outward-velocity sign gate (deg/s)
        public double tauPend = 0.12;    // pending-credit leak (s)
        public double accel = 0.30;      // speed-dependent gain +-accel (0 = pure distance)
        public double accLo = 40.0, accHi = 300.0;
        public double uCut = 0.01;       // below this output is exactly 0
        public double gameDz = 0.08;     // game inner-deadzone compensation
    }

    public static final class FlickAxis {
        private static final int IDLE = 0, OUT = 1, RET = 2;
        private final int[] mode = {IDLE, IDLE};
        private final double[] peak = new double[2], trough = new double[2];
        public double pend = 0.0, S = 0.0;
        private double off = 0.0, restT = 0.0;

        /** Full reset (recenter / mode switch): also clears neutral creep. */
        public void reset() { softReset(); off = 0.0; restT = 0.0; }

        /** Reacquire / pause release: forget strokes and debt, keep the learned creep offset. */
        public void softReset() {
            mode[0] = mode[1] = IDLE;
            peak[0] = peak[1] = trough[0] = trough[1] = 0.0;
            pend = 0.0; S = 0.0;
        }

        /** Face lost: bleed off the stored turn (no holding: holding a rate spins the camera). */
        public void bleed(double factor) { S *= factor; pend = 0.0; mode[0] = mode[1] = IDLE; }

        public int modeState() { return mode[0] == OUT ? 1 : mode[1] == OUT ? -1 : (mode[0] == RET || mode[1] == RET) ? 2 : 0; }

        public double step(double thetaRaw, double omega, double dt, FlickCfg c, boolean creep) {
            if (dt <= 0) return 0.0;
            double speed = Math.abs(omega);

            if (creep) {
                double rel0 = thetaRaw - off;
                if (Math.abs(rel0) < 12.0 && speed < 8.0) {
                    restT += dt;
                    if (restT > 1.5) off += rel0 * (1.0 - Math.exp(-dt / 6.0));   // tau_home = 6 s, only at rest
                } else restT = 0.0;
            } else { off = 0.0; restT = 0.0; }
            double theta = thetaRaw - off;

            double credit = 0.0;
            for (int s = 0; s < 2; s++) {
                int k = (s == 0) ? +1 : -1;
                double x = k * theta;
                if (x <= c.band) { mode[s] = IDLE; peak[s] = trough[s] = c.band; continue; }
                boolean vout = (k * omega) > c.vSign;
                switch (mode[s]) {
                    case IDLE:
                        if (vout) { credit += k * (x - c.band); mode[s] = OUT; peak[s] = x; }
                        break;
                    case OUT:
                        if (x > peak[s]) { if (vout) credit += k * (x - peak[s]); peak[s] = x; }
                        else if (x < peak[s] - c.hOut) { mode[s] = RET; trough[s] = x; }
                        break;
                    default: // RET
                        if (x < trough[s]) trough[s] = x;
                        else if (x > trough[s] + c.hUp && vout) { credit += k * (x - trough[s]); mode[s] = OUT; peak[s] = x; }
                        break;
                }
            }

            pend = pend * Math.exp(-dt / c.tauPend) + credit;
            double g = HeadFilters.smoothstep(c.vLo, c.vHi, speed);
            double rel = pend * g; pend -= rel;
            double acc = 1.0 + c.accel * (2.0 * HeadFilters.smoothstep(c.accLo, c.accHi, speed) - 1.0);
            S = HeadFilters.clamp(S + c.gain * acc * rel, -c.Smax, c.Smax);
            double u = HeadFilters.clamp(S / Math.max(0.01, c.tauPay), -c.uMax, c.uMax);
            S -= u * dt;
            if (Math.abs(u) < c.uCut) return 0.0;
            return Math.copySign(c.gameDz + (1.0 - c.gameDz) * Math.abs(u), u);
        }
    }
}
'''

JAVA['HeadCamera'] = r'''package com.xstreaming;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Bitmap;
import android.hardware.camera2.CaptureRequest;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.util.Range;
import android.util.Size;
import android.view.Surface;
import android.view.WindowManager;

import androidx.annotation.NonNull;
import androidx.camera.camera2.interop.Camera2Interop;
import androidx.camera.camera2.interop.ExperimentalCamera2Interop;
import androidx.camera.core.Camera;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.ZoomState;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.LifecycleRegistry;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.mediapipe.framework.image.BitmapImageBuilder;
import com.google.mediapipe.framework.image.MPImage;
import com.google.mediapipe.tasks.core.BaseOptions;
import com.google.mediapipe.tasks.core.Delegate;
import com.google.mediapipe.tasks.vision.core.ImageProcessingOptions;
import com.google.mediapipe.tasks.vision.core.RunningMode;
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker;
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarkerResult;

import java.nio.ByteBuffer;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * CameraX ImageAnalysis (no preview) -> MediaPipe FaceLandmarker -> HeadTracker.onFaceResult().
 * All CameraX lifecycle calls are posted to the main thread (CameraX / LifecycleRegistry require it),
 * because React Native calls us from its native-modules thread.
 */
@androidx.annotation.OptIn(markerClass = ExperimentalCamera2Interop.class)
public final class HeadCamera implements LifecycleOwner {
    private static final String TAG = "HeadCamera";
    private static final String MODEL_ASSET = "face_landmarker.task";
    private static final long ASSUMED_EXPOSURE_NS = 20_000_000L;   // exposure+readout before the analyzer sees a frame
    private static final float TARGET_FACE_PX = 170f;              // adaptive zoom target (spec 5c-a)

    private final Context context;
    private final HeadTracker tracker;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final LifecycleRegistry lifecycle = new LifecycleRegistry(this);

    private volatile HeadConfig config;
    private volatile boolean running = false;
    private ExecutorService executor;
    private ProcessCameraProvider provider;
    private volatile Camera camera;
    private volatile FaceLandmarker landmarker;
    private volatile String delegateName = "?";
    private int activeCamera;
    private int bindRetries = 0;

    // analysis-thread state
    private Bitmap[] bitmaps = new Bitmap[2];
    private int bmpIdx = 0;
    private ByteBuffer repack;
    private long lastTsMs = 0;
    private int errorStreak = 0;
    private boolean forcedCpu = false;
    private ImageProcessingOptions ipo;
    private int ipoRot = -1;

    // zoom
    private float zoom = 1.0f;
    private long lastZoomCheckMs = 0;

    public HeadCamera(Context context, HeadTracker tracker, HeadConfig config) {
        this.context = context.getApplicationContext();
        this.tracker = tracker;
        this.config = config;
        this.activeCamera = config.camera;
    }

    @NonNull @Override public Lifecycle getLifecycle() { return lifecycle; }
    public String getDelegateName() { return delegateName; }
    public float getZoom() { return zoom; }
    public void updateConfig(HeadConfig c) { this.config = c; }

    // ------------------------------------------------------------------ lifecycle

    public void start() {
        running = true;
        executor = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "HeadCamAnalysis");
            t.setPriority(Thread.MAX_PRIORITY);
            return t;
        });
        try {
            createLandmarker(config.delegate == 2);
        } catch (Throwable t) {
            Log.e(TAG, "Landmarker creation failed", t);
            tracker.onCameraError("Face model failed to load: " + t.getMessage());
            return;
        }
        main.post(() -> {
            if (!running) return;
            lifecycle.setCurrentState(Lifecycle.State.CREATED);
            lifecycle.setCurrentState(Lifecycle.State.STARTED);
            lifecycle.setCurrentState(Lifecycle.State.RESUMED);
            ListenableFuture<ProcessCameraProvider> f = ProcessCameraProvider.getInstance(context);
            f.addListener(() -> {
                try {
                    provider = f.get();
                    bind();
                } catch (Exception e) {
                    Log.e(TAG, "Camera provider failed", e);
                    tracker.onCameraError("Camera provider failed: " + e.getMessage());
                }
            }, ContextCompat.getMainExecutor(context));
        });
    }

    public void stop() {
        running = false;
        main.post(() -> {
            try { if (provider != null) provider.unbindAll(); } catch (Throwable ignored) {}
            try { lifecycle.setCurrentState(Lifecycle.State.DESTROYED); } catch (Throwable ignored) {}
            camera = null;
            final ExecutorService ex = executor;
            if (ex != null) {
                // close the landmarker on the analysis thread, after any frame still in flight
                try {
                    ex.execute(() -> {
                        FaceLandmarker lm = landmarker; landmarker = null;
                        if (lm != null) { try { lm.close(); } catch (Throwable ignored) {} }
                        for (int i = 0; i < bitmaps.length; i++) {
                            if (bitmaps[i] != null) { bitmaps[i].recycle(); bitmaps[i] = null; }
                        }
                    });
                } catch (Throwable ignored) {}
                ex.shutdown();
            }
        });
    }

    public void switchCamera(final int idx) {
        main.post(() -> {
            if (!running || idx == activeCamera) return;
            activeCamera = idx;
            zoom = 1.0f;
            bindRetries = 0;
            bind();
        });
    }

    // ------------------------------------------------------------------ MediaPipe

    private void createLandmarker(boolean cpuOnly) {
        HeadConfig c = config;
        FaceLandmarker old = landmarker; landmarker = null;
        if (old != null) { try { old.close(); } catch (Throwable ignored) {} }

        boolean tryGpu = !cpuOnly && c.delegate != 2 && !forcedCpu;
        Throwable gpuErr = null;
        if (tryGpu) {
            try {
                landmarker = buildLandmarker(c, Delegate.GPU);
                delegateName = "GPU";
                return;
            } catch (Throwable t) {
                gpuErr = t;
                Log.w(TAG, "GPU delegate failed, falling back to CPU", t);
            }
        }
        landmarker = buildLandmarker(c, Delegate.CPU);
        delegateName = "CPU";
    }

    private FaceLandmarker buildLandmarker(HeadConfig c, Delegate d) {
        BaseOptions base = BaseOptions.builder().setModelAssetPath(MODEL_ASSET).setDelegate(d).build();
        FaceLandmarker.FaceLandmarkerOptions.Builder b = FaceLandmarker.FaceLandmarkerOptions.builder()
                .setBaseOptions(base)
                .setMinFaceDetectionConfidence(0.5f)
                .setMinFacePresenceConfidence(0.5f)
                .setMinTrackingConfidence(0.4f)
                // numFaces=2 disables MediaPipe's built-in landmark smoothing (spec 5c-c); we filter ourselves.
                .setNumFaces((c.raw_landmarks || c.multi_face) ? 2 : 1)
                .setOutputFacialTransformationMatrixes(true)
                .setOutputFaceBlendshapes(false);
        if (c.sync_infer) {
            b.setRunningMode(RunningMode.VIDEO);
        } else {
            b.setRunningMode(RunningMode.LIVE_STREAM)
             .setResultListener((result, input) -> {
                 long now = SystemClock.elapsedRealtimeNanos();
                 tracker.onFaceResult(result, now - ASSUMED_EXPOSURE_NS, now, asyncW, asyncH, 0);
             })
             .setErrorListener(e -> Log.e(TAG, "MediaPipe async error", e));
        }
        return FaceLandmarker.createFromOptions(context, b.build());
    }

    private volatile int asyncW = 480, asyncH = 640;

    // ------------------------------------------------------------------ CameraX

    @SuppressLint("UnsafeOptInUsageError")
    private void bind() {
        if (provider == null || !running) return;
        try {
            HeadConfig c = config;
            CameraSelector sel = (activeCamera == 1) ? CameraSelector.DEFAULT_BACK_CAMERA : CameraSelector.DEFAULT_FRONT_CAMERA;
            int w = (c.resolution == 1) ? 1280 : 640, h = (c.resolution == 1) ? 720 : 480;

            ImageAnalysis.Builder ib = new ImageAnalysis.Builder()
                    .setTargetResolution(new Size(w, h))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888);
            try { ib.setTargetRotation(displayRotation()); } catch (Throwable ignored) {}

            // Camera2 options: each one is best-effort. Unsupported keys are ignored by the HAL.
            try {
                Camera2Interop.Extender<ImageAnalysis> ext = new Camera2Interop.Extender<>(ib);
                if (c.fps == 60) ext.setCaptureRequestOption(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<Integer>(60, 60));
                else if (c.fps == 30) ext.setCaptureRequestOption(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<Integer>(30, 30));
                ext.setCaptureRequestOption(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO);
                ext.setCaptureRequestOption(CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE, CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE_OFF);
                ext.setCaptureRequestOption(CaptureRequest.NOISE_REDUCTION_MODE, CaptureRequest.NOISE_REDUCTION_MODE_FAST);
                ext.setCaptureRequestOption(CaptureRequest.EDGE_MODE, CaptureRequest.EDGE_MODE_FAST);
            } catch (Throwable t) {
                Log.w(TAG, "Camera2 interop options skipped: " + t.getMessage());
            }

            ImageAnalysis analysis = ib.build();
            analysis.setAnalyzer(executor, this::analyze);

            provider.unbindAll();
            camera = provider.bindToLifecycle(this, sel, analysis);
            zoom = 1.0f;
            bindRetries = 0;
            Log.d(TAG, "Camera bound: " + (activeCamera == 1 ? "rear" : "front"));
            tracker.onCameraBound();
        } catch (Throwable e) {
            Log.e(TAG, "Camera bind failed", e);
            if (running && bindRetries < 3) {
                bindRetries++;
                main.postDelayed(this::bind, 400L * bindRetries);
            } else {
                tracker.onCameraError("Camera bind failed: " + e.getMessage());
            }
        }
    }

    @SuppressWarnings("deprecation")
    private int displayRotation() {
        WindowManager wm = (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
        return wm != null ? wm.getDefaultDisplay().getRotation() : Surface.ROTATION_0;
    }

    // ------------------------------------------------------------------ analysis thread

    private void analyze(@NonNull ImageProxy proxy) {
        final long tEntryNs = SystemClock.elapsedRealtimeNanos();
        MPImage mp = null;
        try {
            FaceLandmarker lm = landmarker;
            if (lm == null || !running) return;
            HeadConfig c = config;

            final int w = proxy.getWidth(), h = proxy.getHeight();
            ImageProxy.PlaneProxy plane = proxy.getPlanes()[0];
            ByteBuffer buf = plane.getBuffer();
            final int rowStride = plane.getRowStride();

            int bi = c.sync_infer ? 0 : (bmpIdx ^= 1);   // ping-pong in async mode so MediaPipe never reads a bitmap we are rewriting
            Bitmap bmp = bitmaps[bi];
            if (bmp == null || bmp.getWidth() != w || bmp.getHeight() != h) {
                if (bmp != null) bmp.recycle();
                bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
                bitmaps[bi] = bmp;
            }
            buf.rewind();
            if (rowStride == w * 4) {
                bmp.copyPixelsFromBuffer(buf);
            } else {                                      // padded rows: repack into one reused direct buffer
                if (repack == null || repack.capacity() != w * h * 4) repack = ByteBuffer.allocateDirect(w * h * 4);
                repack.clear();
                ByteBuffer src = buf.duplicate();
                for (int r = 0; r < h; r++) {
                    src.limit(Math.min(src.capacity(), r * rowStride + w * 4));
                    src.position(r * rowStride);
                    repack.put(src);
                }
                repack.rewind();
                bmp.copyPixelsFromBuffer(repack);
            }

            int rot = proxy.getImageInfo().getRotationDegrees();
            if (c.cam_rotation > 0) rot = (rot + c.cam_rotation) % 360;
            if (rot != ipoRot || ipo == null) {
                ipo = ImageProcessingOptions.builder().setRotationDegrees(rot).build();
                ipoRot = rot;
            }
            final int upW = (rot % 180 == 0) ? w : h;
            final int upH = (rot % 180 == 0) ? h : w;
            asyncW = upW; asyncH = upH;

            mp = new BitmapImageBuilder(bmp).build();
            long ts = Math.max(lastTsMs + 1, tEntryNs / 1_000_000L);   // strictly increasing ms for MediaPipe
            lastTsMs = ts;
            final long tFrameNs = tEntryNs - ASSUMED_EXPOSURE_NS;

            if (c.sync_infer) {
                long t0 = SystemClock.elapsedRealtime();
                FaceLandmarkerResult res = lm.detectForVideo(mp, ipo, ts);
                long inferMs = SystemClock.elapsedRealtime() - t0;
                errorStreak = 0;
                tracker.onFaceResult(res, tFrameNs, SystemClock.elapsedRealtimeNanos(), upW, upH, inferMs);
                maybeZoom();
            } else {
                lm.detectAsync(mp, ipo, ts);
                mp = null;   // do not close: MediaPipe owns it until the result arrives
            }
        } catch (Throwable e) {
            Log.e(TAG, "Frame analysis error", e);
            errorStreak++;
            if (errorStreak >= 5 && !forcedCpu && "GPU".equals(delegateName)) {
                Log.w(TAG, "Repeated inference errors on GPU: switching to CPU");
                forcedCpu = true;
                try { createLandmarker(true); } catch (Throwable t) { tracker.onCameraError("CPU landmarker failed: " + t.getMessage()); }
                errorStreak = 0;
            }
        } finally {
            if (mp != null) { try { mp.close(); } catch (Throwable ignored) {} }
            proxy.close();
        }
    }

    /** Adaptive sensor zoom: keep the face ~170 px wide for better landmark precision (spec 5c-a). */
    private void maybeZoom() {
        HeadConfig c = config;
        Camera cam = camera;
        if (!c.auto_zoom || cam == null || !tracker.isTrackingSteady()) return;
        long now = SystemClock.elapsedRealtime();
        if (now - lastZoomCheckMs < 500) return;
        lastZoomCheckMs = now;
        float facePx = tracker.getFaceWidthPx();
        if (facePx < 30f) return;
        try {
            float zMax = (activeCamera == 1) ? 1.8f : 2.0f;
            ZoomState zs = cam.getCameraInfo().getZoomState().getValue();
            if (zs != null) zMax = Math.min(zMax, zs.getMaxZoomRatio());
            float wanted = (float) HeadFilters.clamp(zoom * TARGET_FACE_PX / facePx, 1.0, zMax);
            float next = zoom + (wanted - zoom) * 0.25f;
            if (Math.abs(next - zoom) > 0.08f) {          // avoid hunting
                zoom = next;
                cam.getCameraControl().setZoomRatio(zoom);
            }
        } catch (Throwable ignored) {}
    }
}
'''

JAVA['HeadTracker'] = r'''package com.xstreaming;

import android.annotation.SuppressLint;
import android.content.Context;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.util.Log;

import com.facebook.react.bridge.Arguments;
import com.facebook.react.bridge.WritableMap;
import com.google.mediapipe.tasks.components.containers.NormalizedLandmark;
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarkerResult;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.util.List;
import java.util.Optional;

/**
 * Orchestrator: camera results in (any thread) -> Kalman state; a decoupled ~125 Hz ticker reads that state,
 * extrapolates to "now", maps it to the right stick (Hold or Flick) and emits the RN "SensorData" event
 * ({x, y} in +-32767), exactly like Tilt mode, so the JS side is unchanged.
 */
public final class HeadTracker {
    private static final String TAG = "HeadTracker";

    public enum State { IDLE, STARTING, SEARCHING, CALIBRATING, TRACKING, COASTING, LOST, ERROR }

    // ---- tunables (direction to move them is in the comment) ----
    private static final long TICK_MS = 8;                    // ticker period (~125 Hz)
    private static final long MIN_EMIT_MS = 7;                // never emit faster than this (JS thread load)
    private static final double SA_MOVE = 2500.0;             // Kalman agility in motion (deg/s^2). Up = less lag, more noise
    private static final double SA_REST_FLICK = 350.0;        // Kalman calm-at-rest for Flick
    private static final double SIGMA_YAW = 0.7, SIGMA_PITCH = 1.0;   // measurement noise at ipd 70 px (deg)
    private static final double IPD_FRAC = 0.45;              // eye-to-eye distance as a fraction of face width
    private static final long CALIB_MS = 500;                 // initial neutral capture window
    private static final int RING = 15;                       // frames kept for neutral averaging
    private static final long EDGE_HOLD_NS = 1_000_000_000L;  // face lost at >=75% deflection: hold this long
    private static final long MID_HOLD_NS = 250_000_000L;     // face lost mid-range: hold this long
    private static final long LOST_AFTER_NS = 3_000_000_000L; // after this without a face -> LOST, output 0
    private static final double SLEW_PER_S = 25.0;            // stick units/s spike catcher (Hold)
    private static final long CSV_MAX_BYTES = 20L * 1024 * 1024;

    private final Context context;
    private final SensorModule sensorModule;
    private volatile HeadConfig config;
    private HeadCamera camera;

    private HandlerThread tickerThread;
    private Handler tickerHandler;
    private volatile boolean running = false;
    private volatile State state = State.IDLE;

    // ---- filter state (guarded by lock) ----
    private final Object lock = new Object();
    private final HeadFilters.Kalman1D kYaw = new HeadFilters.Kalman1D();
    private final HeadFilters.Kalman1D kPitch = new HeadFilters.Kalman1D();
    private long tFrameLatestNs = 0;
    private double rawYaw, rawPitch, rawRoll;

    // ---- camera-thread state ----
    private double[][] neutral = HeadPoseMath.identity();
    private final double[][] basis = HeadPoseMath.identity();       // learned head basis B (wizard not shipped; identity)
    private final double[][][] ring = new double[RING][3][3];
    private int ringIdx = 0, ringN = 0;
    private long calibStartNs = 0, lastFaceFrameNs = 0;
    private final double[] ypr = new double[3];
    private volatile boolean recenterRequest = false;
    private volatile boolean missing = false;
    private volatile long missStartNs = 0;
    private volatile long tLastResultNs = 0;
    private volatile float faceWidthPx = 100f;
    private volatile long inferMs = 0;
    private long fpsT0 = 0; private int fpsCount = 0; private volatile double fps = 0;

    // ---- ticker-thread state ----
    private final HeadFilters.StillnessGate stillX = new HeadFilters.StillnessGate(), stillY = new HeadFilters.StillnessGate();
    private final HeadFilters.OneEuro euroX = new HeadFilters.OneEuro(), euroY = new HeadFilters.OneEuro();
    private final HeadFilters.SlewLimiter slewX = new HeadFilters.SlewLimiter(SLEW_PER_S), slewY = new HeadFilters.SlewLimiter(SLEW_PER_S);
    private final HeadFlick.FlickAxis flickX = new HeadFlick.FlickAxis(), flickY = new HeadFlick.FlickAxis();
    private volatile HeadFlick.FlickCfg cfgX = new HeadFlick.FlickCfg(), cfgY = new HeadFlick.FlickCfg();
    private volatile boolean flickResetReq = false;
    private volatile boolean paused = false;
    private boolean wasPaused = false;
    private State prevState = State.IDLE;
    private long lastTickNs = 0, nextTickMs = 0;
    private double lastOutX = 0, lastOutY = 0;        // normalised, what we last computed
    private double holdX = 0, holdY = 0, holdMag = 0; // captured when the face is lost
    private int lastIx = 0, lastIy = 0; private long lastEmitMs = 0;
    private long blendStartNs = 0; private double blendFromX = 0, blendFromY = 0; private boolean blending = false;
    private long lastDiagMs = 0, lastCsvFlushMs = 0;
    private double lastLatencyMs = 0;

    // ---- recording / feedback ----
    private BufferedWriter csv; private long csvBytes = 0; private volatile boolean recording = false;
    private final StringBuilder sb = new StringBuilder(256);
    private Vibrator vibrator; private ToneGenerator tone;

    public HeadTracker(Context context, SensorModule sensorModule, HeadConfig config) {
        this.context = context.getApplicationContext();
        this.sensorModule = sensorModule;
        this.config = config;
        rebuildFlickCfg();
        try { vibrator = (Vibrator) this.context.getSystemService(Context.VIBRATOR_SERVICE); } catch (Throwable ignored) {}
        try { tone = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 60); } catch (Throwable ignored) {}
    }

    // ================================================================== control API (any thread)

    public synchronized void start() {
        if (running) return;
        running = true;
        state = State.STARTING;
        resetAll();
        tickerThread = new HandlerThread("HeadTicker", android.os.Process.THREAD_PRIORITY_URGENT_DISPLAY);
        tickerThread.start();
        tickerHandler = new Handler(tickerThread.getLooper());
        camera = new HeadCamera(context, this, config);
        state = State.SEARCHING;
        camera.start();
        nextTickMs = SystemClock.uptimeMillis() + TICK_MS;
        tickerHandler.postAtTime(this::tick, nextTickMs);
    }

    public synchronized void stop() {
        running = false;
        state = State.IDLE;
        if (camera != null) { camera.stop(); camera = null; }
        if (tickerHandler != null) tickerHandler.removeCallbacksAndMessages(null);
        if (tickerThread != null) { tickerThread.quitSafely(); tickerThread = null; }
        emitSensorData(0, 0);
        closeCsv();
        if (tone != null) { try { tone.release(); } catch (Throwable ignored) {} tone = null; }
    }

    public void updateConfig(HeadConfig c) {
        config = c;
        rebuildFlickCfg();
        if (camera != null) camera.updateConfig(c);
    }

    public HeadConfig getConfig() { return config; }

    public void switchCamera(int idx) {
        HeadConfig c = config.copy(); c.camera = idx; updateConfig(c);
        if (camera != null) camera.switchCamera(idx);
        recenterRequest = true;
        hapticTick();
    }

    public void switchMode(int mode) {
        HeadConfig c = config.copy(); c.output_mode = mode; updateConfig(c);
        flickResetReq = true;
        hapticTick();
    }

    public void setPaused(boolean p) { paused = p; if (!p) flickResetReq = true; }

    public void recenter() { recenterRequest = true; }

    public void startCalibration() { recenterRequest = true; toneBeep(); }

    public synchronized void setRecording(boolean on) {
        if (on == recording) return;
        if (!on) { recording = false; closeCsv(); return; }
        try {
            File dir = context.getExternalFilesDir(null);
            File f = new File(dir, "head_" + System.currentTimeMillis() + ".csv");
            csv = new BufferedWriter(new FileWriter(f));
            csvBytes = 0;
            String hdr = "t_ms,state,camera,mode,rawYaw,rawPitch,yaw,pitch,vYaw,vPitch,facePx,inferMs,latencyMs,flickSx,flickPendX,zoom,outX,outY\n";
            csv.write(hdr); csvBytes += hdr.length();
            recording = true;
            Log.d(TAG, "Recording to " + f.getAbsolutePath());
        } catch (Throwable t) { Log.e(TAG, "CSV open failed", t); csv = null; }
    }

    // ================================================================== camera callbacks

    public void onCameraBound() { /* state moves on the first face result */ }

    public void onCameraError(String msg) {
        Log.e(TAG, "Camera error: " + msg);
        state = State.ERROR;
        hapticError();
        emitStatusNow(msg);
    }

    public float getFaceWidthPx() { return faceWidthPx; }

    public boolean isTrackingSteady() {
        if (state != State.TRACKING) return false;
        synchronized (lock) { return Math.abs(kYaw.v) < 30 && Math.abs(kPitch.v) < 30; }
    }

    /** Called from the camera analysis thread (sync) or the MediaPipe thread (async) for EVERY frame, face or not. */
    public void onFaceResult(FaceLandmarkerResult res, long tFrameNs, long tResultNs, int imgW, int imgH, long inferMillis) {
        if (!running) return;
        inferMs = inferMillis;
        tLastResultNs = tResultNs;
        if (fpsT0 == 0) fpsT0 = tResultNs;
        fpsCount++;
        if (tResultNs - fpsT0 >= 1_000_000_000L) { fps = fpsCount * 1e9 / (tResultNs - fpsT0); fpsCount = 0; fpsT0 = tResultNs; }

        List<NormalizedLandmark> lms = null;
        float[] mat = null;
        try {
            if (res != null && !res.faceLandmarks().isEmpty()) lms = res.faceLandmarks().get(0);
            if (res != null) {
                Optional<List<float[]>> opt = res.facialTransformationMatrixes();
                if (opt.isPresent() && !opt.get().isEmpty()) mat = opt.get().get(0);
            }
        } catch (Throwable t) { Log.w(TAG, "result parse: " + t.getMessage()); }

        if (lms == null || mat == null || mat.length < 16) {
            if (!missing) { missStartNs = tResultNs; missing = true; }
            return;
        }
        if (state == State.ERROR) state = State.TRACKING;
        final boolean wasMissing = missing;
        missing = false;

        // face width in upright analysis pixels (used for noise model + adaptive zoom)
        if (lms.size() > 454) {
            NormalizedLandmark a = lms.get(234), b = lms.get(454);
            double dx = (b.x() - a.x()) * imgW, dy = (b.y() - a.y()) * imgH;
            faceWidthPx = (float) Math.hypot(dx, dy);
        }

        double[][] R = HeadPoseMath.extractRotation(mat);
        for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) ring[ringIdx][i][j] = R[i][j];
        ringIdx = (ringIdx + 1) % RING;
        ringN = Math.min(ringN + 1, RING);

        boolean reseed = wasMissing;
        State s = state;
        if (s == State.SEARCHING || s == State.STARTING) {
            state = State.CALIBRATING; calibStartNs = tResultNs; ringN = 1; ringIdx = 1 % RING;
            for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) ring[0][i][j] = R[i][j];
            reseed = true;
        } else if (s == State.CALIBRATING) {
            if (tResultNs - calibStartNs > CALIB_MS * 1_000_000L && ringN >= 8) {
                neutral = meanLast(Math.min(ringN, RING));
                state = State.TRACKING; reseed = true; flickResetReq = true;
                hapticPulse();
            }
        }
        if (recenterRequest) {
            recenterRequest = false;
            neutral = meanLast(Math.min(ringN, 8));
            if (state == State.CALIBRATING || state == State.SEARCHING) state = State.TRACKING;
            reseed = true; flickResetReq = true;
            hapticTick();
        }
        if (wasMissing && (state == State.COASTING || state == State.LOST)) state = State.TRACKING;

        HeadPoseMath.decompose(R, neutral, basis, ypr);
        rawYaw = ypr[0]; rawPitch = ypr[1]; rawRoll = ypr[2];

        double ipd = Math.max(20.0, faceWidthPx * IPD_FRAC);
        double conf = HeadFilters.clamp(ipd / 70.0, 0.3, 1.0);
        double sy = SIGMA_YAW * (70.0 / ipd) / conf, sp = SIGMA_PITCH * (70.0 / ipd) / conf;
        double ry = sy * sy, rp = sp * sp;

        HeadConfig c = config;
        double saRest = (c.output_mode == 0) ? 700.0 * Math.pow(200.0 / 700.0, c.smoothing / 10.0) : SA_REST_FLICK;
        double dt = (lastFaceFrameNs == 0) ? 1.0 / 30.0 : HeadFilters.clamp((tFrameNs - lastFaceFrameNs) / 1e9, 0.001, 0.1);
        lastFaceFrameNs = tFrameNs;

        synchronized (lock) {
            if (reseed || !kYaw.init) {
                kYaw.reset(rawYaw, ry); kPitch.reset(rawPitch, rp);
            } else {
                kYaw.predict(dt, saRest, SA_MOVE, tFrameNs); kYaw.update(rawYaw, ry, tFrameNs);
                kPitch.predict(dt, saRest, SA_MOVE, tFrameNs); kPitch.update(rawPitch, rp, tFrameNs);
            }
            tFrameLatestNs = tFrameNs;
        }
    }

    private double[][] meanLast(int n) {
        double[][][] tmp = new double[n][][];
        for (int i = 0; i < n; i++) tmp[i] = ring[((ringIdx - 1 - i) % RING + RING) % RING];
        return HeadPoseMath.meanRotation(tmp, n);
    }

    // ================================================================== ticker

    private void resetAll() {
        synchronized (lock) { kYaw.init = false; kPitch.init = false; }
        stillX.reset(); stillY.reset(); euroX.reset(); euroY.reset(); slewX.reset(); slewY.reset();
        flickX.reset(); flickY.reset();
        neutral = HeadPoseMath.identity(); ringN = 0; ringIdx = 0; lastFaceFrameNs = 0;
        missing = false; recenterRequest = false; lastOutX = lastOutY = 0; lastIx = lastIy = 0;
        tLastResultNs = SystemClock.elapsedRealtimeNanos();
    }

    private void rebuildFlickCfg() {
        HeadConfig c = config;
        int p = Math.max(0, Math.min(3, c.flick_preset));
        double gain = HeadFlick.PRESET_GAIN[p] * (c.flick_gain / 0.020);
        double glideTau = 0.04 + (c.flick_glide - 1) / 9.0 * 0.11;           // 1..10 -> 0.04..0.15 s
        double tau = HeadFlick.PRESET_TAU[p] * (glideTau / 0.0733);
        double accel = HeadFlick.PRESET_ACCEL[p] * (c.flick_accel / 0.30);

        HeadFlick.FlickCfg x = new HeadFlick.FlickCfg();
        x.gain = gain; x.tauPay = tau; x.accel = accel; x.band = c.flick_band; x.gameDz = c.game_deadzone;
        x.vLo = c.flick_deadzone; x.vHi = 3.2 * c.flick_deadzone;

        HeadFlick.FlickCfg y = new HeadFlick.FlickCfg();
        y.gain = gain * 0.6; y.tauPay = tau; y.accel = accel * 0.67; y.band = c.flick_band + 1.0; y.gameDz = c.game_deadzone;
        y.hOut = 2.2; y.hUp = 3.0;
        y.vLo = 1.15 * c.flick_deadzone; y.vHi = 3.2 * y.vLo;

        cfgX = x; cfgY = y;
    }

    private void tick() {
        if (!running) return;
        try {
            process(SystemClock.elapsedRealtimeNanos(), SystemClock.elapsedRealtime());
        } catch (Throwable t) {
            Log.e(TAG, "tick error", t);
        }
        Handler h = tickerHandler;
        if (running && h != null) {
            nextTickMs += TICK_MS;                       // absolute deadlines: no drift
            long now = SystemClock.uptimeMillis();
            if (nextTickMs < now - 50) nextTickMs = now + TICK_MS;
            h.postAtTime(this::tick, nextTickMs);
        }
    }

    private void process(long nowNs, long nowMs) {
        State s = state;
        HeadConfig c = config;
        double dt = (lastTickNs == 0) ? TICK_MS / 1000.0 : HeadFilters.clamp((nowNs - lastTickNs) / 1e9, 0.001, 0.05);
        lastTickNs = nowNs;

        // ---- loss detection (watchdog: no result for 250 ms counts as a miss) ----
        if (s == State.TRACKING && (missing || nowNs - tLastResultNs > 250_000_000L)) {
            if (!missing) { missStartNs = tLastResultNs; missing = true; }
            state = s = State.COASTING;
            holdX = lastOutX; holdY = lastOutY; holdMag = Math.max(Math.abs(holdX), Math.abs(holdY));
        }
        if (s == State.COASTING && nowNs - missStartNs > LOST_AFTER_NS) {
            state = s = State.LOST;
            hapticDouble();
        }
        // ---- reacquire: start a short ease so the view doesn't jump ----
        if (prevState != State.TRACKING && s == State.TRACKING && (prevState == State.COASTING || prevState == State.LOST)) {
            flickResetReq = true;
            blending = (c.output_mode == 0);
            blendStartNs = nowNs; blendFromX = lastOutX; blendFromY = lastOutY;
            stillX.reset(); stillY.reset(); euroX.reset(); euroY.reset(); slewX.reset(); slewY.reset();
            hapticPulse();
        }
        prevState = s;

        if (flickResetReq) { flickResetReq = false; flickX.softReset(); flickY.softReset(); stillX.reset(); stillY.reset(); }

        double ox = 0, oy = 0;
        double yawHat = 0, pitchHat = 0, vYaw = 0, vPitch = 0, L = 0;

        if (s == State.TRACKING || s == State.COASTING) {
            long tF;
            synchronized (lock) { yawHat = kYaw.x; pitchHat = kPitch.x; vYaw = kYaw.v; vPitch = kPitch.v; tF = tFrameLatestNs; }
            L = HeadFilters.clamp((nowNs - tF) / 1e9, 0.0, 0.15);
            lastLatencyMs = L * 1000.0;
        }

        if (paused) {
            wasPaused = true;
            flickX.softReset(); flickY.softReset();
            stillX.reset(); stillY.reset(); euroX.reset(); euroY.reset();
        } else if (s == State.TRACKING) {
            if (wasPaused) { wasPaused = false; flickX.softReset(); flickY.softReset(); }
            if (c.output_mode == 0) {
                // ------------ HOLD (absolute) ------------
                double frameInt = 1.0 / Math.max(15.0, fps > 0 ? fps : 30.0);
                double tLead = c.prediction_ms / 1000.0;
                double thX = lead(yawHat, vYaw, L, tLead, frameInt);
                double thY = lead(pitchHat, vPitch, L, tLead, frameInt);
                thX = stillX.filter(thX, vYaw, nowNs);
                thY = stillY.filter(thY, vPitch, nowNs);
                if (c.invert_x) thX = -thX;
                if (c.invert_y) thY = -thY;
                double sx = HeadMapper.shape(thX, c.yaw_range, c.yaw_range, c.deadzone_x, c.expo_x, c.game_deadzone, Math.abs(lastOutX) > 0.001);
                double sy = HeadMapper.shape(thY, c.pitch_up_range, c.pitch_down_range, c.deadzone_y, c.expo_y, c.game_deadzone, Math.abs(lastOutY) > 0.001);
                double minCut = 2.5 * Math.pow(0.24, c.smoothing / 10.0);   // smoothing 5 -> ~1.2 Hz
                euroX.minCut = minCut; euroY.minCut = minCut;
                sx = slewX.filter(euroX.filter(sx, dt), dt);
                sy = slewY.filter(euroY.filter(sy, dt), dt);
                ox = sx * c.outer_cap; oy = sy * c.outer_cap;
                if (blending) {
                    double t = (nowNs - blendStartNs) / 150e6;
                    if (t >= 1.0 || (Math.abs(ox - blendFromX) < 0.3 && Math.abs(oy - blendFromY) < 0.3)) blending = false;
                    else { double k = HeadFilters.smoothstep(0, 1, t); ox = blendFromX + (ox - blendFromX) * k; oy = blendFromY + (oy - blendFromY) * k; }
                }
            } else {
                // ------------ FLICK (virtual mouse) ------------
                double thX = yawHat + vYaw * 0.5 * L, thY = pitchHat + vPitch * 0.5 * L;   // reduced compensation, no T_lead
                double wX = vYaw, wY = vPitch;
                if (c.invert_x) { thX = -thX; wX = -wX; }      // velocity must flip with the angle or the ratchet breaks
                if (c.invert_y) { thY = -thY; wY = -wY; }
                ox = flickX.step(thX, wX, dt, cfgX, c.neutral_creep) * c.outer_cap;
                oy = c.flick_pitch ? flickY.step(thY, wY, dt, cfgY, c.neutral_creep) * c.outer_cap : 0.0;
            }
        } else if (s == State.COASTING) {
            // face vanished: keep the view where it was (we lose the face exactly when the user turns far)
            double tm = (nowNs - missStartNs) / 1e9;
            if (c.output_mode == 0) {
                double k;
                if (holdMag >= 0.75) k = (tm < EDGE_HOLD_NS / 1e9) ? 1.0 : Math.exp(-(tm - EDGE_HOLD_NS / 1e9) / 0.300);
                else k = (tm < MID_HOLD_NS / 1e9) ? 1.0 : Math.exp(-(tm - MID_HOLD_NS / 1e9) / 0.200);
                ox = holdX * k; oy = holdY * k;
            } else {
                flickX.bleed(Math.exp(-dt / 0.033)); flickY.bleed(Math.exp(-dt / 0.033));   // ~100 ms to zero
            }
        } else {
            if (s == State.LOST || s == State.ERROR) { flickX.bleed(0); flickY.bleed(0); }
            // SEARCHING / CALIBRATING / IDLE: output 0
        }

        if (Double.isNaN(ox) || Double.isNaN(oy)) { ox = 0; oy = 0; }
        ox = HeadFilters.clamp(ox, -1.0, 1.0); oy = HeadFilters.clamp(oy, -1.0, 1.0);
        lastOutX = ox; lastOutY = oy;

        int ix = (int) Math.round(ox * 32767.0), iy = (int) Math.round(oy * 32767.0);
        if (Math.abs(ix) < 150) ix = 0;
        if (Math.abs(iy) < 150) iy = 0;
        if ((ix != lastIx || iy != lastIy) && nowMs - lastEmitMs >= MIN_EMIT_MS) {
            lastIx = ix; lastIy = iy; lastEmitMs = nowMs;
            emitSensorData(ix, iy);
        }

        if (recording) writeCsv(nowMs, s, c, yawHat, pitchHat, vYaw, vPitch, ox, oy);
        if (c.diag_overlay && nowMs - lastDiagMs >= 250) { lastDiagMs = nowMs; emitStatusNow(null); }
    }

    /** Pipeline compensation + user look-ahead (spec 8.4). hat/v are stamped at the frame time; L = frame age. */
    static double lead(double hat, double v, double L, double tLead, double frameInt) {
        double av = Math.abs(v);
        double ve = v * av / (av + 15.0);                         // tiny velocities predict nothing
        double horizon = Math.min(L + tLead, Math.max(2.5 * frameInt, L + 0.02));
        double cap = Math.max(6.0, 0.10 * Math.abs(ve));
        return hat + HeadFilters.clamp(ve * horizon, -cap, cap);
    }

    // ================================================================== events, CSV, feedback

    private void emitSensorData(int x, int y) {
        try {
            WritableMap m = Arguments.createMap();
            m.putDouble("x", x);
            m.putDouble("y", y);
            sensorModule.sendEvent("SensorData", m);
        } catch (Throwable t) { Log.w(TAG, "emit failed: " + t.getMessage()); }
    }

    private void emitStatusNow(String warning) {
        try {
            WritableMap m = Arguments.createMap();
            m.putString("state", state.name());
            m.putInt("camera", config.camera);
            m.putInt("mode", config.output_mode);
            m.putDouble("fps", fps);
            m.putDouble("inferMs", inferMs);
            m.putDouble("latencyMs", lastLatencyMs);
            m.putDouble("facePx", faceWidthPx);
            m.putDouble("yaw", kYaw.x);
            m.putDouble("pitch", kPitch.x);
            m.putString("delegate", camera != null ? camera.getDelegateName() : "?");
            m.putDouble("zoom", camera != null ? camera.getZoom() : 1.0);
            if (warning != null) m.putString("warning", warning);
            sensorModule.sendEvent("HeadTrackStatus", m);
        } catch (Throwable ignored) {}
    }

    private void writeCsv(long nowMs, State s, HeadConfig c, double yaw, double pitch, double vy, double vp, double ox, double oy) {
        BufferedWriter w = csv;
        if (w == null) return;
        try {
            sb.setLength(0);
            sb.append(nowMs).append(',').append(s.name()).append(',').append(c.camera).append(',').append(c.output_mode).append(',')
              .append(f(rawYaw)).append(',').append(f(rawPitch)).append(',').append(f(yaw)).append(',').append(f(pitch)).append(',')
              .append(f(vy)).append(',').append(f(vp)).append(',').append(f(faceWidthPx)).append(',').append(inferMs).append(',')
              .append(f(lastLatencyMs)).append(',').append(f(flickX.S)).append(',').append(f(flickX.pend)).append(',')
              .append(f(camera != null ? camera.getZoom() : 1.0)).append(',').append(f(ox)).append(',').append(f(oy)).append('\n');
            w.write(sb.toString());
            csvBytes += sb.length();
            if (nowMs - lastCsvFlushMs > 1000) { w.flush(); lastCsvFlushMs = nowMs; }
            if (csvBytes > CSV_MAX_BYTES) { recording = false; closeCsv(); }
        } catch (Throwable t) { recording = false; closeCsv(); }
    }
    private static String f(double v) { return String.format(java.util.Locale.US, "%.3f", v); }

    private synchronized void closeCsv() {
        recording = false;
        if (csv != null) { try { csv.flush(); csv.close(); } catch (Throwable ignored) {} csv = null; }
    }

    @SuppressLint("NewApi")
    private void vibrate(long[] pattern) {
        if (!config.haptics || vibrator == null) return;
        try {
            if (Build.VERSION.SDK_INT >= 26) vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1));
            else vibrator.vibrate(pattern, -1);
        } catch (Throwable ignored) {}
    }
    private void hapticTick()   { vibrate(new long[]{0, 15}); }
    private void hapticPulse()  { vibrate(new long[]{0, 40}); }
    private void hapticDouble() { vibrate(new long[]{0, 40, 60, 40}); }
    private void hapticError()  { vibrate(new long[]{0, 50, 50, 50, 50, 50}); }
    private void toneBeep() {
        if (tone != null) { try { tone.startTone(ToneGenerator.TONE_PROP_BEEP, 150); } catch (Throwable ignored) {} }
    }
}
'''


# ----------------------------------------------------------------------------------------------
# 2. SensorModule.java
# ----------------------------------------------------------------------------------------------
SENSOR_METHODS = r'''
    // HEADTRACK ---------------- camera head tracking (see HeadTracker.java) ----------------
    @ReactMethod
    public synchronized void startHeadTrack(com.facebook.react.bridge.ReadableMap cfg) {
        try {
            if (headTracker == null) {
                headTracker = new HeadTracker(getReactApplicationContext(), this, HeadConfig.fromMap(cfg));
                headTracker.start();
            } else {
                headTracker.updateConfig(headTracker.getConfig().merged(cfg));
            }
        } catch (Throwable t) {
            android.util.Log.e("SensorModule", "startHeadTrack failed", t);
            headTracker = null;
        }
    }

    /** Live tuning: only the keys present in cfg change. */
    @ReactMethod
    public synchronized void updateHeadTrack(com.facebook.react.bridge.ReadableMap cfg) {
        if (headTracker != null) headTracker.updateConfig(headTracker.getConfig().merged(cfg));
    }

    @ReactMethod
    public synchronized void stopHeadTrack() {
        if (headTracker != null) {
            try { headTracker.stop(); } catch (Throwable t) { android.util.Log.e("SensorModule", "stopHeadTrack", t); }
            headTracker = null;
        }
    }

    @ReactMethod
    public void headRecenter() { if (headTracker != null) headTracker.recenter(); }

    @ReactMethod
    public void headSwitchCamera(int camera) { if (headTracker != null) headTracker.switchCamera(camera); }

    @ReactMethod
    public void headSwitchMode(int mode) { if (headTracker != null) headTracker.switchMode(mode); }

    @ReactMethod
    public void headPause(boolean paused) { if (headTracker != null) headTracker.setPaused(paused); }

    @ReactMethod
    public void headCalibrate() { if (headTracker != null) headTracker.startCalibration(); }

    @ReactMethod
    public void headRecord(boolean on) { if (headTracker != null) headTracker.setRecording(on); }
'''


def patch_sensor_module():
    path = JAVA_DIR + "/SensorModule.java"
    text, crlf = read(path)
    if MARK in text:
        print("  skip (already patched):", path)
        return
    kw = ("class SensorModule", "recenter", "stopSensor", "sendEvent")

    m = one(text, r"public\s+class\s+SensorModule\b[^{]*\{", path, "class declaration", kw)
    text = splice(text, m.end(), m.end(), "\n    // HEADTRACK\n    private HeadTracker headTracker = null;\n")

    m = one(text, r"public\s+void\s+recenter\s*\(\s*\)\s*\{", path,
            "recenter() (the tilt patch must run first)", kw)
    text = splice(text, m.end(), m.end(), "\n        if (headTracker != null) { headTracker.recenter(); }")

    m = one(text, r"public\s+void\s+stopSensor\s*\(\s*\)\s*\{", path, "stopSensor()", kw)
    text = splice(text, m.end(), m.end(), "\n        stopHeadTrack();")

    # sendEvent must be callable from HeadTracker (same package): only 'private' blocks that.
    if re.search(r"\bprivate(\s+(?:static\s+)?(?:final\s+)?)void\s+sendEvent\s*\(", text):
        text = re.sub(r"\bprivate(\s+(?:static\s+)?(?:final\s+)?)void(\s+sendEvent\s*\()", r"public\1void\2", text, count=1)
    elif not re.search(r"\bvoid\s+sendEvent\s*\(", text):
        die("Could not find a sendEvent(String, WritableMap) method in SensorModule.", path, text, kw)

    end = text.rstrip().rfind("}")
    if end < 0:
        die("Could not find the closing brace of the class.", path, text, kw)
    text = splice(text, end, end, SENSOR_METHODS + "\n")
    write(path, text, crlf)
    print("  patched", path)


# ----------------------------------------------------------------------------------------------
# 3. settings (sensor.ts + settingStore.ts)
# ----------------------------------------------------------------------------------------------
ONOFF = [(0, "Off"), (1, "On")]
NOYES = [(0, "No"), (1, "Yes")]

# (name, kind, title, description, extra, default)
#   radio  -> extra = list of (value, text)
#   slider -> extra = (min, max, step)
SETTINGS = [
    ("head_camera", "radio", "Head tracking camera", "Which camera watches your head. You can also switch in the stream menu.", [(0, "Front"), (1, "Rear")], 0),
    ("head_output_mode", "radio", "Head tracking mode", "Hold = head angle is the stick (racing, flight, cockpit). Flick = virtual mouse: move your head away from centre to turn, come back freely (shooters, action).", [(0, "Hold (angle = stick)"), (1, "Flick (virtual mouse)")], 0),
    ("head_invert_x", "radio", "Invert head left/right", "Turn on if the view goes the wrong way when you turn your head sideways.", NOYES, 0),
    ("head_invert_y", "radio", "Invert head up/down", "Turn on if the view goes the wrong way when you look up or down.", NOYES, 0),
    ("head_yaw_range", "slider", "Hold: left/right head range (degrees)", "Head turn needed for full stick left or right.", (15, 70, 5), 35),
    ("head_pitch_up_range", "slider", "Hold: look-up range (degrees)", "Head tilt needed for full stick up.", (8, 45, 1), 18),
    ("head_pitch_down_range", "slider", "Hold: look-down range (degrees)", "Head tilt needed for full stick down.", (8, 45, 1), 22),
    ("head_deadzone_x", "slider", "Hold: left/right deadzone (units of 0.5 degree)", "Ignored head movement around centre. 3 = 1.5 degrees.", (0, 12, 1), 3),
    ("head_deadzone_y", "slider", "Hold: up/down deadzone (units of 0.5 degree)", "4 = 2 degrees.", (0, 12, 1), 4),
    ("head_expo_x", "slider", "Hold: left/right curve (10 = linear)", "Higher = finer control near centre.", (10, 25, 1), 14),
    ("head_expo_y", "slider", "Hold: up/down curve (10 = linear)", "Higher = finer control near centre.", (10, 25, 1), 12),
    ("head_smoothing", "slider", "Hold: smoothing", "Raise this first if the view is twitchy at rest. Higher = smoother but slightly slower.", (0, 10, 1), 5),
    ("head_prediction_ms", "slider", "Prediction (ms)", "Extra look-ahead on top of the automatic camera-delay compensation. Raise if it feels laggy.", (0, 60, 5), 15),
    ("head_game_deadzone", "slider", "Game's own right-stick deadzone (%)", "Raise if small head movements do nothing and then jump.", (0, 30, 1), 8),
    ("head_outer_cap", "slider", "Maximum stick (%)", "95 avoids the rim acceleration many shooters add. Use 100 for racing/sims.", (80, 100, 1), 95),
    ("head_flick_preset", "radio", "Flick: feel", "Pre-tuned response for Flick mode.", [(0, "Precise"), (1, "Balanced"), (2, "Snappy"), (3, "Spin")], 1),
    ("head_flick_gain", "slider", "Flick: sensitivity", "How far the camera turns per degree of head movement. Also adjustable in the stream menu.", (5, 60, 1), 20),
    ("head_flick_glide", "slider", "Flick: glide", "Higher = smoother, floatier. Lower if the camera keeps turning after you stop.", (1, 10, 1), 4),
    ("head_flick_deadzone", "slider", "Flick: motion threshold (deg/s)", "Raise if the camera creeps while you sit still.", (6, 30, 1), 14),
    ("head_flick_accel", "slider", "Flick: speed boost (%)", "Fast flicks turn more than slow ones. 0 = pure distance.", (0, 60, 5), 30),
    ("head_flick_band", "slider", "Flick: neutral band (units of 0.5 degree)", "5 = 2.5 degrees. Raise if returning your head turns the camera back.", (2, 12, 1), 5),
    ("head_flick_pitch", "radio", "Flick: use up/down", "Many players prefer yaw-only.", ONOFF, 1),
    ("head_neutral_creep", "radio", "Flick: follow slouching", "Slowly re-centres when your resting posture drifts.", ONOFF, 1),
    ("head_auto_zoom", "radio", "Auto zoom", "Zooms the camera so your face stays big enough for accurate tracking.", ONOFF, 1),
    ("head_haptics", "radio", "Head tracking vibration cues", "Vibrate when your face is found / lost, and on recentre.", ONOFF, 1),
    ("head_delegate", "radio", "Face model runs on", "Auto tries the GPU and falls back to the CPU. Try CPU if the game stutters.", [(0, "Auto"), (1, "GPU"), (2, "CPU")], 0),
    ("head_fps", "radio", "Camera frame rate", "Auto = default.", [(0, "Auto"), (30, "30"), (60, "60")], 0),
    ("head_raw_landmarks", "radio", "Raw landmarks (A/B test)", "Turns off MediaPipe's built-in smoothing. Compare feel and the CSV log.", ONOFF, 0),
]


def js_str(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def sensor_entry(s, indent):
    name, kind, title, desc, extra, _ = s
    i1, i2 = indent + "  ", indent + "    "
    out = [indent + "{", i1 + "name: %s," % js_str(name), i1 + "type: %s," % js_str(kind)]
    if kind == "slider":
        out += [i1 + "min: %d," % extra[0], i1 + "max: %d," % extra[1], i1 + "step: %d," % extra[2]]
    out += [i1 + "title: t(%s)," % js_str(title), i1 + "description: t(%s)," % js_str(desc)]
    if kind == "radio":
        out.append(i1 + "data: [")
        for v, tx in extra:
            out.append(i2 + "{value: %d, text: t(%s)}," % (v, js_str(tx)))
        out.append(i1 + "],")
    else:
        out.append(i1 + "data: [],")
    out.append(indent + "},")
    return "\n".join(out)


def patch_sensor_ts():
    path = "src/common/settings/sensor.ts"
    text, crlf = read(path)
    if MARK in text:
        print("  skip (already patched):", path)
        return
    kw = ("sensor_mode", "Tilt", "tilt_deadzone_deg", "tilt_range_deg")

    # 3rd option on the sensor_mode radio
    m = one(text, r"\{\s*value:\s*1\s*,\s*text:\s*t\(\s*['\"]Tilt['\"]\s*\)\s*,?\s*\}", path,
            "the {value: 1, text: t('Tilt')} radio option", kw)
    before = text[:m.start()]
    ls = before.rfind("\n") + 1
    ind = re.match(r"[ \t]*", text[ls:]).group(0)
    text = splice(text, m.end(), m.end(),
                  ",\n" + ind + "{value: 2, text: t('Head tracking (camera)')}")

    # settings entries after the tilt_deadzone_deg object
    m = one(text, r"\{[^{}]*?name:\s*['\"]tilt_deadzone_deg['\"][^{}]*?\}\s*,?", path,
            "the tilt_deadzone_deg settings entry", kw, re.S)
    obj_start_line = text.rfind("\n", 0, m.start()) + 1
    ind = re.match(r"[ \t]*", text[obj_start_line:]).group(0)
    entries = "\n".join(sensor_entry(s, ind) for s in SETTINGS)
    obj = m.group(0).rstrip()
    if not obj.endswith(","):
        obj += ","
    text = splice(text, m.start(), m.end(), obj + "\n" + entries)
    text = "// HEADTRACK settings added by apply_headtrack_patch.py\n" + text
    write(path, text, crlf)
    print("  patched", path)


def patch_setting_store():
    path = "src/store/settingStore.ts"
    text, crlf = read(path)
    if "head_camera" in text:
        print("  skip (already patched):", path)
        return
    kw = ("tilt_deadzone_deg", "tilt_range_deg", "sensor_mode")

    m = one(text, r"(?m)^([ \t]*)tilt_deadzone_deg\s*:\s*number\s*;", path, "type of tilt_deadzone_deg", kw)
    ind = m.group(1)
    types = "".join("\n%s%s: number;" % (ind, s[0]) for s in SETTINGS)
    text = splice(text, m.end(), m.end(), types)

    m = one(text, r"(?m)^([ \t]*)tilt_deadzone_deg\s*:\s*-?[\d.]+\s*,", path, "default of tilt_deadzone_deg", kw)
    ind = m.group(1)
    defaults = "".join("\n%s%s: %s," % (ind, s[0], s[5]) for s in SETTINGS)
    text = splice(text, m.end(), m.end(), defaults)
    text = "// HEADTRACK settings added by apply_headtrack_patch.py\n" + text
    write(path, text, crlf)
    print("  patched", path)


# ----------------------------------------------------------------------------------------------
# 4. NativeStream.tsx
# ----------------------------------------------------------------------------------------------
JS_START = r'''if (headOn) {
        // HEADTRACK: camera head tracking (needs CAMERA permission)
        try {
          const _rn = require('react-native');
          const _hc: any = {};
          Object.keys(@S@).forEach((k: string) => {
            if (k.indexOf('head_') === 0) {
              _hc[k.slice(5)] = (@S@ as any)[k];
            }
          });
          (globalThis as any).__xsHead = {
            cam: _hc.camera || 0,
            mode: _hc.output_mode || 0,
            gain: _hc.flick_gain || 20,
            invx: _hc.invert_x || 0,
            invy: _hc.invert_y || 0,
            paused: false,
            rec: false,
          };
          _rn.PermissionsAndroid.request(
            _rn.PermissionsAndroid.PERMISSIONS.CAMERA,
          ).then((res: string) => {
            if (res === _rn.PermissionsAndroid.RESULTS.GRANTED) {
              @SM@.startHeadTrack(_hc);
            } else {
              _rn.ToastAndroid.show(
                'Camera permission denied - head tracking is off',
                _rn.ToastAndroid.LONG,
              );
            }
          });
        } catch (e) {
          console.warn('Head tracking start failed', e);
        }
      } else if (tiltOn) {'''

JS_CASES = r'''case 'recenterHead':
        @SM@.headRecenter();
        break;
      case 'switchHeadCamera': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        _h.cam = _h.cam === 1 ? 0 : 1;
        @SM@.headSwitchCamera(_h.cam);
        break;
      }
      case 'switchHeadMode': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        _h.mode = _h.mode === 1 ? 0 : 1;
        @SM@.headSwitchMode(_h.mode);
        break;
      }
      case 'headSensUp':
      case 'headSensDown': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        const _up = id === 'headSensUp';
        let _g = Math.round((_h.gain || 20) * (_up ? 1.15 : 1 / 1.15));
        if (_g === (_h.gain || 20)) {
          _g += _up ? 1 : -1;
        }
        _h.gain = Math.max(5, Math.min(60, _g));
        @SM@.updateHeadTrack({flick_gain: _h.gain});
        require('react-native').ToastAndroid.show(
          'Flick sensitivity ' + _h.gain,
          require('react-native').ToastAndroid.SHORT,
        );
        break;
      }
      case 'headInvertX': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        _h.invx = _h.invx ? 0 : 1;
        @SM@.updateHeadTrack({invert_x: _h.invx});
        break;
      }
      case 'headInvertY': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        _h.invy = _h.invy ? 0 : 1;
        @SM@.updateHeadTrack({invert_y: _h.invy});
        break;
      }
      case 'headPause': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        _h.paused = !_h.paused;
        @SM@.headPause(_h.paused);
        break;
      }
      case 'headRecord': {
        const _h: any = (globalThis as any).__xsHead || ((globalThis as any).__xsHead = {});
        _h.rec = !_h.rec;
        @SM@.headRecord(_h.rec);
        break;
      }'''

MENU = [
    ("recenterHead", "Re-centre head"),
    ("switchHeadCamera", "Head: switch front/rear camera"),
    ("switchHeadMode", "Head: switch Hold/Flick"),
    ("headSensUp", "Head: Flick sensitivity +"),
    ("headSensDown", "Head: Flick sensitivity -"),
    ("headInvertX", "Head: invert left/right"),
    ("headInvertY", "Head: invert up/down"),
    ("headPause", "Head: pause/resume"),
    ("headRecord", "Head: record CSV log"),
]


def patch_native_stream():
    path = "src/pages/NativeStream.tsx"
    text, crlf = read(path)
    if MARK in text:
        print("  skip (already patched):", path)
        return
    kw = ("tiltOn", "tiltActive", "startTilt", "recenterTilt", "sensor_mode", "case '")

    # native module accessor = whatever object the tilt patch calls startTilt on
    m = one(text, r"([A-Za-z_$][\w$.]*)\.startTilt\s*\(", path, "<module>.startTilt(...) call", kw)
    sm = m.group(1)

    # 1. tiltOn line -> add headOn
    m = one(text, r"const\s+tiltOn\s*=\s*([^;]+);", path, "const tiltOn = ...;", kw)
    expr = m.group(1).strip()
    sv = re.search(r"([A-Za-z_$][\w$]*)\.sensor_mode", expr)
    if not sv:
        die("Could not work out the settings variable name from: " + expr, path, text, kw)
    sv = sv.group(1)
    head_expr = re.sub(r"(sensor_mode\s*={2,3}\s*)1", r"\g<1>2", expr)
    if head_expr == expr:
        die("tiltOn expression has no 'sensor_mode === 1' to derive headOn from: " + expr, path, text, kw)
    text = splice(text, m.end(), m.end(), "\n      const headOn = %s;  // HEADTRACK" % head_expr)

    # 2. tiltActive gate: reuse it so the gyro gate / scale bypass applies to head mode
    m = one(text, r"tiltActive\.current\s*=\s*tiltOn\s*;", path, "tiltActive.current = tiltOn;", kw)
    text = splice(text, m.start(), m.end(), "tiltActive.current = tiltOn || headOn;")

    # 3. start branch
    m = one(text, r"\bif\s*\(\s*tiltOn\s*\)\s*\{", path, "if (tiltOn) { ... } start block", kw)
    text = splice(text, m.start(), m.end(), JS_START.replace("@S@", sv).replace("@SM@", sm))

    # 4. menu items (shown only in head mode)
    pat = (r"(?P<indent>[ \t]*)if\s*\((?P<cond>[^\n]*?sensor_mode\s*={2,3}\s*1[^\n]*?)\)\s*\{\s*"
           r"(?P<arr>[A-Za-z_$][\w$.]*)\.push\(\s*\{[^{}]*?id:\s*['\"]recenterTilt['\"][^{}]*\}\s*\)\s*;?\s*\}")
    m = one(text, pat, path, "the 'recenterTilt' menu item block", kw, re.S)
    ind, cond, arr = m.group("indent"), m.group("cond"), m.group("arr")
    cond2 = re.sub(r"(sensor_mode\s*={2,3}\s*)1", r"\g<1>2", cond)
    uses_t = re.search(r"title:\s*t\(", m.group(0)) is not None
    lines = ["", "%sif (%s) {  // HEADTRACK" % (ind, cond2)]
    for mid, title in MENU:
        ttl = ("t(%s)" % js_str(title)) if uses_t else js_str(title)
        lines.append("%s  %s.push({" % (ind, arr))
        lines.append("%s    id: %s," % (ind, js_str(mid)))
        lines.append("%s    title: %s," % (ind, ttl))
        lines.append("%s  });" % ind)
    lines.append("%s}" % ind)
    text = splice(text, m.end(), m.end(), "\n".join(lines))

    # 5. menu actions, inserted just before the existing recenterTilt case
    m = one(text, r"case\s+'recenterTilt'", path, "case 'recenterTilt':", kw)
    line_start = text.rfind("\n", 0, m.start()) + 1
    case_ind = re.match(r"[ \t]*", text[line_start:]).group(0)
    new_cases = JS_CASES.replace("@SM@", sm)
    # JS_CASES is written with 6-space indentation; re-indent to match the file
    new_cases = "\n".join((case_ind + ln[6:]) if ln.startswith("      ") else ln for ln in new_cases.split("\n"))
    text = splice(text, m.start(), m.start(), new_cases + "\n" + case_ind)

    write(path, text, crlf)
    print("  patched", path, "(settings var: %s, module: %s)" % (sv, sm))


# ----------------------------------------------------------------------------------------------
# 5. Manifest / gradle / proguard
# ----------------------------------------------------------------------------------------------

def patch_manifest():
    path = "android/app/src/main/AndroidManifest.xml"
    text, crlf = read(path)
    if MARK in text:
        print("  skip (already patched):", path)
        return
    kw = ("<manifest", "<application", "uses-permission")
    add_top = []
    if "android.permission.CAMERA" not in text:
        add_top.append('<uses-permission android:name="android.permission.CAMERA" />')
    if 'android.hardware.camera"' not in text:
        add_top.append('<uses-feature android:name="android.hardware.camera" android:required="false" />')
    if "android.hardware.camera.front" not in text:
        add_top.append('<uses-feature android:name="android.hardware.camera.front" android:required="false" />')
    m = one(text, r"<manifest\b[^>]*>", path, "<manifest ...> opening tag", kw)
    block = "\n    <!-- HEADTRACK -->\n" + "".join("    %s\n" % a for a in add_top)
    text = splice(text, m.end(), m.end(), block.rstrip("\n"))

    add_app = []
    for lib in ("libOpenCL.so", "libOpenCL-pixel.so"):
        if lib not in text:
            add_app.append('<uses-native-library android:name="%s" android:required="false" />' % lib)
    m = one(text, r"<application\b[^>]*[^/]>", path, "<application ...> opening tag", kw)
    if add_app:
        block = "\n        <!-- HEADTRACK: OpenCL for the MediaPipe GPU delegate (Android 12+) -->\n" + \
                "\n".join("        %s" % a for a in add_app)
        text = splice(text, m.end(), m.end(), block)
    write(path, text, crlf)
    print("  patched", path)


def patch_app_gradle():
    path = "android/app/build.gradle"
    text, crlf = read(path)
    if MARK in text:
        print("  skip (already patched):", path)
        return
    kw = ("dependencies", "android {", "packagingOptions", "implementation")
    m = one(text, r"(?m)^dependencies\s*\{", path, "top-level dependencies { block", kw)
    deps = (
        "\n    // HEADTRACK: camera + face landmarks\n"
        "    implementation \"androidx.camera:camera-core:1.3.4\"\n"
        "    implementation \"androidx.camera:camera-camera2:1.3.4\"\n"
        "    implementation \"androidx.camera:camera-lifecycle:1.3.4\"\n"
        "    implementation \"androidx.lifecycle:lifecycle-runtime:2.6.2\"\n"
        "    implementation \"com.google.mediapipe:tasks-vision:0.10.14\""
    )
    text = splice(text, m.end(), m.end(), deps)
    m = one(text, r"(?m)^android\s*\{", path, "top-level android { block", kw)
    pk = ("\n    // HEADTRACK: React Native and MediaPipe both ship libc++_shared.so\n"
          "    packagingOptions {\n        pickFirst '**/libc++_shared.so'\n    }")
    text = splice(text, m.end(), m.end(), pk)
    write(path, text, crlf)
    print("  patched", path)


def bump_sdk_levels():
    """MediaPipe tasks-vision needs minSdk 24; CameraX 1.3.x needs compileSdk 34."""
    path = "android/build.gradle"
    p = pathlib.Path(path)
    if not p.exists():
        print("  note: android/build.gradle not found; check minSdk>=24 / compileSdk>=34 yourself")
        return
    text, crlf = read(path)
    changed = False
    for key, need in (("minSdkVersion", 24), ("compileSdkVersion", 34), ("targetSdkVersion", 0)):
        if need == 0:
            continue
        m = re.search(r"(%s\s*=\s*)(\d+)" % key, text)
        if not m:
            print("  note: could not find %s in android/build.gradle (ext may live elsewhere): need >= %d" % (key, need))
            continue
        if int(m.group(2)) < need:
            print("  raising %s %s -> %d" % (key, m.group(2), need))
            text = splice(text, m.start(2), m.end(2), str(need))
            changed = True
        else:
            print("  %s = %s (ok)" % (key, m.group(2)))
    if changed:
        write(path, text, crlf)


def patch_proguard():
    path = "android/app/proguard-rules.pro"
    p = pathlib.Path(path)
    text, crlf = read(path) if p.exists() else ("", False)
    if "com.google.mediapipe" in text:
        print("  skip (already patched):", path)
        return
    text = text.rstrip("\n") + (
        "\n\n# HEADTRACK: R8 breaks MediaPipe without these\n"
        "-keep class com.google.mediapipe.** { *; }\n"
        "-keep class com.google.protobuf.** { *; }\n"
        "-dontwarn com.google.mediapipe.**\n"
        "-dontwarn com.google.protobuf.**\n")
    write(path, text, crlf)
    print("  patched", path)


# ----------------------------------------------------------------------------------------------
def main():
    if not pathlib.Path("android").is_dir() or not pathlib.Path("src").is_dir():
        die("Run this from the repo root (the folder that contains android/ and src/).")
    print("1/6 new Java classes")
    for name, src in JAVA.items():
        new_file("%s/%s.java" % (JAVA_DIR, name), src)
    print("2/6 SensorModule.java")
    patch_sensor_module()
    print("3/6 settings")
    patch_sensor_ts()
    patch_setting_store()
    print("4/6 NativeStream.tsx")
    patch_native_stream()
    print("5/6 manifest / gradle / proguard")
    patch_manifest()
    patch_app_gradle()
    patch_proguard()
    print("6/6 sdk levels")
    bump_sdk_levels()
    print("\nSUCCESS: head tracking patch applied.")


if __name__ == "__main__":
    main()
