"""
Webhook mode: checks every event in watches.json once, posts any new resale
tickets to a Discord webhook, saves state, then exits.

No bot account, no slash commands. Built to be run on a schedule
(GitHub Actions, cron, etc). Edit watches.json to add or remove gigs.

  DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... python webhook_check.py
"""

import asyncio
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

from checker import Checker, CheckResult

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("webhook")

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
ROLE_ID = os.getenv("ALERT_ROLE_ID", "").strip()
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
WATCHES_FILE = Path(os.getenv("WATCHES_FILE", "watches.json"))
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))


def post(payload: dict):
    req = urllib.request.Request(
        WEBHOOK,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "ticket-alert-bot/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status >= 300:
            log.error("Webhook returned %s", r.status)


def alert_payload(w: dict, res: CheckResult) -> dict:
    fields = [{"name": "Site", "value": res.site, "inline": True}]
    if res.count is not None:
        fields.append({"name": "Listed", "value": str(res.count), "inline": True})
    if res.prices:
        fields.append({"name": "Prices seen", "value": ", ".join(f"£{p:,.2f}" for p in res.prices[:6]), "inline": False})
    if w.get("max_price"):
        fields.append({"name": "Your max", "value": f"£{w['max_price']:,.2f}", "inline": True})
    ping = f"<@&{ROLE_ID}> " if ROLE_ID else ""
    embed = {
        "title": f"Resale tickets: {w['label']}",
        "url": w["url"],
        "color": 0x2ECC71,
        "fields": fields,
        "footer": {"text": res.detail},
    }
    if res.title:
        embed["description"] = res.title[:200]
    return {
        "content": f"{ping}Tickets just showed up, go go go\n{w['url']}",
        "allowed_mentions": {"roles": [ROLE_ID] if ROLE_ID else []},
        "embeds": [embed],
    }


def should_alert(w: dict, prev: dict, res: CheckResult) -> bool:
    if res.status != "available":
        return False
    if prev.get("status") == "available" and prev.get("fp") == res.fingerprint:
        return False  # same tickets as last time, already told you
    if w.get("max_price") and res.cheapest and res.cheapest > w["max_price"]:
        return False
    return True


async def main() -> int:
    if not WEBHOOK.startswith("https://"):
        log.error("Set DISCORD_WEBHOOK_URL first")
        return 1

    watches = json.loads(WATCHES_FILE.read_text())
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

    checker = Checker(profile_dir="browser-profile", headless=HEADLESS)
    await checker.start()
    try:
        for w in watches:
            if w.get("paused"):
                continue
            key = w["url"]
            prev = state.get(key, {})
            res = await checker.check(w["url"])
            log.info("%s -> %s (%s)", w["label"], res.status, res.detail)

            if should_alert(w, prev, res):
                post(alert_payload(w, res))
                log.info("  alert sent")

            if res.status == "blocked" and not prev.get("blocked_notified"):
                post({"content": f"Heads up: **{res.site}** showed a bot check for **{w['label']}**. "
                                 f"Will keep trying each run."})
                prev["blocked_notified"] = True

            if res.status in ("blocked", "error"):
                state[key] = prev  # keep last good result, don't reset alerts
            else:
                state[key] = {"status": res.status, "fp": res.fingerprint, "blocked_notified": False}
            await asyncio.sleep(2)
    finally:
        await checker.close()

    # drop state for gigs you've removed from watches.json
    live = {w["url"] for w in watches}
    state = {k: v for k, v in state.items() if k in live}
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
