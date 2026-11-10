#!/usr/bin/env python3
"""Applies the XStreaming tilt-mode edits. Run from the repo root.
Stops with a clear message if any 'find' text does not match exactly once."""
import pathlib
import re
import sys


def patch(path, edits, sm=None):
    p = pathlib.Path(path)
    if not p.exists():
        print(f"MISSING FILE: {path}")
        sys.exit(1)
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    for i, (find, repl) in enumerate(edits, 1):
        if sm:
            repl = repl.replace("@SM@", sm)
        n = text.count(find)
        if n != 1:
            print(f"FAILED: {path} edit {i}: find text matched {n} times (needs exactly 1)")
            print("First line of find text:", find.strip().splitlines()[0])
            sys.exit(1)
        text = text.replace(find, repl, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))
    print(f"OK: {path} ({len(edits)} edits)")


# ---------------------------------------------------------------- FILE 1
patch(
    "android/app/src/main/java/com/xstreaming/SensorModule.java",
    [
        # 1.1 fields
        (
            """    private boolean lastWasZero = true;

    public SensorModule(""",
            """    private boolean lastWasZero = true;

    // ---- Tilt mode ----
    private boolean recenterPending = true;
    private float tiltRangeRad = (float) Math.toRadians(30);
    private float tiltDeadRad = (float) Math.toRadians(2);
    private float tiltInvX = 1f;
    private float tiltInvY = 1f;
    private float baseRoll = 0f;
    private float basePitch = 0f;
    private float tiltFX = 0f;
    private float tiltFY = 0f;
    private long lastTiltEmit = 0;
    private final float[] tiltR = new float[9];
    private static final float TILT_ALPHA = 0.35f;

    public SensorModule(""",
        ),
        # 1.2 tilt methods
        (
            """    @ReactMethod
    public void stopSensor() {""",
            """    @ReactMethod
    public void startTilt(int rangeDeg, int deadzoneDeg, boolean invertX, boolean invertY) {
        Log.d("SensorModule", "startTilt");
        tiltRangeRad = (float) Math.toRadians(Math.max(5, rangeDeg));
        tiltDeadRad = (float) Math.toRadians(Math.max(0, deadzoneDeg));
        tiltInvX = invertX ? -1f : 1f;
        tiltInvY = invertY ? -1f : 1f;
        tiltFX = 0f;
        tiltFY = 0f;
        recenterPending = true;
        lastWasZero = true;
        if (sensorManager != null) {
            Sensor rot = sensorManager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR);
            if (rot != null) {
                sensorManager.registerListener(this, rot, SensorManager.SENSOR_DELAY_GAME);
            }
        }
    }

    @ReactMethod
    public void recenter() {
        recenterPending = true;
    }

    private float tiltAxis(float d) {
        float a = Math.abs(d);
        if (a < tiltDeadRad) return 0f;
        float v = (a - tiltDeadRad) / (tiltRangeRad - tiltDeadRad);
        if (v > 1f) v = 1f;
        return d < 0 ? -v : v;
    }

    private void handleTilt(SensorEvent event) {
        SensorManager.getRotationMatrixFromVector(tiltR, event.values);
        // direction of world "up" in device coordinates
        float ux = tiltR[6], uy = tiltR[7], uz = tiltR[8];
        // sx = "up" component toward screen-right, sy = "up" component toward screen-up
        float sx, sy;
        switch (getDisplayRotation()) {
            case Surface.ROTATION_90:  sx = -uy; sy = ux;  break;
            case Surface.ROTATION_270: sx = uy;  sy = -ux; break;
            case Surface.ROTATION_180: sx = -ux; sy = -uy; break;
            default:                   sx = ux;  sy = uy;  break;
        }
        float roll = (float) Math.atan2(sx, sy);
        float pitch = (float) Math.asin(Math.max(-1f, Math.min(1f, uz)));

        if (recenterPending) {
            baseRoll = roll;
            basePitch = pitch;
            tiltFX = 0f;
            tiltFY = 0f;
            recenterPending = false;
        }

        float dRoll = roll - baseRoll;
        while (dRoll > Math.PI) dRoll -= 2 * Math.PI;
        while (dRoll < -Math.PI) dRoll += 2 * Math.PI;
        float dPitch = pitch - basePitch;

        float x = -tiltAxis(dRoll) * tiltInvX;
        float y = tiltAxis(dPitch) * tiltInvY;
        tiltFX = TILT_ALPHA * x + (1f - TILT_ALPHA) * tiltFX;
        tiltFY = TILT_ALPHA * y + (1f - TILT_ALPHA) * tiltFY;

        long now = SystemClock.elapsedRealtime();
        if (now - lastTiltEmit < MIN_EMIT_INTERVAL_MS) return;

        int ox = Math.round(tiltFX * 32767f);
        int oy = Math.round(tiltFY * 32767f);
        if (Math.abs(ox) < 150) ox = 0;
        if (Math.abs(oy) < 150) oy = 0;

        if (ox == 0 && oy == 0) {
            if (lastWasZero) return;
            lastWasZero = true;
        } else {
            lastWasZero = false;
        }
        lastTiltEmit = now;

        WritableMap params = Arguments.createMap();
        params.putDouble("x", ox);
        params.putDouble("y", oy);
        sendEvent("SensorData", params);
    }

    @ReactMethod
    public void stopSensor() {""",
        ),
        # 1.3 route sensor events
        (
            """        if (event.sensor.getType() == Sensor.TYPE_GYROSCOPE) {""",
            """        if (event.sensor.getType() == Sensor.TYPE_GAME_ROTATION_VECTOR) {
            handleTilt(event);
            return;
        }
        if (event.sensor.getType() == Sensor.TYPE_GYROSCOPE) {""",
        ),
    ],
)

