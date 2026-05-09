#!/usr/bin/env python3
"""
PM Crisis Signal Bot — Daily news digest for Ioana
Runs at 8:00 AM Europe/Madrid via APScheduler
Sends two Telegram messages of 3 stories each
"""

import os
import json
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

# ── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
TIMEZONE           = "Europe/Madrid"
SEND_HOUR          = 8
SEND_MINUTE        = 0
PORT               = int(os.environ.get("PORT", 8080))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Minimal web server (keeps Render happy) ──────────────────────────────────
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


# ── Claude API call ──────────────────────────────────────────────────────────
async def fetch_pm_signals() -> tuple:
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%A, %d %B %Y")
    date_short = now.strftime("%-d %b")

    prompt = f"""You are a research assistant for a Principal Product Manager working on AI and data platforms in enterprise software. She creates LinkedIn and video content about data, AI, and product strategy.

Today is {today}. Search the web for today's most relevant news stories across these angles:
1. Real-world cases where data predicted (or could have predicted) a crisis an industry ignored — biological cycles, supply chain signals, environmental patterns, demographic waves, systemic blind spots
2. AI product management strategy — how companies are building or failing with AI products
3. Enterprise software and ERP transformation
4. Unexpected or contrarian data applications in non-tech industries

Find 6 strong, specific stories from today's news. Write each story in this format:

[emoji] *[Title — sharp and specific, max 8 words]*
[Source name] — [full URL]

[2-3 sentences on what happened. Name companies, countries, numbers. Write like a smart journalist.]

[2 sentences on the data or AI angle. What was the blind spot? What does this reveal about how industries use or ignore data?]

Content angle: [One specific hook for a LinkedIn post or short video.]

Separate stories with: ———

Now return your response as a JSON object with exactly this structure (raw JSON only, no markdown fences, no explanation):
{{"batch1": "header + stories 1-3", "batch2": "header + stories 4-6 + footer"}}

For batch1, start with: PM Crisis Signal - {date_short} (1/2)
For batch2, start with: PM Crisis Signal - {date_short} (2/2)
End batch2 with: Tap any angle to use it today.

Write in plain text only — no asterisks, no underscores, no Markdown formatting at all. Keep tone sharp, analytical, human — never hype."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "web-search-2025-03-05"
    }

    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}]
    }

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body
        )
        response.raise_for_status()
        data = response.json()

    text_blocks = [b["text"] for b in data["content"] if b["type"] == "text"]
    raw = "\n".join(text_blocks).strip()

    # Strip accidental markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()

    parsed = json.loads(raw)
    return parsed["batch1"], parsed["batch2"]


# ── Telegram sender ──────────────────────────────────────────────────────────
async def send_daily_digest():
    log.info("Fetching PM signals...")
    try:
        batch1, batch2 = await fetch_pm_signals()
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=batch1)
        await asyncio.sleep(2)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=batch2)
        log.info("Both messages sent successfully.")
    except Exception as e:
        log.error(f"Failed to send digest: {e}")
        try:
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"PM Signal bot failed today: {str(e)[:300]}"
            )
        except Exception:
            pass


# ── Main ─────────────────────────────────────────────────────────────────────
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

    log.info("Sending test message on startup...")
    await send_daily_digest()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
