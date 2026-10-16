"""
Resale ticket alert bot for Discord.

Slash commands:
  /watch url [label] [max_price]   start watching an event page
  /unwatch id                      stop watching
  /watches                         list everything being watched
  /checknow id                     run a check right now and show the result
  /sites                           show supported sites
"""

import asyncio
import json
import logging
import os
import random
import time
import uuid
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

from checker import Checker, CheckResult
from sites import SITES, site_for

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["ALERT_CHANNEL_ID"])
GUILD_ID = os.getenv("GUILD_ID")                       # makes slash commands appear instantly
ALERT_ROLE_ID = os.getenv("ALERT_ROLE_ID")             # optional role to ping
INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "90"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN_SECONDS", "120"))
MAX_BACKOFF = 30 * 60
DATA_FILE = Path(os.getenv("DATA_FILE", "bot_watches.json"))


# ---------- storage ----------

class Store:
    def __init__(self, path: Path):
        self.path = path
        self.watches: dict[str, dict] = {}
        if path.exists():
            self.watches = json.loads(path.read_text())

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.watches, indent=2))
        tmp.replace(self.path)

    def add(self, url: str, label: str, max_price: float | None, user: str) -> dict:
        wid = uuid.uuid4().hex[:6]
        self.watches[wid] = {
            "id": wid, "url": url, "label": label, "max_price": max_price,
            "site": site_for(url).name, "added_by": user,
            "last_status": None, "last_fp": None, "last_alert": 0,
            "next_check": 0, "fails": 0, "blocked_notified": False,
        }
        self.save()
        return self.watches[wid]

    def remove(self, wid: str) -> dict | None:
        w = self.watches.pop(wid, None)
        self.save()
        return w


# ---------- bot ----------

class TicketBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.store = Store(DATA_FILE)
        self.checker = Checker(headless=HEADLESS)

    async def setup_hook(self):
        await self.checker.start()
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.loop.create_task(self.scheduler())

    async def close(self):
        await self.checker.close()
        await super().close()

    async def channel(self) -> discord.abc.Messageable:
        return self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)

    # --- polling loop ---

    async def scheduler(self):
        await self.wait_until_ready()
        log.info("Scheduler running, %d watches, interval ~%ss", len(self.store.watches), INTERVAL)
        while not self.is_closed():
            now = time.time()
            due = [w for w in list(self.store.watches.values()) if w["next_check"] <= now]
            for w in due:
                if w["id"] not in self.store.watches:
                    continue  # removed mid-loop
                res = await self.checker.check(w["url"])
                await self.handle_result(w, res)
                await asyncio.sleep(random.uniform(2, 6))  # spread requests out
            await asyncio.sleep(5)

    async def handle_result(self, w: dict, res: CheckResult):
        now = time.time()
        log.info("[%s] %s -> %s (%s)", w["id"], w["label"], res.status, res.detail)

        if res.status in ("blocked", "error"):
            w["fails"] += 1
            backoff = min(INTERVAL * (2 ** w["fails"]), MAX_BACKOFF)
            w["next_check"] = now + backoff
            if res.status == "blocked" and not w["blocked_notified"]:
                w["blocked_notified"] = True
                await (await self.channel()).send(
                    f"Heads up: **{res.site}** is showing a bot check for `{w['id']}` ({w['label']}). "
                    f"Backing off to every {int(backoff // 60)} min. See README: Ticketmaster tips."
                )
            self.store.save()
            return

        w["fails"] = 0
        w["blocked_notified"] = False
        w["next_check"] = now + INTERVAL * random.uniform(0.8, 1.3)

        should_alert = (
            res.status == "available"
            and (w["last_status"] != "available" or res.fingerprint != w["last_fp"])
            and now - w["last_alert"] >= ALERT_COOLDOWN
            and not (w["max_price"] and res.cheapest and res.cheapest > w["max_price"])
        )
        if should_alert:
            await self.send_alert(w, res)
            w["last_alert"] = now

        w["last_status"] = res.status
        w["last_fp"] = res.fingerprint
        self.store.save()

    async def send_alert(self, w: dict, res: CheckResult):
        embed = discord.Embed(
            title=f"Resale tickets: {w['label']}",
            url=w["url"],
            colour=discord.Colour.green(),
            description=res.title[:200] or None,
        )
        embed.add_field(name="Site", value=res.site)
        if res.count is not None:
            embed.add_field(name="Listed", value=str(res.count))
        if res.prices:
            shown = ", ".join(f"£{p:,.2f}" for p in res.prices[:6])
            embed.add_field(name="Prices seen", value=shown, inline=False)
        if w["max_price"]:
            embed.add_field(name="Your max", value=f"£{w['max_price']:,.2f}")
        embed.set_footer(text=f"Watch {w['id']} · {res.detail}")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open listing", url=w["url"]))
        ping = f"<@&{ALERT_ROLE_ID}> " if ALERT_ROLE_ID else ""
        await (await self.channel()).send(
            content=f"{ping}Tickets just showed up, go go go",
            embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )


