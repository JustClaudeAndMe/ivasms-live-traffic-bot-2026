#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
from telebot import types

# ======================
# 📖 Translations (English only)
# ======================
TRANSLATIONS = {
    'en': {
        'welcome_banner': (
            '<b>   ⚡ FREE NUMBER OTP BOT ⚡   </b>\n\n\n'
            '<b>👋 Welcome to the live bot for activating and receiving OTPs!</b>\n\n'
            '<b>✨ Bot Features:</b>\n'
            '• <b>Instant Delivery:</b> Ultra-fast OTP verification codes.\n'
            '• <b>Fresh Numbers:</b> Continuously rotating and refreshed active numbers.\n'
            '• <b>Global Reach:</b> Wide coverage across countries and top services.\n\n\n'
            '<b>Select your desired country below to get started ⬇️</b>'
        ),
        'number_details': (
            '<b>📱 NUMBER DETAILS</b>\n\n'
            '• <b>Assigned Number:</b> <code>+{number}</code> <i>(Tap to copy)</i>\n'
            '• <b>Country:</b> {flag} <b>{country}</b> <code>[{short}]</code>\n'
            '• <b>App / Service:</b> 📱 <b>{service}</b>\n'
            '• <b>Combo:</b> <code>#{combo}</code>\n'
            '• <b>Status:</b> ⏳ <b>Waiting for OTP SMS code...</b>\n\n\n'
            '<i>📌 Copy the number, paste it into your app, and your verification code will arrive right here!</i>\n'
        ),
        'private_otp_msg': (
            '✨ <b><u>• 𝙉𝙐𝙈𝘽𝙀𝙍 𝘽𝙊𝙏 𝙓 •</u></b>\n'
            '🌍 <b>Country:</b> {country_name} {country_flag}\n'
            '⚙ <b>Service:</b> {service}\n'
            '☎ <b>Number:</b> <code>+{number}</code>\n'
            '🕒 <b>Time:</b> <code>{date_str}</code>\n\n'
            '🔐 <b>Verification Code (OTP):</b>\n'
            '👉 <code>{otp_code}</code> 👈'
        ),
        'btn_change_num': '🔄 Change Number',
        'btn_back': '🔙 Back to Menu',
        'btn_language': '🌐 Language',
        'choose_language': '🌐 <b>Please choose your preferred language from the list below:</b>',
        'language_changed': '✅ Language successfully set to: English 🇺🇸',
        'all_numbers_busy': (
            '<b>❌ Sorry, all numbers for this country are currently in use.</b>\n'
            'Please try another country or check back soon.'
        ),
        'number_assigned_alert': '✅ Number assigned successfully!',
        'number_changed_alert': '✅ Number replaced with a fresh one.',
        'banned_user': '<b>🚫 Sorry, your account has been banned from using this bot.</b>',
        'force_sub_alert': '<b>🔒 Notice: Please join the required channels below to use this bot.</b>',
        'force_sub_check_btn': '✅ Check Subscription',
        'sub_checked_ok': '✅ Channel subscription verified! Welcome.',
        'sub_checked_fail': '⚠️ Channel subscription not verified yet. Please join the channels and try again.',
        'maintenance_caption': (
            '<b>⚙️ MAINTENANCE MODE</b>\n\n'
            '<b>⚠️ We apologize for the inconvenience..</b>\n'
            '<b>The bot is currently undergoing maintenance and updates to ensure top performance.</b>\n\n'
            '<b>⏳ We will be back very shortly. Please try again soon.</b>\n'
        ),

        # --- Admin panel ---
        'admin_manage_admins': '👮‍♂️ Admin Management',
        'admin_add_admin': '➕ Add New Admin',
        'admin_del_admin': '➖ Remove Admin',
        'admin_list_admins': '📋 List Admins',
        'admin_panel_admins_title': (
            '👮‍♂️ <b>Admin Management Panel</b>\n\n'
            '• Manage, add, and remove administrators here.'
        ),
        'admin_prompt_send_id': (
            '📥 <b>Add New Admin:</b>\n\n'
            'Please send the <b>Telegram User ID</b> of the person to promote, '
            'or <b>forward</b> any message from them here:'
        ),
        'admin_added_success': (
            '✅ <b>Admin added successfully!</b>\n\n'
            '• <b>User ID:</b> <code>{admin_id}</code>\n'
            '• Has now full access to the Admin Panel.'
        ),
        'admin_already_exists': '⚠️ This user is already an admin!',
        'admin_removed_success': (
            '🗑️ <b>Admin removed successfully!</b>\n\n'
            '• <b>User ID:</b> <code>{admin_id}</code>'
        ),
        'admin_cannot_remove_owner': '⛔ You cannot remove the main bot owner!',
        'admin_notify_promoted': (
            '🎉 <b>Congratulations! You have been promoted to Admin.</b>\n\n'
            'You can now send /admin to access the Control Panel.'
        ),
        'admin_list_title': '📋 <b>Authorized Admins List:</b>\n\n',
        'admin_owner_badge': '👑 [Main Owner]',
        'admin_role_badge': '🛡️ [Admin]',
        'admin_del_select_prompt': '🗑️ <b>Select the admin to remove from the list below:</b>',
        'admin_no_removable_admins': 'ℹ️ No additional admins to remove currently.',
        'invalid_user_id': '❌ Invalid User ID! Please send numbers only (e.g. 123456789).',

        'admin_title': 'Admin Control Panel',
        'admin_greeting': 'Welcome to the bot administration center.',
        'admin_desc': 'You can manage and customize all bot features and services here.',
        'admin_warning': 'Warning: Any changes made here will reflect immediately on users.',
        'admin_sys_info': 'System Information',
        'admin_bot_status': 'Bot Status',
        'admin_status_online': 'Status: Active & Online',
        'admin_status_maint': 'Status: Under Maintenance',
        'admin_server_conn': 'Server Connection',
        'admin_online_label': 'Online',
        'admin_current_time': 'Current Time',
        'admin_only_alert': '⚠️ Access denied. Admin area only.',

        'admin_add_combo': '📥 Add Combo',
        'admin_del_combo': '🗑️ Delete Combo',
        'admin_stats': '📊 Statistics',
        'admin_full_report': '📄 Full Report',
        'admin_broadcast_all': '📢 Broadcast All',
        'admin_broadcast_user': '📨 Broadcast User',
        'admin_ban': '🚫 Ban User',
        'admin_unban': '✅ Unban User',
        'admin_user_info': '👤 User Info',
        'admin_force_sub': '🔗 Force Sub',
        'admin_dashboards': '🖥️ Dashboards',
        'admin_private_combo': '🔑 Private Combo',
        'admin_cookies_panel': '🍪 Cookies Manager',
        'admin_change_lang': '🌐 Admin Language',
        'admin_leave': '🔙 Exit Admin Panel',
        'admin_btn_back': '🔙 Back to Admin Panel',

        # --- Cookie panel ---
        'cookies_btn_check': '🔍 Test Active Cookies Now',
        'cookies_btn_send': '📤 Upload TXT / Paste JSON',
        'cookies_btn_test_old': '🧪 Test Historical Pull (Date)',
        'cookies_btn_pc': '💻 PC Cookie Guide',
        'cookies_btn_phone': '📱 Phone Cookie Guide',
        'cookies_active': 'Active and Connected to Site',
        'cookies_expired': 'Expired or Disconnected',
        'not_specified': 'Not specified',
        'cookies_panel_title': 'Cookies Management Panel (iVasms)',
        'cookies_saved_count': 'Saved Cookies Count',
        'cookies_last_up': 'Last Update',
        'cookies_storage_file': 'Storage File',
        'choose_admin_lang': '🌐 <b>Select your preferred language for the Admin Panel:</b>',
        'admin_lang_changed': '✅ Admin Panel language updated successfully!',

        # --- iVasms panel ---
        'admin_ivasms_panel': '🌐 iVasms Auto Numbers',
        'ivasms_btn_sync': '🔄 Sync & Pull Numbers to Bot',
        'ivasms_btn_search': '🔎 Search & Add Country Range',
        'ivasms_btn_view_mine': '📋 My Current Site Numbers',
        'ivasms_btn_clear_all': '🗑️ Return & Clear All Numbers',
        'service_all_apps': '🌐 All Apps (WhatsApp, Telegram, TikTok, Facebook...)',
    }
}


