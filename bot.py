import html
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests
from deep_translator import GoogleTranslator


# --------------------------------------------------
# Configuration
# --------------------------------------------------

TRENDS_URL = "https://trends.google.com/trending/rss"
HT_NS = "https://trends.google.com/trending/rss"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TOP_N = int(os.environ.get("TOP_N", "10"))
HOURS = int(os.environ.get("HOURS", "4"))


# Words used to identify Kerala-focused trends.
KERALA_TERMS = {
    # State and language
    "kerala",
    "malayalam",
    "malayali",

    # Districts and cities
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

    # Kerala personalities and cinema
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
    "mollywood",

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


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def traffic_to_number(value: str) -> int:
    """
    Convert Google Trends traffic values into integers.

    Examples:
    500+  -> 500
    2K+   -> 2000
    50K+  -> 50000
    1M+   -> 1000000
    """

    cleaned = (
        value.upper()
        .replace(",", "")
        .replace("+", "")
        .strip()
    )

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*([KMB]?)",
        cleaned,
    )

    if not match:
        return 0

    number = float(match.group(1))
    unit = match.group(2)

    multipliers = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }

    return int(number * multipliers[unit])


def contains_malayalam(text: str) -> bool:
    """Return True when the text contains Malayalam characters."""

    return any(
        "\u0D00" <= character <= "\u0D7F"
        for character in text
    )


def translate_to_english(text: str) -> str:
    """
    Automatically translate text into English.

    When translation fails, return the original text so the
    complete workflow does not fail.
    """

    if not text:
        return ""

    try:
        translated = GoogleTranslator(
            source="auto",
            target="en",
        ).translate(text)

        return translated or text

    except Exception as error:
        print(
            f"Translation warning for '{text[:50]}': {error}",
            file=sys.stderr,
        )
        return text


def shorten(text: str, limit: int) -> str:
    """Shorten long text to avoid Telegram's message limit."""

    cleaned = " ".join(text.split())

    if len(cleaned) <= limit:
        return cleaned

    return cleaned[: limit - 1].rstrip() + "…"


# --------------------------------------------------
# Fetch Google Trends
# --------------------------------------------------

