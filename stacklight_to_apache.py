try:
    from picamera2 import Picamera2
    HAS_PICAMERA2 = True
    HAS_LEGACY_PICAMERA = False
except ImportError:
    HAS_PICAMERA2 = False
    try:
        import picamera
        HAS_LEGACY_PICAMERA = True
        print("[SYSTEM] Picamera2 not found. Using legacy Picamera (Buster).")
    except ImportError:
        HAS_LEGACY_PICAMERA = False
        print("[SYSTEM] Picamera/Picamera2 not found. Falling back to OpenCV capture.")

import time
import cv2
import numpy as np
import sys
from datetime import datetime, timezone
import requests
import argparse
import json
import os
from typing import Optional, Tuple
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except Exception as e:
    print(f"[MQTT DEBUG] Failed to import paho-mqtt: {e}")
    import traceback
    traceback.print_exc()
    MQTT_AVAILABLE = False


# ----------------------------
# CONFIGURATION
# ----------------------------

APACHE_HOST = "raspberrypi.local"
APACHE_PORT = 5000
APACHE_API_PATH = "/api"

MQTT_HOST = "raspberrypi.local"
MQTT_PORT = 1883
MQTT_TOPIC = "hytech/stacklight"
MQTT_HEARTBEAT_TOPIC = "hytech/camera/heartbeat"
LAST_MQTT_HEARTBEAT_TIME = 0

DEFAULT_INGEST_TOKEN = os.environ.get("INGEST_TOKEN")

# Pi Zero W Optimized Resolution
CAMERA_RESOLUTION = (320, 240)
CAMERA_FORMAT = "BGR888"

MACHINE_NAME_FILE = str(Path.home() / ".stacklight" / "machine_name.txt")
CONFIG_FILE = str(Path(__file__).parent / "config.json")

CONFIG = {}
APACHE_HOST = "raspberrypi.local"
APACHE_PORT = 80
APACHE_API_PATH = "/dnc/api.php"
MQTT_HOST = "raspberrypi.local"
MQTT_PORT = 1883
MQTT_TOPIC = "hytech/stacklight"
CONFIG_RELOAD_INTERVAL = 30  # re-read config.json so machine_name changes apply live


def reload_runtime_config() -> None:
    """Reload config.json (machine_name, hosts, MQTT). Called at startup and periodically."""
    global CONFIG, APACHE_HOST, APACHE_PORT, APACHE_API_PATH, MQTT_HOST, MQTT_PORT, MQTT_TOPIC, MQTT_HEARTBEAT_TOPIC
    if not os.path.exists(CONFIG_FILE):
        print(f"[CONFIG] Missing {CONFIG_FILE}")
        return
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            CONFIG = json.load(f)
    except Exception as e:
        print(f"[CONFIG] Error loading config: {e}")
        return
    APACHE_HOST = CONFIG.get("apache_host", "raspberrypi.local")
    APACHE_PORT = CONFIG.get("apache_port", 80)
    APACHE_API_PATH = CONFIG.get("api_path", "/dnc/api.php")
    MQTT_HOST = CONFIG.get("mqtt_host", "raspberrypi.local")
    MQTT_PORT = int(CONFIG.get("mqtt_port", 1883))
    MQTT_TOPIC = CONFIG.get("mqtt_topic", "hytech/stacklight")
    MQTT_HEARTBEAT_TOPIC = CONFIG.get("mqtt_heartbeat_topic", "hytech/camera/heartbeat")


def get_configured_machine_name() -> str:
    """machine_name from config.json only — no hardcoded default."""
    name = str(CONFIG.get("machine_name", "")).strip()
    if not name:
        raise ValueError("config.json must contain a non-empty 'machine_name'")
    return name


reload_runtime_config()

# ROI Settings (Camera V2 Fisheye/Wide alignment)
ROI_X = None      
ROI_Y = None      
ROI_W_PCT = 0.15
ROI_H_PCT = 0.65

# Natural detection thresholds
SAT_THRESHOLD = 40
VAL_THRESHOLD = 60
MIN_PIXELS = 10
DOMINANCE_RATIO = 0.30

