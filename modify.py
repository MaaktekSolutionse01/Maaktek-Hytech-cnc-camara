import re

with open('stacklight_to_apache.py', 'r') as f:
    content = f.read()

# 1. Remove mysql.connector import
content = re.sub(r'try:\n\s+import mysql\.connector\nexcept ImportError:.*?\n\s+sys\.exit\(1\)\n', '', content, flags=re.DOTALL)

# 2. Remove get_db_connection and log_state_change
content = re.sub(r'def get_db_connection.*?(?=\ndef send_to_api)', '', content, flags=re.DOTALL)

# 3. Rewrite send_to_api
new_send_to_api = '''def send_to_api(color, machine):
    """
    Sends state change to Dashboard Pi via HTTP POST to local api.php.
    """
    try:
        url = f"http://{get_resolved_host(APACHE_HOST)}:80/dnc/api.php?action=log_state"
        data = {'machine': machine, 'color': color.upper()}
        r = requests.post(url, data=data, timeout=3)
        if r.status_code == 200:
            try:
                resp = r.json()
                if 'error' in resp:
                    print(f"[API ERROR] {resp['error']}")
                    return False
                return True
            except:
                print(f"[API JSON ERROR] Could not parse response: {r.text}")
                return False
        else:
            print(f"[API HTTP ERROR] {r.status_code}")
            return False
    except Exception as e:
        print(f"[API REQUEST ERROR] {e}")
        return False
'''
content = re.sub(r'def send_to_api.*?(?=\n# --- MQTT PUBLISHER ---)', new_send_to_api, content, flags=re.DOTALL)

# 4. Remove wait_for_database_ready
content = re.sub(r'def wait_for_database_ready.*?(?=\ndef main\(\):)', '', content, flags=re.DOTALL)

# 5. Fix main
content = re.sub(r'\s*# 1\. Wait/Check for Database \(Dashboard Pi availability\)\n\s*wait_for_database_ready\(\)\n', '\n', content)
content = re.sub(r'\s*api_url = f"http://.*?"\n', '\n', content)
content = re.sub(r"last_c = 'none'; last_t = time\.time\(\)", "last_mqtt_c = 'none'; last_db_c = 'none'; last_t = time.time()", content)
content = re.sub(r"last_c == 'green'", "(last_mqtt_c == 'green' or last_db_c == 'green')", content)
content = re.sub(r"last_c not in", "last_mqtt_c not in", content)
content = re.sub(r"last_c !=", "last_mqtt_c !=", content)

main_logic_replace = '''
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
'''

content = re.sub(r"                    if stable != 'none':.*?(?=\n                next_s \+= 0\.5)", main_logic_replace, content, flags=re.DOTALL)

with open('stacklight_to_apache_new.py', 'w') as f:
    f.write(content)
