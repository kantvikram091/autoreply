# -*- coding: utf-8 -*-
"""
worker.py — Uzeron ReplyBot Worker
Runs one Telethon userbot per seller.
Auto-detects online/offline via last_seen and typing status.
"""
import os
import asyncio
import psycopg2
from datetime import datetime, timedelta
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
import google.generativeai as genai
import requests
from dotenv import load_dotenv

load_dotenv()

API_ID         = int(os.getenv('API_ID'))
API_HASH       = os.getenv('API_HASH')
DATABASE_URL   = os.getenv('DATABASE_URL')
GEMINI_KEY     = os.getenv('GEMINI_KEY')
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')

genai.configure(api_key=GEMINI_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# ── How long without activity before considered "offline" (seconds)
OFFLINE_THRESHOLD = 300   # 5 minutes

# ════════════════════════════════════════════
# DATABASE
# ════════════════════════════════════════════

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def get_all_active_sellers():
    conn = get_conn(); c = conn.cursor()
    c.execute('''SELECT user_id, session_string, price_list, business_name,
                        greeting_msg, auto_reply, subscription_expiry, api_id, api_hash
                 FROM reply_users
                 WHERE session_string IS NOT NULL
                   AND subscription_expiry IS NOT NULL
                   AND auto_reply = 1''')
    rows = c.fetchall(); conn.close()
    now = datetime.now()
    return [r for r in rows if r[6] and now < datetime.strptime(r[6], '%Y-%m-%d %H:%M:%S')]

def get_seller_config(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute('''SELECT auto_reply, price_list, business_name, greeting_msg, subscription_expiry
                 FROM reply_users WHERE user_id=%s''', (user_id,))
    r = c.fetchone(); conn.close(); return r

def save_lead(seller_id, customer_id, name, username, message, reply):
    conn = get_conn(); c = conn.cursor()
    c.execute('''INSERT INTO reply_leads
                 (seller_id, customer_id, customer_name, customer_username, message, bot_reply, created_at)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)''',
              (seller_id, customer_id, name, username, message, reply,
               datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    c.execute('UPDATE reply_users SET total_leads = total_leads + 1 WHERE user_id=%s', (seller_id,))
    conn.commit(); conn.close()

def notify_seller(seller_id, text):
    """Send a Telegram message to the seller via the main bot."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage",
            data={'chat_id': seller_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=10)
    except Exception as e:
        print(f"[notify] Error: {e}")

# ════════════════════════════════════════════
# ONLINE DETECTION
# ════════════════════════════════════════════

class OnlineTracker:
    """
    Tracks whether the seller is online.
    We consider them online if they sent a message or read/typed within OFFLINE_THRESHOLD seconds.
    The userbot listens to its own outgoing messages to detect activity.
    """
    def __init__(self):
        self.last_activity: dict[int, datetime] = {}  # seller_id → last active time

    def mark_active(self, seller_id: int):
        self.last_activity[seller_id] = datetime.now()

    def is_online(self, seller_id: int) -> bool:
        last = self.last_activity.get(seller_id)
        if last is None:
            return False  # never seen → treat as offline (safe to reply)
        return (datetime.now() - last).total_seconds() < OFFLINE_THRESHOLD

tracker = OnlineTracker()

# ════════════════════════════════════════════
# AI REPLY
# ════════════════════════════════════════════

conversations: dict[tuple, object] = {}  # (seller_id, customer_id) → Gemini chat

DEFAULT_GREETING = (
    "Hi! 👋 Thanks for reaching out. The owner is currently unavailable, "
    "but I'm here to help! What service or product are you looking for today?"
)

def build_system_prompt(biz_name, price_list, greeting_msg):
    biz   = biz_name   or "this business"
    pl    = price_list or "Price list not set. Tell the customer the owner will share details soon."
    greet = greeting_msg or DEFAULT_GREETING
    return (
        f"You are a professional AI assistant for {biz}. "
        f"Your job is to help customers while the owner is away.\n\n"
        f"GREETING (use this for first message): {greet}\n\n"
        f"PRICE LIST:\n{pl}\n\n"
        f"RULES:\n"
        f"- Be friendly, professional, and concise\n"
        f"- If a service isn't in the price list, say the owner will follow up\n"
        f"- Never make up prices — only use the price list above\n"
        f"- End replies with a helpful follow-up question when appropriate\n"
        f"- Keep replies under 200 words\n"
        f"- Use light emojis naturally"
    )

async def get_ai_reply(seller_id, customer_id, user_text, biz_name, price_list, greeting_msg):
    key = (seller_id, customer_id)
    system = build_system_prompt(biz_name, price_list, greeting_msg)

    if key not in conversations:
        conversations[key] = gemini_model.start_chat(history=[])
        first_msg = f"[System instructions: {system}]\n\nCustomer's first message: {user_text}"
        response  = conversations[key].send_message(first_msg)
    else:
        response = conversations[key].send_message(user_text)

    return response.text

# ════════════════════════════════════════════
# SELLER SESSION RUNNER
# ════════════════════════════════════════════

active_clients: dict[int, TelegramClient] = {}

async def run_seller_session(seller_row):
    (seller_id, session_str, price_list, biz_name,
     greeting_msg, auto_reply, expiry, seller_api_id, seller_api_hash) = seller_row

    if seller_id in active_clients:
        return  # already running

    print(f"[+] Starting session for seller {seller_id}")

    # Use seller's own API creds if available, else fall back to bot's
    use_api_id   = seller_api_id   or API_ID
    use_api_hash = seller_api_hash or API_HASH

    client = TelegramClient(StringSession(session_str), use_api_id, use_api_hash)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(f"[!] Seller {seller_id} session expired — skipping")
            return

        me = await client.get_me()
        active_clients[seller_id] = client
        print(f"[✓] Seller {seller_id} ({me.first_name}) session active")

        # ── Detect outgoing messages → seller is online ──────────
        @client.on(events.NewMessage(outgoing=True))
        async def outgoing_handler(event):
            tracker.mark_active(seller_id)

        # ── Detect UserStatus updates (when seller opens the app) ─
        @client.on(events.UserUpdate())
        async def user_update(event):
            if hasattr(event, 'status') and isinstance(event.status, types.UserStatusOnline):
                tracker.mark_active(seller_id)

        # ── Handle incoming private messages ──────────────────────
        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def on_incoming(event):
            # Re-fetch config fresh from DB
            cfg = get_seller_config(seller_id)
            if not cfg:
                return

            auto_reply_on, pl, biz, greet, sub_expiry = cfg

            # Check subscription still valid
            if not sub_expiry:
                return
            if datetime.now() >= datetime.strptime(sub_expiry, '%Y-%m-%d %H:%M:%S'):
                return

            # Check auto-reply is enabled
            if not auto_reply_on:
                return

            # ── AUTO ONLINE/OFFLINE DETECTION ────────────────────
            # If seller was active recently → they're "online" → skip auto-reply
            if tracker.is_online(seller_id):
                return

            user_text = event.message.text
            if not user_text or not user_text.strip():
                return

            sender         = await event.get_sender()
            customer_id    = sender.id
            customer_name  = (getattr(sender, 'first_name', '') or '') + \
                             (' ' + getattr(sender, 'last_name', '') if getattr(sender, 'last_name', '') else '')
            customer_name  = customer_name.strip() or "Customer"
            customer_uname = getattr(sender, 'username', '') or ''

            print(f"[→] Seller {seller_id} ← {customer_name}: {user_text[:60]}")

            # Show typing indicator
            async with client.action(event.chat_id, 'typing'):
                try:
                    reply = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: asyncio.run(get_ai_reply(
                                seller_id, customer_id, user_text, biz, pl, greet))),
                        timeout=15)
                except Exception:
                    # Fallback reply
                    reply = (f"Hi! 👋 Thanks for reaching out to {biz or 'us'}. "
                             f"The owner is currently busy. "
                             f"I'll make sure they get back to you shortly!")

            await event.reply(reply)
            print(f"[←] Bot replied to {customer_name}")

            # Save lead
            save_lead(seller_id, customer_id, customer_name, customer_uname, user_text, reply)

            # Notify seller
            notify_seller(seller_id,
                f"📩 <b>New Lead!</b>\n\n"
                f"👤 <b>{customer_name}</b>"
                f"{' (@' + customer_uname + ')' if customer_uname else ''}\n\n"
                f"💬 <b>They asked:</b>\n{user_text[:300]}\n\n"
                f"🤖 <b>Bot replied:</b>\n{reply[:300]}")

        await client.run_until_disconnected()

    except Exception as e:
        print(f"[!] Session error for seller {seller_id}: {e}")
    finally:
        active_clients.pop(seller_id, None)
        print(f"[-] Seller {seller_id} session ended")

# ════════════════════════════════════════════
# WATCHDOG — polls DB every 60s
# ════════════════════════════════════════════

async def watchdog():
    print("✓ Worker watchdog started")
    while True:
        try:
            sellers = get_all_active_sellers()
            for seller in sellers:
                sid = seller[0]
                if sid not in active_clients:
                    asyncio.create_task(run_seller_session(seller))

            # Clean up expired sessions
            now = datetime.now()
            for sid in list(active_clients.keys()):
                cfg = get_seller_config(sid)
                if not cfg or not cfg[4]:
                    continue
                if now >= datetime.strptime(cfg[4], '%Y-%m-%d %H:%M:%S'):
                    print(f"[x] Seller {sid} subscription expired — closing session")
                    try:
                        await active_clients[sid].disconnect()
                    except: pass
                    active_clients.pop(sid, None)

        except Exception as e:
            print(f"[watchdog] Error: {e}")

        await asyncio.sleep(60)

async def main():
    print("✓ Uzeron ReplyBot Worker starting...")
    await watchdog()

if __name__ == '__main__':
    asyncio.run(main())
