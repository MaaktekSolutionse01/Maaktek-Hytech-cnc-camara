#!/usr/bin/env python3
"""
Test Color Detection
Usage: python3 test_color_detection.py <image_file>
"""
import cv2
import numpy as np
import sys
import argparse

# --- COPY OF LOGIC FROM stacklight_to_apache.py ---
ROIS = {
    'red':    (120,  40,  40,  40),
    'yellow': (120, 100,  40,  40),
    'green':  (120, 160,  40,  40),
}

EXPECTED_HUES = {
    'red':    [0, 179],
    'yellow': [25],
    'green':  [70],
}

HUE_TOLERANCE = 20
SAT_THRESHOLD = 50
VAL_THRESHOLD = 50
BRIGHT_V_MIN = 80
BRIGHT_S_MIN = 60

COLOR_BANDS = {
    'red':    [(0, 10), (170, 179)],   
    'yellow': [(15, 35)],              
    'green':  [(36, 100)],             
}

def _hue_mask(h, target_hues):
    mask = np.zeros_like(h, dtype=bool)
    for th in target_hues:
        lower = (th - HUE_TOLERANCE) % 180
        upper = (th + HUE_TOLERANCE) % 180
        if lower < upper:
            m = (h >= lower) & (h <= upper)
        else:
            m = (h >= lower) | (h <= upper)
        mask |= m
    return mask

def bright_color_scores(hsv_roi):
    h, s, v = cv2.split(hsv_roi)
    bright = (v >= BRIGHT_V_MIN) & (s >= BRIGHT_S_MIN)
    bright_count = int(np.count_nonzero(bright))
    if bright_count == 0:
        return {"red": 0.0, "yellow": 0.0, "green": 0.0}, 0
    red_m = bright & _hue_mask(h, EXPECTED_HUES['red'])
    yellow_m = bright & _hue_mask(h, EXPECTED_HUES['yellow'])
    green_m = bright & _hue_mask(h, EXPECTED_HUES['green'])
    scores = {
        "red": float(np.count_nonzero(red_m)) / float(bright_count),
        "yellow": float(np.count_nonzero(yellow_m)) / float(bright_count),
        "green": float(np.count_nonzero(green_m)) / float(bright_count),
    }
    return scores, bright_count

def band_color_scores(hsv_roi):
    h, s, v = cv2.split(hsv_roi)
    mask = (s >= max(30, SAT_THRESHOLD)) & (v >= max(30, VAL_THRESHOLD))
    total_w = float(np.sum(v[mask])) + 1e-6
    scores = {"red": 0.0, "yellow": 0.0, "green": 0.0}
    if total_w <= 1e-6:
        return scores
    for color, bands in COLOR_BANDS.items():
        m_color = np.zeros_like(mask)
        for lo, hi in bands:
            if lo <= hi:
                m_band = (h >= lo) & (h <= hi)
            else:
                m_band = (h >= lo) | (h <= hi)
            m_color |= m_band
        wsum = float(np.sum(v[mask & m_color]))
        scores[color] = wsum / total_w
    return scores

def process_image(image_path):
    print(f"Processing: {image_path}")
    img = cv2.imread(image_path)
    if img is None:
        print("Error: Could not read image")
        return

    # Simulate ROI extraction (taking center crop if no ROI logic applied)
    # But here we just use the whole image as if it were the ROI for testing
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Apply smoothing
    roi_sm = cv2.GaussianBlur(hsv, (5,5), 0)

    bright_scores, _ = bright_color_scores(roi_sm)
    band_scores = band_color_scores(roi_sm)
    
    # Weights (same as main script)
    weights = {}
    for k in ('red','yellow','green'):
        # Note: blob_scores omitted for simplicity in this test script, 
        # but we can add it if needed. For now, just test hue/band logic.
        weights[k] = 0.7*float(band_scores.get(k,0.0)) + 0.3*float(bright_scores.get(k,0.0))
    
    print("-" * 30)
    print(f"Scores for {image_path}:")
    print(f"  RED:    {weights['red']:.4f}")
    print(f"  YELLOW: {weights['yellow']:.4f}")
    print(f"  GREEN:  {weights['green']:.4f}")
    
    dominant = max(weights.items(), key=lambda kv: kv[1])[0]
    print(f"DETECTED: {dominant.upper()}")
    print("-" * 30)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_color_detection.py <image_file>")
        sys.exit(1)
    process_image(sys.argv[1])
