# 📋 PRD — Uzeron ReplyBot (Premium Auto-Reply Service)
**Version:** 2.0  
**Product Type:** Premium Telegram Userbot — AI Auto-Reply for Sellers  
**Part of:** Uzeron Suite (companion to Uzeron AdsBot free service)  
**Stack:** Python · Telethon · Groq API · PostgreSQL (Neon.tech) · Railway

---

## 1. PRODUCT OVERVIEW

Uzeron ReplyBot is a **premium, paid AI auto-reply service** for Telegram sellers. When a buyer messages the seller's Telegram account, the bot automatically replies using AI — trained on the seller's own price list and business details — converting inquiries into leads 24/7, even when the seller is offline or busy.

This is a **userbot service** (runs on the seller's own Telegram account, not a bot account), powered by Groq's LLM API for intelligent, context-aware sales conversations.

---

## 2. USER ROLES

| Role | Description |
|---|---|
| **Admin** | Bot owner (you). Creates redeem codes, manages users, views stats. |
| **Seller / User** | Paying customer. Connects their Telegram account, sets price list, gets AI replies sent from their account to buyers. |
| **Buyer** | The seller's customer. Receives AI replies. Never interacts with this bot directly. |

---

## 3. COMPLETE USER FLOW

### 3.1 Onboarding Gate — Join Channels First

When a seller opens the bot for the very first time (`/start`):

1. Bot checks if seller has joined **both** required channels:
   - Updates Channel: `@Uzeron_AdsBot` (or configured channel)
   - Community Group: configured group link
2. If **NOT joined both** → show join-gate screen (see screenshot provided):
   - Message: "Welcome to Uzeron ReplyBot! To unlock the bot, please join both: [Updates Channel] [Community Group]"
   - Shows which ones are ❌ still not joined
   - Buttons: `[📢 Join Updates Channel]` `[👥 Join Community]` `[✅ I've Joined — Continue]`
3. On tapping "I've Joined — Continue" → bot re-checks membership via Telegram API
   - If still not joined → show error, list which ones are missing, ask to join again
   - If joined both → proceed to Step 3.2

> **Implementation note:** Use `client.get_participants()` or check via bot API `getChatMember` to verify membership before allowing continuation.

---

### 3.2 Welcome / Redeem Screen

Once channel gate is passed (and seller is NOT yet premium):

- Show welcome screen with bot features listed
- Two buttons: `[🎟️ Activate Premium]` `[💰 Get Premium]`
- `Get Premium` → shows plan prices and contact info (@Pandaysubscription)
- `Activate Premium` → prompts: *"Send your redeem code: /redeem YOUR_CODE"*

**Redeem flow:**
- Seller sends `/redeem CODE`
- Bot validates code (unused, exists in DB)
- On success: subscription activated, show days granted, open dashboard button
- On failure: show error, show contact button

---

### 3.3 Main Dashboard

After successful redeem (or on `/start` if already premium), show dashboard:

```
⚡ UZERON REPLYBOT — Dashboard
━━━━━━━━━━━━━━━━━━━━━━
🏪 Business: [name or ❌ Not set]
📱 Account: [phone or ❌ Not connected]
📋 Price List: [✅ Set / ❌ Not set]
👋 Greeting: [✅ Set / ⚙️ Default]
🤖 Auto-Reply: [🟢 ON / 🔴 OFF]
💎 Premium: X days left
━━━━━━━━━━━━━━━━━━━━━━
```

**Dashboard buttons (2 per row):**

| Row | Button 1 | Button 2 |
|---|---|---|
| 1 | 👤 My Account | 📊 Status |
| 2 | 📋 Set Price List | 🏪 Business Name |
| 3 | 🤖 AI Greeting Msg | 📩 My Leads |
| 4 | 🟢 Bot ON — Tap to turn OFF *(full row toggle)* | |
| 5 | 🔑 Login Account | 🚪 Logout |
| 6 | 💎 Subscription | 🔔 Updates |
| 7 | ❓ How to Use | |

- **Updates** button → links to `https://t.me/Uzeron_AdsBot`
- **How to Use** button → links to `https://t.me/Uzeron_Ads`

---

### 3.4 Dashboard Button Behaviours

#### 👤 My Account
Shows:
- Phone number connected
- Connection status
- Total leads captured
- Subscription expiry
- Buttons: `[🔑 Login]` `[🚪 Logout]` `[🏠 Dashboard]`

#### 📊 Status
Shows full system snapshot:
- Business name
- Account / phone
- Price list status
- Bot ON/OFF
- Leads count
- Back button

#### 📋 Set Price List
- Shows current price list (if set)
- Example format shown in message
- Seller types their price list freely (multi-line supported)
- Saved on receipt, success confirmation shown
- Example provided:
  ```
  🎨 Logo Design — ₹2,500
  📱 Social Media Post — ₹500
  🌐 Landing Page — ₹8,000
  ```

#### 🏪 Business Name
- Shows current name
- Seller types new name
- Saved immediately

#### 🤖 AI Greeting Msg
- Shows current greeting (or "using default")
- Seller types custom greeting for AI to use when a buyer first messages
- Default fallback if not set:
  > "Hi! 👋 Thanks for reaching out. The owner is currently unavailable but I'm here to help. What are you looking for today?"

#### 📩 My Leads
- Shows last 8 leads
- Each lead: customer name, @username, their message (truncated 50 chars), timestamp
- Total count shown
- Back button

#### 🟢/🔴 Bot ON/OFF Toggle
- Full-width button
- Toggles `auto_reply` field in DB
- Dashboard refreshes showing new state
- When ON: AI replies to all incoming private messages on seller's account
- When OFF: seller handles messages manually, no AI replies sent

#### 🔑 Login Account
**Full multi-step flow (all via inline buttons / text input):**

**Step 1 — API Credentials**
- Bot sends message explaining how to get API ID + Hash from https://my.telegram.org/apps
- Seller sends: `API_ID API_HASH` (space-separated in one message)
- Bot validates (both present, API_ID is numeric)
- Shows ✅ saved, proceeds to Step 2

**Step 2 — Phone Number**
- Bot asks for phone number with country code
- Example: `+91XXXXXXXXXX`
- Seller types phone number
- Bot connects Telethon client with seller's API_ID + API_HASH
- Sends OTP to seller's Telegram

**Step 3 — OTP**
- Bot asks seller to enter the OTP they received
- Seller types the OTP as plain text (no button needed)
- Bot signs in with OTP

**Step 3b — 2FA (if enabled)**
- If `SessionPasswordNeededError` caught → bot asks for 2FA password
- Seller types password
- Bot completes sign-in

**On success:**
- Session string saved to DB
- Auto-reply toggled ON automatically
- Seller notified: "✅ Logged in as [Name]! 🟢 Auto-Reply is now ACTIVE"
- Admin logger notified of new login
- Dashboard shown

#### 🚪 Logout
- Clears phone, api_id, api_hash, session_string from DB
- Auto-reply paused
- Dashboard refreshed

#### 💎 Subscription
- Shows expiry date, days remaining
- Renew button → links to contact

#### 🔔 Updates
- URL button → `https://t.me/Uzeron_AdsBot`

#### ❓ How to Use
- URL button → `https://t.me/Uzeron_Ads`

---

## 4. AUTO-REPLY WORKER (worker.py)

### 4.1 Architecture
- Separate process from the dashboard bot
- **Watchdog loop** polls DB every 30 seconds
- For each active premium seller with a session: launches a Telethon userbot client
- Each seller runs in their own async task

### 4.2 Message Handling Logic

When a **private message** arrives on the seller's Telegram account:

1. Check `auto_reply` flag in DB — if OFF, skip
2. Check subscription expiry — if expired, skip
3. Check message is non-empty text
4. Look up seller's `price_list`, `business_name`, `greeting_msg`
5. Build system prompt for Groq:
   ```
   You are the AI sales assistant for [business_name]. The owner is offline.
   
   On FIRST message from a customer, greet them:
   [greeting_msg or DEFAULT_GREETING]
   
   PRICE LIST — use ONLY these prices, never invent:
   [price_list]
   
   RULES:
   - Answer price questions from the list only
   - For warranty/return questions: answer confidently using sales instincts
   - If asked something not in the list: say "owner will get back to you"
   - If buyer seems hesitant or tries to leave: use persuasive sales techniques to retain them
   - Be friendly, warm, concise (max 80 words)
   - 1-2 emojis naturally placed
   - Reply in same language as customer
   - Never reveal you are an AI unless directly asked
   ```
6. Maintain per-conversation history (capped at last 10 exchanges to prevent memory leak)
7. Call Groq API (model fallback chain: llama-3.3-70b → llama3-70b-8192 → llama3-8b-8192 → mixtral-8x7b)
8. If Groq fails all models → send polite fallback: "Hi! Thanks for contacting [business]. Owner will be with you shortly!"
9. Reply to customer via `event.reply()`
10. Save lead to `reply_leads` table
11. Notify seller via bot message:
    ```
    📩 New Lead!
    👤 [Customer Name] (@username)
    💬 Customer: [their message]
    🤖 Bot replied: [AI reply]
    ```

### 4.3 Conversation Memory
```python
chat_histories = {}  # key: (seller_id, customer_id) → list of {role, content}
MAX_HISTORY = 10     # keep last 10 turns per conversation
```
Cap history to prevent memory leak:
```python
if len(chat_histories[key]) > MAX_HISTORY * 2:
    chat_histories[key] = chat_histories[key][-MAX_HISTORY * 2:]
```

### 4.4 Session Resilience
- `AuthKeyDuplicatedError` → wait 60s, retry (Railway restart race condition)
- `AuthKeyError` → stop, session invalid
- General errors → exponential backoff retry (max 10 retries)
- Keep-alive ping every 4 minutes
- Watchdog disconnects sellers whose subscription expired

---

## 5. ADMIN COMMANDS

All commands only work for user IDs in `ADMIN_IDS`:

| Command | Description |
|---|---|
| `/addcode CODE DAYS` | Create a new redeem code for N days |
| `/codes` | List all unused redeem codes |
| `/users` | List all active premium users with expiry |
| `/revoke USER_ID` | Revoke a user's premium, notify them |
| `/stats` | Total premium users, active subscriptions, connected accounts, total leads |
| `/broadcast MESSAGE` | Send message to all premium users (nice to have) |

---

## 6. DATABASE SCHEMA

### `reply_users`
```sql
user_id           BIGINT PRIMARY KEY
username          TEXT
phone             TEXT
api_id            INTEGER
api_hash          TEXT
session_string    TEXT
business_name     TEXT
price_list        TEXT
greeting_msg      TEXT
auto_reply        INTEGER DEFAULT 1
subscription_expiry TEXT
total_leads       INTEGER DEFAULT 0
created_at        TEXT
```

### `reply_codes`
```sql
code      TEXT PRIMARY KEY
days      INTEGER
used      INTEGER DEFAULT 0
used_by   BIGINT
used_at   TEXT
```

### `reply_leads`
```sql
id                SERIAL PRIMARY KEY
seller_id         BIGINT
customer_id       BIGINT
customer_name     TEXT
customer_username TEXT
message           TEXT
bot_reply         TEXT
created_at        TEXT
```

---

## 7. ENV VARIABLES

| Variable | Description |
|---|---|
| `API_ID` | From https://my.telegram.org |
| `API_HASH` | From https://my.telegram.org |
| `MAIN_BOT_TOKEN` | Dashboard bot token from @BotFather |
| `LOGGER_BOT_TOKEN` | Logger bot token from @BotFather |
| `ADMIN_IDS` | Comma-separated Telegram user IDs |
| `DATABASE_URL` | Neon.tech PostgreSQL connection string |
| `GROQ_API_KEY` | From console.groq.com (free tier available) |
| `UPDATES_CHANNEL` | e.g. `@Uzeron_AdsBot` (channel to force-join) |
| `COMMUNITY_GROUP` | e.g. `@Uzeron_Ads_support` (group to force-join) |
| `SUPPORT_LINK` | https://t.me/Uzeron_Ads_support |
| `CONTACT_USERNAME` | @Pandaysubscription |

---

## 8. FILE STRUCTURE

```
├── main_bot.py       → Dashboard bot (onboarding, login, settings, admin)
├── worker.py         → Userbot runner (auto-reply engine, watchdog)
├── requirements.txt  → Dependencies
├── Procfile          → Railway process definitions
├── Dockerfile        → Container config
├── .env.example      → Env vars template
└── .gitignore        → Protects .env and session files
```

### Procfile
```
main: python main_bot.py
worker: python worker.py
```

### requirements.txt
```
telethon>=1.24.0
python-dotenv
requests
cryptg
pytz
psycopg2-binary
```
> ⚠️ Do NOT include `google-generativeai` — this project uses Groq, not Gemini.

---

## 9. KEY BUGS TO FIX FROM v1 (AUTOTEST3)

| # | Bug | Fix |
|---|---|---|
| 1 | README says `GEMINI_KEY`, code uses `GROQ_API_KEY` | Use `GROQ_API_KEY` everywhere, remove google-generativeai from requirements |
| 2 | `chat_histories` grows forever | Cap at 10 turns per conversation |
| 3 | No channel join gate on `/start` | Implement join-gate as per Section 3.1 |
| 4 | Updates and How to Use buttons missing from dashboard | Add as URL buttons in dashboard keyboard |
| 5 | `logger_bot.py` mentioned in README but doesn't exist | Use inline Logger class in main_bot.py (already done), remove from README |
| 6 | Bare `except:` clauses | Use `except Exception as e:` with proper logging |
| 7 | No `.env` validation on startup | Add missing-var check with clear error messages |

---

## 10. AI REPLY BEHAVIOUR SPECIFICATION

The Groq AI must behave like a **skilled human sales assistant**, not a generic chatbot:

### It SHOULD:
- Greet warmly on first contact using the custom greeting
- Answer price questions accurately from the price list only
- Handle warranty/return questions with confident, reassuring answers ("Yes, we provide X-day warranty")
- If buyer says "too expensive" → negotiate: highlight value, offer to discuss, never immediately discount
- If buyer goes silent or seems to leave → send a gentle follow-up hook
- Match the language of the buyer (Hindi, English, etc.)
- Keep replies short (under 80 words)

### It SHOULD NOT:
- Invent prices not in the price list
- Say "I am an AI" (unless directly asked)
- Give negative or discouraging answers
- Send walls of text

### System Prompt Template:
```
You are a professional sales assistant for {business_name}. 
The owner is currently unavailable. You handle all customer inquiries.

FIRST MESSAGE GREETING:
{greeting_msg}

YOUR PRICE LIST (ONLY quote these prices, never invent):
{price_list}

YOUR BEHAVIOUR:
- Be warm, friendly, and professional
- Answer pricing questions using ONLY the price list above
- For warranty/returns: be reassuring and positive
- If customer hesitates on price: highlight quality and value, offer to help them choose
- If something is not in the price list: say "I'll have the owner follow up on that"
- Never reveal you are AI unless directly asked
- Reply in the same language the customer uses
- Keep replies concise — max 80 words
- Use 1-2 emojis naturally
```

---

## 11. UX NOTES

- All settings (price list, business name, greeting) are entered as **plain text messages** — no complex forms
- All navigation is via **inline keyboard buttons** — minimal typing required
- Every setting screen shows the **current value** before asking for new one
- `/cancel` always works to go back to dashboard from any input state
- Bot state is **never lost** — all state stored in PostgreSQL, not in memory
- Channel join gate must be **re-checked on every /start** while not yet premium

---

## 12. DEPLOYMENT — RAILWAY

1. Push repo to GitHub (private)
2. New project on Railway → Deploy from GitHub
3. Add all env vars from Section 7
4. Railway auto-reads Procfile and runs both `main` and `worker` processes
5. Database: Use same Neon.tech project as AdsBot (different `reply_` prefixed tables)

---

## 13. WHAT'S NEW vs AUTOTEST3 (v1)

| Feature | v1 (AUTOTEST3) | v2 (This PRD) |
|---|---|---|
| Channel join gate | ❌ Missing | ✅ Required |
| Updates button | ❌ Missing | ✅ @Uzeron_AdsBot |
| How to Use button | ❌ Missing | ✅ @Uzeron_Ads |
| AI key | ❌ Groq/Gemini mismatch | ✅ Groq only |
| Chat history cap | ❌ Memory leak | ✅ Max 10 turns |
| AI sales behaviour | Basic Q&A | ✅ Sales-focused with persuasion |
| .env validation | ❌ Silent crash | ✅ Clear startup errors |
| Requirements.txt | ❌ Includes unused google-generativeai | ✅ Clean |

---

*PRD v2.0 — Uzeron ReplyBot | Ready for development*
