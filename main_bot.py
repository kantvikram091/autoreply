# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import psycopg2
from psycopg2 import extras
import json
import pytz
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL     = os.getenv('DATABASE_URL')
BOT_API_ID       = int(os.getenv('API_ID'))
BOT_API_HASH     = os.getenv('API_HASH')
MAIN_BOT_TOKEN   = os.getenv('MAIN_BOT_TOKEN')
LOGGER_BOT_TOKEN = os.getenv('LOGGER_BOT_TOKEN')
ADMINS           = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]
SUPPORT_LINK     = os.getenv('SUPPORT_LINK', 'https://t.me/Uzeron_Ads_support')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME', '@Pandaysubscription')
BOT_USERNAME     = "@UzeronReplyBot"
IST              = pytz.timezone('Asia/Kolkata')

# ════════════════════════════════════════════
# KEYBOARD HELPERS
# ════════════════════════════════════════════

def make_keyboard(buttons):
    return {"inline_keyboard": buttons}

def welcome_keyboard():
    return make_keyboard([
        [{"text": "🎟️ Activate Premium", "callback_data": "redeem_prompt"},
         {"text": "💰 Get Premium",       "callback_data": "get_premium"}],
        [{"text": "📢 Support Channel",   "url": SUPPORT_LINK},
         {"text": "📞 Contact Us",        "url": f"https://t.me/{CONTACT_USERNAME.strip('@')}"}],
    ])

def dashboard_keyboard(auto_reply_on):
    ar_text = "🟢 Auto-Reply: ON  ✦ Tap to Pause" if auto_reply_on else "🔴 Auto-Reply: OFF ✦ Tap to Enable"
    return make_keyboard([
        [{"text": "👤 My Account",         "callback_data": "account"},
         {"text": "📊 Status",             "callback_data": "status"}],
        [{"text": "📋 Set Price List",     "callback_data": "set_price"},
         {"text": "🏪 Business Name",      "callback_data": "set_biz"}],
        [{"text": "🤖 AI Greeting Msg",   "callback_data": "set_greeting"},
         {"text": "📩 My Leads",           "callback_data": "leads"}],
        [{"text": ar_text,                 "callback_data": "toggle_ar"}],
        [{"text": "🔑 Login Account",      "callback_data": "login"},
         {"text": "🚪 Logout",             "callback_data": "logout"}],
        [{"text": "💎 Subscription",       "callback_data": "premium"}],
    ])

def back_keyboard():
    return make_keyboard([[{"text": "🏠 Dashboard", "callback_data": "dashboard"}]])

def cancel_keyboard(cb):
    return make_keyboard([[{"text": "❌ Cancel", "callback_data": cb}]])

# ════════════════════════════════════════════
# DATABASE
# ════════════════════════════════════════════

