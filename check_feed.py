import feedparser
import json
import os
import requests
from datetime import datetime, timezone

FEED_URL = "https://www.thefantasyfootballers.com/articles/feed/"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")

STATE_FILE = "last_seen.json"

MAX_IDS = 200
PRUNE_COUNT = 20


def load_seen():
    if not os.path.exists(STATE_FILE):
        return [], set()

    with open(STATE_FILE, "r") as f:
        data = json.load(f)
        seen_list = data.get("seen_ids", [])
        return seen_list, set(seen_list)


def save_seen(seen_list):
    with open(STATE_FILE, "w") as f:
        json.dump({"seen_ids": seen_list}, f)


def prune_seen(seen_list):
    if len(seen_list) >= MAX_IDS:
        print(f"Pruning oldest {PRUNE_COUNT} entries...")
        seen_list = seen_list[PRUNE_COUNT:]
    return seen_list


def format_timestamp(entry):
    # Prefer published date
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        unix = int(dt.timestamp())
        return f"<t:{unix}:F>"  # Discord dynamic timestamp

    # Fallback to updated date
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        unix = int(dt.timestamp())
        return f"<t:{unix}:F>"

    return "Unknown date"


def send_to_discord(title, link, timestamp):
    payload = {
        "embeds": [
            {
                "title": title,
                "description": f"{link}\n{timestamp}"
            }
        ]
    }

    response = requests.post(WEBHOOK_URL, json=payload)

    if response.status_code not in (200, 204):
        print(f"Failed to send to Discord: {response.status_code} {response.text}")


def main():
    if not WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK environment variable.")
        return

    feed = feedparser.parse(FEED_URL)

    if not feed.entries:
        print("No entries found.")
        return

    seen_list, seen_set = load_seen()
    new_entries = []

    # Find new entries
    for entry in feed.entries:
        entry_id = entry.get("id") or entry.get("link")
        if entry_id and entry_id not in seen_set:
            new_entries.append(entry)

    if not new_entries:
        print("No new articles.")
        return

    # Oldest → newest so order is correct in Discord
    new_entries.reverse()

    for entry in new_entries:
        entry_id = entry.get("id") or entry.get("link")

        print("Posting:", entry.title)

        timestamp = format_timestamp(entry)
        send_to_discord(entry.title, entry.link, timestamp)

        seen_list.append(entry_id)
        seen_set.add(entry_id)

    # Prune after adding
    seen_list = prune_seen(seen_list)

    save_seen(seen_list)


if __name__ == "__main__":
    main()
