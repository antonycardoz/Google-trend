import html
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests
from deep_translator import GoogleTranslator

TRENDS_URL = "https://trends.google.com/trending/rss"
HT_NS = "https://trends.google.com/trending/rss"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TOP_N = int(os.environ.get("TOP_N", "10"))
HOURS = int(os.environ.get("HOURS", "4"))

KERALA_TERMS = {
    "kerala", "malayalam", "malayali", "kochi", "cochin", "ernakulam",
    "thiruvananthapuram", "trivandrum", "kozhikode", "calicut", "thrissur",
    "kollam", "alappuzha", "alleppey", "kannur", "kasaragod", "kottayam",
    "idukki", "palakkad", "pathanamthitta", "wayanad", "malappuram",
    "mohanlal", "mammootty", "dulquer", "fahadh", "tovino", "prithviraj",
    "manorama", "mathrubhumi", "asianet", "24 news", "reporter tv"
}


def traffic_to_number(value: str) -> int:
    cleaned = value.upper().replace(",", "").replace("+", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMB]?)", cleaned)
    if not match:
        return 0

    number = float(match.group(1))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(number * multiplier[match.group(2)])


def contains_malayalam(text: str) -> bool:
    return any("\u0D00" <= char <= "\u0D7F" for char in text)


def translate_to_english(text: str) -> str:
    if not text:
        return ""

    try:
        translated = GoogleTranslator(source="auto", target="en").translate(text)
        return translated or text
    except Exception as exc:
        print(f"Translation warning: {exc}", file=sys.stderr)
        return text


def fetch_india_trends() -> list[dict]:
    response = requests.get(
        TRENDS_URL,
        params={"geo": "IN", "hours": HOURS},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    trends = []

    for item in root.findall("./channel/item"):
        keyword = (item.findtext("title") or "").strip()
        traffic = (
            item.findtext(f"{{{HT_NS}}}approx_traffic") or "Unknown"
        ).strip()

        news_element = item.find(f"{{{HT_NS}}}news_item")
        news = None

        if news_element is not None:
            news = {
                "title": (
                    news_element.findtext(f"{{{HT_NS}}}news_item_title") or ""
                ).strip(),
                "url": (
                    news_element.findtext(f"{{{HT_NS}}}news_item_url") or ""
                ).strip(),
                "source": (
                    news_element.findtext(f"{{{HT_NS}}}news_item_source") or ""
                ).strip(),
            }

        if keyword:
            trends.append(
                {
                    "keyword_original": keyword,
                    "keyword": translate_to_english(keyword),
                    "traffic": traffic,
                    "traffic_number": traffic_to_number(traffic),
                    "news": news,
                }
            )

    trends.sort(key=lambda item: item["traffic_number"], reverse=True)

    for trend in trends:
        if trend["news"]:
            trend["news"]["title"] = translate_to_english(
                trend["news"]["title"]
            )
            trend["news"]["source"] = translate_to_english(
                trend["news"]["source"]
            )

    return trends


def kerala_score(trend: dict) -> int:
    original_keyword = trend["keyword_original"]
    keyword = trend["keyword"]
    news = trend.get("news") or {}

    combined = " ".join(
        [
            original_keyword,
            keyword,
            news.get("title", ""),
            news.get("source", ""),
        ]
    ).lower()

    score = 0

    if contains_malayalam(original_keyword):
        score += 100

    for term in KERALA_TERMS:
        if term in combined:
            score += 20

    return score


def select_kerala_focused(trends: list[dict]) -> list[dict]:
    ranked = sorted(
        trends,
        key=lambda item: (kerala_score(item), item["traffic_number"]),
        reverse=True,
    )
    return [item for item in ranked if kerala_score(item) > 0][:TOP_N]


def shorten(text: str, limit: int = 150) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_message(title: str, trends: list[dict], note: str = "") -> str:
    lines = [f"<b>{html.escape(title)}</b>", ""]

    if note:
        lines.extend([f"<i>{html.escape(note)}</i>", ""])

    if not trends:
        lines.append("No matching trends were found in this four-hour period.")
        return "\n".join(lines)

    for index, trend in enumerate(trends, start=1):
        keyword = html.escape(shorten(trend["keyword"], 80))
        traffic = html.escape(trend["traffic"])

        lines.append(f"{index}. 🔥 <b>{keyword}</b>")
        lines.append(f"Searches: <b>{traffic}</b>")

        news = trend.get("news")
        if news and news.get("title") and news.get("url"):
            news_title = html.escape(shorten(news["title"], 155))
            source = html.escape(shorten(news.get("source") or "News", 45))
            url = html.escape(news["url"], quote=True)
            lines.append(f'📰 <a href="{url}">{news_title}</a> — {source}')
        else:
            lines.append("📰 No related news supplied by Google Trends.")

        lines.append("")

    lines.append("Source: Google Trends Trending Now")
    return "\n".join(lines)


def send_telegram(message: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID."
        )

    trends = fetch_india_trends()

    india = trends[:TOP_N]
    kerala = select_kerala_focused(trends)

    send_telegram(
        build_message(
            "🇮🇳 India — Top 10 Google Trends (Past 4 Hours)",
            india,
        )
    )

    send_telegram(
        build_message(
            "🌴 Kerala-Focused Trends (Past 4 Hours)",
            kerala,
            "Free approximation: selected from India trends using Malayalam "
            "and Kerala-related keywords. It is not official Kerala-only "
            "search-volume data.",
        )
    )

    print(
        f"Sent {len(india)} India trends and "
        f"{len(kerala)} Kerala-focused trends."
    )


if __name__ == "__main__":
    main()