class Database:
    def __init__(self):
        self.init_db()

    def get_conn(self):
        return psycopg2.connect(DATABASE_URL, sslmode='require')

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS reply_users (
            user_id            BIGINT PRIMARY KEY,
            username           TEXT,
            phone              TEXT,
            api_id             INTEGER,
            api_hash           TEXT,
            session_string     TEXT,
            business_name      TEXT,
            price_list         TEXT,
            greeting_msg       TEXT,
            auto_reply         INTEGER DEFAULT 1,
            subscription_expiry TEXT,
            total_leads        INTEGER DEFAULT 0,
            created_at         TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS reply_codes (
            code      TEXT PRIMARY KEY,
            days      INTEGER,
            used      INTEGER DEFAULT 0,
            used_by   BIGINT,
            used_at   TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS reply_leads (
            id                SERIAL PRIMARY KEY,
            seller_id         BIGINT,
            customer_id       BIGINT,
            customer_name     TEXT,
            customer_username TEXT,
            message           TEXT,
            bot_reply         TEXT,
            created_at        TEXT
        )''')
        conn.commit()
        conn.close()

    def add_code(self, code, days):
        conn = self.get_conn(); c = conn.cursor()
        try:
            c.execute('INSERT INTO reply_codes (code, days) VALUES (%s, %s)', (code, days))
            conn.commit(); conn.close(); return True
        except psycopg2.errors.UniqueViolation:
            conn.close(); return False

    def get_unused_codes(self):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT code, days FROM reply_codes WHERE used=0')
        r = c.fetchall(); conn.close(); return r

    def redeem_code(self, code, user_id, username):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT days, used FROM reply_codes WHERE code=%s', (code,))
        row = c.fetchone()
        if not row: conn.close(); return False, "❌ Invalid code."
        days, used = row
        if used: conn.close(); return False, "❌ Code already used."
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('UPDATE reply_codes SET used=1, used_by=%s, used_at=%s WHERE code=%s',
                  (user_id, now_str, code))
        c.execute('SELECT user_id FROM reply_users WHERE user_id=%s', (user_id,))
        if c.fetchone():
            c.execute('UPDATE reply_users SET subscription_expiry=%s, username=%s WHERE user_id=%s',
                      (expiry, username, user_id))
        else:
            c.execute('''INSERT INTO reply_users
                (user_id, username, auto_reply, subscription_expiry, created_at)
                VALUES (%s,%s,1,%s,%s)''',
                (user_id, username, expiry, now_str))
        conn.commit(); conn.close(); return True, days

    def is_premium(self, user_id):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT subscription_expiry FROM reply_users WHERE user_id=%s', (user_id,))
        r = c.fetchone(); conn.close()
        if not r or not r[0]: return False
        return datetime.now() < datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S')

    def days_left(self, user_id):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT subscription_expiry FROM reply_users WHERE user_id=%s', (user_id,))
        r = c.fetchone(); conn.close()
        if not r or not r[0]: return 0
        return max(0, (datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S') - datetime.now()).days)

    def get_user(self, user_id):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT * FROM reply_users WHERE user_id=%s', (user_id,))
        r = c.fetchone(); conn.close(); return r

    def get_all_premium_users(self):
        conn = self.get_conn(); c = conn.cursor()
        c.execute("SELECT user_id, username, subscription_expiry FROM reply_users WHERE subscription_expiry IS NOT NULL")
        rows = c.fetchall(); conn.close()
        now = datetime.now()
        return [r for r in rows if r[2] and now < datetime.strptime(r[2], '%Y-%m-%d %H:%M:%S')]

    def get_all_active_sellers(self):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('''SELECT user_id, session_string, price_list, business_name,
                            greeting_msg, auto_reply, subscription_expiry, api_id, api_hash
                     FROM reply_users
                     WHERE session_string IS NOT NULL AND subscription_expiry IS NOT NULL''')
        rows = c.fetchall(); conn.close()
        now = datetime.now()
        return [r for r in rows if r[6] and now < datetime.strptime(r[6], '%Y-%m-%d %H:%M:%S')]

    def revoke_premium(self, user_id):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('UPDATE reply_users SET subscription_expiry=NULL WHERE user_id=%s', (user_id,))
        conn.commit(); conn.close()

    def save_session(self, user_id, phone, api_id, api_hash, session_string):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('''UPDATE reply_users SET phone=%s, api_id=%s, api_hash=%s, session_string=%s
                     WHERE user_id=%s''',
                  (phone, api_id, api_hash, session_string, user_id))
        conn.commit(); conn.close()

    def logout_user(self, user_id):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('''UPDATE reply_users SET phone=NULL, api_id=NULL, api_hash=NULL,
                     session_string=NULL WHERE user_id=%s''', (user_id,))
        conn.commit(); conn.close()

    def update_field(self, user_id, field, value):
        conn = self.get_conn(); c = conn.cursor()
        c.execute(f'UPDATE reply_users SET {field}=%s WHERE user_id=%s', (value, user_id))
        conn.commit(); conn.close()

    def get_leads(self, seller_id, limit=10):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('''SELECT customer_name, customer_username, message, bot_reply, created_at
                     FROM reply_leads WHERE seller_id=%s ORDER BY id DESC LIMIT %s''',
                  (seller_id, limit))
        r = c.fetchall(); conn.close(); return r

    def get_total_leads(self, seller_id):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM reply_leads WHERE seller_id=%s', (seller_id,))
        r = c.fetchone(); conn.close(); return r[0] if r else 0

    def get_stats(self):
        conn = self.get_conn(); c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM reply_users WHERE subscription_expiry IS NOT NULL')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM reply_leads')
        leads = c.fetchone()[0]
        conn.close()
        return total, leads

# ════════════════════════════════════════════
# BOT API HELPERS
# ════════════════════════════════════════════

def bot_api(method, data=None):
    url = f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/{method}"
    try:
        processed = {k: json.dumps(v) if isinstance(v, dict) else v
                     for k, v in (data or {}).items()}
        requests.post(url, data=processed, timeout=10)
    except Exception as e:
        print(f"Bot API error [{method}]: {e}")

def send_msg(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard: data["reply_markup"] = json.dumps(keyboard)
    bot_api("sendMessage", data)

def edit_msg(chat_id, msg_id, text, keyboard=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if keyboard: data["reply_markup"] = json.dumps(keyboard)
    bot_api("editMessageText", data)

# ════════════════════════════════════════════
# LOGGER
# ════════════════════════════════════════════

class Logger:
    def __init__(self, token):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"

    def log(self, chat_id, text):
        try:
            requests.post(self.url,
                data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
                timeout=10)
        except Exception as e:
            print(f"Logger error: {e}")

# ════════════════════════════════════════════
# MESSAGE TEMPLATES
# ════════════════════════════════════════════

def welcome_text():
    return (
        "🤖 <b>UZERON REPLYBOT</b>\n"
        "<i>AI-Powered Auto Reply System</i>\n\n"
        "╔══════════════════════╗\n"
        "║ ✦ Replies while you're away\n"
        "║ ✦ Uses your own price list\n"
        "║ ✦ Auto-detects when you're offline\n"
        "║ ✦ Saves every customer as a lead\n"
        "║ ✦ 24/7 cloud hosting\n"
        "╚══════════════════════╝\n\n"
        "🔒 <b>Subscription required to activate.</b>\n"
        f"Use /redeem CODE or contact {CONTACT_USERNAME}"
    )

def dashboard_text(user, days):
    # user columns: user_id, username, phone, api_id, api_hash,
    #               session_string, business_name, price_list, greeting_msg,
    #               auto_reply, subscription_expiry, total_leads, created_at
    phone   = user[2]  if user and user[2]  else "❌ Not connected"
    biz     = user[6]  if user and user[6]  else "❌ Not set"
    price   = "✅ Set" if user and user[7]  else "❌ Not set"
    greet   = "✅ Set" if user and user[8]  else "⚙️ Default"
    ar      = "🟢 ON"  if user and user[9]  else "🔴 OFF"
    return (
        "⚡ <b>UZERON REPLYBOT — Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 <b>Business:</b> {biz}\n"
        f"📱 <b>Account:</b> <code>{phone}</code>\n"
        f"📋 <b>Price List:</b> {price}\n"
        f"👋 <b>Greeting:</b> {greet}\n"
        f"🤖 <b>Auto-Reply:</b> {ar}\n"
        f"💎 <b>Premium:</b> {days} days left\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

def get_premium_text():
    return (
        "💎 <b>GET PREMIUM ACCESS</b>\n\n"
        "Let AI handle your customers\n"
        "while you focus on your work!\n\n"
        "╔══════════════════════╗\n"
        "║ 📦 <b>Available Plans:</b>\n"
        "║\n"
        "║ 🥉 Starter  — 7 Days\n"
        "║ 🥈 Growth   — 15 Days\n"
        "║ 🥇 Pro      — 30 Days\n"
        "╚══════════════════════╝\n\n"
        "💳 <b>How to Purchase:</b>\n"
        f"1️⃣ Contact {CONTACT_USERNAME}\n"
        "2️⃣ Choose plan & pay\n"
        "3️⃣ Get your redeem code\n"
        "4️⃣ Use /redeem CODE here\n\n"
        "⚡ <i>Instant activation • 24/7 support</i>"
    )

# ════════════════════════════════════════════
# MAIN BOT
# ════════════════════════════════════════════

class UzeronReplyBot:
    def __init__(self):
        self.bot          = TelegramClient('reply_bot_session', BOT_API_ID, BOT_API_HASH)
        self.db           = Database()
        self.logger       = Logger(LOGGER_BOT_TOKEN)
        self.login_states = {}       # uid → {step, api_id, api_hash, phone, client, ...}
        self.pending      = {}       # uid → field name ('price_list' | 'business_name' | 'greeting_msg')

    async def start(self):
        await self.bot.start(bot_token=MAIN_BOT_TOKEN)
        print("✓ Uzeron ReplyBot dashboard started")
        self.register_handlers()
        print("✓ Bot is live!")
        await self.bot.run_until_disconnected()

    # ── SEND DASHBOARD ─────────────────────────────────────────────
    def send_dashboard(self, uid):
        user = self.db.get_user(uid)
        days = self.db.days_left(uid)
        ar   = user[9] if user else 1
        send_msg(uid, dashboard_text(user, days), dashboard_keyboard(ar))

    def edit_dashboard(self, uid, mid):
        user = self.db.get_user(uid)
        days = self.db.days_left(uid)
        ar   = user[9] if user else 1
        edit_msg(uid, mid, dashboard_text(user, days), dashboard_keyboard(ar))

    # ── HANDLERS ───────────────────────────────────────────────────
    def register_handlers(self):

        # ─── ADMIN COMMANDS ────────────────────────────────────────
        @self.bot.on(events.NewMessage(pattern='/addcode'))
        async def addcode(event):
            if event.sender_id not in ADMINS: return
            try:
                _, code, days = event.message.text.split()
                code = code.upper()
                if self.db.add_code(code, int(days)):
                    await event.reply(
                        f"✅ Code <code>{code}</code> created for <b>{days} days</b>",
                        parse_mode='html')
                else:
                    await event.reply("❌ Code already exists.")
            except:
                await event.reply("❌ Usage: /addcode CODE DAYS")

        @self.bot.on(events.NewMessage(pattern='/codes'))
        async def codes(event):
            if event.sender_id not in ADMINS: return
            rows = self.db.get_unused_codes()
            if not rows:
                await event.reply("📋 No unused codes."); return
            msg = "📋 <b>Unused Codes:</b>\n\n"
            msg += "\n".join(f"• <code>{c}</code> — {d} days" for c, d in rows)
            await event.reply(msg, parse_mode='html')

        @self.bot.on(events.NewMessage(pattern='/users'))
        async def users(event):
            if event.sender_id not in ADMINS: return
            rows = self.db.get_all_premium_users()
            if not rows:
                await event.reply("👥 No active premium users."); return
            msg = f"👥 <b>Premium Users ({len(rows)}):</b>\n\n"
            for uid, uname, exp in rows:
                exp_fmt = datetime.strptime(exp, '%Y-%m-%d %H:%M:%S').strftime('%d %b %Y')
                msg += f"• {'@'+uname if uname else 'ID:'+str(uid)} — {exp_fmt}\n"
            await event.reply(msg, parse_mode='html')

        @self.bot.on(events.NewMessage(pattern='/revoke'))
        async def revoke(event):
            if event.sender_id not in ADMINS: return
            try:
                uid = int(event.message.text.split()[1])
                self.db.revoke_premium(uid)
                await event.reply(f"✅ Premium revoked for {uid}")
                try:
                    await self.bot.send_message(uid,
                        "⚠️ Your Uzeron ReplyBot subscription has been revoked.\n"
                        f"Contact {CONTACT_USERNAME} to renew.")
                except: pass
            except:
                await event.reply("❌ Usage: /revoke USER_ID")

        @self.bot.on(events.NewMessage(pattern='/stats'))
        async def stats(event):
            if event.sender_id not in ADMINS: return
            total_users, total_leads = self.db.get_stats()
            active = len(self.db.get_all_premium_users())
            active_sellers = len(self.db.get_all_active_sellers())
            await event.reply(
                f"📊 <b>Uzeron ReplyBot Stats</b>\n\n"
                f"👥 Total Premium Users: {total_users}\n"
                f"✅ Active Subscriptions: {active}\n"
                f"🔗 Connected Accounts: {active_sellers}\n"
                f"📩 Total Leads Captured: {total_leads}",
                parse_mode='html')

        # ─── USER COMMANDS ─────────────────────────────────────────
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start_cmd(event):
            uid = event.sender_id
            if not self.db.is_premium(uid):
                send_msg(uid, welcome_text(), welcome_keyboard()); return
            self.send_dashboard(uid)

        @self.bot.on(events.NewMessage(pattern='/redeem'))
        async def redeem(event):
            uid      = event.sender_id
            username = event.sender.username or ''
            try:
                code = event.message.text.split()[1].strip().upper()
                ok, result = self.db.redeem_code(code, uid, username)
                if ok:
                    send_msg(uid,
                        f"🎉 <b>Subscription Activated!</b>\n\n"
                        f"💎 Plan: <b>{result} days</b>\n"
                        f"✅ Your Uzeron ReplyBot is now active!\n\n"
                        f"⚡ Set up your account below to get started.",
                        make_keyboard([[{"text": "🚀 Open Dashboard", "callback_data": "dashboard"}]]))
                    self.logger.log(
                        ADMINS[0] if ADMINS else uid,
                        f"🎉 New user! @{username or uid} redeemed code for {result} days")
                else:
                    send_msg(uid,
                        f"{result}\n\nContact {CONTACT_USERNAME} for a valid code.",
                        make_keyboard([[{"text": "💰 Get Premium", "callback_data": "get_premium"}]]))
            except IndexError:
                send_msg(uid, "❌ Usage: /redeem YOUR_CODE")

        @self.bot.on(events.NewMessage(pattern='/dashboard'))
        async def dashboard_cmd(event):
            uid = event.sender_id
            if not self.db.is_premium(uid):
                send_msg(uid, welcome_text(), welcome_keyboard()); return
            self.send_dashboard(uid)

        # ─── CALLBACKS ─────────────────────────────────────────────
        @self.bot.on(events.CallbackQuery())
        async def callbacks(event):
            uid  = event.sender_id
            data = event.data.decode('utf-8')
            await event.answer()
            mid  = event.query.msg_id

            # ── Public (no premium needed) ──
            if data == 'get_premium':
                kb = make_keyboard([
                    [{"text": "📞 Buy Now",           "url": f"https://t.me/{CONTACT_USERNAME.strip('@')}"}],
                    [{"text": "📢 Support Channel",   "url": SUPPORT_LINK}],
                    [{"text": "🔙 Back",              "callback_data": "show_welcome"}],
                ])
                edit_msg(uid, mid, get_premium_text(), kb)
                return

            if data == 'show_welcome':
                edit_msg(uid, mid, welcome_text(), welcome_keyboard()); return

            if data == 'redeem_prompt':
                send_msg(uid,
                    "🎟️ <b>Activate Your Premium</b>\n\n"
                    "Send your code:\n<code>/redeem YOUR_CODE</code>\n\n"
                    f"Don't have one? Contact {CONTACT_USERNAME}")
                return

            # ── Premium required ────────────────────────────────────
            if not self.db.is_premium(uid):
                await event.answer("❌ Premium required!", alert=True); return

            user = self.db.get_user(uid)
            days = self.db.days_left(uid)
            ar   = user[9] if user else 1

            if data == 'dashboard':
                self.edit_dashboard(uid, mid)

            elif data == 'premium':
                exp = user[10] if user and user[10] else "N/A"
                edit_msg(uid, mid,
                    f"💎 <b>Subscription Status</b>\n\n"
                    f"✅ <b>Active</b>\n"
                    f"🗓️ Expires: {exp[:10] if exp != 'N/A' else 'N/A'}\n"
                    f"⏳ Days Left: <b>{days}</b>\n\n"
                    f"To renew contact {CONTACT_USERNAME}",
                    make_keyboard([
                        [{"text": "🔄 Renew Premium", "url": f"https://t.me/{CONTACT_USERNAME.strip('@')}"}],
                        [{"text": "🏠 Dashboard",      "callback_data": "dashboard"}],
                    ]))

            elif data == 'account':
                phone     = user[2] if user and user[2]  else "Not connected"
                connected = "✅ Connected" if user and user[5] else "❌ Not connected"
                total_leads = self.db.get_total_leads(uid)
                edit_msg(uid, mid,
                    f"👤 <b>My Account</b>\n\n"
                    f"📱 Phone: <code>{phone}</code>\n"
                    f"🔗 Status: {connected}\n"
                    f"📩 Total Leads: <b>{total_leads}</b>\n"
                    f"💎 Premium: {days} days left",
                    make_keyboard([
                        [{"text": "🔑 Login",    "callback_data": "login"},
                         {"text": "🚪 Logout",   "callback_data": "logout"}],
                        [{"text": "🏠 Dashboard","callback_data": "dashboard"}],
                    ]))

            elif data == 'status':
                phone    = user[2]  if user and user[2]  else "Not set"
                price_ok = "✅ Set" if user and user[7]  else "❌ Not set"
                biz      = user[6]  if user and user[6]  else "Not set"
                ar_s     = "🟢 Active" if ar              else "🔴 Paused"
                leads    = self.db.get_total_leads(uid)
                edit_msg(uid, mid,
                    f"📊 <b>System Status</b>\n\n"
                    f"🏪 Business: <b>{biz}</b>\n"
                    f"📱 Account: <code>{phone}</code>\n"
                    f"📋 Price List: {price_ok}\n"
                    f"🤖 Auto-Reply: {ar_s}\n"
                    f"📩 Leads Captured: <b>{leads}</b>",
                    back_keyboard())

            elif data == 'set_price':
                cur = user[7] if user and user[7] else "Not set yet"
                self.pending[uid] = 'price_list'
                edit_msg(uid, mid,
                    f"📋 <b>Set Your Price List</b>\n\n"
                    f"<b>Current:</b>\n<code>{cur[:300]}</code>\n\n"
                    f"✍️ Send your new price list now.\n\n"
                    f"<b>Example:</b>\n"
                    f"<code>🎨 Logo Design — ₹2,500\n"
                    f"📱 Social Media Post — ₹500\n"
                    f"🌐 Landing Page — ₹8,000\n"
                    f"🎬 Video Edit (1 min) — ₹800</code>\n\n"
                    f"<i>Type /cancel to go back</i>",
                    cancel_keyboard('dashboard'))

            elif data == 'set_biz':
                cur = user[6] if user and user[6] else "Not set"
                self.pending[uid] = 'business_name'
                edit_msg(uid, mid,
                    f"🏪 <b>Set Business Name</b>\n\n"
                    f"Current: <b>{cur}</b>\n\n"
                    f"Send your business name:\n"
                    f"<code>Vikram Designs</code>\n\n"
                    f"<i>Type /cancel to go back</i>",
                    cancel_keyboard('dashboard'))

            elif data == 'set_greeting':
                cur = user[8] if user and user[8] else "Not set (using default)"
                self.pending[uid] = 'greeting_msg'
                edit_msg(uid, mid,
                    f"👋 <b>Set AI Greeting Message</b>\n\n"
                    f"Current: <code>{cur[:200]}</code>\n\n"
                    f"This is what the AI uses to greet new customers.\n\n"
                    f"<b>Example:</b>\n"
                    f"<code>Hi! Welcome to Vikram Designs 🎨 I'm the virtual assistant here. "
                    f"The owner is currently busy but I'm here to help! "
                    f"What service are you looking for today?</code>\n\n"
                    f"<i>Type /cancel to go back</i>",
                    cancel_keyboard('dashboard'))

            elif data == 'toggle_ar':
                new_val = 0 if ar else 1
                self.db.update_field(uid, 'auto_reply', new_val)
                user = self.db.get_user(uid)
                status = "🟢 Auto-Reply is now <b>ON</b>\n\nYour AI will handle customers automatically." \
                         if new_val else \
                         "🔴 Auto-Reply is now <b>OFF</b>\n\nCustomers won't receive automatic replies."
                edit_msg(uid, mid,
                    f"{status}\n\n" + dashboard_text(user, days),
                    dashboard_keyboard(new_val))

            elif data == 'leads':
                leads = self.db.get_leads(uid, 8)
                total = self.db.get_total_leads(uid)
                if not leads:
                    edit_msg(uid, mid,
                        "📩 <b>My Leads</b>\n\n"
                        "No leads yet!\n\n"
                        "Once customers message you, they'll appear here automatically.",
                        back_keyboard()); return
                msg = f"📩 <b>Recent Leads</b> (Total: {total})\n\n"
                for name, uname, cust_msg, bot_reply, ts in leads:
                    uname_str = f"@{uname}" if uname else "no username"
                    cust_msg_s = cust_msg[:50] + "…" if len(cust_msg) > 50 else cust_msg
                    msg += (f"👤 <b>{name}</b> ({uname_str})\n"
                            f"💬 {cust_msg_s}\n"
                            f"🕐 {ts[:16]}\n\n")
                edit_msg(uid, mid, msg, back_keyboard())

            elif data == 'login':
                if user and user[5]:
                    await event.answer("✅ Already logged in!", alert=True); return
                self.login_states[uid] = {'step': 'api'}
                edit_msg(uid, mid,
                    "🔑 <b>Login Your Telegram Account</b>\n\n"
                    "<b>Step 1 — Get API Credentials</b>\n"
                    "• Go to: https://my.telegram.org/apps\n"
                    "• Login → Create App\n"
                    "• Copy your <b>API ID</b> and <b>API Hash</b>\n\n"
                    "<b>Step 2 — Send here:</b>\n"
                    "<code>API_ID API_HASH</code>\n\n"
                    "Example: <code>12345678 abcdef1234567890abcd</code>\n\n"
                    "<i>Type /cancel to abort</i>",
                    cancel_keyboard('cancel_login'))

            elif data == 'cancel_login':
                self.login_states.pop(uid, None)
                self.edit_dashboard(uid, mid)

            elif data == 'logout':
                self.db.logout_user(uid)
                self.login_states.pop(uid, None)
                user = self.db.get_user(uid)
                edit_msg(uid, mid,
                    "🚪 <b>Logged Out</b>\n\nYour account has been disconnected.\n"
                    "Auto-reply is paused until you log in again.\n\n"
                    + dashboard_text(user, days),
                    dashboard_keyboard(0))

        # ─── TEXT INPUT HANDLER ────────────────────────────────────
        @self.bot.on(events.NewMessage(incoming=True,
                                       func=lambda e: e.is_private and not e.message.text.startswith('/')))
        async def text_input(event):
            uid  = event.sender_id
            text = event.message.text or ''

            # Cancel
            if text.strip().lower() == '/cancel':
                self.pending.pop(uid, None)
                self.login_states.pop(uid, None)
                if self.db.is_premium(uid):
                    self.send_dashboard(uid)
                return

            # Pending field update
            if uid in self.pending:
                field = self.pending.pop(uid)
                self.db.update_field(uid, field, text.strip())
                labels = {
                    'price_list':    ('📋', 'Price list'),
                    'business_name': ('🏪', 'Business name'),
                    'greeting_msg':  ('👋', 'Greeting message'),
                }
                icon, label = labels.get(field, ('✅', field))
                user = self.db.get_user(uid)
                ar   = user[9] if user else 1
                send_msg(uid,
                    f"{icon} <b>{label} saved!</b>\n\n<code>{text[:300]}</code>",
                    dashboard_keyboard(ar))
                return

            # Login flow
            if uid in self.login_states:
                state = self.login_states[uid]

                if state['step'] == 'api':
                    try:
                        parts    = text.strip().split()
                        api_id   = int(parts[0])
                        api_hash = parts[1]
                        state.update({'step': 'phone', 'api_id': api_id, 'api_hash': api_hash})
                        send_msg(uid,
                            "✅ API credentials saved!\n\n"
                            "📱 Now send your phone number:\n<code>+91XXXXXXXXXX</code>")
                    except:
                        send_msg(uid, "❌ Wrong format. Send: <code>API_ID API_HASH</code>")
                    return

                if state['step'] == 'phone':
                    phone = text.strip()
                    try:
                        client = TelegramClient(StringSession(), state['api_id'], state['api_hash'])
                        await client.connect()
                        sent = await client.send_code_request(phone)
                        state.update({
                            'step':            'otp',
                            'phone':           phone,
                            'client':          client,
                            'phone_code_hash': sent.phone_code_hash,
                        })
                        send_msg(uid, "📲 OTP sent to your Telegram!\n\nEnter the code you received:")
                    except Exception as e:
                        send_msg(uid, f"❌ Error: {e}\n\nCheck your phone number and try again.")
                    return

                if state['step'] == 'otp':
                    try:
                        client = state['client']
                        await client.sign_in(state['phone'], text.strip(),
                                             phone_code_hash=state['phone_code_hash'])
                        session_str = client.session.save()
                        me          = await client.get_me()
                        await client.disconnect()
                        self.db.save_session(uid, state['phone'],
                                             state['api_id'], state['api_hash'], session_str)
                        del self.login_states[uid]
                        user = self.db.get_user(uid)
                        self.db.update_field(uid, 'auto_reply', 1)
                        send_msg(uid,
                            f"✅ <b>Logged in as {me.first_name}!</b>\n\n"
                            f"🟢 Auto-Reply is now <b>ACTIVE</b>\n"
                            f"Your AI will handle customers while you're busy! 🎉",
                            dashboard_keyboard(1))
                        self.logger.log(
                            ADMINS[0] if ADMINS else uid,
                            f"🔑 New login: @{user[1] or uid} ({state['phone']})")
                    except SessionPasswordNeededError:
                        state['step'] = '2fa'
                        send_msg(uid, "🔐 Two-Factor Auth enabled.\n\nSend your 2FA password:")
                    except Exception as e:
                        send_msg(uid, f"❌ Wrong OTP: {e}")
                    return

                if state['step'] == '2fa':
                    try:
                        client      = state['client']
                        await client.sign_in(password=text.strip())
                        session_str = client.session.save()
                        me          = await client.get_me()
                        await client.disconnect()
                        self.db.save_session(uid, state['phone'],
                                             state['api_id'], state['api_hash'], session_str)
                        del self.login_states[uid]
                        self.db.update_field(uid, 'auto_reply', 1)
                        send_msg(uid,
                            f"✅ <b>Logged in as {me.first_name}!</b>\n\n"
                            f"🟢 Auto-Reply is <b>ACTIVE</b> 🎉",
                            dashboard_keyboard(1))
                    except Exception as e:
                        send_msg(uid, f"❌ Wrong password: {e}")
                    return

            # Unknown input — if premium, show dashboard
            if self.db.is_premium(uid):
                self.send_dashboard(uid)
            else:
                send_msg(uid, welcome_text(), welcome_keyboard())


async def main():
    bot = UzeronReplyBot()
    await bot.start()

if __name__ == '__main__':
    asyncio.run(main())
