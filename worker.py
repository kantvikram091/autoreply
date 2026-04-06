# -*- coding: utf-8 -*-
import os
import asyncio
import psycopg2
from datetime import datetime
from telethon import TelegramClient, events, types
from telethon.sessions import StringSession
import requests
from dotenv import load_dotenv

load_dotenv()

API_ID         = int(os.getenv('API_ID'))
API_HASH       = os.getenv('API_HASH')
DATABASE_URL   = os.getenv('DATABASE_URL')
GROQ_API_KEY   = os.getenv('GROQ_API_KEY')
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')

OFFLINE_THRESHOLD = 120  # seconds

print(f"[BOOT] GROQ_API_KEY present: {bool(GROQ_API_KEY)}")
print(f"[BOOT] GROQ starts with: {GROQ_API_KEY[:8] if GROQ_API_KEY else 'MISSING'}")

# ════════════════════════════════════════════
# GROQ — simple HTTP call, ultra fast, free
# ════════════════════════════════════════════

def call_groq(system_prompt, history, user_text):
    """
    Calls Groq API (llama-3.3-70b-versatile — free, very fast).
    history = list of {"role": "user"/"assistant", "content": "..."}
    """
    url     = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }

    messages = [{"role": "system", "content": system_prompt}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model":       "llama-3.3-70b-versatile",
        "messages":    messages,
        "max_tokens":  250,
        "temperature": 0.7
    }

    try:
        print(f"[Groq] Sending: {user_text[:50]}")
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print(f"[Groq] HTTP {r.status_code}")
        data = r.json()

        if "choices" in data:
            reply = data["choices"][0]["message"]["content"].strip()
            # Save to history
            history.append({"role": "user",      "content": user_text})
            history.append({"role": "assistant", "content": reply})
            print(f"[Groq] Reply: {reply[:80]}")
            return reply
        else:
            print(f"[Groq] Error response: {data}")
            return None

    except Exception as e:
        print(f"[Groq] Exception: {e}")
        return None

# ════════════════════════════════════════════
# DATABASE
# ════════════════════════════════════════════

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def get_all_active_sellers():
    conn = get_conn(); c = conn.cursor()
    c.execute('''
        SELECT user_id, session_string, price_list, business_name,
               greeting_msg, auto_reply, subscription_expiry, api_id, api_hash
        FROM reply_users
        WHERE session_string IS NOT NULL
          AND subscription_expiry IS NOT NULL
    ''')
    rows = c.fetchall(); conn.close()
    now = datetime.now()
    return [r for r in rows
            if r[6] and now < datetime.strptime(r[6], '%Y-%m-%d %H:%M:%S')]

