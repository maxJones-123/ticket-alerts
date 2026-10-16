"""
Loads event pages in a real Chromium browser and decides whether resale
tickets are showing. Uses a persistent browser profile so cookies and
consent choices stick between checks, which looks far less bot-like.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from sites import COMMON_BLOCKED, COMMON_COOKIE_BUTTONS, Site, site_for

log = logging.getLogger("checker")

PRICE_RE = re.compile(r"£\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)")
MIN_PRICE, MAX_PRICE = 5.0, 5000.0  # ignore junk like "£1 booking fee"


@dataclass
class CheckResult:
    status: str                 # available | none | blocked | unknown | error
    site: str
    count: int | None = None
    prices: list[float] = field(default_factory=list)
    title: str = ""
    detail: str = ""
    fingerprint: str = ""

    @property
    def cheapest(self) -> float | None:
        return min(self.prices) if self.prices else None


def analyse(site: Site, text: str, title: str = "") -> CheckResult:
    """Pure function: page text in, verdict out. Easy to unit test."""
    lower = " ".join(text.lower().split())

    for phrase in COMMON_BLOCKED + site.blocked:
        if phrase in lower:
            return CheckResult("blocked", site.name, title=title, detail=f"bot check: '{phrase}'")

    count = None
    for pat in site.count_patterns:
        m = re.search(r"\b" + pat, lower)
        if m:
            count = int(m.group(1))
            break

    prices = sorted({
        p for p in (float(x.replace(",", "")) for x in PRICE_RE.findall(text))
        if MIN_PRICE <= p <= MAX_PRICE
    })

    neg = next((n for n in site.negative if n in lower), None)
    # Strip negative phrases first so "no tickets available" can't match "tickets available"
    scrubbed = lower
    for n in site.negative:
        scrubbed = scrubbed.replace(n, " ")
    pos = next((p for p in site.positive if p in scrubbed), None)

    if count is not None:
        status = "available" if count > 0 else "none"
        detail = f"counter shows {count}"
    elif pos:
        status, detail = "available", f"matched '{pos}'"
    elif neg:
        status, detail = "none", f"matched '{neg}'"
    else:
        status, detail = "unknown", "no known phrases found"

    if status == "none":
        prices = []

    fp_src = f"{status}|{count}|{','.join(f'{p:.2f}' for p in prices)}"
    return CheckResult(
        status=status,
        site=site.name,
        count=count,
        prices=prices,
        title=title,
        detail=detail,
        fingerprint=hashlib.sha1(fp_src.encode()).hexdigest()[:12],
    )


class Checker:
    def __init__(self, profile_dir: str = "browser-profile", headless: bool = True, max_parallel: int = 2):
        self.profile_dir = profile_dir
        self.headless = headless
        self._sem = asyncio.Semaphore(max_parallel)
        self._pw = None
        self._ctx = None

    async def start(self):
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=self.headless,
            locale="en-GB",
            timezone_id="Europe/London",
            viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        log.info("Browser started (headless=%s)", self.headless)

    async def close(self):
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()

    async def check(self, url: str) -> CheckResult:
        site = site_for(url)
        async with self._sem:
            page = await self._ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await self._dismiss_cookies(page)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except PWTimeout:
                    pass  # busy pages never go idle, carry on
                if site.wait_selector:
                    try:
                        await page.wait_for_selector(site.wait_selector, timeout=10_000)
                    except PWTimeout:
                        pass
                title = await page.title()
                text = await page.inner_text("body")
                return analyse(site, text, title)
            except Exception as e:  # network errors, timeouts, crashes
                log.warning("Check failed for %s: %s", url, e)
                return CheckResult("error", site.name, detail=str(e)[:200])
            finally:
                await page.close()

    @staticmethod
    async def _dismiss_cookies(page):
        # One combined selector so we wait ~3s total, not per button
        try:
            btn = page.locator(", ".join(COMMON_COOKIE_BUTTONS)).first
            await btn.wait_for(state="visible", timeout=3000)
            await btn.click(timeout=1500)
        except Exception:
            pass  # no banner, or already accepted in this profile
