import os
import os

# ✅ CRITICAL FIX: Remove any inherited proxy env vars so requests/telebot
# do NOT route Telegram API calls through the proxy. Only our custom code
# reads IVASMS_PROXY explicitly for iVasms.
for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_proxy_var, None)

from threading import Thread
from flask import Flask

app = Flask("")


@app.route("/")
def home():
    return "Bot is running!"


def run():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)


# Start Flask app in a background thread
Thread(target=run).start()

import time
import requests
from curl_cffi import requests as curl_requests  # ✅ FIX 1: curl_cffi imported
import json
import re
import os
from datetime import datetime, date, timedelta
from urllib.parse import quote_plus
from pathlib import Path
import sqlite3
import telebot
from telebot import types
import threading
import traceback
import random
import itertools
import logging
from locales import (
    get_text,
    get_user_language,
    set_user_language,
    build_language_markup,
    build_admin_language_markup,
    SUPPORTED_LANGUAGES
)
import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# Prevent duplicate cookie expiration message
_cookies_alert_sent = False

# Prevent login conflict from multiple sources
_login_lock = threading.Lock()
_login_in_progress = False
_cookies_expired = False  # When cookies expire, stop all attempts


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(BASE_DIR, "mafia_ck_4235.json")
ACTIVE_HEADERS_FILE = os.path.join(BASE_DIR, "active_headers.json")
_last_cookies_update = None

DEFAULT_DESKTOP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
    'sec-ch-ua': '"Chromium";v="152", "Google Chrome";v="152", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Linux"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'none',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
}

def get_active_headers():
    hdrs = dict(DEFAULT_DESKTOP_HEADERS)
    if os.path.exists(ACTIVE_HEADERS_FILE):
        try:
            with open(ACTIVE_HEADERS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if isinstance(saved, dict) and 'User-Agent' in saved:
                    hdrs.update(saved)
        except Exception:
            pass
    return hdrs


# ✅ PROXY INTEGRATION: helper functions to attach the .env proxy to any session
def get_proxy_url():
    """Return the configured iVasms proxy URL from .env, or None if not set.
    Note: We intentionally use a custom env var name (IVASMS_PROXY) so that
    Python's requests/urllib3/telebot do NOT auto-pick the proxy for Telegram API calls."""
    return os.getenv("IVASMS_PROXY")

def apply_proxy_to_session(session):
    """Attach the proxy from .env to the given curl_cffi session."""
    proxy_url = get_proxy_url()
    if proxy_url:
        session.proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        safe = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
        print(f"[Proxy] Session using proxy: {safe}")
    return session


def save_cookies_to_file(cookies_dict):
    with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(cookies_dict, f, ensure_ascii=False, indent=2)

def load_cookies_from_file():
    import glob
    download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    candidates = glob.glob(os.path.join(download_dir, "*cookie*.txt")) if os.path.isdir(download_dir) else []
    if not candidates:
        candidates = glob.glob(os.path.join(os.getcwd(), "*cookie*.txt"))
    if candidates:
        candidates.sort(key=os.path.getmtime, reverse=True)
        latest_txt = candidates[0]
        try:
            with open(latest_txt, 'r', encoding='utf-8') as f:
                content = f.read()
            parsed = parse_cookies_input(content)
            if parsed:
                return parsed
        except Exception:
            pass

    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Error loading cookies from file: {e}")
    return None

def parse_cookies_input(raw_text):
    """Parse cookies from JSON text or a Netscape (.txt) file"""
    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("The text or file is empty.")

    # 1. Try parsing JSON first
    if raw_text.startswith('[') or raw_text.startswith('{'):
        try:
            data = json.loads(raw_text)
            if isinstance(data, list):
                cookies = []
                for c in data:
                    if isinstance(c, dict) and 'name' in c and 'value' in c:
                        cookies.append({
                            'name': c['name'],
                            'value': c['value'],
                            'domain': c.get('domain', 'www.ivasms.com').lstrip('.'),
                            'path': c.get('path', '/')
                        })
                if cookies:
                    return cookies
            elif isinstance(data, dict):
                return [{'name': k, 'value': str(v), 'domain': 'www.ivasms.com', 'path': '/'} for k, v in data.items()]
        except Exception:
            pass

    # 2. Try parsing Netscape format (Tab-separated)
    cookies = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        elif line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) >= 7:
            domain = parts[0].lstrip('.')
            path = parts[2]
            name = parts[5].strip()
            value = parts[6].strip()
            cookies.append({
                'name': name,
                'value': value,
                'domain': domain,
                'path': path
            })
    if cookies:
        return cookies

    raise ValueError("Could not extract cookies. Make sure to upload a valid Netscape .txt file or paste a valid JSON code.")

UA_PROFILES = [
    {
        "name": "Yandex Browser Mobile (Android)",
        "ua": "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 YaBrowser/24.7.0.0 Mobile",
        "mobile": "?1",
        "platform": '"Android"',
        "brands": '"Chromium";v="128", "Not;A=Brand";v="24", "Yandex";v="24"'
    },
    {
        "name": "Yandex Browser Mobile v24.4 (Android)",
        "ua": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36 YaBrowser/24.4.0.0 Mobile",
        "mobile": "?1",
        "platform": '"Android"',
        "brands": '"Chromium";v="126", "Not;A=Brand";v="24", "Yandex";v="24"'
    },
    {
        "name": "Yandex Browser Desktop Mode (Android/Linux)",
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 YaBrowser/24.7.0.0 Safari/537.36",
        "mobile": "?0",
        "platform": '"Linux"',
        "brands": '"Chromium";v="128", "Not;A=Brand";v="24", "Yandex";v="24"'
    },
    {
        "name": "Yandex Browser Desktop (Windows PC)",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 YaBrowser/24.7.0.0 Safari/537.36",
        "mobile": "?0",
        "platform": '"Windows"',
        "brands": '"Chromium";v="128", "Not;A=Brand";v="24", "Yandex";v="24"'
    },
    {
        "name": "Desktop Linux Chrome",
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        "mobile": "?0",
        "platform": '"Linux"',
        "brands": '"Chromium";v="152", "Google Chrome";v="152", "Not-A.Brand";v="99"'
    },
    {
        "name": "Desktop Windows Chrome",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "mobile": "?0",
        "platform": '"Windows"',
        "brands": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"'
    },
    {
        "name": "Android Mobile Chrome (Kiwi)",
        "ua": "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
        "mobile": "?1",
        "platform": '"Android"',
        "brands": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"'
    },
    {
        "name": "Android Kiwi (Generic)",
        "ua": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
        "mobile": "?1",
        "platform": '"Android"',
        "brands": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"'
    },
    {
        "name": "iPhone Safari Mobile",
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "mobile": "?1",
        "platform": '"iOS"',
        "brands": None
    }
]

def verify_and_test_cookies(cookies_list, preferred_ua=None):
    """Test cookies directly against ivasms.com with multiple UA fingerprints (Yandex, Kiwi, Chrome, Mobile & PC)"""
    if not cookies_list:
        return False, "Cookies list is empty.", None, None

    had_403 = False
    last_err = None

    profiles_to_test = list(UA_PROFILES)
    if preferred_ua:
        is_mob = any(k in preferred_ua for k in ["Mobile", "Android", "iPhone"])
        plat = '"Android"' if "Android" in preferred_ua else ('"iOS"' if "iPhone" in preferred_ua else ('"Windows"' if "Windows" in preferred_ua else '"Linux"'))
        profiles_to_test.insert(0, {
            "name": f"User Custom UA ({preferred_ua[:35]}...)",
            "ua": preferred_ua,
            "mobile": "?1" if is_mob else "?0",
            "platform": plat,
            "brands": '"Chromium";v="128", "Not;A=Brand";v="24", "Yandex";v="24"' if "YaBrowser" in preferred_ua else None
        })

    for profile in profiles_to_test:
        # ✅ FIX 2 + PROXY: Use curl_cffi for the test session and attach proxy
        test_session = curl_requests.Session(impersonate="chrome")
        apply_proxy_to_session(test_session)
        hdrs = {
            'User-Agent': profile['ua'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
        }
        if profile.get('brands'):
            hdrs['sec-ch-ua'] = profile['brands']
        if profile.get('mobile'):
            hdrs['sec-ch-ua-mobile'] = profile['mobile']
        if profile.get('platform'):
            hdrs['sec-ch-ua-platform'] = profile['platform']

        test_session.headers.update(hdrs)

        if isinstance(cookies_list, list):
            for c in cookies_list:
                domain = c.get('domain', 'www.ivasms.com').lstrip('.')
                test_session.cookies.set(c['name'], c['value'], domain=domain, path=c.get('path', '/'))
        elif isinstance(cookies_list, dict):
            for name, value in cookies_list.items():
                test_session.cookies.set(name, value, domain='www.ivasms.com', path='/')

        try:
            resp = test_session.get("https://www.ivasms.com/portal/sms/received", timeout=20, allow_redirects=True)
            if "login" in resp.url.lower():
                return False, "Redirected to login page (cookies expired or not logged in).", None, None

            if resp.status_code == 403:
                had_403 = True
                continue

            if resp.status_code != 200:
                last_err = f"Unexpected response from the site (status code: {resp.status_code})."
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')
            csrf_meta = soup.find('meta', {'name': 'csrf-token'})
            csrf_token = csrf_meta.get('content') if csrf_meta else None

            if not csrf_token:
                match = re.search(r'name=["\'](?:_token|csrf-token)["\']\s+value=["\']([^"\']+)["\']', resp.text)
                if match:
                    csrf_token = match.group(1)

            if not csrf_token:
                return False, "Opened the messages page but could not extract the CSRF token.", None, None

            today = datetime.now()
            payload = {
                'from': (today - timedelta(days=3)).strftime('%m/%d/%Y'),
                'to': today.strftime('%m/%d/%Y'),
                '_token': csrf_token
            }
            api_headers = {
                'Referer': 'https://www.ivasms.com/portal/sms/received',
                'X-Requested-With': 'XMLHttpRequest'
            }
            api_resp = test_session.post("https://www.ivasms.com/portal/sms/received/getsms", headers=api_headers, data=payload, timeout=20)
            if api_resp.status_code == 200:
                return True, f"Successfully verified panel and SMS gateway connection 100% via fingerprint ({profile['name']})!", csrf_token, hdrs
            else:
                return True, f"Logged in successfully via ({profile['name']}) and extracted CSRF (SMS gateway code: {api_resp.status_code}).", csrf_token, hdrs

        # ✅ FIX 3: Broad exception catch (curl_cffi has its own exception classes)
        except Exception as e:
            last_err = f"Connection error: {str(e)}"

    if had_403:
        err_msg = (
            "Connection blocked by Cloudflare protection (403).\n\n"
            "💡 <b>Reasons for this error when uploading from a phone:</b>\n"
            "1️⃣ <b>Browser fingerprint:</b> a phone browser sends a mobile fingerprint; to avoid this, open Kiwi browser and enable 'Desktop site' option before logging in and exporting cookies.\n"
            "2️⃣ <b>IP address (4G network):</b> if your phone is on mobile data, the IP address differs from the bot server, so it gets blocked. Make sure to use the same Wi-Fi network."
        )
        return False, err_msg, None, None

    return False, last_err or "An unexpected error occurred while checking cookies.", None, None

def apply_cookies(cookies_list_or_dict, csrf_token=None, custom_headers=None):
    dash    = IVASMS_DASHBOARD
    session = dash['session']
    session.cookies.clear()

    if custom_headers:
        session.headers.update(custom_headers)
        try:
            with open(ACTIVE_HEADERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(custom_headers, f, indent=2)
        except Exception as e:
            print(f"[!] Error saving active headers: {e}")
    else:
        session.headers.update(get_active_headers())

    print(f"[DEBUG] apply_cookies - data type: {type(cookies_list_or_dict)}")
    if isinstance(cookies_list_or_dict, list):
        print(f"[DEBUG] Cookie count: {len(cookies_list_or_dict)}")
        for c in cookies_list_or_dict:
            name   = c['name']
            value  = c['value']
            domain = c.get('domain', 'www.ivasms.com').lstrip('.')
            session.cookies.set(name, value, domain=domain, path=c.get('path', '/'))
        save_cookies_to_file(cookies_list_or_dict)
    else:
        for name, value in cookies_list_or_dict.items():
            session.cookies.set(name, value, domain='www.ivasms.com', path='/')
        save_cookies_to_file(cookies_list_or_dict)

    if csrf_token:
        dash['csrf_token'] = csrf_token
    dash['is_logged_in'] = True
    dash['cookies'] = session.cookies.get_dict()
    dash['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    global _cookies_expired, _cookies_alert_sent, _last_cookies_update
    _cookies_expired = False
    _cookies_alert_sent = False
    _last_cookies_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DEBUG] Cookies activated successfully ✅ _cookies_expired = False")
    return True


# ======================
# 🔧 Load secrets and environment variables (.env)
# ======================
def _load_env_file():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_env_file()

USERNAME = os.getenv("IVASMS_USERNAME", "")
PASSWORD = os.getenv("IVASMS_PASSWORD", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

_env_chats = os.getenv("CHAT_IDS", "")
CHAT_IDS = [x.strip() for x in _env_chats.split(",") if x.strip()]

REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "6"))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "100"))
MAX_RETRIES = 5
RETRY_DELAY = 5

# Column indexes for the classic dashboard
IDX_DATE = 0
IDX_NUMBER = 2
IDX_SMS = 5
SENT_MESSAGES_FILE = "sent_messages_bot1.json"

_env_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _env_admins.split(",") if x.strip().isdigit()]
DB_PATH = os.getenv("DATABASE_PATH", "bot1.db")
FORCE_SUB_CHANNEL = None
FORCE_SUB_ENABLED = False
BOT_ACTIVE = True

# ======================
# 🖥️ The single dashboard setup (iVasms)
# ======================
# ✅ PROXY INTEGRATION: Create the session and attach the proxy from .env
_ivasms_session = curl_requests.Session(impersonate="chrome")
apply_proxy_to_session(_ivasms_session)

IVASMS_DASHBOARD = {
    "name": "iVasms",
    "type": "ivasms",
    "login_url": "https://www.ivasms.com/login",
    "base_url": "https://www.ivasms.com",
    "sms_api_endpoint": "https://www.ivasms.com/portal/sms/received/getsms",
    "username": USERNAME,
    "password": PASSWORD,
    "session": _ivasms_session,
    "is_logged_in": False,
    "cookies": None,
    "csrf_token": None,
    "last_check": None
}

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN must be set in Environment Variables or .env file (see .env.example)")
if not CHAT_IDS:
    raise SystemExit("❌ CHAT_IDS must be configured in Environment Variables or .env file")
if not USERNAME or not PASSWORD:
    print("⚠️  WARNING: IVASMS_USERNAME and IVASMS_PASSWORD not set in environment")
    print("⚠️  Bot will continue but session auto-login may fail")

# ======================
# 🌍 Country codes and smart apps
# ======================
from country_data import (
    COUNTRY_CODES,
    APP_SHORT_CODES,
    get_app_badge,
    get_service_display,
    get_country_details_smart
)