bot = TicketBot()


# ---------- slash commands ----------

@bot.tree.command(description="Watch an event page for resale tickets")
@app_commands.describe(url="Event page URL", label="Name for this gig", max_price="Only alert if a ticket is at or under this (£)")
async def watch(inter: discord.Interaction, url: str, label: str | None = None, max_price: float | None = None):
    if not url.startswith(("http://", "https://")):
        await inter.response.send_message("That doesn't look like a URL.", ephemeral=True)
        return
    site = site_for(url)
    w = bot.store.add(url, label or url.split("/")[-1][:60] or "event", max_price, str(inter.user))
    msg = f"Watching **{w['label']}** on {site.name} (id `{w['id']}`), checking every ~{INTERVAL}s."
    if site.key == "generic":
        msg += "\nNo custom rules for this site, so results may be rough. You can add rules in `sites.py`."
    elif site.note:
        msg += f"\n_{site.note}_"
    await inter.response.send_message(msg)


@bot.tree.command(description="Stop watching an event")
async def unwatch(inter: discord.Interaction, id: str):
    w = bot.store.remove(id)
    await inter.response.send_message(f"Stopped watching **{w['label']}**." if w else f"No watch with id `{id}`.")


@bot.tree.command(description="List watched events")
async def watches(inter: discord.Interaction):
    if not bot.store.watches:
        await inter.response.send_message("Not watching anything yet. Use `/watch`.")
        return
    lines = []
    for w in bot.store.watches.values():
        cap = f" · max £{w['max_price']:g}" if w["max_price"] else ""
        lines.append(f"`{w['id']}` **{w['label']}** · {w['site']} · last: {w['last_status'] or 'pending'}{cap}")
    await inter.response.send_message("\n".join(lines)[:1900])


@bot.tree.command(description="Run a check right now")
async def checknow(inter: discord.Interaction, id: str):
    w = bot.store.watches.get(id)
    if not w:
        await inter.response.send_message(f"No watch with id `{id}`.", ephemeral=True)
        return
    await inter.response.defer(thinking=True)
    res = await bot.checker.check(w["url"])
    price = f" · cheapest £{res.cheapest:,.2f}" if res.cheapest else ""
    count = f" · {res.count} listed" if res.count is not None else ""
    await inter.followup.send(f"**{w['label']}**: `{res.status}`{count}{price}\n_{res.detail}_")
    await bot.handle_result(w, res)


@bot.tree.command(description="Show supported resale sites")
async def sites(inter: discord.Interaction):
    lines = [f"**{s.name}**: {', '.join(s.domains)}" + (f"\n  _{s.note}_" if s.note else "") for s in SITES]
    await inter.response.send_message("\n".join(lines))


if __name__ == "__main__":
    bot.run(TOKEN)
