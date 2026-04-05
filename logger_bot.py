# -*- coding: utf-8 -*-
"""
logger_bot.py — Uzeron ReplyBot Logger
Receives and stores system logs from the main bot.
Matches zepto's logger_bot.py pattern.
"""
import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

BOT_API_ID       = int(os.getenv('API_ID'))
BOT_API_HASH     = os.getenv('API_HASH')
LOGGER_BOT_TOKEN = os.getenv('LOGGER_BOT_TOKEN')
ADMINS           = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

bot = TelegramClient('logger_session', BOT_API_ID, BOT_API_HASH)

@bot.on(events.NewMessage(incoming=True))
async def handle(event):
    # Logger bot just receives — no action needed
    pass

async def main():
    await bot.start(bot_token=LOGGER_BOT_TOKEN)
    print("✓ Uzeron ReplyBot Logger started")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
