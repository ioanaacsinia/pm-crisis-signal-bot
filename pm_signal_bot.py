#!/usr/bin/env python3
"""
PM Crisis Signal Bot — Daily news digest for Ioana
Runs at 8:00 AM Europe/Madrid via APScheduler
Two Telegram messages of 3 stories each
"""

import os
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import httpx
from telegram import Bot
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

TELEGRAM_MAX_CHARS = 3800  # Telegram limit is 4096, leaving buffer


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
async def fetch_batch(batch_num: int, date_short: str, today: str) -> str:
    batch_note = "Find 3 different stories from batch 1." if batch_num == 2 else ""

    prompt = f"""You are a research assistant for a Principal Product Manager specialising in AI, data platforms, and enterprise software. She creates LinkedIn and video content.

Today is {today}. Search the web for 3 news stories. {batch_note}

Angles to cover:
- Data that predicted a crisis an industry ignored (biological, supply chain, environmental, demographic)
- AI product strategy wins or failures
- Enterprise/ERP transformation
- Contrarian data use in non-tech industries

STRICT FORMAT — follow exactly, keep each section short:

PM Crisis Signal - {date_short} ({batch_num}/2)

[emoji] [Title, max 7 words]
[Source] - [URL]
What: [2 sentences max. Specific facts, names, numbers.]
Data angle: [2 sentences max. The blind spot or insight.]
Content hook: [1 sentence. Specific LinkedIn or video angle.]

----------

[next story same format]

----------

[next story same format]

CRITICAL: Total response must be under 3500 characters. Be concise. Plain text only, no markdown."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "web-search-2025-03-05"
    }

    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1500,
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
    result = "\n".join(text_blocks).strip()

    # Hard truncate as safety net, never exceeds Telegram limit
    if len(result) > TELEGRAM_MAX_CHARS:
        result = result[:TELEGRAM_MAX_CHARS] + "\n[truncated]"

    return result


# ── Telegram sender ──────────────────────────────────────────────────────────
async def send_daily_digest():
    log.info("Fetching PM signals...")
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    today = now.strftime("%A, %d %B %Y")
    date_short = now.strftime("%-d %b")

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        log.info("Fetching batch 1...")
        batch1 = await fetch_batch(1, date_short, today)
        log.info(f"Batch 1 length: {len(batch1)} chars")
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=batch1)
        log.info("Batch 1 sent.")

        await asyncio.sleep(3)

        log.info("Fetching batch 2...")
        batch2 = await fetch_batch(2, date_short, today)
        log.info(f"Batch 2 length: {len(batch2)} chars")
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=batch2)
        log.info("Batch 2 sent. All done.")

    except Exception as e:
        log.error(f"Failed to send digest: {e}")
        try:
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"PM Signal bot failed: {str(e)[:300]}"
            )
        except Exception:
            pass


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    thread = threading.Thread(target=start_web_server, daemon=True)
    thread.start()
    log.info(f"Web server started on port {PORT}")
    log.info(f"PM Crisis Signal Bot starting - will send at {SEND_HOUR:02d}:{SEND_MINUTE:02d} {TIMEZONE}")

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
