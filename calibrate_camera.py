#!/usr/bin/env python3
"""
Camera HSV Calibration Tool for Stacklight Detection
For IMX219 Camera V2 - Auto-tune ColourGains for TRUE COLORS
"""
from picamera2 import Picamera2
import cv2
import numpy as np
import json
import time
from pathlib import Path

# Camera settings
CAMERA_RESOLUTION = (320, 240)
CAMERA_FORMAT = "BGR888"
CONFIG_FILE = str(Path(__file__).parent / "config.json")

# ROI Settings (same as main script)
ROI_W_PCT = 0.15
ROI_H_PCT = 0.65

def init_camera():
    """Initialize camera with manual controls"""
    c = Picamera2()
    cfg = c.create_still_configuration(main={"size": CAMERA_RESOLUTION, "format": CAMERA_FORMAT})
    c.configure(cfg)
    
    # Manual control for consistent calibration
    c.set_controls({
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": 5000,
        "AnalogueGain": 0.8,
        "ColourGains": (1.5, 1.5)  # Start with neutral
    })
    
    c.start()
    time.sleep(2)
    print("[CAMERA] Ready for calibration")
    return c

def get_zone_hsv_stats(frame, roi_x, roi_y, roi_w, roi_h):
    """Get HSV statistics for each zone"""
    zh = roi_h // 3
    zones = {
        'red': (roi_y, zh),
        'yellow': (roi_y + zh, zh),
        'green': (roi_y + 2*zh, roi_h - 2*zh)
    }
    
    stats = {}
    for name, (y_start, height) in zones.items():
        crop = frame[y_start:y_start+height, roi_x:roi_x+roi_w]
        if crop.size == 0:
            stats[name] = {'h_mean': 0, 's_mean': 0, 'v_mean': 0}
            continue
        
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        
        stats[name] = {
            'h_mean': int(np.mean(h)),
            's_mean': int(np.mean(s)),
            'v_mean': int(np.mean(v))
        }
    
    return stats