def get_seller_config(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute('''
        SELECT auto_reply, price_list, business_name, greeting_msg, subscription_expiry
        FROM reply_users WHERE user_id=%s
    ''', (user_id,))
    r = c.fetchone(); conn.close(); return r

def save_lead(seller_id, customer_id, name, username, message, reply):
    try:
        conn = get_conn(); c = conn.cursor()
        c.execute('''
            INSERT INTO reply_leads
            (seller_id, customer_id, customer_name, customer_username, message, bot_reply, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        ''', (seller_id, customer_id, name, username, message, reply,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.execute(
            'UPDATE reply_users SET total_leads = total_leads + 1 WHERE user_id=%s',
            (seller_id,))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB] save_lead error: {e}")

def notify_seller(seller_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage",
            data={'chat_id': seller_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=10)
    except Exception as e:
        print(f"[notify] {e}")

# ════════════════════════════════════════════
# ONLINE TRACKER
# Only tracks UserStatusOnline events — NOT outgoing messages
# (outgoing fires on bot replies too → causes false "online")
# ════════════════════════════════════════════

last_seen_online = {}  # seller_id → datetime

def mark_online(seller_id):
    last_seen_online[seller_id] = datetime.now()
    print(f"[tracker] Seller {seller_id} opened app → ONLINE for {OFFLINE_THRESHOLD}s")

def seller_is_online(seller_id):
    last = last_seen_online.get(seller_id)
    if last is None:
        return False
    secs   = (datetime.now() - last).total_seconds()
    online = secs < OFFLINE_THRESHOLD
    print(f"[tracker] Seller {seller_id}: {int(secs)}s since online → {'ONLINE' if online else 'OFFLINE'}")
    return online

# ════════════════════════════════════════════
# CONVERSATION HISTORY
# ════════════════════════════════════════════

chat_histories = {}  # (seller_id, customer_id) → list of messages

DEFAULT_GREETING = (
    "Hi! 👋 Thanks for reaching out. "
    "The owner is currently unavailable but I'm here to help. "
    "What are you looking for today?"
)

def build_system_prompt(biz, price_list, greeting):
    biz      = biz        or "this business"
    pl       = price_list or "Price list not configured yet."
    greeting = greeting   or DEFAULT_GREETING
    return (
        f"You are the AI sales assistant for {biz}. The owner is offline.\n\n"
        f"When a customer messages for the FIRST time, greet them like this:\n"
        f"{greeting}\n\n"
        f"PRICE LIST — use ONLY these prices, never make up prices:\n"
        f"{pl}\n\n"
        f"IMPORTANT RULES:\n"
        f"- Always answer price questions using the price list above\n"
        f"- If asked about something NOT in the price list, say the owner will follow up\n"
        f"- Be friendly, warm and professional\n"
        f"- Keep replies under 80 words\n"
        f"- Use 1-2 emojis naturally\n"
        f"- Reply in the same language the customer uses"
    )

# ════════════════════════════════════════════
# SELLER SESSION
# ════════════════════════════════════════════

active_clients = {}

async def run_seller_session(seller_row):
    (seller_id, session_str, price_list, biz_name,
     greeting_msg, auto_reply, expiry, seller_api_id, seller_api_hash) = seller_row

    if seller_id in active_clients:
        return

    print(f"\n[+] Launching session for seller {seller_id}")

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
        print(f"[✓] Seller {seller_id} ({me.first_name}) session LIVE")

        # ── Detect when seller opens the Telegram app ──────────────
        @client.on(events.UserUpdate())
        async def on_status(event):
            try:
                if isinstance(event.status, types.UserStatusOnline):
                    mark_online(seller_id)
            except:
                pass

        # ── Handle incoming private messages ───────────────────────
        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def on_message(event):
            try:
                user_text = (event.message.text or '').strip()
                if not user_text:
                    return

                sender         = await event.get_sender()
                customer_id    = sender.id
                customer_name  = (getattr(sender, 'first_name', '') or '').strip() or "Customer"
                customer_uname = getattr(sender, 'username', '') or ''

                print(f"\n{'─'*40}")
                print(f"[MSG] {customer_name}: {user_text}")

                # Get fresh config from DB
                cfg = get_seller_config(seller_id)
                if not cfg:
                    print(f"[!] No config for seller {seller_id}")
                    return

                auto_reply_on, pl, biz, greet, sub_expiry = cfg
                print(f"[CFG] auto_reply={auto_reply_on} | biz='{biz}' | price_list={'SET' if pl else 'EMPTY'}")

                if not sub_expiry:
                    print("[!] No subscription expiry"); return
                if datetime.now() >= datetime.strptime(sub_expiry, '%Y-%m-%d %H:%M:%S'):
                    print("[!] Subscription expired"); return
                if not auto_reply_on:
                    print("[~] Auto-reply is OFF"); return
                if seller_is_online(seller_id):
                    print("[~] Seller is ONLINE — not replying"); return

                # Get/create conversation history
                key = (seller_id, customer_id)
                if key not in chat_histories:
                    chat_histories[key] = []

                system = build_system_prompt(biz, pl, greet)

                # Call Groq in thread pool (non-blocking)
                loop  = asyncio.get_event_loop()
                reply = await loop.run_in_executor(
                    None, call_groq,
                    system, chat_histories[key], user_text
                )

                if not reply:
                    print("[!] Groq returned None — using fallback")
                    reply = (
                        f"Hi! 👋 Thanks for contacting {biz or 'us'}. "
                        f"The owner is currently busy and will get back to you shortly!"
                    )

                await event.reply(reply)
                print(f"[SENT] {reply[:80]}")

                save_lead(seller_id, customer_id,
                          customer_name, customer_uname,
                          user_text, reply)

                notify_seller(seller_id,
                    f"📩 <b>New Lead!</b>\n\n"
                    f"👤 <b>{customer_name}</b>"
                    f"{' (@'+customer_uname+')' if customer_uname else ''}\n\n"
                    f"💬 <b>Customer:</b> {user_text[:200]}\n\n"
                    f"🤖 <b>Bot:</b> {reply[:200]}")

            except Exception as e:
                print(f"[!] on_message error: {e}")
                import traceback; traceback.print_exc()

        print(f"[✓] Handlers registered for seller {seller_id} — listening...")
        await client.run_until_disconnected()

    except Exception as e:
        print(f"[!] Session error seller {seller_id}: {e}")
        import traceback; traceback.print_exc()
    finally:
        active_clients.pop(seller_id, None)
        print(f"[-] Seller {seller_id} session ended")

# ════════════════════════════════════════════
# WATCHDOG
# ════════════════════════════════════════════

async def watchdog():
    print("✓ Watchdog started — checking every 30s")
    while True:
        try:
            sellers = get_all_active_sellers()
            print(f"\n[watchdog] {len(sellers)} seller(s) in DB")
            for s in sellers:
                if s[0] not in active_clients:
                    print(f"[watchdog] Starting session for seller {s[0]}")
                    asyncio.create_task(run_seller_session(s))

            now = datetime.now()
            for sid in list(active_clients.keys()):
                cfg = get_seller_config(sid)
                if not cfg or not cfg[4]: continue
                if now >= datetime.strptime(cfg[4], '%Y-%m-%d %H:%M:%S'):
                    print(f"[watchdog] Seller {sid} expired — disconnecting")
                    try: await active_clients[sid].disconnect()
                    except: pass
                    active_clients.pop(sid, None)

        except Exception as e:
            print(f"[watchdog] Error: {e}")
            import traceback; traceback.print_exc()

        await asyncio.sleep(30)

async def main():
    print("═" * 50)
    print("  Uzeron ReplyBot Worker — Groq Edition")
    print("═" * 50)
    await watchdog()

if __name__ == '__main__':
    asyncio.run(main())
