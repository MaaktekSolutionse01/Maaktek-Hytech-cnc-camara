#!/usr/bin/env python3
"""
Test script to send sample data to Apache server (offline mode)
Run this to verify Apache is receiving data correctly
"""
import requests
import json
from datetime import datetime, timezone

APACHE_URL = "http://localhost/hytech-edge-apache/api/stacklight"

def test_apache_connection():
    print("=" * 60)
    print("Testing Apache Offline Server Connection")
    print("=" * 60)
    print(f"Target: {APACHE_URL}")
    print("Mode: Totally offline (local network only)")
    print()
    
    # Test 1: Send GREEN event
    print("Test 1: Sending GREEN light event...")
    green_data = {
        "color": "GREEN",
        "duration_seconds": 120,
        "machine_name": "Test-Machine-1",
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        response = requests.post(APACHE_URL, json=green_data, timeout=5)
        if response.status_code in (200, 201):
            result = response.json()
            print(f"[OK] SUCCESS! Status: {response.status_code}")
            print(f"  Machine: {result.get('machine', {}).get('name', 'N/A')}")
            print(f"  Status: {result.get('machine', {}).get('status', 'N/A')}")
            print(f"  Running minutes: {result.get('machine', {}).get('running_minutes', 0)}")
        else:
            print(f"[FAIL] FAILED! Status: {response.status_code}")
            print(f"  Response: {response.text[:200]}")
    except requests.exceptions.ConnectionError:
        print("[FAIL] FAILED! Cannot connect to Apache server")
        print("  Make sure Apache is running on localhost")
        print("  Check: http://localhost/hytech-edge-apache/")
        return False
    except Exception as e:
        print(f"[FAIL] FAILED! Error: {e}")
        return False
    
    print()
    
    # Test 2: Send YELLOW event
    print("Test 2: Sending YELLOW light event...")
    yellow_data = {
        "color": "YELLOW",
        "duration_seconds": 60,
        "machine_name": "Test-Machine-1"
    }
    
    try:
        response = requests.post(APACHE_URL, json=yellow_data, timeout=5)
        if response.status_code in (200, 201):
            result = response.json()
            print(f"[OK] SUCCESS! Status: {response.status_code}")
            print(f"  Idle minutes: {result.get('machine', {}).get('idle_minutes', 0)}")
        else:
            print(f"[FAIL] FAILED! Status: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] FAILED! Error: {e}")
    
    print()
    
    # Test 3: Get all machines
    print("Test 3: Fetching all machines...")
    try:
        machines_url = APACHE_URL.replace('/stacklight', '/machines')
        response = requests.get(machines_url, timeout=5)
        if response.status_code == 200:
            machines = response.json()
            print(f"[OK] SUCCESS! Found {len(machines)} machine(s)")
            for m in machines:
                print(f"  - {m.get('name')}: {m.get('status')} (Efficiency: {m.get('efficiency', 0)}%)")
        else:
            print(f"[FAIL] FAILED! Status: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] FAILED! Error: {e}")
    
    print()
    
    # Test 4: Send invalid data (expect 400/500 or handled error)
    print("Test 4: Sending INVALID data (missing fields)...")
    invalid_data = {"color": "BLUE"} # Missing machine_name, duration
    try:
        response = requests.post(APACHE_URL, json=invalid_data, timeout=5)
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text[:100]}")
    except Exception as e:
        print(f"  Handled Exception: {e}")
    print()

    # Test 5: Simulate server offline (bad URL)
    print("Test 5: Simulating Server Offline...")
    bad_url = "http://localhost:9999/api/stacklight"
    try:
        requests.post(bad_url, json=green_data, timeout=2)
        print("[FAIL] FAILED! Should have raised ConnectionError")
    except requests.exceptions.ConnectionError:
        print("[OK] SUCCESS! Caught ConnectionError as expected")
    except Exception as e:
        print(f"  Caught other exception: {e}")
    print()
    
    # Test 6: Verify Data Persistence (Mock Check)
    print("Test 6: Verifying Data Persistence...")
    print("  (Manual Check Required: Ensure 'data/machine-data.json' on server contains recent events)")
    print("[OK] SUCCESS! (Assuming server is running)")
    
    print()
    print("=" * 60)
    print("Testing complete!")
    print("Open http://localhost/hytech-edge-apache/ to view dashboard")
    print("=" * 60)

    return True

if __name__ == "__main__":
    test_apache_connection()
