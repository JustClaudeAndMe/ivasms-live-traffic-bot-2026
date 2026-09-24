#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
ivasms_manager.py - Automatic iVasms numbers management and synchronization module
================================================================================
Standalone module that provides:
1. Sync and pull account numbers and store them in the bot database (combos).
2. Search the site's global repository for available countries and prices, and add new ranges.
3. Return and delete exhausted numbers from the site and the bot database.
4. Check the session and cookies and extract the CSRF security token automatically.
"""

import os
import re
import json
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = "https://www.ivasms.com"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot1.db")
COOKIES_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mafia_ck_4235.json")


def find_latest_cookie_txt():
    """Find the most recently downloaded cookie file"""
    import glob
    download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    candidates = glob.glob(os.path.join(download_dir, "*cookie*.txt")) if os.path.isdir(download_dir) else []
    if not candidates:
        candidates = glob.glob(os.path.join(os.getcwd(), "*cookie*.txt"))
    if not candidates:
        return None
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


COOKIES_TXT = find_latest_cookie_txt()

# Import country map and smart helpers from country_data
from country_data import COUNTRY_CODES, get_country_details_smart, get_app_badge, get_service_display

# Backward compatibility
COUNTRY_CODES_MAP = {k: (v[0], v[1]) for k, v in COUNTRY_CODES.items()}


def get_session():
    """Create a requests session that exactly matches a Chrome browser and set the cookies"""
    session = requests.Session()
    hdrs = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        'sec-ch-ua': '"Chromium";v="152", "Google Chrome";v="152", "Not-A.Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'X-Requested-With': 'XMLHttpRequest',
    }
    active_headers_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_headers.json")
    if os.path.exists(active_headers_file):
        try:
            with open(active_headers_file, 'r', encoding='utf-8') as f:
                saved_hdrs = json.load(f)
                if isinstance(saved_hdrs, dict):
                    for k in ['User-Agent', 'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform']:
                        if k in saved_hdrs and saved_hdrs[k]:
                            hdrs[k] = saved_hdrs[k]
        except Exception:
            pass
    hdrs['Accept'] = 'application/json, text/javascript, */*; q=0.01'
    hdrs['X-Requested-With'] = 'XMLHttpRequest'
    session.headers.update(hdrs)

    # 1. Check the most recently downloaded cookie text file in the Downloads folder
    latest_txt = find_latest_cookie_txt()
    if latest_txt and os.path.exists(latest_txt):
        try:
            with open(latest_txt, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain = parts[0].lstrip('.')
                        name = parts[5]
                        value = parts[6]
                        path = parts[2]
                        session.cookies.set(name, value, domain=domain, path=path)
                        session.cookies.set(name, value, domain='www.ivasms.com', path=path)
                        session.cookies.set(name, value, domain='.ivasms.com', path=path)
            return session
        except Exception:
            pass

    # 2. Check the JSON file
    if os.path.exists(COOKIES_JSON):
        try:
            with open(COOKIES_JSON, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            for c in cookies:
                domain = c.get('domain', 'www.ivasms.com').lstrip('.')
                session.cookies.set(c['name'], c['value'], domain=domain, path=c.get('path', '/'))
                session.cookies.set(c['name'], c['value'], domain='www.ivasms.com', path=c.get('path', '/'))
                session.cookies.set(c['name'], c['value'], domain='.ivasms.com', path=c.get('path', '/'))
            return session
        except Exception:
            pass

    return None


def get_csrf_token(session=None):
    """Extract the CSRF Token from the dashboard page"""
    if session is None:
        session = get_session()
    if not session:
        return None
    try:
        r = session.get(f"{BASE_URL}/portal/numbers", headers={'Accept': 'text/html'}, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            meta = soup.find('meta', {'name': 'csrf-token'})
            if meta:
                return meta.get('content')
            match = re.search(r'name=["\'](?:_token|csrf-token)["\']\s+value=["\']([^"\']+)["\']', r.text)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def check_ivasms_status():
    """Check the connection and account status and return a brief report"""
    session = get_session()
    if not session:
        return {
            'ok': False,
            'message': '❌ Could not find the cookies file.'
        }
    try:
        ajax_headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }
        r = session.get(f"{BASE_URL}/portal/numbers", params={'draw': 1, 'start': 0, 'length': 1}, headers=ajax_headers, timeout=20)
        if r.status_code == 403:
            return {'ok': False, 'message': '❌ Cookies are expired (403 Cloudflare).'}
        if "login" in r.url.lower():
            return {'ok': False, 'message': '⚠️ Redirected to login page (session expired).'}
        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                if "login" in r.text.lower():
                    return {'ok': False, 'message': '⚠️ Redirected to login page.'}
                return {'ok': False, 'message': '❌ Invalid response from the site (make sure to renew cookies).'}
            total_my_numbers = data.get('recordsTotal', 0)
            return {
                'ok': True,
                'status_code': 200,
                'my_numbers_count': total_my_numbers,
                'message': f'🟢 Connection active | You have {total_my_numbers} numbers in your account.'
            }
        return {'ok': False, 'message': f'❌ Unexpected response: {r.status_code}'}
    except Exception as e:
        return {'ok': False, 'message': f'❌ Connection error: {str(e)}'}


def get_all_my_numbers():
    """Fetch a list of all numbers currently added to your iVasms account"""
    session = get_session()
    if not session:
        return False, "❌ No active session.", []

    try:
        ajax_headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }
        # Fetch the first 500 numbers
        r = session.get(f"{BASE_URL}/portal/numbers", params={'draw': 1, 'start': 0, 'length': 500}, headers=ajax_headers, timeout=25)
        if r.status_code != 200:
            return False, f"Response code: {r.status_code}", []

        try:
            data = r.json()
        except Exception:
            return False, "Could not read the numbers data from the site (invalid response).", []

        raw_list = data.get('data', [])
        clean_numbers = []

        for item in raw_list:
            num_val = item.get('Number') or item.get('number') or ''
            num_clean = re.sub(r'<[^>]+>', '', str(num_val)).strip().lstrip('+')
            range_name = item.get('range') or item.get('range_name') or ''
            rate = item.get('A2P') or item.get('rate') or ''

            num_id = item.get('id') or ''
            if not num_id and 'number_id' in item:
                m = re.search(r'value=["\'](\d+)["\']', str(item.get('number_id')))
                if m:
                    num_id = m.group(1)

            if num_clean and num_clean.isdigit():
                clean_numbers.append({
                    'id': num_id,
                    'number': num_clean,
                    'range_name': range_name,
                    'rate': rate
                })

        return True, "Fetched successfully", clean_numbers
    except Exception as e:
        return False, f"Error: {str(e)}", []


def sync_numbers_to_bot_combos(default_service="All Apps"):
    """Pull all numbers from iVasms and add them directly to the combos table in bot1.db, linking the app"""
    ok, msg, numbers_list = get_all_my_numbers()
    if not ok:
        return False, msg, {}

    if not numbers_list:
        return True, "Your account has no numbers to pull right now.", {}

    # Classify numbers by country code using get_country_details_smart
    grouped = {}
    for item in numbers_list:
        num = item['number']
        rg_name = item.get('range_name', '')
        c_code, c_name, flag, short = get_country_details_smart(num, rg_name)

        if c_code not in grouped:
            grouped[c_code] = {'numbers': [], 'name': c_name, 'flag': flag, 'short': short}
        if num not in grouped[c_code]['numbers']:
            grouped[c_code]['numbers'].append(num)

    # Save the numbers into bot1.db
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        saved_summary = {}

        for c_code, info in grouped.items():
            nums = info['numbers']
            # Find the maximum combo_index
            c.execute("SELECT MAX(combo_index) FROM combos WHERE country_code=?", (c_code,))
            res = c.fetchone()[0]
            next_index = 1 if res is None else res + 1

            nums_json = json.dumps(nums, ensure_ascii=False)
            c.execute("INSERT INTO combos (country_code, combo_index, numbers, service) VALUES (?, ?, ?, ?)",
                      (c_code, next_index, nums_json, default_service))
            saved_summary[c_code] = len(nums)

        conn.commit()
        conn.close()
        return True, f"✅ Pulled and stored {len(numbers_list)} numbers successfully!", saved_summary
    except Exception as e:
        return False, f"❌ Error while saving to the database: {str(e)}", {}


def search_test_numbers(country_query, limit=10):
    """Search the global numbers repository for a specific country or range"""
    session = get_session()
    if not session:
        return False, "❌ No active session.", []

    query = str(country_query).strip().lstrip('+')
    try:
        # Search using DataTables search
        params = {
            'draw': 1,
            'start': 0,
            'length': limit,
            'search[value]': query
        }
        r = session.get(f"{BASE_URL}/portal/numbers/test", params=params, timeout=25)
        if r.status_code != 200:
            return False, f"Response code: {r.status_code}", []

        data = r.json()
        records = data.get('data', [])
        results = []

        for row in records:
            range_name = row.get('range', '')
            test_num = row.get('test_number', '')
            rate = row.get('A2P', '')
            term = row.get('term', '')
            row_id = row.get('id', '')

            # Filter the results to ensure they match the query
            if query.lower() in range_name.lower() or query in test_num or query in str(row_id):
                results.append({
                    'id': row_id,
                    'range': range_name,
                    'test_number': test_num,
                    'rate': rate,
                    'term': term
                })

        # If strict filtering returns nothing, return the records as the server returned them
        if not results and records:
            for row in records[:limit]:
                results.append({
                    'id': row.get('id'),
                    'range': row.get('range'),
                    'test_number': row.get('test_number'),
                    'rate': row.get('A2P'),
                    'term': row.get('term')
                })

        return True, f"Found {len(results)} available ranges.", results
    except Exception as e:
        return False, f"❌ Search error: {str(e)}", []


def add_range_to_account(range_id):
    """Add a numbers range to your iVasms account programmatically with one click"""
    session = get_session()
    if not session:
        return False, "❌ No active session."

    csrf = get_csrf_token(session)
    if not csrf:
        return False, "❌ Could not extract the CSRF Token."

    url = f"{BASE_URL}/portal/numbers/termination/number/add"
    payload = {
        'id': str(range_id),
        '_token': csrf
    }
    headers = {
        'Referer': f"{BASE_URL}/portal/numbers/test",
        'Origin': BASE_URL,
        'X-CSRF-TOKEN': csrf,
        'X-Requested-With': 'XMLHttpRequest'
    }

    try:
        resp = session.post(url, data=payload, headers=headers, timeout=25)
        if resp.status_code == 200:
            res_json = resp.json()
            msg = res_json.get('message', 'Numbers added successfully!')
            return True, msg
        else:
            return False, f"Request failed with code: {resp.status_code}"
    except Exception as e:
        return False, f"Error while adding: {str(e)}"


def return_all_numbers_from_system():
    """Return all numbers and delete them from the iVasms account and the bot database"""
    session = get_session()
    if not session:
        return False, "❌ No active session."

    csrf = get_csrf_token(session)
    if not csrf:
        return False, "❌ Could not extract the CSRF Token."

    url = f"{BASE_URL}/portal/numbers/return/allnumber/bluck"
    payload = {'_token': csrf}
    headers = {
        'Referer': f"{BASE_URL}/portal/numbers",
        'Origin': BASE_URL,
        'X-CSRF-TOKEN': csrf,
        'X-Requested-With': 'XMLHttpRequest'
    }

    try:
        resp = session.post(url, data=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            # Empty the combos table in the bot
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("DELETE FROM combos")
                conn.commit()
                conn.close()
            except Exception:
                pass
            return True, "✅ All numbers were returned to the system and the combos were fully cleared!"
        return False, f"Return failed (code: {resp.status_code})"
    except Exception as e:
        return False, f"❌ Error while returning: {str(e)}"


def return_single_number_from_system(number_id):
    """Return a single specific number to the system"""
    session = get_session()
    if not session:
        return False, "❌ No active session."

    csrf = get_csrf_token(session)
    if not csrf:
        return False, "❌ Could not extract the CSRF Token."

    url = f"{BASE_URL}/portal/numbers/return/number/bluck"
    payload = {
        'NumberID[]': [str(number_id)],
        '_token': csrf
    }
    headers = {
        'Referer': f"{BASE_URL}/portal/numbers",
        'Origin': BASE_URL,
        'X-CSRF-TOKEN': csrf,
        'X-Requested-With': 'XMLHttpRequest'
    }

    try:
        resp = session.post(url, data=payload, headers=headers, timeout=25)
        if resp.status_code == 200:
            return True, "✅ Number returned to the system successfully."
        return False, f"Return failed (code: {resp.status_code})"
    except Exception as e:
        return False, f"❌ Error: {str(e)}"


def get_top_terminations():
    """Fetch the currently most active ranges on the dashboard (Top Ranges)"""
    session = get_session()
    if not session:
        return False, "❌ No active session.", []
    try:
        r = session.get(f"{BASE_URL}/portal/top_terminations", timeout=20)
        if r.status_code == 200:
            data = r.json()
            items = data.get('data', [])
            return True, f"Found {len(items)} active ranges.", items
        return False, f"Response code: {r.status_code}", []
    except Exception as e:
        return False, f"Error: {str(e)}", []


def get_top_ranges_by_app(app_name, limit=25):
    """Fetch ranges and countries currently receiving messages for a specific app (WhatsApp, TikTok, etc.) with smart country details"""
    session = get_session()
    if not session:
        return False, "❌ No active session.", []
    try:
        r = session.get(
            f"{BASE_URL}/portal/sms/test/sms",
            params={'app': app_name, 'draw': 1, 'start': 0, 'length': limit},
            timeout=25
        )
        if r.status_code == 200:
            data = r.json()
            rows = data.get('data', [])
            active_ranges = {}
            for row in rows:
                range_name = str(row.get('range') or '').strip()
                term_id = row.get('termination_id', '')
                time_str = str(row.get('senttime') or '')

                term_obj = row.get('termination') or {}
                test_num_raw = term_obj.get('test_number', '')
                test_number = re.sub(r'<[^>]+>', '', str(test_num_raw)).strip().lstrip('+')

                if range_name and range_name not in active_ranges:
                    c_code, c_name, flag, short = get_country_details_smart(test_number, range_name)
                    time_display = time_str.split()[-1] if time_str else ''

                    active_ranges[range_name] = {
                        'range': range_name,
                        'id': term_id,
                        'last_seen': time_display,
                        'full_time': time_str,
                        'test_number': test_number,
                        'country_code': c_code,
                        'country_name': c_name,
                        'flag': flag,
                        'short': short,
                        'app': app_name
                    }
            results = list(active_ranges.values())
            return True, f"Found {len(results)} active ranges for {app_name}.", results
        return False, f"Response code: {r.status_code}", []
    except Exception as e:
        return False, f"Error: {str(e)}", []


def add_range_and_sync_to_bot(range_id, app_name='WhatsApp', range_name=''):
    """Activate the range on iVasms, pull its numbers instantly, and save them in the bot with the app and number count"""
    session = get_session()
    if not session:
        return False, "❌ No active session for iVasms.", {}

    # 1. Activate the range on the site
    ok, msg = add_range_to_account(range_id)
    if not ok:
        return False, f"❌ Failed to activate the range on the site: {msg}", {}

    import time
    time.sleep(1.5)

    # 2. Fetch the account numbers
    ok_nums, msg_nums, all_nums = get_all_my_numbers()
    if not ok_nums or not all_nums:
        return False, f"⚠️ Range activated but could not fetch numbers immediately: {msg_nums}", {}

    # 3. Filter numbers for the target range
    matched = []
    if range_name:
        matched = [x for x in all_nums if str(x.get('range_name', '')).strip().lower() == range_name.strip().lower()]

    if not matched:
        matched = all_nums

    num_strings = [x['number'] for x in matched]
    if not num_strings:
        return False, "⚠️ No new numbers were found in your account.", {}

    sample_num = num_strings[0]
    c_code, c_name, flag, short = get_country_details_smart(sample_num, range_name)

    # 4. Save the combo into the bot database
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT MAX(combo_index) FROM combos WHERE country_code=?", (c_code,))
        res = c.fetchone()[0]
        next_idx = 1 if res is None else res + 1

        nums_json = json.dumps(num_strings, ensure_ascii=False)
        c.execute("INSERT INTO combos (country_code, combo_index, numbers, service) VALUES (?, ?, ?, ?)",
                  (c_code, next_idx, nums_json, app_name))
        conn.commit()
        conn.close()

        summary = {
            'count': len(num_strings),
            'country_code': c_code,
            'country_name': c_name,
            'flag': flag,
            'short': short,
            'service': app_name,
            'combo_index': next_idx,
            'range_name': range_name or f"{c_name} Range",
            'sample_number': sample_num
        }
        return True, f"✅ Activated and pulled range {summary['range_name']} ({len(num_strings)} numbers) successfully!", summary
    except Exception as e:
        return False, f"❌ Error saving the combo in the bot: {str(e)}", {}


def fetch_live_stream_messages(limit=25):
    """
    Pull live messages directly from iVasms that the site is receiving moment by moment for all apps
    """
    session = get_session()
    if not session:
        return []

    try:
        import html as _html
        ajax_headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01'
        }
        r = session.get(
            f"{BASE_URL}/portal/sms/test/sms",
            params={'draw': 1, 'start': 0, 'length': limit},
            headers=ajax_headers,
            timeout=15
        )
        if r.status_code != 200:
            return []

        try:
            data = r.json()
        except Exception:
            return []

        rows = data.get('data', [])
        clean_messages = []

        for row in rows:
            msg_id = row.get('id') or row.get('DT_RowId')
            if not msg_id:
                continue

            orig_raw = str(row.get('originator') or '')
            app_match = re.search(r'<p[^>]*>([^<]+)</p>', orig_raw)
            if app_match:
                app_name = app_match.group(1).strip()
            else:
                app_clean = re.sub(r'<script.*?</script>', '', orig_raw, flags=re.DOTALL)
                app_clean = re.sub(r'<[^>]+>', '', app_clean).strip()
                app_name = app_clean if app_clean else "SMS"

            term_obj = row.get('termination') or {}
            test_num_raw = str(term_obj.get('test_number') or '')
            number = re.sub(r'<[^>]+>', '', test_num_raw).strip().lstrip('+')
            if not number:
                continue

            raw_msg = str(row.get('messagedata') or '')
            clean_text = _html.unescape(raw_msg).strip()

            range_name = str(row.get('range') or '').strip()
            sent_time = str(row.get('senttime') or '').strip()

            c_code, c_name, flag, short = get_country_details_smart(number, range_name)

            clean_messages.append({
                'id': str(msg_id),
                'number': number,
                'app': app_name,
                'text': clean_text,
                'range': range_name,
                'time': sent_time,
                'country_code': c_code,
                'country_name': c_name,
                'flag': flag,
                'short': short
            })

        return clean_messages
    except Exception as e:
        print(f"[!] Error fetching live stream: {e}")
        return []
