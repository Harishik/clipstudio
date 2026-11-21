"""Free posting through your own browser session (no API keys, no paid services).

`clipstudio login <platform>` opens a dedicated ClipStudio browser profile at the platform's sign-in page;
YOU sign in there once (ClipStudio never sees or stores your password). After that, `publish` drives
that same profile to upload like you would: YouTube Studio, TikTok Studio, Instagram web, X.

Web UIs change: every step has a timeout; on failure we save a screenshot + the page URL next to the clip,
fall back to the export folder, and report the error. Personal use; respect each platform's rules.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from .util import die, log

PROFILE = Path("~/.clipstudio/browser-profile").expanduser()
LOGIN_URLS = {
    "youtube": "https://studio.youtube.com/",
    "tiktok": "https://www.tiktok.com/login",
    "instagram": "https://www.instagram.com/accounts/login/",
    "x": "https://x.com/login",
    "facebook": "https://www.facebook.com/login",
}


@contextmanager
def browser(headless: bool = False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("posting needs Playwright: pip install playwright (uses your installed Chrome; "
            "or run `python -m playwright install chromium`)")
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        kw = dict(user_data_dir=str(PROFILE), headless=headless, viewport={"width": 1366, "height": 900},
                  args=["--disable-blink-features=AutomationControlled"], ignore_default_args=["--enable-automation"])
        try:
            ctx = p.chromium.launch_persistent_context(channel="chrome", **kw)
        except Exception:  # noqa: BLE001  (no Chrome installed -> bundled Chromium)
            ctx = p.chromium.launch_persistent_context(**kw)
        try:
            yield ctx
        finally:
            ctx.close()


def login(platform: str, wait_minutes: int = 10):
    url = LOGIN_URLS.get(platform) or die(f"unknown platform {platform}")
    with browser(headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url)
        print(f"Sign in to {platform} in the opened window, then CLOSE the window (waits up to {wait_minutes} min).",
              flush=True)
        t0 = time.time()
        while time.time() - t0 < wait_minutes * 60:
            try:
                if not ctx.pages:
                    break
                ctx.pages[0].wait_for_timeout(1000)
            except Exception:  # noqa: BLE001
                break
    return {"platform": platform, "profile": str(PROFILE)}


def _fail(page, item, msg):
    shot = Path(item["clip"]) / f"post_error_{item['platform']}.png"
    try:
        page.screenshot(path=str(shot), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError(f"{item['platform']}: {msg} (at {page.url}; screenshot {shot})")


# ------------------------------------------------------------------ YouTube Studio
def youtube(page, item) -> str:
    c = item["copy"]
    page.goto("https://www.youtube.com/upload", wait_until="domcontentloaded")
    if "accounts.google.com" in page.url:
        _fail(page, item, "not signed in — run `clipstudio login youtube`")
    page.locator("input[type=file]").first.set_input_files(item["video"], timeout=60000)
    title = page.locator("#title-textarea #textbox, ytcp-social-suggestions-textbox#title-textarea #textbox").first
    title.wait_for(timeout=120000)
    title.click()
    page.keyboard.press("Meta+A" if page.evaluate("navigator.platform").startswith("Mac") else "Control+A")
    page.keyboard.type(c.get("title", "")[:100])
    desc = page.locator("#description-textarea #textbox, ytcp-social-suggestions-textbox#description-textarea #textbox")
    desc.first.click()
    page.keyboard.type(c.get("description", ""))
    page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']").first.click(timeout=30000)
    for _ in range(3):
        page.locator("#next-button").first.click(timeout=30000)
        page.wait_for_timeout(1200)
    page.locator("tp-yt-paper-radio-button[name='PUBLIC']").first.click(timeout=30000)
    link = None
    try:
        link = page.locator("a.style-scope.ytcp-video-info, span.video-url-fadeable a").first.get_attribute(
            "href", timeout=60000)
    except Exception:  # noqa: BLE001
        pass
    done = page.locator("#done-button").first
    t0 = time.time()
    while time.time() - t0 < 900 and done.get_attribute("aria-disabled") == "true":
        page.wait_for_timeout(3000)  # still uploading
    done.click(timeout=30000)
    page.wait_for_timeout(4000)
    return link or "posted (YouTube Studio)"


# ------------------------------------------------------------------ TikTok Studio
def tiktok(page, item) -> str:
    c = item["copy"]
    page.goto("https://www.tiktok.com/tiktokstudio/upload", wait_until="domcontentloaded")
    if "/login" in page.url:
        _fail(page, item, "not signed in — run `clipstudio login tiktok`")
    page.locator("input[type=file]").first.set_input_files(item["video"], timeout=60000)
    editor = page.locator("div[contenteditable='true']").first
    editor.wait_for(timeout=180000)
    editor.click()
    page.keyboard.press("Meta+A" if page.evaluate("navigator.platform").startswith("Mac") else "Control+A")
    page.keyboard.press("Backspace")
    for part in (c.get("caption") or "").split(" "):
        page.keyboard.type(part + " ")
        if part.startswith("#"):
            page.wait_for_timeout(700)
            page.keyboard.press("Escape")   # close the hashtag suggestion popup
    post = page.locator("button[data-e2e='post_video_button'], button:has-text('Post')").first
    t0 = time.time()
    while time.time() - t0 < 600 and (post.is_disabled() or post.get_attribute("data-disabled") == "true"):
        page.wait_for_timeout(2000)
    post.click(timeout=30000)
    page.wait_for_timeout(8000)
    return "posted (TikTok Studio)"


# ------------------------------------------------------------------ Instagram (Reels)
def instagram(page, item) -> str:
    c = item["copy"]
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    if "/accounts/login" in page.url:
        _fail(page, item, "not signed in — run `clipstudio login instagram`")
    page.locator("svg[aria-label='New post'], svg[aria-label='Create']").first.click(timeout=30000)
    try:
        page.get_by_text("Post", exact=True).first.click(timeout=4000)
    except Exception:  # noqa: BLE001
        pass
    page.locator("input[type=file]").first.set_input_files(item["video"], timeout=60000)
    try:
        page.get_by_role("button", name="OK").click(timeout=8000)   # "video posts are now shared as reels"
    except Exception:  # noqa: BLE001
        pass
    for _ in range(2):
        page.get_by_role("button", name="Next").first.click(timeout=60000)
        page.wait_for_timeout(1500)
    cap = page.locator("div[aria-label='Write a caption...'], textarea[aria-label='Write a caption...']").first
    cap.click(timeout=30000)
    page.keyboard.type(c.get("caption", ""))
    page.get_by_role("button", name="Share").first.click(timeout=30000)
    page.get_by_text("Your reel has been shared").first.wait_for(timeout=600000)
    return "posted (Instagram)"


# ------------------------------------------------------------------ X
def x(page, item) -> str:
    c = item["copy"]
    page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
    if "/login" in page.url or "/i/flow/login" in page.url:
        _fail(page, item, "not signed in — run `clipstudio login x`")
    page.locator("input[data-testid='fileInput']").first.set_input_files(item["video"], timeout=60000)
    page.locator("div[data-testid='tweetTextarea_0']").first.click(timeout=30000)
    page.keyboard.type(c.get("text") or c.get("caption") or "")
    btn = page.locator("button[data-testid='tweetButton']").first
    t0 = time.time()
    while time.time() - t0 < 600 and btn.is_disabled():
        page.wait_for_timeout(2000)
    btn.click(timeout=30000)
    page.wait_for_timeout(6000)
    return "posted (X)"


FLOWS = {"youtube": youtube, "tiktok": tiktok, "instagram": instagram, "x": x}


def post(item: dict, headless: bool = False) -> str:
    flow = FLOWS.get(item["platform"])
    if not flow:
        raise RuntimeError(f"no browser flow for {item['platform']}")
    with browser(headless=headless) as ctx:
        page = ctx.new_page()
        page.set_default_timeout(60000)
        try:
            return flow(page, item)
        except RuntimeError:
            raise
        except Exception as ex:  # noqa: BLE001
            _fail(page, item, repr(ex)[:300])