# ---------------------------------------------------------------- FILE 2
patch(
    "src/common/settings/sensor.ts",
    [
        (
            """  {
    name: 'sensor_type',""",
            """  {
    name: 'sensor_mode',
    type: 'radio',
    title: t('Gyro mode'),
    description: t('Motion moves the stick while the phone moves, Tilt holds it at the phone angle (use with Device)'),
    data: [
      {value: 0, text: t('Motion')},
      {value: 1, text: t('Tilt')},
    ],
  },
  {
    name: 'tilt_range_deg',
    type: 'slider',
    min: 10,
    max: 60,
    step: 5,
    title: t('Tilt range in degrees'),
    description: t('Angle that gives full stick deflection'),
    data: [],
  },
  {
    name: 'tilt_deadzone_deg',
    type: 'slider',
    min: 0,
    max: 10,
    step: 1,
    title: t('Tilt deadzone in degrees'),
    description: t('Angle around neutral that is ignored'),
    data: [],
  },
  {
    name: 'sensor_type',""",
        ),
    ],
)

# ---------------------------------------------------------------- FILE 3
patch(
    "src/store/settingStore.ts",
    [
        (
            """  sensor_invert: number;""",
            """  sensor_invert: number;
  sensor_mode: number;
  tilt_range_deg: number;
  tilt_deadzone_deg: number;""",
        ),
        (
            """  sensor_invert: 0,""",
            """  sensor_invert: 0,
  sensor_mode: 0,
  tilt_range_deg: 30,
  tilt_deadzone_deg: 2,""",
        ),
    ],
)

# ---------------------------------------------------------------- FILE 4
ns_path = pathlib.Path("src/pages/NativeStream.tsx")
ns_text = ns_path.read_text(encoding="utf-8") if ns_path.exists() else ""
if re.search(r"\bSensorModule\b", ns_text):
    SM = "SensorModule"
else:
    SM = "require('react-native').NativeModules.SensorModule"
print("Using native module reference:", SM)

patch(
    "src/pages/NativeStream.tsx",
    [
        # 4a ref
        (
            """  const gyroStick = React.useRef({x: 0, y: 0});""",
            """  const gyroStick = React.useRef({x: 0, y: 0});
  const tiltActive = React.useRef(false);""",
        ),
        # 4b start tilt
        (
            """      sensorManager.startSensor(
        _settings.sensor_sensitivity_x,
        _settings.sensor_sensitivity_y,
      );""",
            """      const tiltOn = _settings.sensor === 1 && _settings.sensor_mode === 1;
      tiltActive.current = tiltOn;
      if (tiltOn) {
        @SM@.startTilt(
          _settings.tilt_range_deg || 30,
          _settings.tilt_deadzone_deg ?? 2,
          false,
          false,
        );
      } else {
        sensorManager.startSensor(
          _settings.sensor_sensitivity_x,
          _settings.sensor_sensitivity_y,
        );
      }""",
        ),
        # 4c ignore trigger gate
        (
            """            isGyroTriggerActive = true;""",
            """            isGyroTriggerActive = true;
          }
          if (tiltActive.current) {
            isGyroTriggerActive = true;""",
        ),
        # 4d no extra scaling
        (
            """              x: Number((stickX * scaleX).toFixed(3)),
              y: Number((stickY * scaleY).toFixed(3)),""",
            """              x: Number((stickX * (tiltActive.current ? 1 : scaleX)).toFixed(3)),
              y: Number((stickY * (tiltActive.current ? 1 : scaleY)).toFixed(3)),""",
        ),
        # 4e menu item
        (
            """      items.push({
        id: 'pressNexus',""",
            """      if (settings.sensor === 1 && settings.sensor_mode === 1) {
        items.push({
          id: 'recenterTilt',
          title: t('Re-centre tilt'),
        });
      }
      items.push({
        id: 'pressNexus',""",
        ),
        # 4e handler
        (
            """      case 'pressNexus':""",
            """      case 'recenterTilt':
        @SM@.recenter();
        break;
      case 'pressNexus':""",
        ),
    ],
    sm=SM,
)

# ------------------------------------------- install next to the original app
gp = pathlib.Path("android/app/build.gradle")
if gp.exists():
    g = gp.read_text(encoding="utf-8")
    g2, n = re.subn(r"(applicationId\s+[\"'])([^\"']+)([\"'])", r"\1\2.tilt\3", g, count=1)
    if n:
        gp.write_text(g2, encoding="utf-8")
        print("applicationId now ends with .tilt (installs next to the original app)")
    else:
        print("WARNING: applicationId not found; uninstall the original app before installing")

print("ALL PATCHES APPLIED")