def get_text(key, lang='en', **kwargs):
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get('en', {}).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


# ======================
# 🌐 Supported languages (English only)
# ======================
SUPPORTED_LANGUAGES = {
    'en': {'name': 'English', 'flag': '🇺🇸', 'dir': 'ltr'},
}

DEFAULT_LANGUAGE = 'en'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot1.db")


# ======================
# 🛠️ Schema migration for users table
# ======================
def init_user_lang_column():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA table_info(users)")
        cols = [col[1] for col in c.fetchall()]
        if 'lang' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'en'")
            conn.commit()
            print("[locales] ✅ Added 'lang' column to users table.")
        conn.close()
    except Exception as e:
        print(f"[locales] ⚠️ Error checking 'lang' column: {e}")


init_user_lang_column()


def get_user_language(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        if row and row[0] and row[0] in SUPPORTED_LANGUAGES:
            return row[0]
    except Exception as e:
        print(f"[locales] Error reading user language for {user_id}: {e}")
    return DEFAULT_LANGUAGE


def set_user_language(user_id, lang_code):
    if lang_code not in SUPPORTED_LANGUAGES:
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        exists = c.fetchone()
        if exists:
            c.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang_code, user_id))
        else:
            c.execute("INSERT INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang_code))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[locales] Error saving user language for {user_id}: {e}")
        return False


def build_language_markup(current_lang=DEFAULT_LANGUAGE):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for code, info in SUPPORTED_LANGUAGES.items():
        is_selected = "✓ " if code == current_lang else ""
        btn_title = f"{is_selected}{info['flag']} {info['name']}"
        btn_style = 'success' if code == current_lang else 'primary'
        buttons.append(types.InlineKeyboardButton(btn_title, callback_data=f"set_lang_{code}", style=btn_style))
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i + 2])
    back_text = get_text("btn_back", current_lang)
    markup.add(types.InlineKeyboardButton(back_text, callback_data="back_to_countries", style='danger'))
    return markup


def build_admin_language_markup(current_lang=DEFAULT_LANGUAGE):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for code, info in SUPPORTED_LANGUAGES.items():
        is_selected = "✓ " if code == current_lang else ""
        btn_title = f"{is_selected}{info['flag']} {info['name']}"
        btn_style = 'success' if code == current_lang else 'primary'
        buttons.append(types.InlineKeyboardButton(btn_title, callback_data=f"set_admin_lang_{code}", style=btn_style))
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i + 2])
    back_text = get_text("admin_btn_back", current_lang)
    markup.add(types.InlineKeyboardButton(back_text, callback_data="admin_panel", style='danger'))
    return markup
