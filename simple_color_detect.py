#!/usr/bin/env python3
"""
Simple BGR-based color detection function
Replace the detect_color_from_frame function with this code
"""
import numpy as np

def detect_color_from_frame_simple(picam2, presence: float):
    """Capture a frame and detect color using SIMPLE BGR detection.
    
    Returns:
        tuple: (color_name, weights_dict)
    """
    frame_bgr = picam2.capture_array()
    H, W = frame_bgr.shape[:2]
    
    # Use center region of frame (60% of image)
    roi_w = int(W * 0.6)
    roi_h = int(H * 0.6)
    roi_x = max(0, (W - roi_w) // 2)
    roi_y = max(0, (H - roi_h) // 2)
    roi_bgr = frame_bgr[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
    
    # Calculate average BGR values in ROI
    b_mean = float(np.mean(roi_bgr[:, :, 0]))  # Blue channel
    g_mean = float(np.mean(roi_bgr[:, :, 1]))  # Green channel
    r_mean = float(np.mean(roi_bgr[:, :, 2]))  # Red channel
    
    # Calculate total brightness
    total = b_mean + g_mean + r_mean
    
    # Minimum brightness threshold to detect any color
    if total < 100:  # Too dark, no color visible
        return 'none', {'red': 0.0, 'yellow': 0.0, 'green': 0.0}
    
    # Normalize to get color ratios
    b_ratio = b_mean / total
    g_ratio = g_mean / total
    r_ratio = r_mean / total
    
    # Simple BGR-based color detection
    # RED: High R, Low G, Low B
    # GREEN: Low R, High G, Low B  
    # YELLOW/ORANGE: High R, High G, Low B
    
    weights = {}
    
    # Red detection: R should be dominant
    if r_ratio > 0.45 and g_ratio < 0.35 and b_ratio < 0.35:
        weights['red'] = r_ratio
    else:
        weights['red'] = 0.0
    
    # Yellow/Orange detection: Both R and G should be high, B low
    if r_ratio > 0.35 and g_ratio > 0.35 and b_ratio < 0.30:
        weights['yellow'] = (r_ratio + g_ratio) / 2.0
    else:
        weights['yellow'] = 0.0
    
    # Green detection: G should be dominant
    if g_ratio > 0.45 and r_ratio < 0.35 and b_ratio < 0.35:
        weights['green'] = g_ratio
    else:
        weights['green'] = 0.0
    
    # Find dominant color
    if max(weights.values()) > 0:
        dominant = max(weights.items(), key=lambda kv: kv[1])[0]
        current_color = dominant
    else:
        current_color = 'none'
    
    print(f"[BGR] B={b_mean:.1f} G={g_mean:.1f} R={r_mean:.1f} | Ratios: B={b_ratio:.2f} G={g_ratio:.2f} R={r_ratio:.2f}")
    
    return current_color, weights