def fetch_india_trends() -> list[dict]:
    """
    Get Google's India trends for the past four hours.

    The original order supplied by Google is preserved.
    The trends are not sorted by search volume.
    """

    response = requests.get(
        TRENDS_URL,
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

    xml_root = ET.fromstring(response.content)

    trends = []

    for item in xml_root.findall("./channel/item"):
        original_keyword = (
            item.findtext("title") or ""
        ).strip()

        traffic = (
            item.findtext(f"{{{HT_NS}}}approx_traffic")
            or "Unknown"
        ).strip()

        published = (
            item.findtext("pubDate") or ""
        ).strip()

        news_element = item.find(
            f"{{{HT_NS}}}news_item"
        )

        news = None

        if news_element is not None:
            news_title = (
                news_element.findtext(
                    f"{{{HT_NS}}}news_item_title"
                )
                or ""
            ).strip()

            news_url = (
                news_element.findtext(
                    f"{{{HT_NS}}}news_item_url"
                )
                or ""
            ).strip()

            news_source = (
                news_element.findtext(
                    f"{{{HT_NS}}}news_item_source"
                )
                or ""
            ).strip()

            news = {
                "original_title": news_title,
                "title": news_title,
                "url": news_url,
                "source": news_source,
            }

        if original_keyword:
            trends.append(
                {
                    "keyword_original": original_keyword,
                    "keyword": original_keyword,
                    "traffic": traffic,
                    "traffic_number": traffic_to_number(
                        traffic
                    ),
                    "published": published,
                    "news": news,
                }
            )

    # Do not sort this list.
    # This preserves the relevance order returned by Google.

    return trends


# --------------------------------------------------
# Translation
# --------------------------------------------------

def translate_trend(trend: dict) -> dict:
    """Translate one trend and its related news into English."""

    translated_trend = trend.copy()

    translated_trend["keyword"] = translate_to_english(
        trend["keyword_original"]
    )

    if trend.get("news"):
        translated_news = trend["news"].copy()

        translated_news["title"] = translate_to_english(
            trend["news"].get("original_title", "")
        )

        translated_news["source"] = translate_to_english(
            trend["news"].get("source", "")
        )

        translated_trend["news"] = translated_news

    return translated_trend


def translate_trends(trends: list[dict]) -> list[dict]:
    """Translate all selected trends into English."""

    translated = []

    for trend in trends:
        translated.append(translate_trend(trend))

    return translated


# --------------------------------------------------
# Kerala selection
# --------------------------------------------------

def kerala_score(trend: dict) -> int:
    """
    Identify whether a trend appears related to Kerala.

    Malayalam text receives a high score. Kerala place names,
    personalities and news sources also increase the score.
    """

    original_keyword = trend.get(
        "keyword_original",
        "",
    )

    news = trend.get("news") or {}

    combined_text = " ".join(
        [
            original_keyword,
            news.get("original_title", ""),
            news.get("source", ""),
        ]
    ).lower()

    score = 0

    if contains_malayalam(original_keyword):
        score += 100

    if contains_malayalam(
        news.get("original_title", "")
    ):
        score += 50

    for term in KERALA_TERMS:
        if term in combined_text:
            score += 20

    return score


def select_kerala_focused(
    trends: list[dict],
) -> list[dict]:
    """
    Select Kerala-focused trends while preserving Google's
    original relevance order.

    The list is not re-sorted by search volume or Kerala score.
    """

    kerala_trends = []

    for trend in trends:
        if kerala_score(trend) > 0:
            kerala_trends.append(trend)

        if len(kerala_trends) >= TOP_N:
            break

    return kerala_trends


# --------------------------------------------------
# Telegram message
# --------------------------------------------------

def build_message(
    heading: str,
    trends: list[dict],
    note: str = "",
) -> str:
    """Create one formatted Telegram message."""

    lines = [
        f"<b>{html.escape(heading)}</b>",
        "",
    ]

    if note:
        lines.append(
            f"<i>{html.escape(note)}</i>"
        )
        lines.append("")

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
                    145,
                )
            )

            source = html.escape(
                shorten(
                    news.get("source") or "News",
                    45,
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
    """Send one message through Telegram Bot API."""

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


# --------------------------------------------------
# Main program
# --------------------------------------------------

def main() -> None:
    try:
        print(
            "Fetching India Google Trends..."
        )

        all_trends = fetch_india_trends()

        if not all_trends:
            raise RuntimeError(
                "Google Trends returned no results."
            )

        # Keep the first 10 results exactly in Google's
        # original relevance order.
        india_original = all_trends[:TOP_N]

        # Select Kerala-related entries without changing
        # Google's original relevance order.
        kerala_original = select_kerala_focused(
            all_trends
        )

        print(
            "Translating India trends into English..."
        )

        india_trends = translate_trends(
            india_original
        )

        print(
            "Translating Kerala-focused trends "
            "into English..."
        )

        kerala_trends = translate_trends(
            kerala_original
        )

        india_message = build_message(
            heading=(
                "🇮🇳 India — Top 10 Google Trends "
                "(Past 4 Hours, By Relevance)"
            ),
            trends=india_trends,
        )

        kerala_message = build_message(
            heading=(
                "🌴 Kerala-Focused Google Trends "
                "(Past 4 Hours, By Relevance)"
            ),
            trends=kerala_trends,
            note=(
                "Kerala-focused results are selected "
                "from India's Google Trends feed using "
                "Malayalam and Kerala-related terms."
            ),
        )

        print(
            "Sending India message to Telegram..."
        )
        send_telegram(india_message)

        print(
            "Sending Kerala message to Telegram..."
        )
        send_telegram(kerala_message)

        print(
            f"Success: sent {len(india_trends)} "
            f"India trends and {len(kerala_trends)} "
            "Kerala-focused trends."
        )

    except Exception as error:
        print(
            f"Bot failed: {error}",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
