#!/usr/bin/env python3
"""
PM Crisis Signal Bot — Daily news digest for Ioana
Runs at 9:00 AM Europe/Madrid via APScheduler
Searches news with Claude API, sends to Telegram
Includes minimal HTTP server to satisfy Render's port requirement
"""

import os
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import httpx
from telegram import Bot
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

PORT = int(os.environ.get("PORT", 8080))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"PM Crisis Signal Bot is running.")
    def log_message(self, format, *args):
        pass

def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

# ── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]   # From @BotFather
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]     # From @userinfobot
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]    # From console.anthropic.com
TIMEZONE           = "Europe/Madrid"
SEND_HOUR          = 9
SEND_MINUTE        = 0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Claude API call ─────────────────────────────────────────────────────────
async def fetch_pm_signals() -> str:
    today = datetime.now(pytz.timezone(TIMEZONE)).strftime("%A, %d %B %Y")

    prompt = f"""Search today's news for stories relevant to a Principal Product Manager 
working on AI and data platforms in enterprise software.

Today is {today}.

Focus on these angles:
1. Real-world cases where publicly available data predicted (or could have predicted) a crisis, 
   failure, or disruption that an industry ignored — biological cycles, supply chain signals, 
   environmental patterns, demographic waves
2. AI product management strategy shifts
3. Enterprise software and ERP transformation
4. Unexpected or contrarian data applications in non-tech industries

Return exactly 5 story ideas formatted for Telegram Markdown. Use this exact structure:

🧠 *PM Signal — {datetime.now(pytz.timezone(TIMEZONE)).strftime("%-d %b")}*

For each of the 5 ideas:
[relevant emoji] *[Short punchy title — max 8 words]*
[2 sentences: what happened and what the data/AI angle is]
💡 _Content angle: [one sentence on how to turn this into a LinkedIn post or short video]_

End with:
—
_Tap any angle to use it today\\._

Use Telegram MarkdownV2 escaping rules. Keep the tone sharp and analytical — not hype."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "web-search-2025-03-05"   # enables web search tool
    }

    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1500,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}]
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body
        )
        response.raise_for_status()
        data = response.json()

    # Extract text blocks from response (Claude may return tool_use + text blocks)
    text_blocks = [b["text"] for b in data["content"] if b["type"] == "text"]
    return "\n".join(text_blocks)


# ── Telegram sender ─────────────────────────────────────────────────────────
async def send_daily_digest():
    log.info("Fetching PM signals...")
    try:
        message = await fetch_pm_signals()
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
        log.info("Message sent successfully.")
    except Exception as e:
        log.error(f"Failed to send digest: {e}")
        # Send error notification so you know it broke
        try:
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"⚠️ PM Signal bot failed today: `{str(e)[:200]}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass


# ── Scheduler ───────────────────────────────────────────────────────────────
async def main():
    thread = threading.Thread(target=start_web_server, daemon=True)
    thread.start()
    log.info(f"Web server started on port {PORT}")
    log.info(f"PM Crisis Signal Bot starting — will send at {SEND_HOUR:02d}:{SEND_MINUTE:02d} {TIMEZONE}")

    scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))
    scheduler.add_job(
        send_daily_digest,
        trigger=CronTrigger(hour=SEND_HOUR, minute=SEND_MINUTE, timezone=TIMEZONE),
        id="daily_digest",
        name="Daily PM Signal",
        replace_existing=True
    )
    scheduler.start()

    # Send one immediately on startup so you can verify it works
    log.info("Sending test message on startup...")
    await send_daily_digest()

    # Keep the process alive
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
