# -*- coding: utf-8 -*-
import os
import asyncio
import psycopg2
from datetime import datetime
from telethon import TelegramClient, events, types
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

OFFLINE_THRESHOLD = 300  # 5 minutes

# ── DB ──────────────────────────────────────────────────────────────

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
    try:
        requests.post(
            f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage",
            data={'chat_id': seller_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=10)
    except Exception as e:
        print(f"[notify] Error: {e}")

# ── ONLINE TRACKER ───────────────────────────────────────────────────

class OnlineTracker:
    def __init__(self):
        self.last_activity = {}

    def mark_active(self, seller_id):
        self.last_activity[seller_id] = datetime.now()

    def is_online(self, seller_id):
        last = self.last_activity.get(seller_id)
        if last is None:
            return False
        return (datetime.now() - last).total_seconds() < OFFLINE_THRESHOLD

tracker = OnlineTracker()

# ── AI REPLY ─────────────────────────────────────────────────────────
# Store conversation history per (seller_id, customer_id) as plain lists
# so we can reconstruct a fresh Gemini chat each time safely
conversation_history = {}  # (seller_id, customer_id) → list of {role, parts}

DEFAULT_GREETING = (
    "Hi! 👋 Thanks for reaching out. The owner is currently unavailable, "
    "but I'm here to help! What service or product are you looking for today?"
)

def build_system_prompt(biz_name, price_list, greeting_msg):
    biz   = biz_name     or "this business"
    pl    = price_list   or "Price list not available. Tell the customer the owner will share details soon."
    greet = greeting_msg or DEFAULT_GREETING
    return (
        f"You are a professional AI sales assistant for {biz}. "
        f"The owner is currently offline and you handle customer inquiries.\n\n"
        f"YOUR GREETING for first-time customers: {greet}\n\n"
        f"PRICE LIST (use ONLY these prices, never make up prices):\n{pl}\n\n"
        f"RULES:\n"
        f"- Always greet first-time customers warmly\n"
        f"- Answer price questions using ONLY the price list above\n"
        f"- If asked about something not in the price list, say the owner will follow up\n"
        f"- Be concise, friendly, and professional\n"
        f"- Use 1-2 emojis per message naturally\n"
        f"- Keep replies under 120 words"
    )

def call_gemini_sync(system_prompt, history, new_message):
    """
    Synchronous Gemini call — safe to run in executor.
    Creates a fresh model instance each time with full history.
    """
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=system_prompt   # ← system prompt via system_instruction
    )
    chat = model.start_chat(history=history)
    response = chat.send_message(new_message)
    return response.text, chat.history  # return updated history too

async def get_ai_reply(seller_id, customer_id, user_text, biz_name, price_list, greeting_msg):
    key           = (seller_id, customer_id)
    system_prompt = build_system_prompt(biz_name, price_list, greeting_msg)
    history       = conversation_history.get(key, [])

    loop = asyncio.get_event_loop()

    # Run blocking Gemini call safely in thread pool
    reply_text, updated_history = await loop.run_in_executor(
        None,
        call_gemini_sync,
        system_prompt,
        history,
        user_text
    )

    # Save updated history
    conversation_history[key] = updated_history
    return reply_text

# ── SELLER SESSION ───────────────────────────────────────────────────

active_clients = {}

async def run_seller_session(seller_row):
    (seller_id, session_str, price_list, biz_name,
     greeting_msg, auto_reply, expiry, seller_api_id, seller_api_hash) = seller_row

    if seller_id in active_clients:
        return

    print(f"[+] Starting session for seller {seller_id}")

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
        print(f"[✓] Seller {seller_id} ({me.first_name}) session live")

        @client.on(events.NewMessage(outgoing=True))
        async def outgoing(event):
            tracker.mark_active(seller_id)

        @client.on(events.UserUpdate())
        async def user_update(event):
            if hasattr(event, 'status') and isinstance(event.status, types.UserStatusOnline):
                tracker.mark_active(seller_id)

        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def on_incoming(event):
            # Fresh config from DB every message
            cfg = get_seller_config(seller_id)
            if not cfg:
                return

            auto_reply_on, pl, biz, greet, sub_expiry = cfg

            if not sub_expiry:
                return
            if datetime.now() >= datetime.strptime(sub_expiry, '%Y-%m-%d %H:%M:%S'):
                return
            if not auto_reply_on:
                return
            if tracker.is_online(seller_id):
                print(f"[~] Seller {seller_id} online — skipping")
                return

            user_text = event.message.text
            if not user_text or not user_text.strip():
                return

            sender         = await event.get_sender()
            customer_id    = sender.id
            customer_name  = (getattr(sender, 'first_name', '') or '').strip() or "Customer"
            customer_uname = getattr(sender, 'username', '') or ''

            print(f"[→] {customer_name}: {user_text[:80]}")

            try:
                async with client.action(event.chat_id, 'typing'):
                    reply = await asyncio.wait_for(
                        get_ai_reply(seller_id, customer_id, user_text, biz, pl, greet),
                        timeout=25
                    )
            except asyncio.TimeoutError:
                print(f"[!] Gemini timeout for seller {seller_id}")
                reply = f"Hi! 👋 Thanks for contacting {biz or 'us'}. The owner will get back to you shortly!"
            except Exception as e:
                print(f"[!] Gemini error: {e}")
                reply = f"Hi! 👋 Thanks for reaching out to {biz or 'us'}. We'll get back to you soon!"

            await event.reply(reply)
            print(f"[←] Sent: {reply[:80]}")

            save_lead(seller_id, customer_id, customer_name, customer_uname, user_text, reply)

            notify_seller(seller_id,
                f"📩 <b>New Lead!</b>\n\n"
                f"👤 <b>{customer_name}</b>"
                f"{' (@' + customer_uname + ')' if customer_uname else ''}\n\n"
                f"💬 <b>Customer:</b> {user_text[:200]}\n\n"
                f"🤖 <b>Bot replied:</b> {reply[:200]}")

        await client.run_until_disconnected()

    except Exception as e:
        print(f"[!] Session error seller {seller_id}: {e}")
    finally:
        active_clients.pop(seller_id, None)
        print(f"[-] Seller {seller_id} session ended")

# ── WATCHDOG ─────────────────────────────────────────────────────────

async def watchdog():
    print("✓ Watchdog started")
    while True:
        try:
            sellers = get_all_active_sellers()
            print(f"[watchdog] {len(sellers)} active seller(s)")
            for seller in sellers:
                if seller[0] not in active_clients:
                    asyncio.create_task(run_seller_session(seller))

            now = datetime.now()
            for sid in list(active_clients.keys()):
                cfg = get_seller_config(sid)
                if not cfg or not cfg[4]:
                    continue
                if now >= datetime.strptime(cfg[4], '%Y-%m-%d %H:%M:%S'):
                    try:
                        await active_clients[sid].disconnect()
                    except: pass
                    active_clients.pop(sid, None)

        except Exception as e:
            print(f"[watchdog] Error: {e}")

        await asyncio.sleep(30)

async def main():
    print("✓ Uzeron ReplyBot Worker starting...")
    await watchdog()

if __name__ == '__main__':
    asyncio.run(main())