def main():
    print("=" * 60)
    print("STACKLIGHT CAMERA HSV CALIBRATION TOOL")
    print("=" * 60)
    print("\nINSTRUCTIONS:")
    print("1. Turn on ONE light at a time")
    print("2. Press R = Calibrate RED light")
    print("3. Press Y = Calibrate YELLOW light")
    print("4. Press G = Calibrate GREEN light")
    print("5. Press S = Save calibration to config.json")
    print("6. Press Q = Quit")
    print("=" * 60)
    
    cam = init_camera()
    
    calibration_data = {
        'red': None,
        'yellow': None,
        'green': None,
        'camera_settings': {
            'exposure_time': 5000,
            'analogue_gain': 0.8,
            'colour_gains': [1.5, 1.5]
        }
    }
    
    try:
        while True:
            frame = cam.capture_array()
            if frame is None:
                continue
            
            H, W = frame.shape[:2]
            
            # Calculate ROI
            roi_w = int(W * ROI_W_PCT)
            roi_h = int(H * ROI_H_PCT)
            roi_x = (W - roi_w) // 2
            roi_y = (H - roi_h) // 2
            
            # Get zone statistics
            stats = get_zone_hsv_stats(frame, roi_x, roi_y, roi_w, roi_h)
            
            # Draw ROI and zones
            cv2.rectangle(frame, (roi_x, roi_y), (roi_x+roi_w, roi_y+roi_h), (255, 0, 0), 2)
            
            zh = roi_h // 3
            zones_coords = {
                'red': (roi_y, zh, (0, 0, 255)),
                'yellow': (roi_y + zh, zh, (0, 255, 255)),
                'green': (roi_y + 2*zh, roi_h - 2*zh, (0, 255, 0))
            }
            
            y_offset = 20
            for name, (y_start, height, color) in zones_coords.items():
                cv2.rectangle(frame, (roi_x, y_start), (roi_x+roi_w, y_start+height), color, 1)
                
                # Display HSV values
                h_mean = stats[name]['h_mean']
                s_mean = stats[name]['s_mean']
                v_mean = stats[name]['v_mean']
                
                text = f"{name.upper()}: H={h_mean:3d} S={s_mean:3d} V={v_mean:3d}"
                cv2.putText(frame, text, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
                y_offset += 15
            
            # Display calibration status
            y_offset += 10
            for color_name in ['red', 'yellow', 'green']:
                status = "✓ SAVED" if calibration_data[color_name] else "- NOT SET"
                text_color = (0, 255, 0) if calibration_data[color_name] else (0, 0, 255)
                cv2.putText(frame, f"{color_name.upper()}: {status}", (10, y_offset), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1)
                y_offset += 15
            
            cv2.imshow("HSV Calibration", frame)
            
            # Print real-time stats
            print(f"\rRED: H={stats['red']['h_mean']:3d} S={stats['red']['s_mean']:3d} V={stats['red']['v_mean']:3d} | "
                  f"YELLOW: H={stats['yellow']['h_mean']:3d} S={stats['yellow']['s_mean']:3d} V={stats['yellow']['v_mean']:3d} | "
                  f"GREEN: H={stats['green']['h_mean']:3d} S={stats['green']['s_mean']:3d} V={stats['green']['v_mean']:3d}", end='')
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('r'):
                calibration_data['red'] = stats['red'].copy()
                print(f"\n[SAVED] RED calibration: {stats['red']}")
            
            elif key == ord('y'):
                calibration_data['yellow'] = stats['yellow'].copy()
                print(f"\n[SAVED] YELLOW calibration: {stats['yellow']}")
            
            elif key == ord('g'):
                calibration_data['green'] = stats['green'].copy()
                print(f"\n[SAVED] GREEN calibration: {stats['green']}")
            
            elif key == ord('s'):
                if all(calibration_data[c] is not None for c in ['red', 'yellow', 'green']):
                    # Generate COLOR_BANDS from calibration
                    red_h = calibration_data['red']['h_mean']
                    yellow_h = calibration_data['yellow']['h_mean']
                    green_h = calibration_data['green']['h_mean']
                    
                    # Load existing config to preserve settings
                    existing_config = {}
                    if Path(CONFIG_FILE).exists():
                        try:
                            with open(CONFIG_FILE, 'r') as f:
                                existing_config = json.load(f)
                        except: pass

                    # Update with new calibration data
                    # DYNAMIC RED BAND GENERATION
                    # Handle wraparound if Red is near 0/180, otherwise simple +/- 15
                    red_bands = []
                    if red_h < 15:
                        # Near 0: Wrap to high end (e.g. 0-25 AND 165-180)
                        red_bands.append((0, red_h + 15))
                        red_bands.append((180 - (15 - red_h), 180))
                    elif red_h > 165:
                        # Near 180: Wrap to low end
                        red_bands.append((red_h - 15, 179))
                        red_bands.append((0, 15 - (179 - red_h)))
                    else:
                        # Normal case (e.g. 120) - Just use the range
                        red_bands.append((red_h - 15, red_h + 15))

                    existing_config['calibration'] = calibration_data
                    existing_config['color_bands'] = {
                            'red': red_bands,
                            'yellow': [(max(0, yellow_h - 10), min(179, yellow_h + 10))],
                            'green': [(max(0, green_h - 15), min(179, green_h + 15))]
                    }
                    existing_config['camera_settings'] = calibration_data['camera_settings']
                    
                    with open(CONFIG_FILE, 'w') as f:
                        json.dump(existing_config, f, indent=4)
                    
                    print(f"\n[SUCCESS] Calibration saved to {CONFIG_FILE}")
                    print(f"Suggested COLOR_BANDS:")
                    print(f"  red:    {existing_config['color_bands']['red']}")
                    print(f"  yellow: {existing_config['color_bands']['yellow']}")
                    print(f"  green:  {existing_config['color_bands']['green']}")
                else:
                    print("\n[ERROR] Please calibrate all three colors first!")
            
            elif key == ord('q'):
                print("\n[EXIT] Calibration tool closed")
                break
    
    except KeyboardInterrupt:
        print("\n[EXIT] Interrupted")
    finally:
        cam.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
