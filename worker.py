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
GEMINI_KEY     = os.getenv('GEMINI_KEY')
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')

OFFLINE_THRESHOLD = 300

def gemini_reply(system_prompt, history, user_text):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.0-flash:generateContent?key={GEMINI_KEY}")
    contents = list(history) + [{"role": "user", "parts": [{"text": user_text}]}]
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.7}
    }
    try:
        print(f"[Gemini] Sending: {user_text[:40]}")
        resp = requests.post(url, json=payload, timeout=20)
        data = resp.json()
        print(f"[Gemini] Status: {resp.status_code}")
        if "candidates" in data:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            history.append({"role": "user",  "parts": [{"text": user_text}]})
            history.append({"role": "model", "parts": [{"text": text}]})
            print(f"[Gemini] Reply: {text[:60]}")
            return text
        else:
            print(f"[Gemini] Error response: {data}")
            return None
    except Exception as e:
        print(f"[Gemini] Exception: {e}")
        return None

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
    try:
        conn = get_conn(); c = conn.cursor()
        c.execute('''INSERT INTO reply_leads
                     (seller_id, customer_id, customer_name, customer_username, message, bot_reply, created_at)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                  (seller_id, customer_id, name, username, message, reply,
                   datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        c.execute('UPDATE reply_users SET total_leads = total_leads + 1 WHERE user_id=%s', (seller_id,))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[DB] Error: {e}")

def notify_seller(seller_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage",
            data={'chat_id': seller_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=10)
    except: pass

last_activity = {}

def mark_active(seller_id):
    last_activity[seller_id] = datetime.now()
    print(f"[online] Seller {seller_id} marked ONLINE")

def is_online(seller_id):
    last = last_activity.get(seller_id)
    if last is None:
        return False
    secs = (datetime.now() - last).total_seconds()
    online = secs < OFFLINE_THRESHOLD
    print(f"[online] Seller {seller_id}: {int(secs)}s ago → {'ONLINE' if online else 'OFFLINE'}")
    return online

histories = {}

DEFAULT_GREETING = (
    "Hi! 👋 Thanks for reaching out. The owner is currently unavailable "
    "but I'm here to help! What are you looking for today?"
)

def build_system(biz, price_list, greeting):
    biz      = biz        or "this business"
    pl       = price_list or "Price list not set — owner will share details soon."
    greeting = greeting   or DEFAULT_GREETING
    return (
        f"You are the AI sales assistant for {biz}. The owner is offline.\n\n"
        f"FIRST MESSAGE GREETING: {greeting}\n\n"
        f"PRICE LIST:\n{pl}\n\n"
        f"RULES: Be friendly and concise. "
        f"Only use prices from the list above. "
        f"If not listed, say owner will follow up. "
        f"Keep replies under 100 words. Use 1-2 emojis."
    )

active_clients = {}

async def run_seller_session(seller_row):
    (seller_id, session_str, price_list, biz_name,
     greeting_msg, auto_reply, expiry, seller_api_id, seller_api_hash) = seller_row

    if seller_id in active_clients:
        return

    print(f"[+] Starting seller {seller_id}")
    use_api_id   = seller_api_id   or API_ID
    use_api_hash = seller_api_hash or API_HASH

    client = TelegramClient(StringSession(session_str), use_api_id, use_api_hash)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(f"[!] Seller {seller_id} session expired")
            return

        me = await client.get_me()
        active_clients[seller_id] = client
        print(f"[✓] Seller {seller_id} ({me.first_name}) LIVE")

        @client.on(events.NewMessage(outgoing=True))
        async def outgoing(event):
            mark_active(seller_id)

        @client.on(events.UserUpdate())
        async def on_update(event):
            try:
                if isinstance(event.status, types.UserStatusOnline):
                    mark_active(seller_id)
            except: pass

        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def on_message(event):
            try:
                user_text = event.message.text
                if not user_text or not user_text.strip():
                    return

                sender         = await event.get_sender()
                customer_id    = sender.id
                customer_name  = (getattr(sender, 'first_name', '') or '').strip() or "Customer"
                customer_uname = getattr(sender, 'username', '') or ''

                print(f"\n[MSG] {customer_name}: {user_text}")

                cfg = get_seller_config(seller_id)
                if not cfg:
                    print("[!] No config"); return

                auto_reply_on, pl, biz, greet, sub_expiry = cfg
                print(f"[CFG] auto_reply={auto_reply_on}, biz={biz}")

                if not sub_expiry: return
                if datetime.now() >= datetime.strptime(sub_expiry, '%Y-%m-%d %H:%M:%S'):
                    print("[!] Expired"); return
                if not auto_reply_on:
                    print("[~] Auto-reply OFF"); return
                if is_online(seller_id):
                    print("[~] ONLINE — skip"); return

                key = (seller_id, customer_id)
                if key not in histories:
                    histories[key] = []

                system = build_system(biz, pl, greet)
                loop   = asyncio.get_event_loop()
                reply  = await loop.run_in_executor(
                    None, gemini_reply, system, histories[key], user_text
                )

                if not reply:
                    reply = f"Hi! 👋 Thanks for contacting {biz or 'us'}. The owner will get back to you shortly!"

                await event.reply(reply)
                print(f"[✓] Replied: {reply[:60]}")

                save_lead(seller_id, customer_id, customer_name, customer_uname, user_text, reply)
                notify_seller(seller_id,
                    f"📩 <b>New Lead!</b>\n\n"
                    f"👤 <b>{customer_name}</b>"
                    f"{' (@'+customer_uname+')' if customer_uname else ''}\n\n"
                    f"💬 {user_text[:200]}\n\n🤖 {reply[:200]}")

            except Exception as e:
                print(f"[!] Handler error: {e}")
                import traceback; traceback.print_exc()

        await client.run_until_disconnected()

    except Exception as e:
        print(f"[!] Session error {seller_id}: {e}")
        import traceback; traceback.print_exc()
    finally:
        active_clients.pop(seller_id, None)
        print(f"[-] Seller {seller_id} ended")

async def watchdog():
    print("✓ Watchdog started")
    while True:
        try:
            sellers = get_all_active_sellers()
            print(f"[watchdog] {len(sellers)} seller(s)")
            for s in sellers:
                if s[0] not in active_clients:
                    asyncio.create_task(run_seller_session(s))
            now = datetime.now()
            for sid in list(active_clients.keys()):
                cfg = get_seller_config(sid)
                if not cfg or not cfg[4]: continue
                if now >= datetime.strptime(cfg[4], '%Y-%m-%d %H:%M:%S'):
                    try: await active_clients[sid].disconnect()
                    except: pass
                    active_clients.pop(sid, None)
        except Exception as e:
            print(f"[watchdog] Error: {e}")
            import traceback; traceback.print_exc()
        await asyncio.sleep(30)

async def main():
    print("✓ Uzeron ReplyBot Worker starting...")
    await watchdog()

if __name__ == '__main__':
    asyncio.run(main())
