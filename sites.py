"""
Per-site rules for spotting resale tickets.

Each site is matched by domain. The checker loads the page in a real browser,
grabs the visible text, and applies these rules in order:

  1. blocked   -> the site served a bot check / captcha page
  2. count     -> a regex that captures how many tickets are listed
  3. positive  -> phrases that mean resale tickets are on the page
  4. negative  -> phrases that mean nothing is available

Sites change their wording. If a site stops working, open the event page,
look at what it says when tickets are / aren't available, and edit the
phrases below. All matching is case-insensitive.
"""

from dataclasses import dataclass, field
from urllib.parse import urlparse

COMMON_BLOCKED = [
    "access denied",
    "pardon the interruption",
    "your browsing activity has been paused",
    "verify you are human",
    "are you a robot",
    "checking your browser",
    "unusual traffic",
    "request unsuccessful. incapsula",
    "please enable cookies",
]

COMMON_COOKIE_BUTTONS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept All')",
    "button:has-text('Accept all')",
    "button:has-text('Accept Cookies')",
    "button:has-text('Accept cookies')",
    "button:has-text('I Accept')",
    "button:has-text('Allow all')",
]


@dataclass
class Site:
    key: str
    name: str
    domains: list[str]
    positive: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    count_patterns: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    wait_selector: str | None = None   # optional CSS selector to wait for
    note: str = ""


SITES: list[Site] = [
    Site(
        key="twickets",
        name="Twickets",
        domains=["twickets.live", "twickets.co.uk"],
        positive=["buy now", "tickets available", "ticket available", "view tickets"],
        negative=[
            "no tickets available",
            "there are currently no tickets",
            "no tickets listed",
            "get notified when tickets",
            "create an alert",
        ],
        count_patterns=[r"(\d+)\s+tickets?\s+available", r"(\d+)\s+listings?"],
        note="Best supported. Twickets only sells at face value or less.",
    ),
    Site(
        key="ticketmaster",
        name="Ticketmaster UK",
        domains=["ticketmaster.co.uk", "ticketmaster.ie"],
        positive=["fan-to-fan resale", "fan to fan resale", "resale ticket", "verified resale"],
        negative=[
            "no tickets currently available",
            "there are no tickets available",
            "tickets are not currently available",
            "no resale tickets",
        ],
        count_patterns=[r"(\d+)\s+resale tickets?"],
        note="Heavy bot protection. Run on your Mac with HEADLESS=false for best results.",
    ),
    Site(
        key="axs",
        name="AXS Official Resale",
        domains=["axs.com", "axs.co.uk"],
        positive=["official resale", "resale tickets available", "buy resale"],
        negative=["no resale tickets", "no tickets available", "currently no tickets"],
        count_patterns=[r"(\d+)\s+resale tickets?"],
    ),
    Site(
        key="seetickets",
        name="See Tickets",
        domains=["seetickets.com"],
        positive=["fan-to-fan", "fan to fan", "resale tickets available", "resale ticket"],
        negative=["no resale tickets", "no tickets available", "sold out"],
        count_patterns=[r"(\d+)\s+resale tickets?"],
    ),
    Site(
        key="ticketswap",
        name="TicketSwap",
        domains=["ticketswap.com", "ticketswap.co.uk", "ticketswap.uk"],
        positive=[],  # TicketSwap shows a count, see below
        negative=["0 available", "no tickets available"],
        count_patterns=[r"(\d+)\s+available"],
        note="Uses the 'X available' counter on the event page.",
    ),
]

GENERIC = Site(
    key="generic",
    name="Other site",
    domains=[],
    positive=["resale", "buy now", "tickets available"],
    negative=["sold out", "no tickets available", "not currently available"],
    count_patterns=[r"(\d+)\s+tickets?\s+available"],
    note="No custom rules. Falls back to change detection.",
)


def site_for(url: str) -> Site:
    host = (urlparse(url).hostname or "").lower()
    for site in SITES:
        if any(host == d or host.endswith("." + d) for d in site.domains):
            return site
    return GENERIC