# Fallback/Heuristic safety
SCENE_MIN_VAL = 1500
HEURISTIC_MIN_PIXELS = 1200

# Standard natural HSV bands (green widened for easier detection)
# RED and YELLOW may be overridden by config.json calibration
# GREEN is NEVER changed - it stays exactly as defined here
COLOR_BANDS = {
    'red':    [(0, 10), (170, 179)],
    'yellow': [(15, 35)],
    'green':  [(35, 95)]   # widen green range - NEVER OVERRIDE THIS
}

# ----------------------------
# COLOR DETECTION LOGIC
# ----------------------------

def detect_color_from_frame(picam2, show_roi: bool = False) -> tuple[str, dict]:
    """
    detect_color_from_frame with Per-Color Thresholds and Fallback Heuristics.
    """
    global ROI_X, ROI_Y, ROI_W_PCT, ROI_H_PCT
    
    # Capture
    if HAS_PICAMERA2:
        frame_bgr = picam2.capture_array()
    elif HAS_LEGACY_PICAMERA:
        # Legacy Picamera capture
        import picamera.array
        with picamera.array.PiRGBArray(picam2) as stream:
            picam2.capture(stream, format='bgr')
            frame_bgr = stream.array
    else:
        # OpenCV fallback capture
        ret, frame_bgr = picam2.read()
        if not ret: frame_bgr = None
    if frame_bgr is None: return 'none', {'decision': 'Capture failed'}
    H, W = frame_bgr.shape[:2]
    
    # ROI Calculation
    rw = int(W * ROI_W_PCT); rh = int(H * ROI_H_PCT)
    rx = int(ROI_X) if ROI_X is not None else (W - rw) // 2
    ry = int(ROI_Y) if ROI_Y is not None else (H - rh) // 2
    rx = max(0, min(rx, W - 1)); ry = max(0, min(ry, H - 1))
    rw = max(1, min(rw, W - rx)); rh = max(1, min(rh, H - ry))
    
    # SPLIT into 3 ZONES
    zh = rh // 3
    zones = {
        'red':    (ry, zh),
        'yellow': (ry + zh, zh),
        'green':  (ry + 2*zh, rh - 2*zh)
    }

    stats = {}
    for name, (y_s, h_s) in zones.items():
        crop = frame_bgr[y_s:y_s+h_s, rx:rx+rw]
        if crop.size == 0: stats[name] = (0, 0); continue
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        v_mask = (s >= SAT_THRESHOLD) & (v >= VAL_THRESHOLD)
        val_px = np.count_nonzero(v_mask)
        bands = COLOR_BANDS[name]
        hue_mask = np.zeros(h.shape, dtype=np.uint8)
        for (lo, hi) in bands:
            if lo > hi: hue_mask |= ((h >= lo) | (h <= hi)).astype(np.uint8)
            else: hue_mask |= ((h >= lo) & (h <= hi)).astype(np.uint8)
        col_px = np.count_nonzero(v_mask & (hue_mask > 0))
        stats[name] = (val_px, col_px)
    
    # Compute BGR means for ROI and each zone
    roi = frame_bgr[ry:ry+rh, rx:rx+rw]
    if roi.size > 0:
        b_mean, g_mean, r_mean = [int(x) for x in cv2.mean(roi)[:3]]
    else:
        b_mean = g_mean = r_mean = 0
    
    zone_means = {}
    for name, (y_s, h_s) in zones.items():
        z = frame_bgr[y_s:y_s+h_s, rx:rx+rw]
        if z.size > 0:
            zb, zg, zr = [int(x) for x in cv2.mean(z)[:3]]
        else:
            zb = zg = zr = 0
        zone_means[name] = (zb, zg, zr)

    # Winner zone by brightness
    winner_name = max(stats, key=lambda k: stats[k][0])
    w_val, w_col = stats[winner_name]
    ratio = w_col / float(w_val) if w_val > 0 else 0.0
    
    # 1. Scene Brightness Gate (Stop false detections in dark/OFF scenes)
    r_val, r_col = stats['red']
    y_val, y_col = stats['yellow']
    g_val, g_col = stats['green']
    total_val = r_val + y_val + g_val
    
    # GREEN vs YELLOW dominance override
    green_dominant = False
    if g_val > 0 and y_val > 0:
        green_ratio = g_col / float(g_val)
        yellow_ratio = y_col / float(y_val)
        # If green ratio is clearly stronger than yellow, prefer green
        if green_ratio >= yellow_ratio + 0.05 and g_val >= HEURISTIC_MIN_PIXELS:
            green_dominant = True
    
    # Override winner if green is dominant
    if green_dominant:
        winner_name = 'green'
        w_val, w_col = stats['green']
        ratio = w_col / float(w_val) if w_val > 0 else 0.0
    
    # SATURATION MODE - Pick highest col_px when all zones saturated
    if r_val >= 2300 and y_val >= 2300 and g_val >= 2300:
        # All zones bright → choose by color pixels, but ignore zero
        candidates = {
            'red':   r_col,
            'yellow': y_col,
            'green':  g_col
        }
        # remove colors with 0 pixels
        candidates = {k:v for k,v in candidates.items() if v > 0}
        if candidates:
            detected = max(candidates, key=candidates.get)
            ratio = candidates[detected] / float(stats[detected][0]) if stats[detected][0] > 0 else 0.0
            msg = f"SATURATION MODE: {detected.upper()} (col_px: R={r_col} Y={y_col} G={g_col})"
            
            # CYAN/GREENISH BRIGHT OVERRIDE:
            # If saturation mode chose YELLOW but BGR shows pattern like (0,255,255) or (55,254,254),
            # force GREEN (green LED appearing yellowish due to saturation).
            if detected == 'yellow':
                # Pattern: first channel low, second and third channels very high and close
                if (b_mean < 100 and g_mean > 200 and r_mean > 200 and
                    abs(g_mean - r_mean) < 60):
                    detected = 'green'
                    msg = f"SATURATION MODE: FORCING GREEN by BGR (ROI=({b_mean}, {g_mean}, {r_mean}))"
        else:
            # If all color pixels are zero, try a simple BGR-based fallback:
            # Check if any channel is dominant (handles potential BGR channel swap)
            max_channel = max(b_mean, g_mean, r_mean)
            min_channel = min(b_mean, g_mean, r_mean)
            
            if (stats['red'][0] >= 2000 and        # bright scene
                max_channel > 150 and              # One channel is high
                max_channel > min_channel + 80):   # Strong dominance
                detected = 'red'
                msg = f"SATURATION MODE: FORCING RED by BGR (ROI=({b_mean}, {g_mean}, {r_mean}))"
            else:
                detected = 'none'
                msg = f"SATURATION MODE: NO COLOR (col_px all zero R={r_col} Y={y_col} G={g_col})"
    elif total_val < SCENE_MIN_VAL:
        detected = 'none'
        msg = f"Too dark / OFF scene (total_val={total_val})"
    else:
        # 2. Main Decision with Per-Color Dominance
        eff_ratio = DOMINANCE_RATIO
        if winner_name == 'red':    eff_ratio = max(0.05, DOMINANCE_RATIO)  # 5% enough
        elif winner_name == 'yellow': eff_ratio = max(0.05, DOMINANCE_RATIO - 0.25)  # 5% enough
        elif winner_name == 'green':  eff_ratio = 0.05   # always 5% for green

        detected = 'none'
        if w_val >= MIN_PIXELS and ratio >= eff_ratio:
            detected = winner_name
            msg = f"[ROI] Using {winner_name.upper()}_ROI ({w_val} valid px)"
        else:
            # 3. Fallback Heuristics (GREEN priority with very easy threshold)
            # (a) GREEN FIRST - very easy detection (3% threshold)
            if g_val >= HEURISTIC_MIN_PIXELS and g_col >= (0.03 * g_val):
                detected = 'green'
                ratio = g_col / float(g_val)
                msg = f"[ROI] Heuristic: forcing GREEN ({g_val} px, ratio {ratio:.2f})"
            # (b) YELLOW SECOND - 6% ratio (slightly harder than green)
            elif y_val >= HEURISTIC_MIN_PIXELS and y_col >= (0.06 * y_val):
                detected = 'yellow'
                ratio = y_col / float(y_val)
                msg = f"[ROI] Heuristic: forcing YELLOW ({y_val} px, ratio {ratio:.2f})"
            # (c) Strong RED (Guarded against ambient noise)
            elif r_val >= HEURISTIC_MIN_PIXELS and r_col >= (0.40 * r_val):
                # Only force RED if Y and G are truly quiet
                if y_col < (0.10 * y_val) and g_col < (0.10 * g_val):
                    detected = 'red'
                    ratio = r_col / float(r_val)
                    msg = f"[ROI] Heuristic: forcing RED ({r_val} px, ratio {ratio:.2f})"
                else:
                    detected = 'none'
                    msg = f"Ambiguous (RED wins with {w_val} px but Y/G also active)"
            else:
                msg = f"Ambiguous ({winner_name.upper()} wins with {w_val} px, Ratio {ratio:.2f})" if w_val >= MIN_PIXELS else f"Too dark ({w_val} px)"

    debug_info = {
        'stats': stats, 'ratio': f"{ratio:.2f}", 'raw_ratio': ratio,
        'decision': msg, 'best': winner_name,
        'roi_x': rx, 'roi_y': ry, 'roi_w': rw, 'roi_h': rh,
        'roi_bgr_mean': (b_mean, g_mean, r_mean),
        'zone_bgr_means': zone_means
    }

    if show_roi:
        cv2.rectangle(frame_bgr, (rx, ry), (rx+rw, ry+rh), (255, 0, 0), 1)
        for name, (y_s, h_s) in zones.items():
            active = (name == winner_name) or (name == detected)
            thick = 2 if active else 1
            color = (0,0,255) if name == 'red' else (0,255,255) if name == 'yellow' else (0,255,0)
            cv2.rectangle(frame_bgr, (rx, y_s), (rx+rw, y_s+h_s), color, thick)
        cv2.putText(frame_bgr, f"Win:{winner_name.upper()} Det:{detected.upper()}", (10, H-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
        cv2.imshow("Monitor", frame_bgr)
        key = cv2.waitKey(1) & 0xFF
        if key != 255:
            if key == ord('i'): ROI_Y -= 5
            elif key == ord('k'): ROI_Y += 5
            elif key == ord('j'): ROI_X -= 5
            elif key == ord('l'): ROI_X += 5
            elif key == ord('w'): ROI_H_PCT += 0.01
            elif key == ord('s'): ROI_H_PCT -= 0.01
            elif key == ord('d'): ROI_W_PCT += 0.01
            elif key == ord('a'): ROI_W_PCT -= 0.01
            elif key == ord('r'): ROI_X = None; ROI_Y = None

    return detected, debug_info

# ----------------------------
# CONFIG LOADING
# ----------------------------

def load_camera_config() -> Optional[dict]:
    """Load calibrated camera settings from config.json"""
    try:
        config_path = Path(__file__).parent / "config.json"
        if not config_path.exists():
            return None
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Validate camera_settings
        if "camera_settings" in config:
            cam_settings = config["camera_settings"]
            required_keys = ["exposure_time", "analogue_gain", "colour_gains"]
            if all(k in cam_settings for k in required_keys):
                # Validate colour_gains is a list/tuple of 2 floats
                if isinstance(cam_settings["colour_gains"], (list, tuple)) and len(cam_settings["colour_gains"]) == 2:
                    return config
        return None
    except Exception as e:
        print(f"[WARNING] Failed to load config.json: {e}")
        return None

def apply_calibrated_color_bands(config: dict) -> None:
    """Apply calibrated RED and YELLOW bands from config (GREEN stays unchanged)"""
    global COLOR_BANDS
    try:
        if "color_bands" in config:
            bands = config["color_bands"]
            # Only update RED and YELLOW - NEVER touch GREEN
            if "red" in bands:
                COLOR_BANDS['red'] = bands['red']
                print(f"[CONFIG] Using calibrated RED bands: {COLOR_BANDS['red']}")
            if "yellow" in bands:
                COLOR_BANDS['yellow'] = bands['yellow']
                print(f"[CONFIG] Using calibrated YELLOW bands: {COLOR_BANDS['yellow']}")
            # GREEN is intentionally not loaded from config - it stays as hardcoded
    except Exception as e:
        print(f"[WARNING] Failed to apply color_bands from config: {e}")

# ----------------------------
# SYSTEM & API
# ----------------------------

# ----------------------------
# DATABASE CONNECTION
# ----------------------------

def send_to_api(color, machine):
    """
    Sends state change to Dashboard Pi via HTTP POST to local api.php.
    """
    port = CONFIG.get("apache_port", 80)
    path = CONFIG.get("api_path", "/dnc/api.php")
    if not path.startswith("/"):
        path = "/" + path
    base = f"http://{APACHE_HOST}:{port}{path}"
    url = base if "action=" in base else f"{base}?action=log_state"
    data = {'machine': machine, 'color': color.upper()}
    for attempt in range(3):
        try:
            r = requests.post(url, data=data, timeout=5)
            if r.status_code == 200:
                try:
                    resp = r.json()
                    if 'error' in resp:
                        print(f"[API ERROR] {resp['error']}")
                        return False
                    return True
                except Exception:
                    print(f"[API JSON ERROR] Could not parse response: {r.text}")
                    return False
            print(f"[API HTTP ERROR] {r.status_code} (attempt {attempt + 1}/3)")
        except Exception as e:
            print(f"[API REQUEST ERROR] {e} (attempt {attempt + 1}/3)")
        time.sleep(1)
    return False

# --- MQTT PUBLISHER ---
mqtt_client = None

def init_mqtt():
    global mqtt_client
    if not MQTT_AVAILABLE:
        print("[MQTT] Error: paho-mqtt not installed. Cannot use MQTT.")
        return False
        
    try:
        mqtt_client = mqtt.Client()
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[MQTT] Connected to broker at {MQTT_HOST}:{MQTT_PORT}")
        return True
    except Exception as e:
        print(f"[MQTT] Failed to connect to broker: {e}")
        return False

def send_to_mqtt(color, dur, machine):
    global mqtt_client
    if not mqtt_client:
        return False
        
    try:
        payload = {
            "machine_name": machine,
            "color": color.upper(),
            "duration_seconds": dur,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        json_payload = json.dumps(payload)
        mqtt_client.publish(MQTT_TOPIC, json_payload)
        return True
    except Exception as e:
        print(f"[MQTT] Error publishing: {e}")
        return False
# ----------------------


def send_camera_heartbeat(machine, alive):
    """Periodic MQTT heartbeat: camera device liveness only, NOT color status."""
    global mqtt_client
    if not mqtt_client:
        return
    try:
        payload = json.dumps({
            "machine_name": machine,
            "alive": alive,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        mqtt_client.publish(MQTT_HEARTBEAT_TOPIC, payload)
    except Exception as e:
        print(f"[MQTT HEARTBEAT] Error: {e}")
# ----------------------

def init_camera():
    """Initialize camera with calibrated or auto settings (10 Retries / 1 Min)"""
    # Load calibration config
    config = load_camera_config()
    
    # User requested: "try to connect to my camara 10 time in 1 min"
    # 10 attempts * 6 seconds = 60 seconds
    max_retries = 10
    retry_delay = 6
    
    for attempt in range(max_retries):
        try:
            print(f"[CAMERA] Initialization Attempt {attempt+1}/{max_retries}...")
            
            if HAS_PICAMERA2:
                c = Picamera2()
                cfg = c.create_still_configuration(main={"size": CAMERA_RESOLUTION, "format": CAMERA_FORMAT})
                c.configure(cfg)
                
                # Apply camera controls based on config
                if config and "camera_settings" in config:
                    cam_settings = config["camera_settings"]
                    c.set_controls({
                        "AeEnable": False,
                        "AwbEnable": False,
                        "ExposureTime": int(cam_settings["exposure_time"]),
                        "AnalogueGain": float(cam_settings["analogue_gain"]),
                        "ColourGains": tuple(cam_settings["colour_gains"])
                    })
                    print(f"[CAMERA] Using calibrated manual settings")
                else:
                    c.set_controls({"AeEnable": True, "AwbEnable": True})
                    print("[CAMERA] Using AUTO settings")
                
                # Always load calibrated color bands if available (independent of camera_settings)
                if config:
                    apply_calibrated_color_bands(config)
                
                c.start()
            elif HAS_LEGACY_PICAMERA:
                import picamera
                c = picamera.PiCamera()
                c.resolution = CAMERA_RESOLUTION
                print("[CAMERA] Using legacy PiCamera library")
            else:
                # Use OpenCV fallback for older OS versions
                c = cv2.VideoCapture(0)
                c.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_RESOLUTION[0])
                c.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_RESOLUTION[1])
                if not c.is_opened():
                    raise Exception("Could not open OpenCV VideoCapture")
                print("[CAMERA] Using OpenCV VideoCapture (Buster/Legacy)")

            print("[CAMERA] Settling sensor...")
            time.sleep(2)
            print("[CAMERA] Ready")
            return c
        except Exception as e:
            print(f"[CAMERA] Init fail: {e}")
            if attempt < max_retries - 1:
                print(f"[CAMERA] Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print("[CAMERA] FATAL: Could not initialize camera after 1 minute.")
                
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apache-host", default=None, help="Override apache_host from config.json")
    parser.add_argument("--apache-port", type=int, default=None, help="Override apache_port from config.json")
    parser.add_argument("--show-roi", action="store_true")
    parser.add_argument("--debug-full", action="store_true")
    args = parser.parse_args()

    print("[STARTUP] Waiting additional 30 seconds buffer...")
    time.sleep(30)

    reload_runtime_config()
    global LAST_MQTT_HEARTBEAT_TIME
    if args.apache_host:
        global APACHE_HOST
        APACHE_HOST = args.apache_host
    if args.apache_port is not None:
        global APACHE_PORT
        APACHE_PORT = args.apache_port

    try:
        m_name = get_configured_machine_name()
    except ValueError as e:
        print(f"[FATAL] {e}")
        return

    print(f"[CONFIG] machine_name from config.json: {m_name}")

    Path(MACHINE_NAME_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(MACHINE_NAME_FILE, "w") as f:
        f.write(m_name)

    # 2. Initialize Camera
    cam = init_camera()
    if not cam: return
    
    # 3. Initialize MQTT (Best effort)
    init_mqtt()

    # STABILITY (5 samples window, 3 required for production stability)
    window_pts = 5; majority_req = 3; buffer = []
    
    last_mqtt_c = 'none'; last_db_c = 'none'; last_t = time.time()
    last_real_color_time = time.time()
    OFF_TIMEOUT = 60.0

    print(f"[START] Fixed Monitor: {m_name}")
    print(f"[DB] Ready to write to MariaDB Table 'machine_state'")
    
    last_pulse_time = 0
    last_config_reload = time.time()

    try:
        next_s = time.time()
        while True:
            now = time.time()

            # Re-read config.json so machine_name changes apply without restart
            if now - last_config_reload >= CONFIG_RELOAD_INTERVAL:
                reload_runtime_config()
                try:
                    new_name = get_configured_machine_name()
                    if new_name != m_name:
                        print(f"[CONFIG] machine_name changed: {m_name} -> {new_name}")
                        m_name = new_name
                        with open(MACHINE_NAME_FILE, "w") as f:
                            f.write(m_name)
                        last_mqtt_c = last_db_c = "none"
                except ValueError as e:
                    print(f"[CONFIG] {e}")
                last_config_reload = now
            
            # --- SEPARATE HEARTBEAT PULSE ---
            # Sends a "I am ON" signal every 10 seconds
            if now - last_pulse_time > 10:
                try:
                    port = CONFIG.get("apache_port", 80)
                    path = CONFIG.get("api_path", "/dnc/api.php")
                    if not path.startswith("/"):
                        path = "/" + path
                    base = f"http://{APACHE_HOST}:{port}{path}"
                    sep = "&" if "?" in base else "?"
                    pulse_url = f"{base}{sep}action=camera_pulse&name={m_name}"
                    requests.get(pulse_url, timeout=2)
                    last_pulse_time = now
                except:
                    pass
            # --- MQTT CAMERA HEARTBEAT (device liveness, independent of color) ---
            if now - LAST_MQTT_HEARTBEAT_TIME >= 10:
                send_camera_heartbeat(m_name, True)
                LAST_MQTT_HEARTBEAT_TIME = now
            # -------------------------------------------------------------------
            # -------------------------------

            if now >= next_s:
                raw, dbg = detect_color_from_frame(cam, show_roi=args.show_roi)
                
                if args.debug_full:
                    print(f"ZONES R:{dbg['stats']['red']} Y:{dbg['stats']['yellow']} G:{dbg['stats']['green']} RATIO:{dbg['raw_ratio']:.2f}")
                    print(f"MEAN ROI BGR: {dbg['roi_bgr_mean']}")
                    print(f"ZONE BGR: RED={dbg['zone_bgr_means']['red']} YEL={dbg['zone_bgr_means']['yellow']} GRN={dbg['zone_bgr_means']['green']}")
                
                print(f"[RAW] {raw.upper():<7} | {dbg['decision']}")

                # No smoothing - use raw detection directly
                displayed_raw = raw

                buffer.append(displayed_raw)
                if len(buffer) > window_pts: buffer.pop(0)
                
                # GREEN priority in the temporal window
                counts = {x: buffer.count(x) for x in set(buffer)}
                if counts.get('green', 0) >= 2 and counts.get('yellow', 0) <= 1:
                    # If we saw green at least 2 times and yellow almost never, prefer green
                    stable = 'green'
                else:
                    stable = None
                    if len(buffer) >= window_pts:
                        best = max(counts, key=counts.get)
                        if counts[best] >= majority_req: stable = best

                if stable:
                    # Prevent YELLOW from immediately overriding a recent GREEN
                    MIN_GREEN_HOLD = 1.0  # seconds
                    now = time.time()
                    if stable == 'yellow' and (last_mqtt_c == 'green' or last_db_c == 'green'):
                        if now - last_t < MIN_GREEN_HOLD:
                            # Ignore this yellow; keep reporting green
                            stable = 'green'
                    
                    # Update last_real_color_time if we see a valid color
                    if stable in ('red', 'yellow', 'green'):
                        last_real_color_time = time.time()


                    if stable != 'none':
                        if stable != last_mqtt_c:
                            if last_mqtt_c not in ('none', 'off'):
                                dur = time.time() - last_t
                                send_to_mqtt(last_mqtt_c, dur, m_name)
                            
                            mqtt_ok = send_to_mqtt(stable, 0.0, m_name)
                            if mqtt_ok:
                                print(f"[MQTT] {last_mqtt_c} -> {stable}")
                                last_mqtt_c = stable
                                last_t = time.time()
                            else:
                                print(f"[MQTT FAIL] Retrying next cycle...")
                                
                        if stable != last_db_c:
                            db_ok = send_to_api(stable, m_name)
                            if db_ok:
                                print(f"[DB] {last_db_c} -> {stable}")
                                last_db_c = stable
                            else:
                                print(f"[DB FAIL] Retrying next cycle...")
                    else:
                        if last_mqtt_c != 'off' or last_db_c != 'off':
                            time_since_real = time.time() - last_real_color_time
                            if time_since_real >= OFF_TIMEOUT:
                                print(f"[OFF] Timeout reached ({OFF_TIMEOUT}s)")
                                
                                if last_mqtt_c != 'off':
                                    if send_to_mqtt('off', 0.0, m_name):
                                        print(f"[MQTT] {last_mqtt_c} -> OFF")
                                        last_mqtt_c = 'off'
                                        last_t = time.time()
                                
                                if last_db_c != 'off':
                                    if send_to_api('off', m_name):
                                        print(f"[DB] {last_db_c} -> OFF")
                                        last_db_c = 'off'

                next_s += 0.5
            time.sleep(0.05)
    except KeyboardInterrupt: pass
    finally:
        send_camera_heartbeat(m_name, False)  # Signal device going offline
        if HAS_PICAMERA2:
            cam.stop()
        elif HAS_LEGACY_PICAMERA:
            cam.close()
        else:
            cam.release()

if __name__ == "__main__":
    main()
