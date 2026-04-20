import json
import os
import requests
import time
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

API_URL = "https://www.thefantasyfootballers.com/wp-json/wp/v2/posts"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")

STATE_FILE = "last_seen.json"

MAX_IDS = 200
PRUNE_COUNT = 20

# ----------------------------
# DISCORD TAG IDS
# ----------------------------
TAG_IDS = {
    "analysis": "1495638590447943861",
    "best-ball": "1495638678993895544",
    "dfs": "1495638703065006171",
    "dynasty": "1495638845029486682",
    "props": "1495638912159453274",
    "fantasy-reaction": "1495638943998152774",
    "strategy": "1495638975992565871"
}


# ----------------------------
# STATE MANAGEMENT
# ----------------------------
def load_seen():
    if not os.path.exists(STATE_FILE):
        return [], set()

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            seen_list = data.get("seen_ids", [])
            return seen_list, set(seen_list)
    except Exception as e:
        print("Error reading state file:", e)
        return [], set()


def save_seen(seen_list):
    tmp_file = STATE_FILE + ".tmp"

    with open(tmp_file, "w") as f:
        json.dump({"seen_ids": seen_list}, f)

    os.replace(tmp_file, STATE_FILE)


def prune_seen(seen_list):
    if len(seen_list) >= MAX_IDS:
        print(f"Pruning oldest {PRUNE_COUNT} entries...")
        seen_list = seen_list[PRUNE_COUNT:]
    return seen_list


# ----------------------------
# FILTERING (URL-BASED)
# ----------------------------
def should_post(link):
    blocked_prefixes = [
        "https://www.thefantasyfootballers.com/dfs-podcast/",
        "https://www.thefantasyfootballers.com/episodes/",
        "https://www.thefantasyfootballers.com/dynasty-podcast/"
    ]

    for prefix in blocked_prefixes:
        if link.startswith(prefix):
            return False

    return True


# ----------------------------
# TAG EXTRACTION
# ----------------------------
def extract_tag_id(link):
    try:
        path = urlparse(link).path.strip("/")
        prefix = path.split("/")[0].lower()

        tag_id = TAG_IDS.get(prefix)

        if tag_id:
            print(f"Tag detected: {prefix}")
            return [tag_id]

        print(f"⚠️ No matching tag for prefix: {prefix}")
        return []

    except Exception as e:
        print("Error extracting tag:", e)
        return []


# ----------------------------
# DISCORD POST
# ----------------------------
def send_to_discord(title, link, timestamp):
    tags = extract_tag_id(link)

    payload = {
        "thread_name": title[:100],
        "content": f"{timestamp}\n{link}",
        "applied_tags": tags
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)

        # Handle rate limiting
        if response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            print(f"Rate limited. Retrying after {retry_after} seconds...")
            time.sleep(retry_after)
            response = requests.post(WEBHOOK_URL, json=payload, timeout=10)

        print("DISCORD STATUS:", response.status_code)
        print("DISCORD RESPONSE:", response.text)

    except Exception as e:
        print("Error sending to Discord:", e)


# ----------------------------
# FETCH POSTS
# ----------------------------
def fetch_posts():
    try:
        response = requests.get(API_URL, params={"per_page": 10}, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("Error fetching posts:", e)
        return []


# ----------------------------
# MAIN
# ----------------------------
def main():
    if not WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK environment variable.")
        return

    posts = fetch_posts()

    print("Total posts fetched:", len(posts))

    if not posts:
        print("No posts found.")
        return

    seen_list, seen_set = load_seen()
    new_posts = []

    for post in posts:
        post_id = str(post.get("id"))
        raw_title = post.get("title", {}).get("rendered", "")
        title = unescape(raw_title)
        link = post.get("link")

        print("Checking:", title)

        if post_id not in seen_set and should_post(link):
            print("ALLOWED:", title)
            new_posts.append(post)
        else:
            print("SKIPPED:", title)

    if not new_posts:
        print("No new articles.")
        return

    # Post oldest → newest
    new_posts.reverse()

    for post in new_posts:
        post_id = str(post.get("id"))
        raw_title = post.get("title", {}).get("rendered", "No title")
        title = unescape(raw_title)
        link = post.get("link")
        date = post.get("date")

        print("Posting:", title)

        # format timestamp
        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            unix = int(dt.timestamp())
            timestamp = f"<t:{unix}:F>"
        except:
            timestamp = "Unknown date"

        send_to_discord(title, link, timestamp)

        seen_list.append(post_id)
        seen_set.add(post_id)

    seen_list = prune_seen(seen_list)
    save_seen(seen_list)


if __name__ == "__main__":
    main()
