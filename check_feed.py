import json
import os
import requests
from datetime import datetime

API_URL = "https://www.thefantasyfootballers.com/wp-json/wp/v2/posts"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")

STATE_FILE = "last_seen.json"

MAX_IDS = 200
PRUNE_COUNT = 20


# ----------------------------
# STATE MANAGEMENT
# ----------------------------
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
# DISCORD POST
# ----------------------------
def send_to_discord(title, link, timestamp):
    payload = {
        "thread_name": title[:100],
        "content": f"{timestamp}\n{link}"
    }

    response = requests.post(WEBHOOK_URL, json=payload)

    print("DISCORD STATUS:", response.status_code)
    print("DISCORD RESPONSE:", response.text)


# ----------------------------
# FETCH POSTS
# ----------------------------
def fetch_posts():
    try:
        response = requests.get(API_URL, params={"per_page": 10})
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
        title = post.get("title", {}).get("rendered", "")
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
        title = post.get("title", {}).get("rendered", "No title")
        link = post.get("link")
        date = post.get("date")

        print("Posting:", title)

        # format timestamp
        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            timestamp = dt.strftime("%Y-%m-%d %H:%M UTC")
        except:
            timestamp = "Unknown date"

        send_to_discord(title, link, timestamp)

        seen_list.append(post_id)
        seen_set.add(post_id)

    seen_list = prune_seen(seen_list)
    save_seen(seen_list)


if __name__ == "__main__":
    main()
