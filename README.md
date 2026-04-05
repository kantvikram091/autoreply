# 🤖 Uzeron ReplyBot

AI-powered auto-reply system for Telegram sellers.
Replies to customers using your price list while you're away.

---

## 📁 File Structure

```
├── main_bot.py      → Dashboard bot (seller setup & controls)
├── worker.py        → Userbot runner (handles actual auto-replies)
├── logger_bot.py    → Logger bot (receives system logs)
├── requirements.txt → Python dependencies
├── Procfile         → For Railway deployment
├── Dockerfile       → Container config
├── .env.example     → Environment variables template
└── .gitignore       → Protects sensitive files
```

---

## ⚙️ Environment Variables

| Variable | Description |
|---|---|
| `API_ID` | From https://my.telegram.org |
| `API_HASH` | From https://my.telegram.org |
| `MAIN_BOT_TOKEN` | From @BotFather |
| `LOGGER_BOT_TOKEN` | From @BotFather (2nd bot) |
| `ADMIN_IDS` | Your Telegram user ID |
| `DATABASE_URL` | Neon.tech PostgreSQL URL |
| `GEMINI_KEY` | From aistudio.google.com (free) |
| `SUPPORT_LINK` | Your support channel link |
| `CONTACT_USERNAME` | Your contact username |

---

## 🤖 Bot Commands

### Admin Commands
| Command | Description |
|---|---|
| `/addcode CODE DAYS` | Create a redeem code |
| `/codes` | List unused codes |
| `/users` | List premium users |
| `/revoke USER_ID` | Revoke user's premium |
| `/stats` | View bot statistics |

### Seller Commands
| Command | Description |
|---|---|
| `/start` | Open dashboard |
| `/redeem CODE` | Activate subscription |
| `/dashboard` | Open dashboard |

### Dashboard Buttons
| Button | Action |
|---|---|
| 👤 My Account | View account & leads count |
| 📊 Status | Full system status |
| 📋 Set Price List | Set your services & prices |
| 🏪 Business Name | Set your business name |
| 🤖 AI Greeting Msg | Customize the AI greeting |
| 📩 My Leads | View recent customer leads |
| 🟢 Auto-Reply ON/OFF | Toggle auto-reply |
| 🔑 Login Account | Connect Telegram account |
| 🚪 Logout | Disconnect account |
| 💎 Subscription | Check subscription status |

---

## 🚀 Deploy on Railway (Free)

### Step 1 — Create GitHub Repo
1. Go to https://github.com → New Repository
2. Name: `uzeron-replybot` → **Private** → Create
3. Upload all files

### Step 2 — Deploy
1. Go to https://railway.app
2. Login with GitHub (no credit card needed)
3. New Project → Deploy from GitHub Repo
4. Select your repo

### Step 3 — Add Variables
Go to Variables tab and add all env vars from `.env.example`

**For DATABASE_URL:** Use your Neon.tech connection string
(same Neon project as your other bots)

### Step 4 — Deploy
Railway reads the `Procfile` and runs all 3 processes:
- `main` → Dashboard bot
- `worker` → Auto-reply engine
- `logger` → Log receiver

---

## 💡 How Auto-Detection Works

The bot automatically detects if the seller is online or offline:
- When the seller sends **any message** → marked as "online" for 5 minutes
- When 5 minutes pass with no activity → treated as "offline"
- Customers only get AI replies when the seller is offline
- No manual `/online` or `/offline` command needed!

---

## ⚠️ Important Notes

- Never share your `.env` file or session files publicly
- Each seller logs in with their own `API_ID` + `API_HASH` + phone OTP
- The `.gitignore` protects session files from being uploaded
- Gemini free tier: 1M tokens/day — more than enough for most sellers
- Database tables are prefixed with `reply_` to avoid conflicts with zepto tables

---

## 🔑 Before You Start

### Get Your ADMIN_IDS
1. Open Telegram → search `@userinfobot` → `/start` → copy your ID

### Create 2 Bots
1. Open Telegram → `@BotFather`
2. `/newbot` → follow steps → copy token → `MAIN_BOT_TOKEN`
3. `/newbot` again → `LOGGER_BOT_TOKEN`

### Get Gemini Key (Free)
1. Go to https://aistudio.google.com
2. Sign in with Google → Get API Key → Copy

---

## 🧑‍💻 Part of the Uzeron Suite

This bot is part of the same organisation as **Uzeron AdsBot**.
Both bots share the same Neon.tech database (different tables).