# ======================
# 🧰 Database management functions (updated)
# ======================
def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ======================
# 🧠 Database creation (with new tables)
# ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            country_code TEXT,
            assigned_number TEXT,
            is_banned INTEGER DEFAULT 0,
            private_combo_country TEXT DEFAULT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS combos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_code TEXT,
            combo_index INTEGER DEFAULT 1,
            numbers TEXT,
            UNIQUE(country_code, combo_index)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS otp_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT,
            otp TEXT,
            full_message TEXT,
            timestamp TEXT,
            assigned_to INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_url TEXT,
            ajax_path TEXT,
            login_page TEXT,
            login_post TEXT,
            username TEXT,
            password TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS private_combos (
            user_id INTEGER,
            country_code TEXT,
            numbers TEXT,
            PRIMARY KEY (user_id, country_code)
        )
    ''')
    # ✅ New channels table
    c.execute('''
        CREATE TABLE IF NOT EXISTS force_sub_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_url TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1
        )
    ''')
    # ✅ Admins table
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_at TEXT,
            added_by INTEGER
        )
    ''')
    for admin_id in ADMIN_IDS:
        c.execute("INSERT OR IGNORE INTO admins (user_id, added_at, added_by) VALUES (?, datetime('now'), 0)", (admin_id,))

    # Initialize old settings (backward compatible with the old bot)
    c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('force_sub_channel', '')")
    c.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('force_sub_enabled', '0')")

    # 🔄 Migrate the old channel (if any) automatically to the new table
    c.execute("SELECT value FROM bot_settings WHERE key = 'force_sub_channel'")
    old_channel = c.fetchone()
    if old_channel and old_channel[0].strip():
        channel = old_channel[0].strip()
        # Make sure it's not duplicated in the new table
        c.execute("SELECT 1 FROM force_sub_channels WHERE channel_url = ?", (channel,))
        if not c.fetchone():
            enabled = 1 if get_setting("force_sub_enabled") == "1" else 0
            c.execute("INSERT INTO force_sub_channels (channel_url, description, enabled) VALUES (?, ?, ?)",
                      (channel, "Primary Channel", enabled))

    # ✅ Registered groups table for periodic reminders
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id TEXT PRIMARY KEY,
            title TEXT,
            is_admin INTEGER DEFAULT 1,
            added_at TEXT
        )
    ''')
    for cid in CHAT_IDS:
        c.execute("INSERT OR IGNORE INTO bot_groups (chat_id, title, is_admin, added_at) VALUES (?, ?, 1, datetime('now'))", (str(cid), "Default Group"))

    conn.commit()
    conn.close()

init_db()

# ======================
# 🧰 Database management functions (updated)
# ======================

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, username="", first_name="", last_name="", country_code=None, assigned_number=None, private_combo_country=None, lang=None):
    """
    Saves or updates user data while fully preserving the user's language, ban status, and other data.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    existing_data = get_user(user_id)
    if existing_data:
        if not username:
            username = existing_data[1]
        if not first_name:
            first_name = existing_data[2]
        if not last_name:
            last_name = existing_data[3]
        if country_code is None:
            country_code = existing_data[4]
        if assigned_number is None:
            assigned_number = existing_data[5]
        if private_combo_country is None:
            private_combo_country = existing_data[7]
        if lang is None and len(existing_data) > 8:
            lang = existing_data[8]

    if not lang:
        lang = "en"

    c.execute("""
        INSERT INTO users (user_id, username, first_name, last_name, country_code, assigned_number, is_banned, private_combo_country, lang)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = CASE WHEN excluded.username != '' THEN excluded.username ELSE users.username END,
            first_name = CASE WHEN excluded.first_name != '' THEN excluded.first_name ELSE users.first_name END,
            last_name = CASE WHEN excluded.last_name != '' THEN excluded.last_name ELSE users.last_name END,
            country_code = COALESCE(excluded.country_code, users.country_code),
            assigned_number = COALESCE(excluded.assigned_number, users.assigned_number),
            private_combo_country = COALESCE(excluded.private_combo_country, users.private_combo_country),
            lang = COALESCE(excluded.lang, users.lang)
    """, (
        user_id,
        username,
        first_name,
        last_name,
        country_code,
        assigned_number,
        private_combo_country,
        lang
    ))
    conn.commit()
    conn.close()

def ban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_banned(user_id):
    user = get_user(user_id)
    return user and user[6] == 1

def is_maintenance_mode():
    return not BOT_ACTIVE

def set_maintenance_mode(status):
    global BOT_ACTIVE
    BOT_ACTIVE = not status

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned=0")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

def get_combo(country_code, combo_index=1, user_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    raw_data = None
    if user_id:
        c.execute("SELECT numbers FROM private_combos WHERE user_id=? AND country_code=?", (user_id, country_code))
        row = c.fetchone()
        if row and row[0]:
            raw_data = row[0]
    if raw_data is None:
        c.execute("SELECT numbers FROM combos WHERE country_code=? AND combo_index=?", (country_code, combo_index))
        row = c.fetchone()
        if row and row[0]:
            raw_data = row[0]
    conn.close()

    if not raw_data:
        return []

    try:
        data = json.loads(raw_data)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        return [str(data).strip()]
    except Exception:
        return [line.strip() for line in str(raw_data).splitlines() if line.strip()]

def save_combo(country_code, numbers, user_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if user_id:
        c.execute("REPLACE INTO private_combos (user_id, country_code, numbers) VALUES (?, ?, ?)",
                  (user_id, country_code, json.dumps(numbers)))
    else:
        # Find the last combo_index for this country
        c.execute("SELECT MAX(combo_index) FROM combos WHERE country_code=?", (country_code,))
        max_index = c.fetchone()[0]
        next_index = 1 if max_index is None else max_index + 1

        c.execute("INSERT INTO combos (country_code, combo_index, numbers) VALUES (?, ?, ?)",
                  (country_code, next_index, json.dumps(numbers)))

    conn.commit()
    conn.close()

def get_combo_service(country_code, combo_index=1, user_id=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        svc = None
        if user_id:
            c.execute("SELECT service FROM private_combos WHERE user_id=? AND country_code=?", (user_id, country_code))
            row = c.fetchone()
            if row and row[0]:
                svc = row[0]
        if not svc:
            c.execute("SELECT service FROM combos WHERE country_code=? AND combo_index=?", (country_code, combo_index))
            row = c.fetchone()
            if row and row[0]:
                svc = row[0]
        conn.close()
        return svc or "All Apps"
    except Exception:
        return "All Apps"

def set_combo_service(country_code, combo_index=1, service="All Apps", user_id=None):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if user_id:
            c.execute("UPDATE private_combos SET service=? WHERE user_id=? AND country_code=?", (service, user_id, country_code))
        else:
            c.execute("UPDATE combos SET service=? WHERE country_code=? AND combo_index=?", (service, country_code, combo_index))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error setting combo service: {e}")
        return False

def delete_combo(country_code, combo_index=None, user_id=None):
    """
    Combo delete function with database error handling
    """
    conn = None
    try:
        # ⚠️ Use a large timeout and check_same_thread=False
        conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
        c = conn.cursor()

        if user_id:
            c.execute("DELETE FROM private_combos WHERE user_id=? AND country_code=?", (user_id, country_code))
        elif combo_index:
            c.execute("DELETE FROM combos WHERE country_code=? AND combo_index=?", (country_code, combo_index))
        else:
            c.execute("DELETE FROM combos WHERE country_code=?", (country_code,))

        conn.commit()
        print(f"✅ Combo deleted: {country_code} (index: {combo_index})")
        return True

    except sqlite3.Error as e:
        print(f"❌ SQLite error in delete_combo: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def get_all_combos():
    """Returns a list of (country_code, combo_index)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT country_code, combo_index FROM combos ORDER BY country_code, combo_index")
    combos = c.fetchall()
    conn.close()
    return combos  # [(country_code, combo_index), ...]

def assign_number_to_user(user_id, number):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET assigned_number=? WHERE user_id=?", (number, user_id))
    conn.commit()
    conn.close()

def get_user_by_number(number):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE assigned_number=?", (number,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def log_otp(number, otp, full_message, assigned_to=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO otp_logs (number, otp, full_message, timestamp, assigned_to) VALUES (?, ?, ?, ?, ?)",
              (number, otp, full_message, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), assigned_to))
    conn.commit()
    conn.close()

def release_number(old_number):
    if not old_number:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET assigned_number=NULL WHERE assigned_number=?", (old_number,))
    conn.commit()
    conn.close()

def get_otp_logs():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM otp_logs")
    logs = c.fetchall()
    conn.close()
    return logs

def get_user_info(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

# --- Force-sub channels management functions (multiple) ---
def get_all_force_sub_channels(enabled_only=True):
    """Fetch channels (only enabled ones or all)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if enabled_only:
        c.execute("SELECT id, channel_url, description FROM force_sub_channels WHERE enabled = 1 ORDER BY id")
    else:
        c.execute("SELECT id, channel_url, description FROM force_sub_channels ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows

def add_force_sub_channel(channel_url, description=""):
    """Add a new channel (no duplicates allowed)"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO force_sub_channels (channel_url, description, enabled) VALUES (?, ?, 1)",
                  (channel_url.strip(), description.strip()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # Duplicate channel
    finally:
        conn.close()

def delete_force_sub_channel(channel_id):
    """Delete a channel by ID"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM force_sub_channels WHERE id = ?", (channel_id,))
    changed = c.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def toggle_force_sub_channel(channel_id):
    """Enable/disable a channel"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE force_sub_channels SET enabled = 1 - enabled WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()

# ======================
# 🔐 Force-subscription functions
# ======================
def force_sub_check(user_id):
    """Verify the user's subscription to **all** enabled channels"""
    channels = get_all_force_sub_channels(enabled_only=True)
    if not channels:
        return True  # No channels → no verification

    for _, url, _ in channels:
        try:
            # Normalize format: @xxx instead of https://t.me/xxx
            if url.startswith("https://t.me/"):
                ch = "@" + url.split("/")[-1]
            elif url.startswith("@"):
                ch = url
            else:
                continue  # Ignore invalid links
            member = bot.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            print(f"[!] Error verifying channel {url}: {e}")
            return False  # Any failure = not subscribed
    return True

def force_sub_markup():
    """Create a button for each enabled channel + a verify button"""
    channels = get_all_force_sub_channels(enabled_only=True)
    if not channels:
        return None

    markup = types.InlineKeyboardMarkup()
    for _, url, desc in channels:
        text = f"📢 {desc}" if desc else "📢 Join the channel"
        markup.add(types.InlineKeyboardButton(text, url=url, style='primary'))
    markup.add(types.InlineKeyboardButton("✅ Verify Subscription", callback_data="check_sub", style='success'))
    return markup

# ======================
# 🤖 Create the Telegram bot
# ======================
bot = telebot.TeleBot(BOT_TOKEN)

# ======================
# 🎮 Interactive bot functions
def get_all_admins():
    """Fetch all admin IDs from the database merged with the base IDs"""
    admins = set(ADMIN_IDS)
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_at TEXT, added_by INTEGER)")
        c.execute("SELECT user_id FROM admins")
        rows = c.fetchall()
        for r in rows:
            admins.add(r[0])
        conn.close()
    except Exception as e:
        print(f"Error fetching admins: {e}")
    return list(admins)

def add_admin_db(user_id, added_by=0):
    """Add a new admin to the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_at TEXT, added_by INTEGER)")
        c.execute("INSERT OR REPLACE INTO admins (user_id, added_at, added_by) VALUES (?, datetime('now'), ?)", (user_id, added_by))
        conn.commit()
        conn.close()
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
        return True
    except Exception as e:
        print(f"Error adding admin: {e}")
        return False

def remove_admin_db(user_id):
    """Remove an admin from the database (with primary owner protection)"""
    if user_id == 123456789:
        return False, "owner"
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        if user_id in ADMIN_IDS and user_id != 123456789:
            ADMIN_IDS.remove(user_id)
        return True, "ok"
    except Exception as e:
        print(f"Error removing admin: {e}")
        return False, str(e)

def get_admins_details():
    """Fetch details of all admins for display"""
    details = []
    details.append({'user_id': 123456789, 'is_owner': True, 'added_at': 'Primary Owner', 'added_by': 0})
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_at TEXT, added_by INTEGER)")
        c.execute("SELECT user_id, added_at, added_by FROM admins")
        rows = c.fetchall()
        for r in rows:
            if r[0] != 123456789:
                details.append({'user_id': r[0], 'is_owner': False, 'added_at': r[1] or 'N/A', 'added_by': r[2] or 0})
        conn.close()
    except Exception as e:
        print(f"Error getting admin details: {e}")
    return details

def is_admin(user_id):
    return user_id in get_all_admins()

def safe_html(text):
    """Sanitizes text from invalid HTML tags"""
    if not text:
        return ""
    # Replace HTML tags with safe alternatives
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text

def save_group_chat(chat_id, title=""):
    """Save or update group data in the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO bot_groups (chat_id, title, is_admin, added_at)
            VALUES (?, ?, 1, datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title
        """, (str(chat_id), str(title or 'Group')))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Groups] Error saving group {chat_id}: {e}")

def get_all_bot_groups():
    """Fetch all groups the bot has been registered in"""
    groups = []
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT chat_id, title FROM bot_groups")
        rows = c.fetchall()
        conn.close()
        for r in rows:
            groups.append((r[0], r[1]))
    except Exception:
        pass
    # Always ensure the base groups and those specified in settings exist
    for cid in CHAT_IDS:
        if str(cid) not in [g[0] for g in groups]:
            groups.append((str(cid), "Default Group"))
    try:
        ls_id = get_live_stream_chat_id()
        if ls_id and str(ls_id) not in [g[0] for g in groups]:
            groups.append((str(ls_id), "Live Stream Group"))
    except Exception:
        pass
    return groups

@bot.my_chat_member_handler()
def handle_my_chat_member(update):
    """Detect when the bot is added to a group and promoted to admin"""
    try:
        chat = update.chat
        if chat.type in ['group', 'supergroup']:
            status = update.new_chat_member.status
            if status in ['administrator', 'creator']:
                save_group_chat(chat.id, chat.title)
                print(f"[Groups] ➕ Bot is admin in group: {chat.title} ({chat.id})")
    except Exception as e:
        print(f"[Groups] Error updating membership status: {e}")


@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_language(user_id)


    # If a regular user and cookies are expired, show maintenance message
    if not is_admin(user_id) and not IVASMS_DASHBOARD.get('is_logged_in', False):
        maintenance_caption = get_text("maintenance_caption", lang)
        maintenance_photo = "https://i.ibb.co/2352v1FN/file-000000004f20720aaa70039fcd26faab-1.png"
        try:
            bot.send_photo(chat_id, maintenance_photo, caption=maintenance_caption, parse_mode="HTML")
        except Exception:
            bot.send_message(chat_id, maintenance_caption, parse_mode="HTML")
        return

    # 1. Check maintenance mode with image
    if is_maintenance_mode() and not is_admin(user_id):
        maintenance_caption = get_text("maintenance_caption", lang)
        maintenance_photo = "https://i.ibb.co/2352v1FN/file-000000004f20720aaa70039fcd26faab-1.png"
        try:
            bot.send_photo(
                chat_id,
                maintenance_photo,
                caption=maintenance_caption,
                parse_mode="HTML"
            )
        except:
            bot.send_message(chat_id, maintenance_caption, parse_mode="HTML")
        return

    # 2. Check banned users
    if is_banned(user_id):
        bot.reply_to(message, get_text("banned_user", lang), parse_mode="HTML")
        return

    # 3. Check force subscribe
    if not force_sub_check(user_id):
        markup = force_sub_markup()
        if markup:
            bot.send_message(chat_id, get_text("force_sub_alert", lang), parse_mode="HTML", reply_markup=markup)
        else:
            bot.send_message(chat_id, "<b>🔒 Force-sub is enabled but no channel has been set!</b>", parse_mode="HTML")
        return

    # 4. Save new user and notify admins
    if not get_user(user_id):
        save_user(
            user_id,
            username=message.from_user.username or "",
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name or ""
        )
        for admin in ADMIN_IDS:
            try:
                caption = (
                    f"👤 <b>New user joined the bot:</b>\n"
                    f"• <b>ID:</b> <code>{user_id}</code>\n"
                    f"• <b>Username:</b> @{safe_html(message.from_user.username or 'None')}\n"
                    f"• <b>Name:</b> {safe_html(message.from_user.first_name or '')}"
                )
                bot.send_message(admin, caption, parse_mode="HTML")
            except:
                pass

    # 5. Build the button menu (countries and combos)
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    user_data = get_user(user_id)
    private_combo = user_data[7] if user_data else None
    all_combos = get_all_combos()

    # Group combos by country
    country_combos = {}
    for country_code, combo_index in all_combos:
        if country_code not in country_combos:
            country_combos[country_code] = []
        country_combos[country_code].append(combo_index)

    # Private combo first
    if private_combo:
        c_info = COUNTRY_CODES.get(private_combo)
        name, flag, _ = c_info if c_info else ("Special", "⭐", "PV")
        svc = get_combo_service(private_combo, 1, user_id)
        app_badge = get_app_badge(svc)
        app_prefix = f"{app_badge} " if app_badge else ""
        buttons.append(types.InlineKeyboardButton(f"{flag} {app_prefix}{name} (Private)", callback_data=f"country_{private_combo}_1", style='success'))

    # Create a button for each combo
    for country_code, indices in country_combos.items():
        if country_code != private_combo:
            c_info = COUNTRY_CODES.get(country_code)
            if not c_info:
                _, name, flag, _ = get_country_details_smart(country_code)
            else:
                name, flag, _ = c_info

            for idx in indices:
                svc = get_combo_service(country_code, idx)
                app_badge = get_app_badge(svc)
                app_prefix = f"{app_badge} " if app_badge else ""
                if len(indices) == 1:
                    btn_text = f"{flag} {app_prefix}{name}"
                else:
                    btn_text = f"{flag} {app_prefix}{name} ({idx})"
                buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"country_{country_code}_{idx}", style='primary'))

    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i+2])

    # Language button for all users
    markup.add(types.InlineKeyboardButton(get_text("btn_language", lang), callback_data="change_language", style='primary'))

    # Admin panel button only for admins
    if is_admin(user_id):
        markup.add(types.InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel", style='danger'))

    # 6. Professional formatted welcome message per user language
    fancy_text = get_text("welcome_banner", lang)

    bot.send_message(
        chat_id,
        fancy_text,
        parse_mode="HTML",
        reply_markup=markup,
        disable_web_page_preview=True
    )

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_subscription(call):
    lang = get_user_language(call.from_user.id)
    if force_sub_check(call.from_user.id):
        bot.answer_callback_query(call.id, get_text("sub_checked_ok", lang), show_alert=True)
        send_welcome(call.message)
    else:
        bot.answer_callback_query(call.id, get_text("sub_checked_fail", lang), show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("country_"))
def handle_country_selection(call):
    try:
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        lang = get_user_language(user_id)

        # 1. Security checks (ban and subscription)
        if is_banned(user_id):
            bot.answer_callback_query(call.id, get_text("banned_user", lang), show_alert=True)
            return
        if not force_sub_check(user_id):
            bot.answer_callback_query(call.id)
            markup = force_sub_markup()
            bot.send_message(chat_id, get_text("force_sub_alert", lang), parse_mode="HTML", reply_markup=markup)
            return

        # 2. Extract country and combo_index
        parts = call.data.split("_")
        country_code = parts[1]
        combo_index = int(parts[2]) if len(parts) > 2 else 1

        available_numbers = get_available_numbers(country_code, combo_index, user_id)

        if not available_numbers:
            bot.answer_callback_query(call.id)
            error_msg = get_text("all_numbers_busy", lang)
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="back_to_countries", style="danger"))
            bot.edit_message_text(error_msg, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return

        # 3. Assign the number and release the old one
        assigned = random.choice(available_numbers)
        old_user = get_user(user_id)
        if old_user and old_user[5]:
            release_number(old_user[5])

        assign_number_to_user(user_id, assigned)
        save_user(user_id, country_code=country_code, assigned_number=assigned)

        # 4. Fetch country data and format the text
        c_info = COUNTRY_CODES.get(country_code)
        if not c_info:
            _, name, flag, short = get_country_details_smart(country_code)
        else:
            name, flag, short = c_info

        svc = get_combo_service(country_code, combo_index, user_id)
        service_display = get_service_display(svc)

        msg_text = get_text(
            "number_details",
            lang,
            number=assigned,
            country=name,
            flag=flag,
            short=short,
            combo=combo_index,
            service=service_display
        )

        # 5. Build the button panel
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton(get_text("btn_change_num", lang), callback_data=f"change_num_{country_code}_{combo_index}", style='success'),
            types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="back_to_countries", style='danger')
        )

        # 6. Final update of the message
        try:
            bot.edit_message_text(
                text=msg_text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            bot.answer_callback_query(call.id, get_text("number_assigned_alert", lang))
        except Exception as e:
            bot.answer_callback_query(call.id)
            print(f"Edit message error: {e}")
    except Exception as err:
        import traceback
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, f"❌ Error: {err}", show_alert=True)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("change_num_"))
def change_number(call):
    user_id = call.from_user.id
    lang = get_user_language(user_id)

    # 1. Security checks
    if is_banned(user_id):
        return
    if not force_sub_check(user_id):
        return

    # 2. Extract country code and combo_index
    parts = call.data.split("_")
    country_code = parts[2]
    combo_index = int(parts[3]) if len(parts) > 3 else 1

    available_numbers = get_available_numbers(country_code, combo_index, user_id)

    if not available_numbers:
        bot.answer_callback_query(call.id, get_text("all_numbers_busy", lang), show_alert=True)
        return

    # 3. Release the old number and assign a new one
    old_user = get_user(user_id)
    if old_user and old_user[5]:
        release_number(old_user[5])

    assigned = random.choice(available_numbers)
    assign_number_to_user(user_id, assigned)
    save_user(user_id, assigned_number=assigned)

    # 4. Fetch country data and format
    c_info = COUNTRY_CODES.get(country_code)
    if not c_info:
        _, name, flag, short = get_country_details_smart(country_code)
    else:
        name, flag, short = c_info

    svc = get_combo_service(country_code, combo_index, user_id)
    service_display = get_service_display(svc)

    msg_text = get_text(
        "number_details",
        lang,
        number=assigned,
        country=name,
        flag=flag,
        short=short,
        combo=combo_index,
        service=service_display
    )

    # 5. Build updated buttons
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(get_text("btn_change_num", lang), callback_data=f"change_num_{country_code}_{combo_index}", style='success'),
        types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="back_to_countries", style='danger')
    )

    # 6. Update the message
    try:
        bot.edit_message_text(
            text=msg_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        bot.answer_callback_query(call.id, get_text("number_changed_alert", lang))
    except Exception as e:
        print(f"Error in change_number: {e}")
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_countries")
def back_to_countries(call):
    lang = get_user_language(call.from_user.id)
    # 1. Build the button menu
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    # Fetch data
    user = get_user(call.from_user.id)
    private_combo = user[7] if user else None
    all_combos = get_all_combos()

    # Group combos by country
    country_combos = {}
    for country_code, combo_index in all_combos:
        if country_code not in country_combos:
            country_combos[country_code] = []
        country_combos[country_code].append(combo_index)

    # Add the private combo first (if any)
    if private_combo:
        c_info = COUNTRY_CODES.get(private_combo)
        name, flag, _ = c_info if c_info else ("Special", "⭐", "PV")
        svc = get_combo_service(private_combo, 1, call.from_user.id)
        app_badge = get_app_badge(svc)
        app_prefix = f"{app_badge} " if app_badge else ""
        buttons.append(types.InlineKeyboardButton(f"{flag} {app_prefix}{name} (Private)", callback_data=f"country_{private_combo}_1", style='success'))

    # Add the public combos
    for country_code, indices in country_combos.items():
        if country_code != private_combo:
            c_info = COUNTRY_CODES.get(country_code)
            if not c_info:
                _, name, flag, _ = get_country_details_smart(country_code)
            else:
                name, flag, _ = c_info

            for idx in indices:
                svc = get_combo_service(country_code, idx)
                app_badge = get_app_badge(svc)
                app_prefix = f"{app_badge} " if app_badge else ""
                if len(indices) == 1:
                    btn_text = f"{flag} {app_prefix}{name}"
                else:
                    btn_text = f"{flag} {app_prefix}{name} ({idx})"
                buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"country_{country_code}_{idx}", style='primary'))

    # Distribute the buttons in rows
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i+2])

    # Language button for all users
    markup.add(types.InlineKeyboardButton(get_text("btn_language", lang), callback_data="change_language", style='primary'))

    # Add the admin button for admins
    if is_admin(call.from_user.id):
        admin_btn = types.InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel", style='danger')
        markup.add(admin_btn)

    # 2. Professional formatted text per user language
    fancy_text = get_text("welcome_banner", lang)

    # 3. Edit the current message
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=fancy_text,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Error editing message: {e}")
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "change_language")
def handle_change_language_menu(call):
    lang = get_user_language(call.from_user.id)
    prompt = get_text("choose_language", lang)
    markup = build_language_markup(lang)
    try:
        bot.edit_message_text(
            text=prompt,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception:
        bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_lang_"))
def handle_set_language_callback(call):
    new_lang = call.data.split("_", 2)[2]
    if new_lang in SUPPORTED_LANGUAGES:
        set_user_language(call.from_user.id, new_lang)
        alert_text = get_text("language_changed", new_lang)
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        back_to_countries(call)
    else:
        bot.answer_callback_query(call.id)


# ======================
# 🔐 Admin control panel (updated)
# ======================
user_states = {}

def admin_main_menu(lang='en'):
    markup = types.InlineKeyboardMarkup()

    # 1. Bot status button (takes top priority)
    status_icon = "🟢" if not is_maintenance_mode() else "🔴"
    status_text = get_text("admin_status_online", lang) if not is_maintenance_mode() else get_text("admin_status_maint", lang)
    status_style = 'success' if not is_maintenance_mode() else 'danger'
    markup.add(types.InlineKeyboardButton(f"{status_icon} {status_text} {status_icon}", callback_data="toggle_maintenance", style=status_style))

    # 2. Combo management section (big buttons)
    markup.row(
        types.InlineKeyboardButton(get_text("admin_add_combo", lang), callback_data="admin_add_combo", style='success'),
        types.InlineKeyboardButton(get_text("admin_del_combo", lang), callback_data="admin_del_combo", style='danger')
    )
    markup.add(
        types.InlineKeyboardButton("🏷️ Assign app to combo (WhatsApp / TikTok..)", callback_data="admin_combo_service_menu", style='primary')
    )

    # 3. Statistics and reports section
    markup.row(
        types.InlineKeyboardButton(get_text("admin_stats", lang), callback_data="admin_stats", style='primary'),
        types.InlineKeyboardButton(get_text("admin_full_report", lang), callback_data="admin_full_report", style='primary')
    )

    # 4. Broadcast section
    markup.row(
        types.InlineKeyboardButton(get_text("admin_broadcast_all", lang), callback_data="admin_broadcast_all", style='primary'),
        types.InlineKeyboardButton(get_text("admin_broadcast_user", lang), callback_data="admin_broadcast_user", style='primary')
    )

    # 5. User management section
    markup.row(
        types.InlineKeyboardButton(get_text("admin_ban", lang), callback_data="admin_ban", style='danger'),
        types.InlineKeyboardButton(get_text("admin_unban", lang), callback_data="admin_unban", style='success'),
        types.InlineKeyboardButton(get_text("admin_user_info", lang), callback_data="admin_user_info", style='primary')
    )

    # 6. Advanced settings section
    markup.row(
        types.InlineKeyboardButton(get_text("admin_force_sub", lang), callback_data="admin_force_sub", style='primary'),
        types.InlineKeyboardButton(get_text("admin_dashboards", lang), callback_data="admin_dashboards", style='primary'),
        types.InlineKeyboardButton(get_text("admin_private_combo", lang), callback_data="admin_private_combo", style='primary')
    )

    # 7. iVasms numbers and cookies section
    markup.row(
        types.InlineKeyboardButton(get_text("admin_ivasms_panel", lang), callback_data="admin_ivasms_panel", style='primary'),
        types.InlineKeyboardButton(get_text("admin_cookies_panel", lang), callback_data="admin_cookies_panel", style='primary')
    )

    # 8. Admin management section
    markup.row(
        types.InlineKeyboardButton(get_text("admin_manage_admins", lang), callback_data="admin_manage_admins", style='primary')
    )

    # 9. Admin language change button
    markup.add(types.InlineKeyboardButton(get_text("admin_change_lang", lang), callback_data="admin_change_lang", style='primary'))

    # 10. Exit button
    markup.add(types.InlineKeyboardButton(get_text("admin_leave", lang), callback_data="back_to_countries", style='danger'))

    return markup

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    lang = get_user_language(message.from_user.id)
    if not is_admin(message.from_user.id):
        bot.reply_to(message, get_text("admin_only_alert", lang))
        return
    status_str = f"{get_text('admin_status_online', lang)} 🟢" if not is_maintenance_mode() else f"{get_text('admin_status_maint', lang)} 🔴"
    admin_text = (
        f"🛡️ <b>{get_text('admin_title', lang)}</b>\n\n"
        f"<b>👋 {get_text('admin_greeting', lang)}</b>\n\n"
        f"<b>⚙️ {get_text('admin_desc', lang)}</b>\n"
        f"<b>⚠️ {get_text('admin_warning', lang)}</b>\n\n"
        f"📊 <b>{get_text('admin_sys_info', lang)}:</b>\n"
        f"• <b>{get_text('admin_bot_status', lang)}:</b> {status_str}\n"
        f"• <b>{get_text('admin_server_conn', lang)}:</b> <u>{get_text('admin_online_label', lang)}</u> ✅\n"
        f"• <b>{get_text('admin_current_time', lang)}:</b> <code>{datetime.now().strftime('%H:%M - %Y/%m/%d')}</code>"
    )
    try:
        bot.send_message(
            message.chat.id,
            admin_text,
            parse_mode="HTML",
            reply_markup=admin_main_menu(lang),
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Admin Command Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def show_admin_panel(call):
    lang = get_user_language(call.from_user.id)
    # Verify role first
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, get_text("admin_only_alert", lang), show_alert=True)
        return

    status_str = f"{get_text('admin_status_online', lang)} 🟢" if not is_maintenance_mode() else f"{get_text('admin_status_maint', lang)} 🔴"
    admin_text = (
        f"🛡️ <b>{get_text('admin_title', lang)}</b>\n\n"
        f"<b>👋 {get_text('admin_greeting', lang)}</b>\n\n"
        f"<b>⚙️ {get_text('admin_desc', lang)}</b>\n"
        f"<b>⚠️ {get_text('admin_warning', lang)}</b>\n\n"
        f"📊 <b>{get_text('admin_sys_info', lang)}:</b>\n"
        f"• <b>{get_text('admin_bot_status', lang)}:</b> {status_str}\n"
        f"• <b>{get_text('admin_server_conn', lang)}:</b> <u>{get_text('admin_online_label', lang)}</u> ✅\n"
        f"• <b>{get_text('admin_current_time', lang)}:</b> <code>{datetime.now().strftime('%H:%M - %Y/%m/%d')}</code>"
    )

    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=admin_text,
            parse_mode="HTML",
            reply_markup=admin_main_menu(lang),
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"Admin Panel Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_change_lang")
def handle_admin_change_lang_menu(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    prompt = get_text("choose_admin_lang", lang)
    markup = build_admin_language_markup(lang)
    try:
        bot.edit_message_text(
            text=prompt,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception:
        bot.send_message(call.message.chat.id, prompt, reply_markup=markup, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_admin_lang_"))
def handle_set_admin_lang_callback(call):
    if not is_admin(call.from_user.id):
        return
    new_lang = call.data.split("_", 3)[3]
    if new_lang in SUPPORTED_LANGUAGES:
        set_user_language(call.from_user.id, new_lang)
        alert_text = get_text("admin_lang_changed", new_lang)
        bot.answer_callback_query(call.id, alert_text, show_alert=True)
        show_admin_panel(call)
    else:
        bot.answer_callback_query(call.id)

# ======================
# 👮‍♂️ Admin management from the control panel
# ======================
def build_admin_manage_markup(lang='en'):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton(get_text("admin_add_admin", lang), callback_data="admin_add_admin", style='success'),
        types.InlineKeyboardButton(get_text("admin_del_admin", lang), callback_data="admin_del_admin", style='danger')
    )
    markup.row(
        types.InlineKeyboardButton(get_text("admin_list_admins", lang), callback_data="admin_list_admins", style='primary')
    )
    markup.row(
        types.InlineKeyboardButton(get_text("admin_btn_back", lang), callback_data="admin_panel", style='danger')
    )
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "admin_manage_admins")
def handle_admin_manage_admins(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    admins_count = len(get_all_admins())
    text = (
        f"{get_text('admin_panel_admins_title', lang)}\n\n"
        f"• <b>{get_text('admin_stats', lang)}:</b> <code>{admins_count}</code>"
    )
    markup = build_admin_manage_markup(lang)
    try:
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_admin")
def handle_admin_add_admin(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    chat_id = call.message.chat.id
    user_states[chat_id] = "add_admin"

    mar = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="admin_manage_admins", style='danger')
    ]])
    prompt_text = get_text("admin_prompt_send_id", lang)
    try:
        bot.edit_message_text(prompt_text, chat_id=chat_id, message_id=call.message.message_id, reply_markup=mar, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, prompt_text, reply_markup=mar, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "add_admin")
def process_add_admin_msg(message):
    lang = get_user_language(message.from_user.id)
    if not is_admin(message.from_user.id):
        return

    target_id = None
    if message.forward_from:
        target_id = message.forward_from.id
    else:
        text = message.text.strip() if message.text else ""
        if text.isdigit():
            target_id = int(text)

    if not target_id:
        bot.reply_to(message, get_text("invalid_user_id", lang))
        return

    if target_id in get_all_admins():
        bot.reply_to(message, get_text("admin_already_exists", lang))
        user_states.pop(message.from_user.id, None)
        return

    success = add_admin_db(target_id, added_by=message.from_user.id)
    if success:
        user_states.pop(message.from_user.id, None)
        bot.reply_to(
            message,
            get_text("admin_added_success", lang, admin_id=target_id),
            parse_mode="HTML"
        )
        try:
            target_lang = get_user_language(target_id)
            bot.send_message(
                target_id,
                get_text("admin_notify_promoted", target_lang),
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        bot.reply_to(message, "❌ Error adding the admin to the database.")

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_admins")
def handle_admin_list_admins(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    details = get_admins_details()

    text = get_text("admin_list_title", lang)
    for idx, adm in enumerate(details, 1):
        uid = adm['user_id']
        badge = get_text("admin_owner_badge", lang) if adm['is_owner'] else get_text("admin_role_badge", lang)
        date_info = f" ({adm['added_at']})" if not adm['is_owner'] else ""
        text += f"{idx}. <code>{uid}</code> {badge}{date_info}\n"

    mar = types.InlineKeyboardMarkup(row_width=1)
    mar.add(
        types.InlineKeyboardButton(get_text("admin_add_admin", lang), callback_data="admin_add_admin", style='success'),
        types.InlineKeyboardButton(get_text("admin_del_admin", lang), callback_data="admin_del_admin", style='danger'),
        types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="admin_manage_admins", style='danger')
    )
    try:
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=mar, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=mar, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_del_admin")
def handle_admin_del_admin(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    details = [a for a in get_admins_details() if not a['is_owner']]

    if not details:
        text = get_text("admin_no_removable_admins", lang)
        mar = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="admin_manage_admins", style='danger')
        ]])
    else:
        text = get_text("admin_del_select_prompt", lang)
        mar = types.InlineKeyboardMarkup(row_width=1)
        for adm in details:
            uid = adm['user_id']
            mar.add(types.InlineKeyboardButton(f"🗑️ {uid}", callback_data=f"del_admin_id_{uid}", style='danger'))
        mar.add(types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="admin_manage_admins", style='danger'))

    try:
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=mar, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=mar, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_admin_id_"))
def handle_do_del_admin(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    try:
        target_id = int(call.data.split("_")[3])
    except Exception:
        bot.answer_callback_query(call.id, "Error", show_alert=True)
        return

    success, reason = remove_admin_db(target_id)
    if success:
        bot.answer_callback_query(call.id, get_text("admin_removed_success", lang, admin_id=target_id), show_alert=True)
        handle_admin_del_admin(call)
    else:
        if reason == "owner":
            bot.answer_callback_query(call.id, get_text("admin_cannot_remove_owner", lang), show_alert=True)
        else:
            bot.answer_callback_query(call.id, f"Error: {reason}", show_alert=True)

# ======================
# 📌 Force-sub feature in the admin panel
# ======================
@bot.callback_query_handler(func=lambda call: call.data == "admin_force_sub")
def admin_force_sub(call):
    if not is_admin(call.from_user.id):
        return

    channels = get_all_force_sub_channels(enabled_only=False)
    text = "⚙️ Force-subscription channel management:\n"
    text += f"Total channels: {len(channels)}\n\n"

    markup = types.InlineKeyboardMarkup()
    for ch_id, url, desc in channels:
        # Fetch the status accurately
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT enabled FROM force_sub_channels WHERE id=?", (ch_id,))
        enabled = c.fetchone()[0]
        conn.close()
        status = "✅" if enabled else "❌"
        btn_text = f"{status} {desc or url[:25]}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"edit_force_ch_{ch_id}", style='primary'))

    markup.add(types.InlineKeyboardButton("➕ Add channel", callback_data="add_force_ch", style='success'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "toggle_maintenance")
def handle_maintenance_toggle(call):
    if not is_admin(call.from_user.id): return

    # Flip the current status
    current_status = is_maintenance_mode()
    set_maintenance_mode(not current_status)  # Save function

    new_status_text = "🔓 Bot opened for everyone" if current_status else "🔒 Bot locked (maintenance mode)"

    # Quick admin notification
    bot.answer_callback_query(call.id, new_status_text, show_alert=True)

    # Update the panel immediately to change the button shape
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=admin_main_menu())

# --- Add new channel ---
@bot.callback_query_handler(func=lambda call: call.data == "add_force_ch")
def add_force_ch_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "add_force_ch_url"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_force_sub", style='danger'))
    bot.edit_message_text("Send the channel link (e.g. https://t.me/xxx or @xxx):", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "add_force_ch_url")
def add_force_ch_step2(message):
    url = message.text.strip()
    if not (url.startswith("@") or url.startswith("https://t.me/")):
        bot.reply_to(message, "❌ Invalid link! It must start with @ or https://t.me/")
        return
    user_states[message.from_user.id] = {"step": "add_force_ch_desc", "url": url}
    bot.reply_to(message, "Enter a description for the channel (or leave empty):")

@bot.message_handler(func=lambda msg: isinstance(user_states.get(msg.from_user.id), dict) and user_states[msg.from_user.id].get("step") == "add_force_ch_desc")
def add_force_ch_step3(message):
    data = user_states[message.from_user.id]
    url = data["url"]
    desc = message.text.strip()
    if add_force_sub_channel(url, desc):
        bot.reply_to(message, f"✅ Channel added:\n{url}\nDescription: {desc or '—'}")
    else:
        bot.reply_to(message, "❌ Channel already exists!")
    del user_states[message.from_user.id]

# --- Edit/delete individual channel ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_force_ch_"))
def edit_force_ch(call):
    if not is_admin(call.from_user.id):
        return
    try:
        ch_id = int(call.data.split("_", 3)[3])
    except:
        return
    # Fetch channel data
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel_url, description, enabled FROM force_sub_channels WHERE id=?", (ch_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        bot.answer_callback_query(call.id, "❌ Channel not found!", show_alert=True)
        return

    url, desc, enabled = row
    status = "Enabled" if enabled else "Disabled"
    text = f"🔧 Channel management:\nLink: {url}\nDescription: {desc or '—'}\nStatus: {status}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✏️ Edit description", callback_data=f"edit_desc_{ch_id}", style='primary'))
    if enabled:
        markup.add(types.InlineKeyboardButton("❌ Disable", callback_data=f"toggle_ch_{ch_id}", style='danger'))
    else:
        markup.add(types.InlineKeyboardButton("✅ Enable", callback_data=f"toggle_ch_{ch_id}", style='success'))
    markup.add(types.InlineKeyboardButton("🗑️ Delete", callback_data=f"del_ch_{ch_id}", style='danger'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_force_sub", style='danger'))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_ch_"))
def toggle_ch(call):
    ch_id = int(call.data.split("_", 2)[2])
    toggle_force_sub_channel(ch_id)
    bot.answer_callback_query(call.id, "🔄 Channel status changed", show_alert=True)
    admin_force_sub(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_ch_"))
def del_ch(call):
    ch_id = int(call.data.split("_", 2)[2])
    if delete_force_sub_channel(ch_id):
        bot.answer_callback_query(call.id, "✅ Deleted!", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "❌ Delete failed!", show_alert=True)
    admin_force_sub(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_desc_"))
def edit_desc_step1(call):
    ch_id = int(call.data.split("_", 2)[2])
    user_states[call.from_user.id] = f"edit_desc_{ch_id}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data=f"edit_force_ch_{ch_id}", style='danger'))
    bot.edit_message_text("Enter the new description:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: isinstance(user_states.get(msg.from_user.id), str) and user_states[msg.from_user.id].startswith("edit_desc_"))
def edit_desc_step2(message):
    try:
        ch_id = int(user_states[message.from_user.id].split("_")[2])
        desc = message.text.strip()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE force_sub_channels SET description = ? WHERE id = ?", (desc, ch_id))
        conn.commit()
        conn.close()
        bot.reply_to(message, "✅ Description updated!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_combo")
def admin_add_combo(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "waiting_combo_file"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("📤 Send the combo file as TXT", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(content_types=['document'])
def handle_combo_file(message):
    if not is_admin(message.from_user.id):
        return
    if user_states.get(message.from_user.id) != "waiting_combo_file":
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8')
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            bot.reply_to(message, "❌ The file is empty!")
            return
        first_num = clean_number(lines[0])
        country_code = None
        for code in COUNTRY_CODES:
            if first_num.startswith(code):
                country_code = code
                break
        if not country_code:
            bot.reply_to(message, "❌ Could not determine the country from the numbers!")
            return
        save_combo(country_code, lines)
        name, flag, _ = COUNTRY_CODES[country_code]
        bot.reply_to(message, f"✅ Combo saved for {flag} {name}\n🔢 Number count: {len(lines)}")
        del user_states[message.from_user.id]
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_del_combo")
def admin_del_combo(call):
    if not is_admin(call.from_user.id):
        return
    combos = get_all_combos()
    if not combos:
        bot.answer_callback_query(call.id, "No combos found!")
        return
    markup = types.InlineKeyboardMarkup()
    # Group combos by country
    country_combos = {}
    for country_code, combo_index in combos:
        if country_code not in country_combos:
            country_combos[country_code] = []
        country_combos[country_code].append(combo_index)

    for country_code, indices in country_combos.items():
        if country_code in COUNTRY_CODES:
            name, flag, _ = COUNTRY_CODES[country_code]
            for idx in indices:
                # If only the first combo or a single country, don't add the number
                if len(indices) == 1:
                    btn_text = f"{flag} {name}"
                else:
                    btn_text = f"{flag} {name} ({idx})"
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"del_combo_{country_code}_{idx}", style='primary'))

    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("Select the combo to delete:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_combo_"))
def confirm_del_combo(call):
    if not is_admin(call.from_user.id):
        return

    parts = call.data.split("_")
    country_code = parts[2]
    combo_index = int(parts[3]) if len(parts) > 3 else 1

    # Call the updated function
    success = delete_combo(country_code, combo_index)

    name, flag, _ = COUNTRY_CODES.get(country_code, ("Unknown", "🌍", ""))

    if success:
        bot.answer_callback_query(call.id, f"✅ Combo deleted: {flag} {name} ({combo_index})", show_alert=True)
    else:
        bot.answer_callback_query(call.id, f"❌ Combo delete failed!", show_alert=True)

    # Refresh the list
    admin_del_combo(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if not is_admin(call.from_user.id):
        return
    total_users = len(get_all_users())
    combos = get_all_combos()

    # Count unique combos
    unique_countries = set()
    total_combos = 0
    for country_code, combo_index in combos:
        unique_countries.add(country_code)
        total_combos += 1

    total_numbers = 0
    for country_code, combo_index in combos:
        total_numbers += len(get_combo(country_code, combo_index))

    otp_count = len(get_otp_logs())
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text(
        f"📊 Bot Statistics:\n"
        f"👥 Active Users: {total_users}\n"
        f"🌐 Countries Added: {len(unique_countries)}\n"
        f"📦 Combos: {total_combos}\n"
        f"📞 Total Numbers: {total_numbers}\n"
        f"🔑 Total Codes Received: {otp_count}",
        call.message.chat.id, call.message.message_id, reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_full_report")
def admin_full_report(call):
    if not is_admin(call.from_user.id):
        return
    try:
        report = "📊 Full Bot Report\n" + "="*40 + "\n\n"
        # Users
        report += "👥 Users:\n"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM users")
        users = c.fetchall()
        for u in users:
            status = "Banned" if u[6] else "Active"
            report += f"ID: {u[0]} | @{u[1] or 'N/A'} | Number: {u[5] or 'N/A'} | Status: {status}\n"
        report += "\n" + "="*40 + "\n\n"
        # Codes
        report += "🔑 OTP Log:\n"
        c.execute("SELECT * FROM otp_logs")
        logs = c.fetchall()
        for log in logs:
            user_info = get_user_info(log[5]) if log[5] else None
            user_tag = f"@{user_info[1]}" if user_info and user_info[1] else f"ID:{log[5] or 'N/A'}"
            report += f"Number: {log[1]} | Code: {log[2]} | User: {user_tag} | Time: {log[4]}\n"

        # Combos
        report += "\n" + "="*40 + "\n\n"
        report += "📦 Combos:\n"
        c.execute("SELECT country_code, combo_index, LENGTH(numbers) FROM combos")
        combos_data = c.fetchall()
        for country_code, combo_index, num_length in combos_data:
            name, flag, _ = COUNTRY_CODES.get(country_code, ("Unknown", "🌍", ""))
            num_count = len(get_combo(country_code, combo_index))
            report += f"{flag} {name} ({combo_index}): {num_count} numbers\n"

        conn.close()
        report += "\n" + "="*40 + "\n\n"
        report += "Report generated at: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("bot_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        with open("bot_report.txt", "rb") as f:
            bot.send_document(call.from_user.id, f)
        os.remove("bot_report.txt")
        bot.answer_callback_query(call.id, "✅ Report sent!", show_alert=True)
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Error: {e}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "admin_ban")
def admin_ban_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "ban_user"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("Enter the user ID to ban:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "ban_user")
def admin_ban_step2(message):
    try:
        uid = int(message.text)
        ban_user(uid)
        bot.reply_to(message, f"✅ User {uid} banned")
        del user_states[message.from_user.id]
    except:
        bot.reply_to(message, "❌ Invalid ID!")

@bot.callback_query_handler(func=lambda call: call.data == "admin_unban")
def admin_unban_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "unban_user"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("Enter the user ID to unban:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "unban_user")
def admin_unban_step2(message):
    try:
        uid = int(message.text)
        unban_user(uid)
        bot.reply_to(message, f"✅ User {uid} unbanned")
        del user_states[message.from_user.id]
    except:
        bot.reply_to(message, "❌ Invalid ID!")

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast_all")
def admin_broadcast_all_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "broadcast_all"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("Send the message to broadcast to everyone:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "broadcast_all")
def admin_broadcast_all_step2(message):
    users = get_all_users()
    success = 0
    for uid in users:
        try:
            bot.send_message(uid, message.text)
            success += 1
        except:
            pass
    bot.reply_to(message, f"✅ Sent to {success}/{len(users)} users")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast_user")
def admin_broadcast_user_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "broadcast_user_id"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("Enter the user ID:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "broadcast_user_id")
def admin_broadcast_user_step2(message):
    try:
        uid = int(message.text)
        user_states[message.from_user.id] = f"broadcast_msg_{uid}"
        bot.reply_to(message, "Send the message:")
    except:
        bot.reply_to(message, "❌ Invalid ID!")

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, "").startswith("broadcast_msg_"))
def admin_broadcast_user_step3(message):
    uid = int(user_states[message.from_user.id].split("_")[2])
    try:
        bot.send_message(uid, message.text)
        bot.reply_to(message, f"✅ Sent to user {uid}")
    except Exception as e:
        bot.reply_to(message, f"❌ Failed: {e}")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "admin_user_info")
def admin_user_info_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "get_user_info"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("Enter the user ID:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "get_user_info")
def admin_user_info_step2(message):
    try:
        uid = int(message.text)
        user = get_user_info(uid)
        if not user:
            bot.reply_to(message, "❌ User not found!")
            return
        status = "Banned" if user[6] else "Active"
        info = f"👤 User Info:\n"
        info += f"🆔: {user[0]}\n"
        info += f".Username: @{user[1] or 'N/A'}\n"
        info += f"Name: {user[2] or ''} {user[3] or ''}\n"
        info += f"Assigned Number: {user[5] or 'N/A'}\n"
        info += f"Status: {status}"
        bot.reply_to(message, info)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "admin_private_combo")
def admin_private_combo(call):
    if not is_admin(call.from_user.id):
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Add private combo", callback_data="add_private_combo", style='success'))
    markup.add(types.InlineKeyboardButton("🗑️ Clear private combo", callback_data="del_private_combo", style='danger'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel", style='danger'))
    bot.edit_message_text("👤 Private combo:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_private_combo")
def add_private_combo_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "add_private_user_id"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_private_combo", style='danger'))
    bot.edit_message_text("Enter the user ID:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "add_private_user_id")
def add_private_combo_step2(message):
    try:
        uid = int(message.text)
        user_states[message.from_user.id] = f"add_private_country_{uid}"
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = []
        # Group combos by country
        all_combos = get_all_combos()
        country_combos = {}
        for country_code, combo_index in all_combos:
            if country_code not in country_combos:
                country_combos[country_code] = []
            country_combos[country_code].append(combo_index)

        for country_code, indices in country_combos.items():
            if country_code in COUNTRY_CODES:
                name, flag, _ = COUNTRY_CODES[country_code]
                for idx in indices:
                    if len(indices) == 1:
                        btn_text = f"{flag} {name}"
                    else:
                        btn_text = f"{flag} {name} ({idx})"
                    buttons.append(types.InlineKeyboardButton(btn_text, callback_data=f"select_private_{uid}_{country_code}", style='primary'))
        for i in range(0, len(buttons), 2):
            markup.row(*buttons[i:i+2])
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_private_combo", style='danger'))
        bot.reply_to(message, "Select the country:", reply_markup=markup)
    except:
        bot.reply_to(message, "❌ Invalid ID!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_private_"))
def select_private_combo(call):
    parts = call.data.split("_")
    uid = int(parts[2])
    country_code = parts[3]
    save_user(uid, private_combo_country=country_code)
    name, flag, _ = COUNTRY_CODES[country_code]
    bot.answer_callback_query(call.id, f"✅ Private combo assigned to {uid} - {flag} {name}", show_alert=True)
    admin_private_combo(call)

@bot.callback_query_handler(func=lambda call: call.data == "del_private_combo")
def del_private_combo_step1(call):
    if not is_admin(call.from_user.id):
        return
    user_states[call.from_user.id] = "del_private_user_id"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_private_combo", style='danger'))
    bot.edit_message_text("Enter the user ID:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "del_private_user_id")
def del_private_combo_step2(message):
    try:
        uid = int(message.text)
        save_user(uid, private_combo_country=None)
        bot.reply_to(message, f"✅ Private combo cleared for user {uid}")
    except:
        bot.reply_to(message, "❌ Invalid ID!")
    del user_states[message.from_user.id]

# ======================
# 🆕 New function: fetch available (unused) numbers with private support
# ======================
def get_available_numbers(country_code, combo_index=1, user_id=None):
    all_numbers = get_combo(country_code, combo_index, user_id)
    if not all_numbers:
        return []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT assigned_number FROM users WHERE assigned_number IS NOT NULL AND assigned_number != ''")
    used_numbers = set(row[0] for row in c.fetchall())
    conn.close()
    available = [num for num in all_numbers if num not in used_numbers]
    return available

# ======================
# 🔄 Core cleaning and processing functions (as in the original)
# ======================
def clean_html(text):
    if not text:
        return ""
    text = str(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.strip()
    return text

def clean_number(number):
    if not number:
        return ""
    number = re.sub(r'\D', '', str(number))
    return number

def get_country_info(number):
    _, name, flag, short = get_country_details_smart(number)
    return name, flag, short

def mask_number(number):
    number = number.strip()
    if len(number) > 8:
        return number[:4] + "⁦⁦••••" + number[-3:]
    return number

def extract_otp(message):
    patterns = [
        r'(?:code|verification|otp|pin)[:\s]+[‎]?(\d{3,8}(?:[- ]\d{3,4})?)',
        r'(\d{3})[- ](\d{3,4})',
        r'\b(\d{4,8})\b',
        r'[‎](\d{3,8})',
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            if len(match.groups()) > 1:
                return ''.join(match.groups())
            return match.group(1).replace(' ', '').replace('-', '')
    all_numbers = re.findall(r'\d{4,8}', message)
    if all_numbers:
        return all_numbers[0]
    return "N/A"

def detect_service(message):
    message_lower = message.lower()

    # Base dictionary
    services = {
        "#WP": ["whatsapp"],
        "#FB": ["facebook", "fb"],
        "#IG": ["instagram"],
        "#TG": ["telegram"],
        "#TW": ["twitter", "x.com"],
        "#GG": ["google", "gmail"],
        "#DC": ["discord"],
        "#LN": ["line"],
        "#VB": ["viber"],
        "#SK": ["skype"],
        "#SC": ["snapchat"],
        "#TT": ["tiktok"],
        "#AMZ": ["amazon"],
        "#APL": ["apple", "icloud"],
        "#MS": ["microsoft"],
        "#IN": ["linkedin"],
        "#UB": ["uber"],
        "#AB": ["airbnb"],
        "#NF": ["netflix"],
        "#SP": ["spotify"],
        "#YT": ["youtube"],
        "#GH": ["github"],
        "#PT": ["pinterest"],
        "#PP": ["paypal"],
        "#BK": ["booking"],
        "#TL": ["tala"],
        "#OLX": ["olx"],
        "#STC": ["stcpay", "stc"],
    }

    # Basic check
    for service_code, keywords in services.items():
        for keyword in keywords:
            if keyword in message_lower:
                return service_code

    # Smart fallback from the OTP message format itself
    if "code" in message_lower or "verification" in message_lower:
        if "telegram" in message_lower:
            return "#TG"
        if "whatsapp" in message_lower:
            return "#WP"
        if "facebook" in message_lower:
            return "#FB"
        if "instagram" in message_lower:
            return "#IG"
        if "google" in message_lower or "gmail" in message_lower:
            return "#GG"
        if "twitter" in message_lower or "x.com" in message_lower:
            return "#TW"

    # Last resort
    return "Unknown"

def html_escape(text):
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")   # Very important
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def format_message(date_str, number, sms):
    country_name, country_flag, country_code = get_country_info(number)
    masked_num = mask_number(number)
    otp_code = extract_otp(sms)
    service = detect_service(sms)

    header = "• ✘ 𝙍𝘼𝙑𝙀𝙉 | 🏴☠️ • 𝙉𝙐𝙈𝘽𝙀𝙍 𝘽𝙊𝙏 𝙓  •"
    info_line = f"→ {country_flag} #{country_code} [{service}] {masked_num} ┥"
    sms_content = f"<blockquote>{html_escape(sms)}</blockquote>"
    time_content = f"<blockquote>⏰ ~ {date_str}</blockquote>"

    final_message = f"{header}\n{info_line}\n{sms_content}\n{time_content}"
    return final_message

# ======================
# 📡 iVasms dashboard connection functions
# ======================

# --- Login to iVasms ---
def login_to_ivasms():
    """Login using saved cookies"""
    global _cookies_alert_sent, _login_in_progress, _cookies_expired
    if _login_in_progress:
        return IVASMS_DASHBOARD.get('is_logged_in', False)
    if _cookies_expired:
        return False  # Won't retry until cookies change
    _login_in_progress = True
    try:
        dash    = IVASMS_DASHBOARD
        session = dash["session"]

        print(f"[{dash['name']}] Attempting login...")

        # Load cookies from file or defaults
        saved = load_cookies_from_file()

        session.headers.update(get_active_headers())
        session.cookies.clear()

        # ✅ FIX 5: Removed undefined `default_cookies` — bail out if no cookies
        if not saved:
            print(f"[{dash['name']}] ❌ No cookies found — cannot login.")
            dash['is_logged_in'] = False
            return False
        cookies_to_use = saved
        if isinstance(cookies_to_use, list):
            for c in cookies_to_use:
                domain = c.get('domain', 'www.ivasms.com').lstrip('.')
                path = c.get('path', '/')
                session.cookies.set(c['name'], c['value'], domain=domain, path=path)
                session.cookies.set(c['name'], c['value'], domain='www.ivasms.com', path=path)
                session.cookies.set(c['name'], c['value'], domain='.ivasms.com', path=path)
        else:
            for name, value in cookies_to_use.items():
                session.cookies.set(name, value, domain='www.ivasms.com', path='/')
                session.cookies.set(name, value, domain='.ivasms.com', path='/')

        dashboard_resp = session.get(
            "https://www.ivasms.com/portal/sms/received",
            timeout=30, allow_redirects=True
        )

        print(f"[{dash['name']}] 🔍 URL after login: {dashboard_resp.url}")
        print(f"[{dash['name']}] 🔍 Status: {dashboard_resp.status_code}")
        print(f"[{dash['name']}] 🔍 Cookies in session: {list(session.cookies.keys())}")
        print(f"[{dash['name']}] 🔍 Cookies details:")
        for c in session.cookies:
            print(f"    {c.name} | domain={c.domain} | value={c.value[:30]}")
        print(f"[{dash['name']}] 🔍 Response (500 chars):\n{dashboard_resp.text[200:700]}")

        is_expired = False
        expire_reason = ""

        if dashboard_resp.status_code != 200:
            is_expired = True
            expire_reason = f"Response code {dashboard_resp.status_code}"
        elif "login" in dashboard_resp.url.lower():
            is_expired = True
            expire_reason = "Redirected to login page"

        if not is_expired:
            soup = BeautifulSoup(dashboard_resp.text, 'html.parser')
            csrf_meta = soup.find('meta', {'name': 'csrf-token'})
            csrf_token = csrf_meta.get('content') if csrf_meta else None
            if not csrf_token:
                token_input = soup.find('input', {'name': '_token'})
                csrf_token = token_input['value'] if token_input else None
            if not csrf_token:
                is_expired = True
                expire_reason = "CSRF token not found"
            else:
                dash['csrf_token'] = csrf_token

        if is_expired:
            print(f"[{dash['name']}] ❌ Cookies expired ({expire_reason}) — bot will stop attempts until new cookies are sent")
            dash['is_logged_in'] = False
            _cookies_expired = True
            mar = types.InlineKeyboardMarkup(row_width=1)
            mar.add(
                types.InlineKeyboardButton("📤 Send new cookies", callback_data="cookies_send", style="success"),
                types.InlineKeyboardButton("🍪 Cookie management panel", callback_data="admin_cookies_panel", style="primary"),
                types.InlineKeyboardButton("💻 How to get cookies from PC",    callback_data="cookies_guide_pc", style="primary"),
                types.InlineKeyboardButton("📱 How to get cookies from phone", callback_data="cookies_guide_phone", style="primary")
            )
            # Send notification only once without any repetition
            if not _cookies_alert_sent:
                _cookies_alert_sent = True
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(
                            admin_id,
                            "⚠️ <b>Alert: iVasms cookies expired!</b>\n\n"
                            "The bot is currently stopped from receiving new messages.\n"
                            "Please renew the cookies from the admin panel to continue 👇",
                            reply_markup=mar,
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            return False

        print(f"[{dash['name']}] ✅ Login successful via cookies")
        dash['is_logged_in'] = True
        dash['cookies']      = session.cookies.get_dict()
        _cookies_expired     = False
        _cookies_alert_sent  = False
        return True

    except Exception as e:
        print(f"[{dash['name']}] ❌ Login error: {e}")
        return False
    finally:
        _login_in_progress = False

# --- Fetch messages from iVasms ---
def fetch_ivasms_messages():
    """Fetch SMS messages from the iVasms dashboard"""
    dash = IVASMS_DASHBOARD

    # Ensure we're logged in
    if not dash.get('is_logged_in', False):
        if not login_to_ivasms():
            return []

    try:
        session  = dash['session']
        base_url = "https://www.ivasms.com"

        # Use saved CSRF token and renew only when needed to avoid extra requests
        csrf_token = dash.get('csrf_token')
        if not csrf_token:
            dashboard_page = session.get(f"{base_url}/portal/sms/received", timeout=30)
            if dashboard_page.status_code != 200:
                print(f"[{dash['name']}] ❌ Error in messages page response: {dashboard_page.status_code}")
                dash['is_logged_in'] = False
                return []
            soup_dash  = BeautifulSoup(dashboard_page.text, 'html.parser')
            csrf_meta  = soup_dash.find('meta', {'name': 'csrf-token'})
            csrf_token = csrf_meta.get('content') if csrf_meta else None
            if not csrf_token:
                token_input = soup_dash.find('input', {'name': '_token'})
                csrf_token  = token_input['value'] if token_input else None
            if not csrf_token:
                print(f"[{dash['name']}] ❌ Could not fetch CSRF token")
                dash['is_logged_in'] = False
                return []
            dash['csrf_token'] = csrf_token

        headers = {
            'Referer':          f"{base_url}/portal/sms/received",
            'Origin':           base_url,
            'X-Requested-With': 'XMLHttpRequest',
            'Accept':           'application/json, text/javascript, */*; q=0.01',
            'sec-ch-ua':        '"Chromium";v="152", "Google Chrome";v="152", "Not-A.Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest':   'empty',
            'sec-fetch-mode':   'cors',
            'sec-fetch-site':   'same-origin',
        }

        # Fetch the message summary for the last 3 days
        today      = datetime.utcnow()
        start_date = (today - timedelta(days=3)).strftime('%m/%d/%Y')
        end_date   = today.strftime('%m/%d/%Y')

        sms_api_url     = f"{base_url}/portal/sms/received/getsms"
        summary_payload = {
            'from':   start_date,
            'to':     end_date,
            '_token': csrf_token
        }

        summary_resp = session.post(sms_api_url, headers=headers, data=summary_payload, timeout=30)
        if summary_resp.status_code == 419:
            print(f"[{dash['name']}] ⚠️ CSRF token expired, will refresh on next cycle")
            dash['csrf_token'] = None
            return []
        if summary_resp.status_code == 403:
            print(f"[{dash['name']}] ❌ Cloudflare block (403)")
            dash['is_logged_in'] = False
            return []
        summary_resp.raise_for_status()

        # Parse HTML
        summary_soup  = BeautifulSoup(summary_resp.text, 'html.parser')
        country_groups = summary_soup.find_all('div', class_='rng')
        if not country_groups:
            country_groups = [el for el in summary_soup.find_all('div') if 'toggleRange' in el.get('onclick', '')]

        if not country_groups:
            # No groups means simply no new SMS in this time range
            return []

        group_ids = []
        for group in country_groups:
            onclick = group.get('onclick', '')
            match = re.search(r"toggleRange\('([^']+)'\s*,\s*'([^']+)'\)", onclick)
            if match:
                range_id = match.group(1).strip()
                safe_id  = match.group(2).strip()
                if range_id not in [g[0] for g in group_ids]:
                    group_ids.append((range_id, safe_id))

        print(f"[{dash['name']}] 📋 Groups: {[g[0] for g in group_ids]}")
        if not group_ids:
            return []

        all_messages    = []
        numbers_url     = f"{base_url}/portal/sms/received/getsms/number"
        sms_details_url = f"{base_url}/portal/sms/received/getsms/number/sms"

        for (range_id, safe_id) in group_ids:
            numbers_payload = {
                'start':  start_date,
                'end':    end_date,
                'range':  range_id,
                '_token': csrf_token
            }
            numbers_resp = session.post(numbers_url, headers=headers, data=numbers_payload, timeout=30)
            numbers_soup = BeautifulSoup(numbers_resp.text, 'html.parser')

            phone_numbers = []
            for el in numbers_soup.find_all(['div', 'span', 'li', 'a', 'td']):
                onclick_val = el.get('onclick', '')
                if onclick_val:
                    nm = re.search(r"'(\d{7,})'", onclick_val)
                    if nm and nm.group(1) not in phone_numbers:
                        phone_numbers.append(nm.group(1))
                else:
                    txt = el.get_text(strip=True)
                    if re.fullmatch(r'\d{7,15}', txt) and txt not in phone_numbers:
                        phone_numbers.append(txt)

            if not phone_numbers:
                continue

            for phone in phone_numbers:
                sms_payload = {
                    'start':  start_date,
                    'end':    end_date,
                    'Number': phone,
                    'Range':  range_id,
                    '_token': csrf_token
                }
                sms_resp = session.post(sms_details_url, headers=headers, data=sms_payload, timeout=30)
                sms_soup = BeautifulSoup(sms_resp.text, 'html.parser')

                rows = sms_soup.select('table tbody tr')
                for row in rows:
                    msg_div = row.find('div', class_='msg-text')
                    if not msg_div:
                        continue
                    sms_text = msg_div.get_text(separator=' ').strip()
                    if not sms_text:
                        continue
                    sender_tag = row.find('span', class_='cli-tag')
                    sender     = sender_tag.get_text(strip=True) if sender_tag else 'Unknown'
                    message_id = f"{phone}-{sms_text[:50]}"
                    all_messages.append({
                        'id':        message_id,
                        'number':    phone,
                        'text':      sms_text,
                        'sender':    sender,
                        'country':   range_id,
                        'timestamp': datetime.utcnow().isoformat()
                    })

        print(f"[{dash['name']}] ✅ Fetched {len(all_messages)} messages")
        return all_messages

    except Exception as e:
        print(f"[{dash['name']}] ❌ Error fetching messages: {e}")
        traceback.print_exc()
        # If fetching fails, the session may have expired
        dash['is_logged_in'] = False
        return []

# ======================
# 🔄 Modified function: send OTP to user + group
# ======================
def send_otp_to_user_and_group(date_str, number, sms):
    # Extract the code
    otp_code = extract_otp(sms)

    # Auto-detect country and flag
    country_name, country_flag, country_code = get_country_info(number)

    # Detect the service
    service = detect_service(sms)

    # Get user_id if it exists
    user_id = get_user_by_number(number)
    log_otp(number, otp_code, sms, user_id)

    if user_id:
        try:
            lang = get_user_language(user_id)
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("• Channel •", url="https://t.me/Raven_xx24", style="primary"),
                types.InlineKeyboardButton("• Developer •", url="https://t.me/P_X_24", style="primary")
            )
            user_msg = get_text(
                "private_otp_msg",
                lang,
                country_name=safe_html(country_name),
                country_flag=country_flag,
                service=safe_html(service),
                number=safe_html(number),
                date_str=safe_html(date_str),
                otp_code=safe_html(otp_code)
            )
            bot.send_message(
                user_id,
                user_msg,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[!] Failed to send OTP to user {user_id}: {e}")
    # Send the same message to the group
    text = format_message(date_str, number, sms)
    send_to_telegram_group(text, otp_code)

def delete_message_after_delay(chat_id, message_id, delay=300):
    """Delete the message after `delay` seconds"""
    time.sleep(delay)
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        payload = {"chat_id": chat_id, "message_id": message_id}
        requests.post(url, data=payload)
    except Exception as e:
        print(f"❌ Failed to delete message: {e}")

def send_to_telegram_group(text, otp_code):
    success_count = 0

    markup = types.InlineKeyboardMarkup()

    try:
        copy_btn = types.InlineKeyboardButton(
            f"📋🔑 {otp_code}",
            copy_text=types.CopyTextButton(text=str(otp_code)),
            style='success'
        )
    except AttributeError:
        copy_btn = types.InlineKeyboardButton(
            f"📋🔑 {otp_code}",
            callback_data=f"copy_{otp_code}",
            style='success'
        )
    markup.add(copy_btn)

    markup.row(
        types.InlineKeyboardButton("• Channel •", url="https://t.me/Raven_xx24", style='primary'),
        types.InlineKeyboardButton("• Developer •", url="https://t.me/P_X_24", style='primary')
    )

    for chat_id in CHAT_IDS:
        try:
            bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                reply_markup=markup,
                disable_web_page_preview=True
            )
            print(f"[+] Message sent successfully to: {chat_id}")
            success_count += 1
        except Exception as e:
            print(f"[!] Error sending to {chat_id}: {e}")

    return success_count > 0

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_"))
def handle_copy_button(call):
    otp_code = call.data.split("_", 1)[1]
    bot.answer_callback_query(call.id, f"✅ Code copied: {otp_code}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_num_"))
def handle_copy_num_button(call):
    num = call.data.split("copy_num_", 1)[1]
    bot.answer_callback_query(call.id, f"✅ Number copied: +{num}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_range_"))
def handle_copy_range_button(call):
    r_code = call.data.split("copy_range_", 1)[1]
    bot.answer_callback_query(call.id, f"✅ Range code:\n{r_code}", show_alert=True)

def is_live_stream_enabled():
    val = get_setting('live_stream_enabled')
    if val is None:
        set_setting('live_stream_enabled', '1')
        return True
    return str(val) == '1'

def set_live_stream_enabled(enabled: bool):
    set_setting('live_stream_enabled', '1' if enabled else '0')

def get_live_stream_chat_id():
    val = get_setting('live_stream_chat_id')
    if val:
        val_str = str(val).strip()
        if val_str:
            return val_str
    return None

def set_live_stream_chat_id(chat_id):
    if chat_id:
        set_setting('live_stream_chat_id', str(chat_id).strip())
    else:
        set_setting('live_stream_chat_id', '')

# ======================
# 📡 Live traffic streamer to the group
# ======================
SENT_LIVE_FILE = os.path.join(BASE_DIR, "sent_live_messages.json")

def format_live_stream_message(m):
    """
    Format the live stream message for the Telegram group with all details,
    keeping it clearly separate from regular user OTP messages.
    """
    flag = m.get('flag') or '🌐'
    c_name = m.get('country_name') or 'Unknown'
    c_code = m.get('country_code') or ''
    range_name = (m.get('range') or '').strip()
    app_name = m.get('app') or 'SMS'
    number = m.get('number') or ''
    sms_text = html_escape(m.get('text') or '')
    time_str = m.get('time') or ''
    otp_code = extract_otp(m.get('text') or '')

    c_code_line = f" (+{c_code})" if c_code else ""
    otp_line = f"\n🔐 <b>Verification code (OTP):</b> <code>{otp_code}</code>" if otp_code else ""

    return (
        "🌐 <b>LIVE TRAFFIC • Live stream</b>\n\n"
        f"🌍 <b>Country:</b> {flag} <b>{c_name}</b><code>{c_code_line}</code>\n"
        f"🏷️ <b>Range code:</b> <code>{range_name}</code>\n"
        f"⚙️ <b>Service / App:</b> <b>[{app_name}]</b>\n"
        f"☎️ <b>Test number:</b> <code>+{number}</code>{otp_line}\n\n"
        f"📩 <b>Received message:</b>\n<blockquote>{sms_text}</blockquote>\n"
        f"⏰ <b>Time:</b> <code>{time_str}</code>"
    )

def live_stream_worker():
    """
    Live stream monitor: automatically pulls live messages and codes from iVasms
    and sends them exclusively to the live-stream group defined in the admin panel.
    """
    print("[LiveStream] 🚀 Starting the live stream monitor for the Telegram group...")
    sent_live_ids = set()
    if os.path.exists(SENT_LIVE_FILE):
        try:
            with open(SENT_LIVE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if isinstance(saved, list):
                    sent_live_ids = set(saved)
        except Exception:
            pass

    first_run = True

    while True:
        try:
            time.sleep(4)
            if not is_live_stream_enabled():
                continue

            target_chat = get_live_stream_chat_id()
            if not target_chat:
                # If no live-stream group has been set yet, don't send to the user group
                continue

            if _cookies_expired:
                continue

            import ivasms_manager as _im
            messages = _im.fetch_live_stream_messages(limit=10)
            if not messages:
                continue

            if first_run:
                for m in messages:
                    sent_live_ids.add(str(m['id']))
                first_run = False
                continue

            unseen = [m for m in messages if str(m['id']) not in sent_live_ids]
            if not unseen:
                continue

            # Mark all messages as seen so they don't pile up
            for m in unseen:
                sent_live_ids.add(str(m['id']))

            # Send only the two most recent messages per cycle to avoid Telegram spam and 429 bans
            to_send = unseen[-2:]
            new_sent = 0

            for m in to_send:
                number = m.get('number', '')
                range_name = (m.get('range') or '').strip()
                if not range_name:
                    range_name = f"{m.get('country_name', 'RANGE').upper()} {m.get('country_code', '')}"

                group_text = format_live_stream_message(m)

                # Single button containing the range code for one-tap copy, styled like the code message
                markup = types.InlineKeyboardMarkup()
                try:
                    markup.add(types.InlineKeyboardButton(
                        f"📋 {range_name}",
                        copy_text=types.CopyTextButton(text=range_name),
                        style='success'
                    ))
                except Exception:
                    markup.add(types.InlineKeyboardButton(
                        f"📋 {range_name}",
                        callback_data=f"copy_range_{range_name[:30]}",
                        style='success'
                    ))

                try:
                    bot.send_message(
                        target_chat,
                        group_text,
                        parse_mode="HTML",
                        reply_markup=markup,
                        disable_web_page_preview=True
                    )
                    new_sent += 1
                except Exception as e:
                    err_s = str(e)
                    if "429" in err_s or "Too Many Requests" in err_s:
                        m_wait = re.search(r'retry after (\d+)', err_s)
                        wait_sec = int(m_wait.group(1)) + 1 if m_wait else 15
                        print(f"[LiveStream] ⏳ Waiting for Telegram rate limit ({wait_sec}s)...")
                        time.sleep(wait_sec)
                    else:
                        print(f"[LiveStream] Send error to {target_chat}: {e}")

                user_id = get_user_by_number(number)
                if user_id:
                    try:
                        lang = get_user_language(user_id)
                        user_markup = types.InlineKeyboardMarkup()
                        user_markup.row(
                            types.InlineKeyboardButton("• Channel •", url="https://t.me/Raven_xx24", style="primary"),
                            types.InlineKeyboardButton("• Developer •", url="https://t.me/P_X_24", style="primary")
                        )
                        user_msg = get_text(
                            "private_otp_msg",
                            lang,
                            country_name=safe_html(m.get('country_name', '')),
                            country_flag=m.get('flag', ''),
                            service=safe_html(m.get('app', '')),
                            number=safe_html(number),
                            date_str=safe_html(m.get('time', '')),
                            otp_code=safe_html(extract_otp(m.get('text', '')) or "N/A")
                        )
                        bot.send_message(
                            user_id,
                            user_msg,
                            reply_markup=user_markup,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        print(f"[LiveStream] Failed to send private message to user {user_id}: {e}")

                time.sleep(3.5)  # Safety delay between messages to avoid Telegram limits

            if new_sent > 0:
                print(f"[LiveStream] 📡 New live messages streamed to the group successfully ✅")
                try:
                    with open(SENT_LIVE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(list(sent_live_ids)[-1000:], f)
                except Exception:
                    pass

            if len(sent_live_ids) > 3000:
                sent_live_ids = set(list(sent_live_ids)[-1500:])

        except Exception as ex:
            print(f"[LiveStream] ❌ Error in stream loop: {ex}")
            time.sleep(5)

# ======================
# ⏰ Periodic hourly reminder for groups
# ======================
def hourly_group_reminder_worker():
    """
    Send a periodic reminder every hour to groups where the bot is an admin,
    with a red button to open the bot.
    """
    print("[Reminder] 🚀 Starting the periodic group reminder (once per hour)...")
    time.sleep(25)  # Startup grace period

    while True:
        try:
            bot_me = bot.get_me()
            bot_username = bot_me.username or "Free_Numberv1bot"
            bot_id = bot_me.id

            groups = get_all_bot_groups()

            reminder_text = (
                "🌐 <b>PLATFORM: iVASMS</b>\n\n"
                "⚡ <b>iVASMS platform for numbers and account activation</b>\n"
                "📩 Instant reception of SMS and verification codes for all apps!\n"
                "🚀 Click the button below to start using it in a private chat ⬇️"
            )

            markup = types.InlineKeyboardMarkup()
            try:
                markup.add(types.InlineKeyboardButton(
                    "⚡ Open the bot | START BOT",
                    url=f"https://t.me/{bot_username}?start=group_reminder",
                    style='danger'
                ))
            except Exception:
                markup.add(types.InlineKeyboardButton(
                    "⚡ Open the bot | START BOT",
                    url=f"https://t.me/{bot_username}?start=group_reminder"
                , style='danger'))

            sent_count = 0
            for chat_id, title in groups:
                try:
                    # Check if the bot is admin in the group
                    member = bot.get_chat_member(chat_id, bot_id)
                    if member.status in ['administrator', 'creator']:
                        sent_m = bot.send_message(
                            chat_id,
                            reminder_text,
                            parse_mode="HTML",
                            reply_markup=markup,
                            disable_web_page_preview=True
                        )
                        # Auto-delete after one minute (60 seconds) to avoid piling up
                        threading.Thread(
                            target=delete_message_after_delay,
                            args=(chat_id, sent_m.message_id, 60),
                            daemon=True
                        ).start()
                        sent_count += 1
                        print(f"[Reminder] ✅ Reminder sent to group (auto-delete in 60s): {title} ({chat_id})")
                        time.sleep(2)
                    else:
                        print(f"[Reminder] ⚠️ Bot is not admin in {title} ({chat_id}) — skipping")
                except Exception as e:
                    print(f"[Reminder] ❌ Failed to send to group {chat_id}: {e}")

            if sent_count > 0:
                print(f"[Reminder] 📢 Reminder cycle completed — sent to {sent_count} groups")

        except Exception as e:
            print(f"[Reminder] Error in reminder cycle: {e}")

        # Wait a full hour (3600 seconds)
        time.sleep(3600)

# ======================
# 🔄 Main loop (adapted for iVasms dashboard only)
# ======================
def main_loop():
    global REFRESH_INTERVAL
    REFRESH_INTERVAL = 6  # 6 seconds safe polling to avoid Cloudflare bans

    # Single-dashboard list
    DASHBOARDS = [IVASMS_DASHBOARD]

    # File to store sent message IDs
    SENT_MESSAGES_FILE = "mafia_sent_messages.json"
    sent_messages = {}
    try:
        if os.path.exists(SENT_MESSAGES_FILE):
            with open(SENT_MESSAGES_FILE, 'r') as f:
                data = json.load(f)
                sent_messages = {mid: "" for mid in data} if isinstance(data, list) else data
    except Exception as e:
        print(f"⚠️ Error loading sent messages: {e}")

    print("=" * 60)
    print(f"🚀 Starting iVasms dashboard monitor (every {REFRESH_INTERVAL} seconds)")
    print("=" * 60)

    consecutive_errors = {dash["name"]: 0 for dash in DASHBOARDS}

    # Initial login + notify if cookies are expired
    for dash in DASHBOARDS:
        if not dash.get('is_logged_in', False):
            success = login_to_ivasms()
            if not success:
                mar = types.InlineKeyboardMarkup(row_width=1)
                mar.add(
                    types.InlineKeyboardButton("💻 How to get cookies from PC",    callback_data="cookies_guide_pc", style="primary"),
                    types.InlineKeyboardButton("📱 How to get cookies from phone", callback_data="cookies_guide_phone", style="primary"),
                    types.InlineKeyboardButton("📤 Send new cookies",     callback_data="cookies_send", style="success")
                )
                def _send_first_alert():
                    for admin_id in ADMIN_IDS:
                        try:
                            bot.send_message(
                                admin_id,
                                "👋 <b>Welcome! The bot started for the first time or cookies are expired</b>\n\n"
                                "⚠️ You need to get the cookies for your iVasms account\n"
                                "so the bot can start working with you.\n\n"
                                "Choose the cookie retrieval method 👇",
                                reply_markup=mar,
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                import threading as _th2
                _th2.Thread(target=_send_first_alert, daemon=True).start()

    while True:
        for dash in DASHBOARDS:
            if _cookies_expired:
                time.sleep(15)
                continue
            try:
                print(f"[{dash['name']}] ⏱️ Fetching messages...")

                # Fetch messages
                messages = fetch_ivasms_messages()

                if messages:
                    new_messages = 0
                    # Process messages from newest to oldest
                    for msg in messages:
                        msg_id = msg['id']

                        if msg_id not in sent_messages:
                            # Extract data
                            number = clean_number(msg['number'])
                            sms_text = msg['text']
                            date_str = msg['timestamp']

                            # Send the message
                            send_otp_to_user_and_group(date_str, number, sms_text)

                            # Add to sent list
                            sent_messages[msg_id] = datetime.utcnow().isoformat()
                            new_messages += 1

                    if new_messages > 0:
                        print(f"[{dash['name']}] ✅ Sent {new_messages} new messages")

                        # Save the sent messages list
                        try:
                            with open(SENT_MESSAGES_FILE, 'w') as f:
                                json.dump(list(sent_messages)[-1000:], f)  # Save only the last 1000 messages
                        except Exception as e:
                            print(f"⚠️ Error saving sent messages: {e}")

                    consecutive_errors[dash["name"]] = 0
                else:
                    print(f"[{dash['name']}] [=] No new messages")
                    # If session is expired but cookies aren't, retry login
                    if not dash.get('is_logged_in', False) and not _login_in_progress and not _cookies_expired:
                        print(f"[{dash['name']}] 🔄 Retrying login...")
                        threading.Thread(target=login_to_ivasms, daemon=True).start()

                # ✅ FIX 6: Fixed set/dict bug — keep as dict when trimming
                if len(sent_messages) > 2000:
                    keys = list(sent_messages)[-1000:]
                    sent_messages = {k: sent_messages[k] for k in keys}

            except Exception as e:
                consecutive_errors[dash["name"]] += 1
                print(f"[{dash['name']}] ❌ Error ({consecutive_errors[dash['name']]}): {e}")
                if consecutive_errors[dash["name"]] >= 5:
                    print(f"[{dash['name']}] ⛔ Re-login after 5 errors")
                    dash['is_logged_in'] = False
                    if not _login_in_progress:
                        threading.Thread(target=login_to_ivasms, daemon=True).start()
                    consecutive_errors[dash["name"]] = 0

            time.sleep(REFRESH_INTERVAL)


# ======================
# 🔄 Advanced cookie management and testing system
# ======================
def build_cookies_panel_markup(lang='en'):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(get_text("cookies_btn_check", lang), callback_data="cookies_check_now", style='primary'),
        types.InlineKeyboardButton(get_text("cookies_btn_send", lang), callback_data="cookies_send", style='success'),
        types.InlineKeyboardButton(get_text("cookies_btn_test_old", lang), callback_data="test_old_pull_start", style='primary'),
        types.InlineKeyboardButton(get_text("cookies_btn_pc", lang), callback_data="cookies_guide_pc", style='primary'),
        types.InlineKeyboardButton(get_text("cookies_btn_phone", lang), callback_data="cookies_guide_phone", style='primary'),
        types.InlineKeyboardButton(get_text("admin_btn_back", lang), callback_data="admin_panel", style='danger')
    )
    return markup

def get_cookies_status_text(lang='en'):
    is_active = IVASMS_DASHBOARD.get('is_logged_in', False) and not _cookies_expired
    status_icon = "🟢" if is_active else "🔴"
    status_str = get_text("cookies_active", lang) if is_active else get_text("cookies_expired", lang)
    saved = load_cookies_from_file()
    cookies_count = len(saved) if isinstance(saved, (list, dict)) else 0
    last_up = _last_cookies_update or get_text("not_specified", lang)

    text = (
        f"🍪 <b>{get_text('cookies_panel_title', lang)}</b>\n\n"
        f"• <b>{get_text('admin_bot_status', lang)}:</b> {status_icon} <u>{status_str}</u>\n"
        f"• <b>{get_text('cookies_saved_count', lang)}:</b> <code>{cookies_count}</code>\n"
        f"• <b>{get_text('cookies_last_up', lang)}:</b> <code>{last_up}</code>\n"
        f"• <b>{get_text('cookies_storage_file', lang)}:</b> <code>mafia_ck_4235.json</code>\n\n"
        "⚡ <b>Features:</b>\n"
        "• Support TXT files from browser extension directly.\n"
        "• Automated live verification before applying cookies.\n"
        "• Zero-loss safety: existing cookies kept safe if check fails."
    )
    return text

@bot.message_handler(commands=['cookies'])
def cmd_cookies(message):
    lang = get_user_language(message.from_user.id)
    if not is_admin(message.from_user.id):
        return
    bot.reply_to(
        message,
        get_cookies_status_text(lang),
        reply_markup=build_cookies_panel_markup(lang),
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data in [
    "admin_cookies_panel", "cookies_main", "cookies_check_now",
    "cookies_send", "cookies_guide_pc", "cookies_guide_phone",
    "test_old_pull_start"
])
def cookies_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⚠️ This section is for developers only.", show_alert=True)
        return

    chat_id = call.message.chat.id
    msg_id  = call.message.message_id

    lang = get_user_language(call.from_user.id)
    if call.data in ["admin_cookies_panel", "cookies_main"]:
        try:
            bot.edit_message_text(
                get_cookies_status_text(lang),
                chat_id, msg_id,
                reply_markup=build_cookies_panel_markup(lang),
                parse_mode="HTML"
            )
        except Exception:
            bot.send_message(
                chat_id,
                get_cookies_status_text(lang),
                reply_markup=build_cookies_panel_markup(lang),
                parse_mode="HTML"
            )
        bot.answer_callback_query(call.id)

    elif call.data == "cookies_check_now":
        bot.answer_callback_query(call.id, "⏳ Checking current cookies...")
        try:
            bot.edit_message_text(
                "⏳ <b>Checking current cookies against iVasms...</b>\n\nPlease wait a few seconds.",
                chat_id, msg_id,
                parse_mode="HTML"
            )
        except Exception:
            pass

        def _do_check():
            saved = load_cookies_from_file()
            if not saved:
                mar = types.InlineKeyboardMarkup(row_width=1)
                mar.add(
                    types.InlineKeyboardButton("📤 Upload TXT file or JSON code", callback_data="cookies_send", style="success"),
                    types.InlineKeyboardButton("🔙 Back", callback_data="admin_cookies_panel", style="danger")
                )
                try:
                    bot.edit_message_text(
                        "⚠️ <b>No saved cookies found!</b>\n\nPlease upload the cookie file first.",
                        chat_id, msg_id,
                        reply_markup=mar,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                return

            res = verify_and_test_cookies(saved)
            if len(res) == 4:
                ok, msg, token, matched_hdrs = res
            else:
                ok, msg, token = res[:3]
                matched_hdrs = None

            mar = types.InlineKeyboardMarkup(row_width=1)
            mar.add(
                types.InlineKeyboardButton("📤 Upload new cookies", callback_data="cookies_send", style="success"),
                types.InlineKeyboardButton("🔄 Re-check", callback_data="cookies_check_now", style="primary"),
                types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style="danger")
            )

            global _cookies_expired, _cookies_alert_sent
            if ok:
                IVASMS_DASHBOARD['is_logged_in'] = True
                if token:
                    IVASMS_DASHBOARD['csrf_token'] = token
                if matched_hdrs:
                    apply_cookies(saved, csrf_token=token, custom_headers=matched_hdrs)
                _cookies_expired = False
                _cookies_alert_sent = False
                res_text = (
                    "🟢 <b>Check result: Cookies work perfectly 100%!</b>\n\n"
                    "• <b>Site:</b> <code>ivasms.com</code> ✅\n"
                    "• <b>Messages page:</b> <code>200 OK</code> ✅\n"
                    "• <b>CSRF token:</b> present and valid ✅\n"
                    "• <b>Status:</b> Bot is connected and ready to pull OTP messages instantly 🚀"
                )
            else:
                IVASMS_DASHBOARD['is_logged_in'] = False
                _cookies_expired = True
                res_text = (
                    "🔴 <b>Check result: Cookies are invalid or expired!</b>\n\n"
                    f"• <b>Reason:</b> {msg}\n\n"
                    "⚠️ <b>Solution:</b> Log in via the browser and export fresh cookies, then click 'Upload new cookies'."
                )

            try:
                bot.edit_message_text(res_text, chat_id, msg_id, reply_markup=mar, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, res_text, reply_markup=mar, parse_mode="HTML")

        threading.Thread(target=_do_check, daemon=True).start()

    elif call.data == "cookies_send":
        cancel_mar = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton("🔙 Cancel and go back", callback_data="admin_cookies_panel", style="danger")
        ]])
        prompt_text = (
            "📤 <b>Send new cookies</b>\n\n"
            "You can send cookies in one of two ways:\n\n"
            "1️⃣ <b>Upload a text file:</b> send a <code>.txt</code> file (e.g. the file exported by the Get cookies.txt extension).\n"
            "2️⃣ <b>Paste directly:</b> paste the JSON code or Netscape lines here in the chat.\n\n"
            "🛡️ <b>Auto-verification:</b>\n"
            "The cookies will be tested immediately against iVasms. They will only be installed if the connection succeeds 100%.\n\n"
            "🔙 To cancel send: <code>cancel</code>"
        )
        try:
            bot.edit_message_text(prompt_text, chat_id, msg_id, reply_markup=cancel_mar, parse_mode="HTML")
        except Exception:
            bot.send_message(chat_id, prompt_text, reply_markup=cancel_mar, parse_mode="HTML")
        bot.register_next_step_handler(call.message, receive_new_cookies_enhanced)
        bot.answer_callback_query(call.id)

    elif call.data == "cookies_guide_pc":
        mar = types.InlineKeyboardMarkup(row_width=1)
        mar.add(
            types.InlineKeyboardButton("📤 Upload TXT file or JSON code", callback_data="cookies_send", style="success"),
            types.InlineKeyboardButton("🔙 Back to cookie panel", callback_data="admin_cookies_panel", style="danger")
        )
        guide_pc = (
            "💻 <b>Getting cookies from a PC or laptop</b>\n\n"
            "1️⃣ Open Chrome, Firefox, or Edge.\n"
            "2️⃣ Open the site and log in:\n"
            "<code>https://www.ivasms.com/login</code>\n"
            "3️⃣ Go to the received messages page:\n"
            "<code>https://www.ivasms.com/portal/sms/received</code>\n"
            "4️⃣ Install the <b>Get cookies.txt LOCALLY</b> or <b>Cookie-Editor</b> extension from your browser's store.\n"
            "5️⃣ Open the extension and press:\n"
            "• For <b>Get cookies.txt</b>: click <b>Export</b> and a <code>.txt</code> file will download.\n"
            "• For <b>Cookie-Editor</b>: click <b>Export as JSON</b> and copy the text.\n"
            "6️⃣ Return to the bot and upload the <code>.txt</code> file or paste the text here 👇"
        )
        try:
            bot.edit_message_text(guide_pc, chat_id, msg_id, reply_markup=mar, parse_mode="HTML")
        except Exception:
            pass
        bot.answer_callback_query(call.id)

    elif call.data == "test_old_pull_start":
        cancel_mar = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton("🔙 Cancel and go back", callback_data="admin_cookies_panel", style="danger")
        ]])
        prompt_text = (
            "📅 <b>Test pulling historical messages from the site</b>\n\n"
            "Enter the start date to pull messages from:\n"
            "• Format: <code>DD/MM/YYYY</code> (e.g. <code>01/01/2026</code> or <code>1/1/2026</code>)\n"
            "• Or send the word: <code>default</code> to use <code>01/01/2026</code>.\n\n"
            "⚡ <b>What will happen?</b>\n"
            "The bot will connect to the site and pull up to 10 old messages from this date and send them immediately to the official group in the new format with copy buttons to confirm the pull works.\n\n"
            "🔙 To cancel send: <code>cancel</code>"
        )
        try:
            bot.edit_message_text(prompt_text, chat_id, msg_id, reply_markup=cancel_mar, parse_mode="HTML")
        except Exception:
            bot.send_message(chat_id, prompt_text, reply_markup=cancel_mar, parse_mode="HTML")
        bot.register_next_step_handler(call.message, handle_test_old_pull_date)
        bot.answer_callback_query(call.id)

    elif call.data == "cookies_guide_phone":
        mar = types.InlineKeyboardMarkup(row_width=1)
        mar.add(
            types.InlineKeyboardButton("📤 Upload TXT file or JSON code", callback_data="cookies_send", style="success"),
            types.InlineKeyboardButton("🔙 Back to cookie panel", callback_data="admin_cookies_panel", style="danger")
        )
        guide_phone = (
            "📱 <b>Getting cookies from a phone and bypassing Cloudflare (403):</b>\n\n"
            "🌐 <b>Supported mobile browsers:</b>\n"
            "• <b>Yandex Browser</b> (easiest and best) 🟢\n"
            "• <b>Kiwi Browser</b> 🟢\n\n"
            "⚠️ <b>Two most important conditions for phone cookies to work:</b>\n"
            "1️⃣ <b>Desktop site mode:</b> in Yandex or Kiwi, tap the menu (⋮) and enable 'Desktop site' 💻 before opening the site, so the browser fingerprint matches exactly.\n"
            "2️⃣ <b>Network (Wi-Fi):</b> use the same Wi-Fi network and avoid mobile data (4G/5G) because Cloudflare binds the cookie to the IP address.\n\n"
            "<b>How to extract cookies from Yandex Browser:</b>\n"
            "1️⃣ Install <b>Yandex Browser</b> from the Play Store.\n"
            "2️⃣ Open the browser and go to the Chrome Web Store to install the <b>Cookie-Editor</b> extension.\n"
            "3️⃣ Tap the three-dot menu (⋮) at the bottom and enable <b>'Desktop site'</b> 💻.\n"
            "4️⃣ Open <code>www.ivasms.com/login</code> and log in until the dashboard opens.\n"
            "5️⃣ Tap (⋮) → <b>Extensions</b> and open <b>Cookie-Editor</b>.\n"
            "6️⃣ Click <b>Export</b> and save as <b>JSON</b> or <b>Netscape</b>.\n"
            "7️⃣ Return to the bot and upload the file or paste the text here 👇"
        )
        try:
            bot.edit_message_text(guide_phone, chat_id, msg_id, reply_markup=mar, parse_mode="HTML")
        except Exception:
            pass
        bot.answer_callback_query(call.id)

def receive_new_cookies_enhanced(message):
    if not is_admin(message.from_user.id):
        return

    # Check for cancellation
    if message.text and message.text.strip().lower() in ["cancel", "/cancel"]:
        bot.reply_to(
            message,
            "❌ <b>Cookie update cancelled.</b>",
            reply_markup=build_cookies_panel_markup(),
            parse_mode="HTML"
        )
        return

    raw_content = None

    # Case: uploading a document (.txt or .json)
    if message.document:
        try:
            file_info = bot.get_file(message.document.file_id)
            if message.document.file_size > 2 * 1024 * 1024:
                bot.reply_to(message, "⚠️ File too large. Please send a valid text cookie file.")
                return
            downloaded = bot.download_file(file_info.file_path)
            raw_content = downloaded.decode('utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message, f"❌ Failed to load and read the file: {e}")
            return
    elif message.text:
        raw_content = message.text
    else:
        bot.reply_to(message, "⚠️ Please send a valid .txt file or JSON cookie code.")
        bot.register_next_step_handler(message, receive_new_cookies_enhanced)
        return

    wait_msg = bot.reply_to(
        message,
        "⏳ <b>Analyzing cookies and testing connection with the site using Yandex, mobile, and PC fingerprints...</b>\nPlease wait a few seconds.",
        parse_mode="HTML"
    )

    def _process_cookies():
        try:
            parsed_cookies = parse_cookies_input(raw_content)
        except ValueError as ve:
            err_text = f"❌ <b>Cookie format error:</b>\n{str(ve)}"
            mar = types.InlineKeyboardMarkup([[
                types.InlineKeyboardButton("🔄 Retry", callback_data="cookies_send", style='primary'),
                types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style='danger')
            ]])
            try:
                bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
            except Exception:
                bot.reply_to(message, err_text, reply_markup=mar, parse_mode="HTML")
            return
        except Exception as ex:
            err_text = f"❌ Error while reading cookies: {ex}"
            try:
                bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="HTML")
            except Exception:
                bot.reply_to(message, err_text)
            return

        # Extract a custom User-Agent if provided in the text
        custom_ua = None
        for line in raw_content.splitlines():
            l_str = line.strip()
            if l_str.lower().startswith("user-agent:"):
                custom_ua = l_str.split(":", 1)[1].strip()
                break
            elif "Mozilla/5.0" in l_str and " " in l_str and not l_str.startswith("{") and not l_str.startswith("["):
                custom_ua = l_str
                break

        # Test cookies directly against the site using multiple fingerprints
        res = verify_and_test_cookies(parsed_cookies, preferred_ua=custom_ua)
        if len(res) == 4:
            ok, test_msg, csrf_token, matched_hdrs = res
        else:
            ok, test_msg, csrf_token = res[:3]
            matched_hdrs = None

        if ok:
            # Apply and save cookies officially with the matching fingerprint
            apply_cookies(parsed_cookies, csrf_token=csrf_token, custom_headers=matched_hdrs)
            success_text = (
                "🎉 <b>Confirmed: Cookies checked and installed successfully! 🟢</b>\n\n"
                "• <b>Site connection:</b> connected successfully (HTTP 200 OK) ✅\n"
                "• <b>Protection bypass:</b> Cloudflare verified and bypassed ✅\n"
                "• <b>CSRF security token:</b> extracted and verified ✅\n"
                "• <b>Message gateway (getsms):</b> active response 200 OK ✅\n"
                f"• <b>Number of active cookies:</b> <code>{len(parsed_cookies)}</code>\n"
                "• <b>Storage file:</b> <code>mafia_ck_4235.json</code> ✅\n\n"
                "🚀 <b>Cookies are now working 100% and the bot is monitoring messages instantly.</b>\n"
                "You can click below to test pulling old messages now to confirm the pull 👇"
            )
            mar = types.InlineKeyboardMarkup(row_width=1)
            mar.add(
                types.InlineKeyboardButton("🧪 Test pulling old messages now", callback_data="test_old_pull_start", style='success'),
                types.InlineKeyboardButton("🔍 Check current cookies", callback_data="cookies_check_now", style='primary'),
                types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style='danger')
            )
            try:
                bot.edit_message_text(success_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
            except Exception:
                bot.reply_to(message, success_text, reply_markup=mar, parse_mode="HTML")
        else:
            fail_text = (
                "❌ <b>Cookie check failed against iVasms!</b>\n\n"
                f"• <b>Reason:</b> {test_msg}\n\n"
                "🛡️ <b>System safety:</b> old cookies were not modified or cleared to protect you.\n\n"
                "💡 <b>Tip:</b> Make sure to open the page <code>/portal/sms/received</code> inside the browser and verify it opens without a Cloudflare challenge, then export the cookies immediately."
            )
            mar = types.InlineKeyboardMarkup([[
                types.InlineKeyboardButton("🔄 Retry", callback_data="cookies_send", style='primary'),
                types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style='danger')
            ]])
            try:
                bot.edit_message_text(fail_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
            except Exception:
                bot.reply_to(message, fail_text, reply_markup=mar, parse_mode="HTML")

    threading.Thread(target=_process_cookies, daemon=True).start()

def handle_test_old_pull_date(message):
    if not is_admin(message.from_user.id):
        return

    text = message.text.strip() if message.text else ""
    if not text or text.lower() in ["cancel", "/cancel"]:
        bot.reply_to(
            message,
            "❌ <b>Old pull test cancelled.</b>",
            reply_markup=build_cookies_panel_markup(),
            parse_mode="HTML"
        )
        return

    # Parse date
    start_date_str = None
    if text in ["default"]:
        start_date_str = "01/01/2026"
    else:
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d'):
            try:
                dt = datetime.strptime(text, fmt)
                start_date_str = dt.strftime('%m/%d/%Y')
                break
            except ValueError:
                pass

    if not start_date_str:
        mar = types.InlineKeyboardMarkup([[
            types.InlineKeyboardButton("🔄 Retry", callback_data="test_old_pull_start", style='primary'),
            types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style='danger')
        ]])
        bot.reply_to(
            message,
            "❌ <b>Invalid date format!</b>\n\n"
            "Please send the date in the format: <code>01/01/2026</code> or <code>2026-01-01</code>\n"
            "Or send the word: <code>default</code>",
            reply_markup=mar,
            parse_mode="HTML"
        )
        return

    wait_msg = bot.reply_to(
        message,
        f"⏳ <b>Starting the test pull...</b>\n"
        f"• Start date: <code>{start_date_str}</code>\n"
        "Connecting to iVasms, pulling messages, and sending them to the group. Please wait...",
        parse_mode="HTML"
    )

    def _execute_old_pull():
        try:
            saved = load_cookies_from_file()
            if not saved:
                err_text = "❌ No saved cookies found! Upload the cookies first."
                try:
                    bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="HTML")
                except Exception:
                    bot.reply_to(message, err_text)
                return

            # ✅ FIX 7 + PROXY: Use curl_cffi for the historical pull and attach proxy
            session = curl_requests.Session(impersonate="chrome")
            apply_proxy_to_session(session)
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': 'https://www.ivasms.com/portal/sms/received',
                'X-Requested-With': 'XMLHttpRequest'
            })
            if isinstance(saved, list):
                for c in saved:
                    domain = c.get('domain', 'www.ivasms.com').lstrip('.')
                    session.cookies.set(c['name'], c['value'], domain=domain, path=c.get('path', '/'))
            elif isinstance(saved, dict):
                for k, v in saved.items():
                    session.cookies.set(k, v, domain='www.ivasms.com', path='/')

            base_url = "https://www.ivasms.com"
            resp = session.get(f"{base_url}/portal/sms/received", timeout=25, allow_redirects=True)
            if "login" in resp.url.lower() or resp.status_code != 200:
                err_text = f"❌ Failed to connect to the site (status code: {resp.status_code}). Cookies may be expired."
                try:
                    bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="HTML")
                except Exception:
                    bot.reply_to(message, err_text)
                return

            soup = BeautifulSoup(resp.text, 'html.parser')
            csrf_meta = soup.find('meta', {'name': 'csrf-token'})
            csrf = csrf_meta.get('content') if csrf_meta else None
            if not csrf:
                err_text = "❌ Could not extract the CSRF security token from the site."
                try:
                    bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="HTML")
                except Exception:
                    bot.reply_to(message, err_text)
                return

            today_str = datetime.now().strftime('%m/%d/%Y')
            r = session.post(
                f"{base_url}/portal/sms/received/getsms",
                data={'from': start_date_str, 'to': today_str, '_token': csrf},
                timeout=25
            )
            soup_summary = BeautifulSoup(r.text, 'html.parser')
            country_groups = [el for el in soup_summary.find_all('div') if 'toggleRange' in el.get('onclick', '')]

            if not country_groups:
                no_msg_text = (
                    f"⚠️ <b>No messages found in this time range!</b>\n\n"
                    f"• From: <code>{start_date_str}</code> To: <code>{today_str}</code>\n"
                    "Your account has no messages in this period, try an older date or the word <code>default</code>."
                )
                mar = types.InlineKeyboardMarkup([[
                    types.InlineKeyboardButton("🔄 Try another date", callback_data="test_old_pull_start", style='primary'),
                    types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style='danger')
                ]])
                try:
                    bot.edit_message_text(no_msg_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
                except Exception:
                    bot.reply_to(message, no_msg_text, reply_markup=mar, parse_mode="HTML")
                return

            fetched_messages = []
            for g in country_groups:
                onclick = g.get('onclick', '')
                m = re.search(r"toggleRange\('([^']+)'\s*,\s*'([^']+)'\)", onclick)
                if not m:
                    continue
                range_id = m.group(1).strip()
                nr = session.post(
                    f"{base_url}/portal/sms/received/getsms/number",
                    data={'start': start_date_str, 'end': today_str, 'range': range_id, '_token': csrf},
                    timeout=25
                )
                nsoup = BeautifulSoup(nr.text, 'html.parser')
                phone_numbers = []
                for el in nsoup.find_all(['div', 'span', 'li', 'a', 'td']):
                    on = el.get('onclick', '')
                    if on:
                        nm = re.search(r"'(\d{7,})'", on)
                        if nm and nm.group(1) not in phone_numbers:
                            phone_numbers.append(nm.group(1))
                    else:
                        txt = el.get_text(strip=True)
                        if re.fullmatch(r'\d{7,15}', txt) and txt not in phone_numbers:
                            phone_numbers.append(txt)

                for phone in phone_numbers:
                    sr = session.post(
                        f"{base_url}/portal/sms/received/getsms/number/sms",
                        data={'start': start_date_str, 'end': today_str, 'Number': phone, 'Range': range_id, '_token': csrf},
                        timeout=25
                    )
                    ssoup = BeautifulSoup(sr.text, 'html.parser')
                    rows = ssoup.select('table tbody tr')
                    for row in rows:
                        msg_div = row.find('div', class_='msg-text')
                        sms_text = msg_div.get_text(separator=' ').strip() if msg_div else ''
                        if not sms_text:
                            continue
                        cols = row.find_all('td')
                        time_val = cols[2].get_text(strip=True) if len(cols) > 2 else '00:00:00'
                        date_str = f"{start_date_str} {time_val}"
                        fetched_messages.append({
                            'phone': phone,
                            'sms': sms_text,
                            'date': date_str,
                            'range': range_id
                        })
                        if len(fetched_messages) >= 10:
                            break
                    if len(fetched_messages) >= 10:
                        break
                if len(fetched_messages) >= 10:
                    break

            if not fetched_messages:
                err_text = "⚠️ Groups were found but message texts could not be read."
                try:
                    bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="HTML")
                except Exception:
                    bot.reply_to(message, err_text)
                return

            sent_count = 0
            for m_item in fetched_messages:
                num = clean_number(m_item['phone'])
                sms_t = m_item['sms']
                d_str = m_item['date']
                otp_c = extract_otp(sms_t)
                text_formatted = format_message(d_str, num, sms_t)
                if send_to_telegram_group(text_formatted, otp_c):
                    sent_count += 1
                time.sleep(1.2)

            report_text = (
                "🎉 <b>Historical message pull test completed successfully! 🟢</b>\n\n"
                f"• <b>Requested date:</b> <code>{start_date_str}</code>\n"
                f"• <b>Groups detected:</b> <code>{len(country_groups)}</code> groups\n"
                f"• <b>Messages pulled:</b> <code>{len(fetched_messages)}</code> messages\n"
                f"• <b>Sent to group:</b> <code>{sent_count}/{len(fetched_messages)}</code> ✅\n"
                f"• <b>Receiving group:</b> <code>{CHAT_IDS[0] if CHAT_IDS else 'N/A'}</code>\n\n"
                "🚀 <b>Messages sent to the group in Raven format with copy buttons and links successfully.</b>"
            )
            mar = types.InlineKeyboardMarkup(row_width=1)
            mar.add(
                types.InlineKeyboardButton("🔄 Test another date", callback_data="test_old_pull_start", style='primary'),
                types.InlineKeyboardButton("🔙 Cookie panel", callback_data="admin_cookies_panel", style='danger')
            )
            try:
                bot.edit_message_text(report_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
            except Exception:
                bot.reply_to(message, report_text, reply_markup=mar, parse_mode="HTML")

        except Exception as e:
            traceback.print_exc()
            err_text = f"❌ Error during test pull: {str(e)}"
            try:
                bot.edit_message_text(err_text, wait_msg.chat.id, wait_msg.message_id, parse_mode="HTML")
            except Exception:
                bot.reply_to(message, err_text)

    threading.Thread(target=_execute_old_pull, daemon=True).start()

# ==============================================================================
# 🌐 Automatic iVasms number management module (admin panel)
# ==============================================================================
import ivasms_manager as im

# Cache to store displayed live range data
LIVE_RANGES_CACHE = {}

# Short app code map
LIVE_APP_MAP = {
    "WS": "WhatsApp",
    "TG": "Telegram",
    "TT": "TikTok",
    "FB": "Facebook",
    "AP": "Apple",
    "GO": "Google",
    "TOP": "TOP",
    "ALL": "All Apps"
}

@bot.callback_query_handler(func=lambda call: call.data == "admin_ivasms_panel")
def admin_ivasms_panel_callback(call):
    if not is_admin(call.from_user.id):
        return
    user_states.pop(call.from_user.id, None)
    lang = get_user_language(call.from_user.id)
    status_info = im.check_ivasms_status()
    status_icon = "🟢" if status_info.get('ok') else "🔴"
    status_msg = status_info.get('message', '')
    nums_count = status_info.get('my_numbers_count', 0)
    combos_count = len(get_all_combos())

    stream_active = is_live_stream_enabled()
    stream_status_text = "🟢 Running and live-streaming to destination" if stream_active else "🔴 Temporarily stopped"
    stream_btn_text = "📡 Channel/Group stream: 🟢 Running (stop)" if stream_active else "📡 Channel/Group stream: 🔴 Stopped (start)"

    live_chat = get_live_stream_chat_id()
    live_chat_display = f"<code>{live_chat}</code>" if live_chat else "<i>Not set yet (click below to set)</i>"

    text = (
        "🌐 <b>iVasms live number management and pull</b>\n\n"
        f"<b>📡 Connection status:</b> {status_icon} {status_msg}\n"
        f"<b>📡 Auto stream:</b> {stream_status_text}\n"
        f"<b>📢/👥 Live stream destination (channel or group):</b> {live_chat_display}\n"
        f"<b>📊 Numbers in your site account:</b> <code>{nums_count}</code> numbers\n"
        f"<b>💾 Combos saved in the bot:</b> <code>{combos_count}</code> combos\n\n"
        "🔥 <b>Live stream of numbers receiving codes right now:</b>\n"
        "<i>Messages are pulled and streamed to the channel/group automatically, second by second, just like the site ⬇️</i>"
    )

    stream_btn_style = 'danger' if is_live_stream_active() else 'success'
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton(stream_btn_text, callback_data="ivasms_toggle_livestream", style=stream_btn_style)
    )
    if live_chat:
        markup.row(
            types.InlineKeyboardButton("📢/👥 Change channel or group", callback_data="ivasms_set_live_group", style='primary'),
            types.InlineKeyboardButton("❌ Remove destination", callback_data="ivasms_remove_live_group", style='danger')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("📢/👥 ➕ Set a channel or group for streaming", callback_data="ivasms_set_live_group", style='primary')
        )
    markup.row(
        types.InlineKeyboardButton("🟢 WhatsApp (WS) • live", callback_data="ivasms_live_WS", style='primary'),
        types.InlineKeyboardButton("✈️ Telegram (TG) • live", callback_data="ivasms_live_TG", style='primary')
    )
    markup.row(
        types.InlineKeyboardButton("🎵 TikTok (TT) • live", callback_data="ivasms_live_TT", style='primary'),
        types.InlineKeyboardButton("🔵 Facebook (FB) • live", callback_data="ivasms_live_FB", style='primary')
    )
    markup.row(
        types.InlineKeyboardButton("🍎 Apple (AP) • live", callback_data="ivasms_live_AP", style='primary'),
        types.InlineKeyboardButton("🌐 Google (GO) • live", callback_data="ivasms_live_GO", style='primary')
    )
    markup.row(
        types.InlineKeyboardButton("🔥 Top worldwide activity", callback_data="ivasms_live_TOP", style='primary')
    )
    markup.row(
        types.InlineKeyboardButton("🔄 Pull my current account numbers", callback_data="ivasms_sync_all", style='success'),
        types.InlineKeyboardButton("📋 My current site numbers", callback_data="ivasms_view_mine", style='primary')
    )
    markup.row(
        types.InlineKeyboardButton("🏷️ Assign app to combo", callback_data="admin_combo_service_menu", style='primary'),
        types.InlineKeyboardButton("🗑️ Return and delete all numbers", callback_data="ivasms_confirm_clear", style='danger')
    )
    markup.add(types.InlineKeyboardButton(get_text("admin_btn_back", lang), callback_data="admin_panel", style='danger'))

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_toggle_livestream")
def ivasms_toggle_livestream_callback(call):
    if not is_admin(call.from_user.id):
        return
    current = is_live_stream_enabled()
    set_live_stream_enabled(not current)
    new_state = not current
    state_txt = "🟢 Live stream enabled successfully!" if new_state else "🔴 Live stream temporarily stopped."
    bot.answer_callback_query(call.id, state_txt, show_alert=True)
    admin_ivasms_panel_callback(call)

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_set_live_group")
def ivasms_set_live_group_callback(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    chat_id = call.message.chat.id
    user_states[call.from_user.id] = "set_live_stream_group"

    current = get_live_stream_chat_id()
    curr_txt = f"\n• <b>Current destination:</b> <code>{current}</code>" if current else ""

    text = (
        "<b>📢/👥 Set a channel or group for live streaming (Live Traffic)</b>\n\n"
        "You can use a <b>channel</b> or a <b>group</b> to stream live messages to automatically.\n\n"
        "Now send one of the following options:\n"
        "1️⃣ <b>Public channel/group username:</b> like <code>@MyLiveChannel</code>\n"
        "2️⃣ <b>Channel link:</b> like <code>https://t.me/MyLiveChannel</code>\n"
        "3️⃣ <b>Numeric ID:</b> like <code>-100xxxxxxxxxx</code>\n"
        "4️⃣ Or simply <b>forward any message</b> from the channel or group here and the bot will recognize it automatically!"
        f"{curr_txt}\n\n"
        "⚠️ <b>Important note:</b> Make sure to add the bot as an Admin with message-posting permission in the channel or group first."
    )
    mar = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="admin_ivasms_panel", style="danger")
    ]])
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=call.message.message_id, reply_markup=mar, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=mar, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_remove_live_group")
def ivasms_remove_live_group_callback(call):
    if not is_admin(call.from_user.id):
        return
    set_live_stream_chat_id("")
    bot.answer_callback_query(call.id, "✅ Live stream destination removed and streaming stopped.", show_alert=True)
    admin_ivasms_panel_callback(call)

@bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == "set_live_stream_group")
def process_set_live_stream_group_msg(message):
    if not is_admin(message.from_user.id):
        return
    lang = get_user_language(message.from_user.id)
    raw = ""

    if message.forward_from_chat:
        raw = str(message.forward_from_chat.id)
    elif message.text:
        t = message.text.strip()
        if "t.me/" in t:
            parts = t.split("t.me/")
            sub = parts[1].strip().split("/")[0].split("?")[0]
            if sub:
                raw = f"@{sub}"
        else:
            raw = t

    if not raw:
        return

    target_id = raw
    target_title = "Channel / Group"
    chat_type_label = "Stream destination"

    try:
        chat_obj = bot.get_chat(raw)
        target_id = str(chat_obj.id)
        target_title = chat_obj.title or (f"@{chat_obj.username}" if chat_obj.username else "channel/group")
        if chat_obj.type == "channel":
            chat_type_label = "channel 📢"
        elif chat_obj.type in ["supergroup", "group"]:
            chat_type_label = "group 👥"
    except Exception:
        if not (raw.startswith("-100") or raw.startswith("@") or (raw.startswith("-") and raw[1:].isdigit())):
            mar = types.InlineKeyboardMarkup([[
                types.InlineKeyboardButton(get_text("btn_back", lang), callback_data="admin_ivasms_panel", style="danger")
            ]])
            bot.reply_to(
                message,
                "⚠️ <b>Invalid ID or link!</b>\n"
                "You can send:\n"
                "• Channel username (e.g. <code>@MyChannel</code>)\n"
                "• Channel link (e.g. <code>https://t.me/MyChannel</code>)\n"
                "• Numeric ID (e.g. <code>-1001234567890</code>)\n"
                "• Or forward a message from the channel directly to the bot.",
                parse_mode="HTML",
                reply_markup=mar
            )
            return

    set_live_stream_chat_id(target_id)
    user_states.pop(message.from_user.id, None)

    # Test send to verify bot permissions
    test_ok = True
    try:
        bot.send_message(
            target_id,
            "<b>📡 This destination has been successfully linked as [Live Traffic] for iVasms numbers!</b>\nAll live messages and test codes will be posted here automatically.",
            parse_mode="HTML"
        )
    except Exception as e:
        test_ok = False
        print(f"[LiveStream] Warning sending test message to {target_id}: {e}")

    mar = types.InlineKeyboardMarkup([[
        types.InlineKeyboardButton("🔙 Back to iVasms panel", callback_data="admin_ivasms_panel", style="danger")
    ]])

    if test_ok:
        succ_txt = (
            f"✅ <b>{chat_type_label} set successfully!</b>\n\n"
            f"• <b>Name:</b> <b>{html_escape(target_title)}</b>\n"
            f"• <b>ID:</b> <code>{target_id}</code>\n"
            f"• <b>Connection status:</b> 🟢 Connected successfully (confirmation message sent to the destination).\n\n"
            "The live stream will start sending live messages here immediately."
        )
    else:
        succ_txt = (
            f"✅ <b>ID saved:</b> <code>{target_id}</code>\n\n"
            f"⚠️ <i>Note: The bot could not send a test message. Please make sure the bot is added as an <b>Admin</b> in the {chat_type_label} and given permission to post messages.</i>"
        )

    bot.reply_to(message, succ_txt, parse_mode="HTML", reply_markup=mar)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ivasms_live_"))
def ivasms_live_app_callback(call):
    if not is_admin(call.from_user.id):
        return
    app_code = call.data.replace("ivasms_live_", "")
    app_target = LIVE_APP_MAP.get(app_code, "WhatsApp")
    badge = f"[{app_code}]" if app_code != "TOP" else ""

    bot.answer_callback_query(call.id, f"⏳ Fetching live stream for {app_target}...")

    mar = types.InlineKeyboardMarkup(row_width=1)

    if app_code == "TOP":
        ok, msg, items = im.get_top_terminations()
        if ok and items:
            text = (
                "🔥 <b>Most globally active ranges right now</b>\n\n"
                "<i>⚡ These ranges are experiencing the highest message reception activity worldwide at the moment:</i>\n\n"
            )
            for idx, t in enumerate(items[:6], 1):
                name = t.get('termination_name', '')
                total = t.get('total', 0)
                tid = t.get('id', '')
                c_code, c_name, flag, short = get_country_details_smart('', name)
                text += f"<b>{idx}.</b> {flag} [{short}] <b>{name}</b> — <code>{total:,}</code> messages\n"
                if tid:
                    LIVE_RANGES_CACHE[str(tid)] = {'range_name': name, 'app': 'All Apps'}
                    mar.add(types.InlineKeyboardButton(f"⚡ Activate and pull {name} (100 numbers)", callback_data=f"liveadd_ALL_{tid}", style='success'))
        else:
            text = "❌ Could not fetch the most active ranges currently."
    else:
        ok, msg, items = im.get_top_ranges_by_app(app_target, limit=10)
        if ok and items:
            text = (
                f"📱 <b>Live stream: {app_target} numbers {badge}</b>\n\n"
                "<i>⚡ Active ranges receiving live OTP codes right now:</i>\n\n"
            )
            for idx, r in enumerate(items[:6], 1):
                rg = r.get('range', '')
                tid = r.get('id', '')
                c_name = r.get('country_name', '')
                flag = r.get('flag', '🌍')
                short = r.get('short', 'UN')
                last_time = r.get('last_seen', '')
                test_num = r.get('test_number', '')

                text += f"<b>{idx}.</b> {flag} <b>[{short}] {rg}</b>\n"
                text += f"   • Last code: <code>{last_time}</code> | Test number: <code>+{test_num}</code>\n\n"

                if tid:
                    LIVE_RANGES_CACHE[str(tid)] = {'range_name': rg, 'app': app_target}
                    mar.add(types.InlineKeyboardButton(f"⚡ Activate and pull range {rg} ({app_code})", callback_data=f"liveadd_{app_code}_{tid}", style='success'))
            text += "<i>Click any button below to activate and pull the range and link it to the bot instantly!</i>"
        else:
            text = f"ℹ️ No active messages recorded for <b>{app_target}</b> at this minute on the site."

    mar.add(types.InlineKeyboardButton(f"🔄 Refresh live stream for {app_target}", callback_data=f"ivasms_live_{app_code}", style="primary"))
    mar.add(types.InlineKeyboardButton("🔙 Choose another app", callback_data="admin_ivasms_panel", style="danger"))

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=mar, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=mar, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("liveadd_"))
def ivasms_liveadd_callback(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split("_")
    app_code = parts[1]
    tid = parts[2]
    app_target = LIVE_APP_MAP.get(app_code, "All Apps")

    cached_info = LIVE_RANGES_CACHE.get(str(tid), {})
    range_name = cached_info.get('range_name', '')

    bot.answer_callback_query(call.id, f"⏳ Activating and pulling range {range_name or tid} for {app_target}...")

    wait_msg = bot.send_message(
        call.message.chat.id,
        f"⏳ <b>Activating the range on iVasms, pulling numbers, and saving them to the bot for ({app_target})...</b>",
        parse_mode="HTML"
    )

    def _do_add_and_sync():
        ok, msg, summary = im.add_range_and_sync_to_bot(tid, app_name=app_target, range_name=range_name)
        mar = types.InlineKeyboardMarkup(row_width=1)
        mar.add(
            types.InlineKeyboardButton(f"🔙 Back to {app_target} stream", callback_data=f"ivasms_live_{app_code}", style="danger"),
            types.InlineKeyboardButton("🌐 iVasms numbers panel", callback_data="admin_ivasms_panel", style="primary")
        )

        if ok and summary:
            c_flag = summary.get('flag', '🌍')
            c_name = summary.get('country_name', '')
            c_short = summary.get('short', '')
            c_code = summary.get('country_code', '')
            count = summary.get('count', 0)
            rg_name = summary.get('range_name', '')
            badge = f"[{app_code}] " if app_code != "ALL" else ""

            res_text = (
                "🎉 <b>Activation and pull successful!</b>\n\n"
                f"📌 <b>Range:</b> <code>{rg_name}</code>\n"
                f"📱 <b>Assigned app:</b> <b>{app_target} {badge.strip()}</b>\n"
                f"🌍 <b>Country:</b> {c_flag} <b>{c_name}</b> <code>(+{c_code})</code>\n"
                f"📊 <b>Range size (number count):</b> <code>{count}</code> numbers\n\n"
                "✨ <b>Numbers were linked to the bot database instantly and are ready for users!</b>\n"
                f"🏷️ <i>The country button will appear to users as: <code>{c_flag} {badge}{c_name}</code></i>"
            )
        else:
            res_text = f"❌ <b>Operation failed:</b>\n\n{msg}"

        try:
            bot.edit_message_text(res_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, res_text, reply_markup=mar, parse_mode="HTML")

    threading.Thread(target=_do_add_and_sync, daemon=True).start()

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_sync_all")
def ivasms_sync_all_callback(call):
    if not is_admin(call.from_user.id):
        return
    lang = get_user_language(call.from_user.id)
    bot.answer_callback_query(call.id, "⏳ Syncing and pulling numbers from the site...")

    wait_msg = bot.send_message(call.message.chat.id, "⏳ <b>Connecting to iVasms, pulling numbers, and adding them to combos...</b>", parse_mode="HTML")

    def _do_sync():
        ok, msg, summary = im.sync_numbers_to_bot_combos()
        mar = types.InlineKeyboardMarkup()
        mar.add(types.InlineKeyboardButton("🔙 iVasms numbers panel", callback_data="admin_ivasms_panel", style="danger"))

        if ok and summary:
            detail_lines = []
            for c_code, count in summary.items():
                c_info = COUNTRY_CODES.get(c_code)
                if c_info:
                    c_name, c_flag, c_short = c_info
                else:
                    _, c_name, c_flag, c_short = get_country_details_smart(c_code)
                detail_lines.append(f"• {c_flag} <b>{c_name} [{c_short}] (+{c_code}):</b> <code>{count}</code> numbers")

            res_text = (
                "🎉 <b>Sync completed successfully</b>\n\n"
                f"{msg}\n\n"
                "<b>📋 Details of numbers added to combos:</b>\n" +
                "\n".join(detail_lines) + "\n\n"
                "✨ <i>Numbers are now available and updated instantly for all bot users!</i>"
            )
        elif ok:
            res_text = f"ℹ️ <b>Notice:</b> {msg}\n\nPlease activate ranges from the live stream first, then re-sync."
        else:
            res_text = f"❌ <b>Sync failed:</b>\n{msg}"

        try:
            bot.edit_message_text(res_text, wait_msg.chat.id, wait_msg.message_id, reply_markup=mar, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, res_text, reply_markup=mar, parse_mode="HTML")

    threading.Thread(target=_do_sync, daemon=True).start()

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_view_mine")
def ivasms_view_mine_callback(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id, "⏳ Fetching your account numbers...")
    ok, msg, numbers = im.get_all_my_numbers()
    mar = types.InlineKeyboardMarkup()
    mar.add(types.InlineKeyboardButton("🔙 iVasms numbers panel", callback_data="admin_ivasms_panel", style="danger"))

    if not ok:
        text = f"❌ {msg}"
    elif not numbers:
        text = "ℹ️ <b>Your account currently has no numbers added on the site.</b>\n\nYou can use the [Live stream per app] buttons to activate and pull numbers instantly."
    else:
        sample_lines = []
        for i, item in enumerate(numbers[:15], 1):
            sample_lines.append(f"{i}. <code>+{item['number']}</code> ({item['range_name']}) - ${item['rate']}")

        text = (
            f"📋 <b>Your current iVasms numbers ({len(numbers)} numbers)</b>\n\n" +
            "\n".join(sample_lines) +
            (f"\n\n<i>... and {len(numbers) - 15} more numbers registered on your account.</i>" if len(numbers) > 15 else "")
        )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=mar, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=mar, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_confirm_clear")
def ivasms_confirm_clear_callback(call):
    if not is_admin(call.from_user.id):
        return
    mar = types.InlineKeyboardMarkup(row_width=1)
    mar.add(
        types.InlineKeyboardButton("⚠️ Yes, confirm returning and deleting all numbers", callback_data="ivasms_do_clear_all", style="danger"),
        types.InlineKeyboardButton("🔙 Cancel and go back", callback_data="admin_ivasms_panel", style="primary")
    )
    text = (
        "<b>⚠️ Important security warning!</b>\n\n"
        "Are you absolutely sure you want to:\n"
        "1. Return and delete <b>all numbers</b> from your iVasms account?\n"
        "2. Empty and delete all combos saved in the bot?\n\n"
        "<i>This action cannot be undone.</i>"
    )
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=mar, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "ivasms_do_clear_all")
def ivasms_do_clear_all_callback(call):
    if not is_admin(call.from_user.id):
        return
    bot.answer_callback_query(call.id, "⏳ Returning numbers...")
    ok, msg = im.return_all_numbers_from_system()
    mar = types.InlineKeyboardMarkup()
    mar.add(types.InlineKeyboardButton("🔙 iVasms numbers panel", callback_data="admin_ivasms_panel", style="danger"))
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=mar, parse_mode="HTML")

# ======================
# 🏷️ Combo app assignment management for admins
# ======================
@bot.callback_query_handler(func=lambda call: call.data == "admin_combo_service_menu")
def admin_combo_service_menu_callback(call):
    if not is_admin(call.from_user.id):
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT country_code, combo_index, service FROM combos ORDER BY country_code, combo_index")
    rows = c.fetchall()
    conn.close()

    if not rows:
        bot.answer_callback_query(call.id, "⚠️ There are no combos in the bot right now.", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for c_code, c_idx, svc in rows:
        name, flag, short = COUNTRY_CODES.get(c_code, ("Unknown", "🌍", "UN"))
        current_svc = svc or "All Apps"
        btn_text = f"{flag} [{short}] {name} (#{c_idx}) ➔ {current_svc}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"set_svc_pick_{c_code}_{c_idx}", style='primary'))

    markup.add(types.InlineKeyboardButton("🔙 Back to admin panel", callback_data="admin_panel", style="danger"))
    text = (
        "🏷️ <b>Assign an app to each combo</b>\n\n"
        "Click on any country/combo to set its app (WhatsApp, TikTok, etc.) or make it for all apps.\n\n"
        "<i>📌 The app name will reflect instantly on the country button and in the number details message for users.</i>"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_svc_pick_"))
def admin_set_svc_pick_callback(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split("_")
    c_code = parts[3]
    c_idx = int(parts[4])
    name, flag, short = COUNTRY_CODES.get(c_code, ("Unknown", "🌍", "UN"))
    current_svc = get_combo_service(c_code, c_idx)

    markup = types.InlineKeyboardMarkup(row_width=2)
    apps = [
        ("🟢 WhatsApp", "WhatsApp"),
        ("✈️ Telegram", "Telegram"),
        ("🎵 TikTok", "TikTok"),
        ("🔵 Facebook", "Facebook"),
        ("🍎 Apple", "Apple"),
        ("🌐 All Apps", "All Apps")
    ]
    app_buttons = [types.InlineKeyboardButton(label, callback_data=f"do_set_svc_{c_code}_{c_idx}_{val}", style='primary') for label, val in apps]
    for i in range(0, len(app_buttons), 2):
        markup.row(*app_buttons[i:i+2])
    markup.add(types.InlineKeyboardButton("🔙 Back to combo list", callback_data="admin_combo_service_menu", style="danger"))

    text = (
        f"<b>🏷️ Choose the assigned app for {flag} [{short}] {name} (#{c_idx}):</b>\n\n"
        f"• <b>Current app:</b> <code>{current_svc}</code>\n\n"
        "Choose the desired app from the list below ⬇️"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("do_set_svc_"))
def admin_do_set_svc_callback(call):
    if not is_admin(call.from_user.id):
        return
    parts = call.data.split("_")
    c_code = parts[3]
    c_idx = int(parts[4])
    app_val = "_".join(parts[5:])

    set_combo_service(c_code, c_idx, app_val)
    name, flag, short = COUNTRY_CODES.get(c_code, ("Unknown", "🌍", "UN"))
    bot.answer_callback_query(call.id, f"✅ App ({app_val}) assigned to {name}!", show_alert=True)
    admin_combo_service_menu_callback(call)

# ======================
# ▶️ Run the interactive bot in a separate thread
# ======================
def run_bot():
    print("[*] Starting bot...")
    # ✅ FIX 8: Clear any stale Telegram webhook before polling
    try:
        bot.delete_webhook(drop_pending_updates=True)
        print("[*] Webhook cleared. Using long polling.")
    except Exception as e:
        print(f"[!] delete_webhook failed: {e}")
    while True:
        try:
            bot.polling(none_stop=True, timeout=30)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[!] Polling error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=main_loop, daemon=True).start()
    threading.Thread(target=live_stream_worker, daemon=True).start()
    threading.Thread(target=hourly_group_reminder_worker, daemon=True).start()
    run_bot()
