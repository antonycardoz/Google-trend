import html
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests
from deep_translator import GoogleTranslator
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TOP_N = int(os.environ.get("TOP_N", "10"))
HOURS = int(os.environ.get("HOURS", "4"))

TRENDS_PAGE_URL = (
    f"https://trends.google.com/trending"
    f"?geo=IN&hours={HOURS}&hl=en"
)

TRENDS_RSS_URL = "https://trends.google.com/trending/rss"
HT_NS = "https://trends.google.com/trending/rss"


KERALA_TERMS = {
    # State and language
    "kerala",
    "malayalam",
    "malayali",
    "mollywood",

    # Kerala districts and locations
    "alappuzha",
    "alleppey",
    "ernakulam",
    "kochi",
    "cochin",
    "thiruvananthapuram",
    "trivandrum",
    "kozhikode",
    "calicut",
    "thrissur",
    "kollam",
    "kannur",
    "kasaragod",
    "kottayam",
    "idukki",
    "palakkad",
    "pathanamthitta",
    "wayanad",
    "malappuram",

    # Kerala cinema and personalities
    "mohanlal",
    "mammootty",
    "dulquer",
    "dulquer salmaan",
    "fahadh",
    "fahadh faasil",
    "tovino",
    "tovino thomas",
    "prithviraj",
    "prithviraj sukumaran",
    "nivin pauly",
    "suresh gopi",
    "manju warrier",
    "nazriya",
    "malayalam cinema",

    # Kerala news sources
    "manorama",
    "malayala manorama",
    "mathrubhumi",
    "asianet",
    "asianet news",
    "24 news",
    "reporter tv",
    "mediaone",
    "media one",
    "janam tv",
    "news18 kerala",
    "the cue",
    "marunadan",
}


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(value: str) -> str:
    """Normalize text so webpage and RSS titles can be matched."""

    value = value.casefold().strip()
    value = re.sub(r"[^\w\u0D00-\u0D7F]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def contains_malayalam(value: str) -> bool:
    """Check whether a string contains Malayalam characters."""

    return any(
        "\u0D00" <= character <= "\u0D7F"
        for character in value
    )


def translate_to_english(value: str) -> str:
    """
    Translate text into English.

    If translation fails, return the original text so the
    workflow can continue.
    """

    if not value:
        return ""

    try:
        translated = GoogleTranslator(
            source="auto",
            target="en",
        ).translate(value)

        return translated or value

    except Exception as error:
        print(
            f"Translation warning: {error}",
            file=sys.stderr,
        )
        return value


def shorten(value: str, limit: int) -> str:
    """Shorten text to help stay within Telegram's message limit."""

    value = " ".join(value.split())

    if len(value) <= limit:
        return value

    return value[: limit - 1].rstrip() + "…"


def extract_search_volume(row_text: str) -> str:
    """
    Extract values such as:

    500+
    1K+
    2K+
    50K+
    1M+
    """

    patterns = [
        r"\b\d+(?:\.\d+)?\s*[KMB]\+",
        r"\b\d[\d,]*\+",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            row_text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0).replace(" ", "")

    return "Unknown"


# ============================================================
# LIVE GOOGLE TRENDS PAGE
# ============================================================

def looks_like_data_row(row_text: str) -> bool:
    """Determine whether an element looks like a trends table row."""

    lowered = row_text.casefold()

    excluded_phrases = {
        "search volume",
        "trend breakdown",
        "past 4 hours",
        "rows per page",
        "trends updated",
        "started",
    }

    if any(phrase in lowered for phrase in excluded_phrases):
        return False

    if not extract_search_volume(row_text) == "Unknown":
        return True

    return False


def extract_keyword_from_row(row_text: str) -> Optional[str]:
    """Extract the trend keyword from a Google Trends table row."""

    lines = [
        line.strip()
        for line in row_text.splitlines()
        if line.strip()
    ]

    if not lines:
        return None

    for line in lines:
        lowered = line.casefold()

        if extract_search_volume(line) != "Unknown":
            continue

        if re.search(
            r"\b\d+\s*(?:minutes?|hours?|days?)\s+ago\b",
            lowered,
        ):
            continue

        if lowered in {
            "active",
            "all trends",
            "trend breakdown",
        }:
            continue

        if re.fullmatch(
            r"[↑+,\d.%\s]+",
            line,
        ):
            continue

        if len(line) < 2:
            continue

        return line

    return None


def scrape_live_relevance_order() -> list[dict]:
    """
    Open the live Google Trends Trending Now page and collect
    its displayed order.

    This keeps the same order shown under:
    India → Past 4 hours → By relevance.
    """

    results: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            viewport={
                "width": 1920,
                "height": 1080,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        print(f"Opening live Google Trends page: {TRENDS_PAGE_URL}")

        page.goto(
            TRENDS_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            print(
                "Google Trends continued loading resources; "
                "continuing with the visible page."
            )

        # Allow the trends table to render.
        time.sleep(5)

        # Try to close a consent dialog if Google displays one.
        consent_buttons = [
            "Accept all",
            "I agree",
            "Accept",
            "Got it",
        ]

        for button_text in consent_buttons:
            try:
                button = page.get_by_role(
                    "button",
                    name=button_text,
                    exact=True,
                )

                if button.is_visible(timeout=1_000):
                    button.click()
                    time.sleep(2)
                    break

            except Exception:
                pass

        # Google may use either accessibility rows or Material
        # table containers. Try several possible selectors.
        selector_candidates = [
            '[role="row"]',
            "table tbody tr",
            "tbody tr",
            'div[role="row"]',
        ]

        row_locator = None

        for selector in selector_candidates:
            locator = page.locator(selector)

            try:
                count = locator.count()
            except Exception:
                count = 0

            if count > 1:
                row_locator = locator
                print(
                    f"Using row selector: {selector} "
                    f"({count} elements)"
                )
                break

        if row_locator is None:
            browser.close()
            raise RuntimeError(
                "Could not locate the live Google Trends table. "
                "Google may have changed the webpage structure."
            )

        seen_keywords: set[str] = set()

        for index in range(row_locator.count()):
            if len(results) >= TOP_N:
                break

            row = row_locator.nth(index)

            try:
                row_text = row.inner_text(
                    timeout=5_000,
                ).strip()
            except Exception:
                continue

            if not row_text:
                continue

            if not looks_like_data_row(row_text):
                continue

            keyword = extract_keyword_from_row(row_text)

            if not keyword:
                continue

            normalized_keyword = normalize_text(keyword)

            if not normalized_keyword:
                continue

            if normalized_keyword in seen_keywords:
                continue

            seen_keywords.add(normalized_keyword)

            results.append(
                {
                    "keyword_original": keyword,
                    "keyword": keyword,
                    "traffic": extract_search_volume(
                        row_text
                    ),
                    "row_text": row_text,
                    "news": None,
                }
            )

        browser.close()

    if not results:
        raise RuntimeError(
            "No trends were extracted from the live "
            "Google Trends page."
        )

    print(
        f"Extracted {len(results)} live trends "
        "in Google's relevance order."
    )

    return results


# ============================================================
# GOOGLE TRENDS RSS NEWS
# ============================================================

def fetch_rss_trends() -> list[dict]:
    """
    Fetch Google Trends RSS data.

    RSS is used to obtain the news title, source and URL.
    The RSS ordering is not used.
    """

    response = requests.get(
        TRENDS_RSS_URL,
        params={
            "geo": "IN",
            "hours": HOURS,
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
        },
        timeout=30,
    )

    response.raise_for_status()

    root = ET.fromstring(response.content)

    rss_results: list[dict] = []

    for item in root.findall("./channel/item"):
        keyword = (
            item.findtext("title") or ""
        ).strip()

        traffic = (
            item.findtext(
                f"{{{HT_NS}}}approx_traffic"
            )
            or "Unknown"
        ).strip()

        news_items = item.findall(
            f"{{{HT_NS}}}news_item"
        )

        news = None

        # Use the first news item supplied by Google Trends.
        if news_items:
            news_element = news_items[0]

            news = {
                "title": (
                    news_element.findtext(
                        f"{{{HT_NS}}}news_item_title"
                    )
                    or ""
                ).strip(),
                "url": (
                    news_element.findtext(
                        f"{{{HT_NS}}}news_item_url"
                    )
                    or ""
                ).strip(),
                "source": (
                    news_element.findtext(
                        f"{{{HT_NS}}}news_item_source"
                    )
                    or ""
                ).strip(),
            }

        if keyword:
            rss_results.append(
                {
                    "keyword_original": keyword,
                    "normalized_keyword": normalize_text(
                        keyword
                    ),
                    "traffic": traffic,
                    "news": news,
                }
            )

    print(
        f"Fetched {len(rss_results)} RSS trend records."
    )

    return rss_results


def find_matching_rss_item(
    live_keyword: str,
    rss_results: list[dict],
) -> Optional[dict]:
    """Match a live webpage trend with its RSS news record."""

    normalized_live = normalize_text(live_keyword)

    # First attempt: exact normalized title match.
    for rss_item in rss_results:
        if (
            rss_item["normalized_keyword"]
            == normalized_live
        ):
            return rss_item

    # Second attempt: one title contains the other.
    for rss_item in rss_results:
        normalized_rss = rss_item[
            "normalized_keyword"
        ]

        if (
            normalized_live in normalized_rss
            or normalized_rss in normalized_live
        ):
            return rss_item

    # Third attempt: compare overlapping words.
    live_words = set(normalized_live.split())

    best_item = None
    best_score = 0.0

    for rss_item in rss_results:
        rss_words = set(
            rss_item["normalized_keyword"].split()
        )

        if not live_words or not rss_words:
            continue

        overlap = len(
            live_words.intersection(rss_words)
        )

        union = len(
            live_words.union(rss_words)
        )

        score = overlap / union if union else 0

        if score > best_score:
            best_score = score
            best_item = rss_item

    if best_score >= 0.5:
        return best_item

    return None


def attach_google_news(
    live_trends: list[dict],
    rss_results: list[dict],
) -> list[dict]:
    """
    Add the Google Trends news headline and URL to each
    live-page trend without changing the live page order.
    """

    combined_results = []

    for live_trend in live_trends:
        result = live_trend.copy()

        rss_match = find_matching_rss_item(
            live_trend["keyword_original"],
            rss_results,
        )

        if rss_match:
            result["news"] = rss_match.get("news")

            if (
                result.get("traffic") == "Unknown"
                and rss_match.get("traffic")
            ):
                result["traffic"] = rss_match[
                    "traffic"
                ]

        combined_results.append(result)

    return combined_results


# ============================================================
# TRANSLATION
# ============================================================

def translate_trend(trend: dict) -> dict:
    """Translate a trend keyword and its news into English."""

    translated = trend.copy()

    translated["keyword"] = translate_to_english(
        trend.get("keyword_original", "")
    )

    news = trend.get("news")

    if news:
        translated_news = news.copy()

        translated_news["title"] = (
            translate_to_english(
                news.get("title", "")
            )
        )

        translated_news["source"] = (
            translate_to_english(
                news.get("source", "")
            )
        )

        translated["news"] = translated_news

    return translated


def translate_trends(
    trends: list[dict],
) -> list[dict]:
    """Translate a list of trends."""

    translated_results = []

    for index, trend in enumerate(
        trends,
        start=1,
    ):
        print(
            f"Translating trend "
            f"{index}/{len(trends)}..."
        )

        translated_results.append(
            translate_trend(trend)
        )

    return translated_results


# ============================================================
# KERALA SELECTION
# ============================================================

def kerala_score(trend: dict) -> int:
    """Calculate whether a trend appears Kerala-related."""

    keyword = trend.get(
        "keyword_original",
        "",
    )

    news = trend.get("news") or {}

    news_title = news.get("title", "")
    news_source = news.get("source", "")

    combined = " ".join(
        [
            keyword,
            news_title,
            news_source,
        ]
    ).casefold()

    score = 0

    if contains_malayalam(keyword):
        score += 100

    if contains_malayalam(news_title):
        score += 50

    for term in KERALA_TERMS:
        if term in combined:
            score += 20

    return score


def select_kerala_trends(
    all_live_trends: list[dict],
) -> list[dict]:
    """
    Select Kerala-related items while keeping their original
    Google relevance order.
    """

    selected = []

    for trend in all_live_trends:
        if kerala_score(trend) > 0:
            selected.append(trend)

        if len(selected) >= TOP_N:
            break

    return selected


# ============================================================
# TELEGRAM
# ============================================================

def build_message(
    heading: str,
    trends: list[dict],
    note: str = "",
) -> str:
    """Build a Telegram HTML message."""

    lines = [
        f"<b>{html.escape(heading)}</b>",
        "",
    ]

    if note:
        lines.extend(
            [
                f"<i>{html.escape(note)}</i>",
                "",
            ]
        )

    if not trends:
        lines.append(
            "No matching trends were found during "
            "this four-hour period."
        )
        return "\n".join(lines)

    for position, trend in enumerate(
        trends,
        start=1,
    ):
        keyword = html.escape(
            shorten(
                trend.get("keyword", ""),
                85,
            )
        )

        traffic = html.escape(
            trend.get("traffic", "Unknown")
        )

        lines.append(
            f"{position}. 🔥 <b>{keyword}</b>"
        )

        lines.append(
            f"Searches: <b>{traffic}</b>"
        )

        news = trend.get("news")

        if (
            news
            and news.get("title")
            and news.get("url")
        ):
            news_title = html.escape(
                shorten(
                    news["title"],
                    140,
                )
            )

            source = html.escape(
                shorten(
                    news.get("source") or "News",
                    40,
                )
            )

            news_url = html.escape(
                news["url"],
                quote=True,
            )

            lines.append(
                f'📰 <a href="{news_url}">'
                f"{news_title}</a> — {source}"
            )

        else:
            lines.append(
                "📰 No related news was supplied "
                "by Google Trends."
            )

        lines.append("")

    lines.append(
        "Source: Google Trends Trending Now"
    )

    return "\n".join(lines)


def send_telegram(message: str) -> None:
    """Send a message using Telegram Bot API."""

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    response = requests.post(
        (
            "https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendMessage"
        ),
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {result}"
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    try:
        print(
            "Reading the live Google Trends page..."
        )

        live_trends = scrape_live_relevance_order()

        print(
            "Fetching Google Trends related news..."
        )

        rss_results = fetch_rss_trends()

        combined_trends = attach_google_news(
            live_trends,
            rss_results,
        )

        india_original = combined_trends[:TOP_N]

        kerala_original = select_kerala_trends(
            combined_trends
        )

        india_trends = translate_trends(
            india_original
        )

        kerala_trends = translate_trends(
            kerala_original
        )

        india_message = build_message(
            heading=(
                "🇮🇳 India — Top 10 Google Trends "
                "(Past 4 Hours, Live Relevance Order)"
            ),
            trends=india_trends,
        )

        kerala_message = build_message(
            heading=(
                "🌴 Kerala-Focused Google Trends "
                "(Past 4 Hours)"
            ),
            trends=kerala_trends,
            note=(
                "Kerala-focused results are filtered "
                "from the live India trends using "
                "Malayalam and Kerala-related terms."
            ),
        )

        print(
            "Sending India trends to Telegram..."
        )
        send_telegram(india_message)

        print(
            "Sending Kerala trends to Telegram..."
        )
        send_telegram(kerala_message)

        print(
            f"Successfully sent "
            f"{len(india_trends)} India trends and "
            f"{len(kerala_trends)} Kerala-focused trends."
        )

    except Exception as error:
        print(
            f"Bot failed: {error}",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
