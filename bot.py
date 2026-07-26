import html
import os
import re
import sys
import xml.etree.ElementTree as ET

import requests

TRENDS_URL = "https://trends.google.com/trending/rss"
HT_NS = "https://trends.google.com/trending/rss"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TOP_N = int(os.environ.get("TOP_N", "5"))
HOURS = int(os.environ.get("HOURS", "4"))


def traffic_to_number(value: str) -> int:
    """Convert values such as '10K+', '2M+', or '500+' into integers."""
    cleaned = value.upper().replace(",", "").replace("+", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMB]?)", cleaned)
    if not match:
        return 0

    number = float(match.group(1))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(number * multiplier[match.group(2)])


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
        title = (item.findtext("title") or "").strip()
        traffic = (
            item.findtext(f"{{{HT_NS}}}approx_traffic")
            or "Unknown"
        ).strip()
        published = (item.findtext("pubDate") or "").strip()

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

        if title:
            trends.append(
                {
                    "keyword": title,
                    "traffic": traffic,
                    "traffic_number": traffic_to_number(traffic),
                    "published": published,
                    "news": news,
                }
            )

    trends.sort(key=lambda trend: trend["traffic_number"], reverse=True)
    return trends[:TOP_N]


def build_message(trends: list[dict]) -> str:
    if not trends:
        return "🇮🇳 <b>Google Trends India</b>\n\nNo trends were available."

    lines = [
        "🇮🇳 <b>Google Trends India — Past 4 Hours</b>",
        "",
    ]

    for index, trend in enumerate(trends, start=1):
        keyword = html.escape(trend["keyword"])
        traffic = html.escape(trend["traffic"])

        lines.append(f"{index}. 🔥 <b>{keyword}</b>")
        lines.append(f"   Searches: <b>{traffic}</b>")

        news = trend["news"]
        if news and news["title"] and news["url"]:
            news_title = html.escape(news["title"])
            news_source = html.escape(news["source"] or "News")
            news_url = html.escape(news["url"], quote=True)
            lines.append(
                f'   📰 <a href="{news_url}">{news_title}</a> — {news_source}'
            )
        else:
            lines.append("   📰 No related news was supplied by Google Trends.")

        lines.append("")

    lines.append("Source: Google Trends Trending Now")
    return "\n".join(lines)


def send_telegram(message: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variable."
        )

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
    try:
        trends = fetch_india_trends()
        send_telegram(build_message(trends))
        print(f"Sent {len(trends)} trend(s) successfully.")
    except Exception as exc:
        print(f"Bot failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
