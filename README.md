# Resale Ticket Alert Bot

Watches UK resale pages and pings your Discord channel when tickets show up.

**Supported:** Twickets, Ticketmaster UK (Fan-to-Fan), AXS Official Resale, See Tickets, TicketSwap. Any other site works in rough "best guess" mode.

**Alerts only.** It never buys anything. You click the link and buy by hand.

There are two ways to run it:

| | **Webhook mode (recommended)** | **Bot mode** |
|---|---|---|
| Runs on | GitHub, for free. Mac can be off. | Your Mac or a server, always on |
| Add a gig | Edit `watches.json` on GitHub | `/watch` command in Discord |
| Checks every | ~5 min (sometimes later) | ~90 sec |
| Ticketmaster | Often blocked (data centre IP) | Works better from your Mac |

---

# Webhook mode (GitHub Actions)

## 1. Make a Discord webhook

In your server: **channel settings (cog) > Integrations > Webhooks > New Webhook**. Name it, then **Copy Webhook URL**. Treat it like a password: anyone with it can post in that channel.

## 2. Put the code on GitHub

1. Make a free account at github.com if you don't have one.
2. Create a new repository called `ticket-alerts`. **Make it Public.** Actions are free with no limit on public repos. Private repos only get 2,000 free minutes a month, which every-5-minute checks would burn through in about a week. Your webhook stays hidden either way (next step).
3. Upload every file from this folder, **including the `.github` folder**. Easiest way: on the repo page click **Add file > Upload files** and drag the folder contents in. On a Mac, press `Cmd+Shift+.` in Finder to show hidden folders like `.github`.

## 3. Add your webhook as a secret

Repo **Settings > Secrets and variables > Actions > New repository secret**:

- Name: `DISCORD_WEBHOOK_URL`, value: the webhook URL
- Optional: `ALERT_ROLE_ID` to @mention a role on alerts

## 4. Add your gigs

Edit `watches.json` on GitHub (click it, then the pencil icon):

```json
[
  { "label": "Fontaines Cardiff", "url": "https://www.twickets.live/en/event/...", "max_price": 80 },
  { "label": "Oasis Wembley Sat", "url": "https://www.ticketswap.com/event/..." }
]
```

- `max_price` is optional. Leave it out to get every alert.
- Add `"paused": true` to skip a gig without deleting it.
- Delete the example entry.

## 5. Test it

**Actions** tab > **Check resale tickets** > **Run workflow**. Click the run to see the log. You'll see a line per gig like `Fontaines Cardiff -> none (matched 'no tickets available')`.

If a gig says `unknown`, the wording rules need tuning for that site (see "Fixing a site" below).

After that it runs every 5 minutes by itself. It saves what it's already told you in `state.json`, so you won't get the same tickets twice.

**Good to know:** GitHub runs scheduled jobs late at busy times, so 5 minutes can become 10 to 15. It also pauses scheduled jobs on repos with no activity for 60 days. If you get an email about that, click the button in it to turn it back on.

You can also run webhook mode on your own computer: put `DISCORD_WEBHOOK_URL=...` in `.env` and run `python webhook_check.py`.

---

# Bot mode

## 1. Create the Discord bot (5 min)

1. Go to https://discord.com/developers/applications and click **New Application**. Call it something like "Ticket Alerts".
2. **Bot** tab: click **Reset Token**, copy it. That's your `DISCORD_TOKEN`. Never share it or commit it.
3. **OAuth2 > URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Embed Links`, `Mention Everyone` (only if you want role pings)
4. Open the generated URL and add the bot to your server.
5. In Discord: **User Settings > Advanced > Developer Mode** on. Then:
   - Right-click your alerts channel > **Copy Channel ID** → `ALERT_CHANNEL_ID`
   - Right-click your server icon > **Copy Server ID** → `GUILD_ID`

## 2. Install on your Mac

```bash
cd ticket-alert-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Open `.env` and paste in your token and IDs.

## 3. Run it

```bash
source .venv/bin/activate
caffeinate -i python bot.py
```

`caffeinate -i` stops your Mac from sleeping while the bot runs. Leave the terminal open.

## 4. Use it

| Command | What it does |
|---|---|
| `/watch url label max_price` | Start watching an event page. `label` and `max_price` are optional. |
| `/watches` | List everything being watched, with IDs |
| `/checknow id` | Check right now. **Use this after every new /watch** to confirm the site is being read properly. |
| `/unwatch id` | Stop watching |
| `/sites` | Show supported sites |

Example:
```
/watch url:https://www.twickets.live/en/event/1234567890 label:Fontaines Cardiff max_price:80
```

Paste the **specific event page**, not a search page or artist page.

### What the statuses mean

- `available`: resale tickets found. You get an alert.
- `none`: nothing listed right now.
- `unknown`: page loaded but no known wording matched. See "Fixing a site" below.
- `blocked`: the site showed a bot check. The bot backs off automatically (up to 30 min) and tells you once.
- `error`: page didn't load (network, timeout).

You only get pinged when tickets **appear** or the **listings change** (new price or count), with a 2 minute cooldown. No spam while the same tickets sit there.

## Ticketmaster tips

Ticketmaster has the toughest bot protection. If you see `blocked`:

1. Set `HEADLESS=false` in `.env`. A real browser window opens, which gets through far more often.
2. Restart the bot. If a captcha appears in that window, solve it once. The bot keeps cookies in `browser-profile/`, so it usually stays through after that.
3. Keep `CHECK_INTERVAL_SECONDS` at 90 or higher. Checking faster gets you blocked faster.

Twickets and TicketSwap are much more forgiving.

## Fixing a site (when it says `unknown`, or gets it wrong)

Sites change their wording. All rules live in `sites.py`, as plain lists of phrases:

- `positive`: text that appears **when tickets are listed**
- `negative`: text that appears **when nothing's available**
- `count_patterns`: a regex that grabs the number, e.g. `(\d+)\s+available`

Open the event page in your browser, note the exact wording in both states, add it to the lists, restart the bot. Matching ignores case.

## Running it 24/7 (optional)

Your Mac needs to stay awake for the bot to work. To keep it running all the time, put it on a small always-on Linux server (Hetzner, DigitalOcean, or an Oracle Cloud free-tier VM all work):

```bash
sudo apt install -y python3-venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

Then run it with `systemd` or inside `tmux`. One catch: datacenter IPs get blocked by Ticketmaster much more than home broadband. For Ticketmaster, your Mac is the better option.

## Good to know

- **No official APIs.** None of these sites offer a public resale API, so the bot reads the page like a person would. Scraping is against most sites' terms, and a site can block you at any time. Keep the check intervals reasonable.
- **Alerts only.** In the UK it's illegal to use software to buy more tickets than a seller allows. This bot never adds to basket or checks out.
- **Use the official alerts too.** Twickets has alerts built into its app, and they can be faster than any scraper. Turn them on as a backup.

## Files

```
webhook_check.py          Webhook mode: one round of checks, then exits
watches.json              Webhook mode: your list of gigs (edit this)
state.json                Webhook mode: created automatically, remembers past alerts
.github/workflows/        Webhook mode: the GitHub schedule
bot.py                    Bot mode: Discord bot, slash commands, polling loop
bot_watches.json          Bot mode: created automatically, stores your watch list
checker.py                Both: headless browser + "tickets or not" logic
sites.py                  Both: per-site wording rules (edit this to tune)
.env                      Your secrets and settings (create from .env.example)
```
