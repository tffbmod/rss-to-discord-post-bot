import json
import os
import requests
import time
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

API_URL = "https://www.thefantasyfootballers.com/wp-json/wp/v2/posts"

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
ALERT_WEBHOOK = os.environ.get("DISCORD_ALERT_WEBHOOK")
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID")

STATE_FILE = "last_seen.json"
FAILURE_FILE = "failure_state.json"

MAX_IDS = 200
PRUNE_COUNT = 20

# ----------------------------
# FAIL FAST
# ----------------------------
if not WEBHOOK_URL:
    raise ValueError("DISCORD_WEBHOOK is not set")


# ----------------------------
# FAILURE TRACKING (WITH ALERT CONTROL)
# ----------------------------
def load_failure_state():
    if not os.path.exists(FAILURE_FILE):
        return {"fail_count": 0, "alert_sent": False}

    try:
        with open(FAILURE_FILE, "r") as f:
            data = json.load(f)
            return {
                "fail_count": data.get("fail_count", 0),
                "alert_sent": data.get("alert_sent", False)
            }
    except:
        return {"fail_count": 0, "alert_sent": False}


def save_failure_state(fail_count, alert_sent):
    with open(FAILURE_FILE, "w") as f:
        json.dump({
            "fail_count": fail_count,
            "alert_sent": alert_sent
        }, f)


def send_alert(message):
    if not ALERT_WEBHOOK or not DISCORD_USER_ID:
        print("Alert webhook or user ID not set.")
        return

    payload = {
        "content": f"<@{DISCORD_USER_ID}> 🚨 RSS Bot:\n{message}"
    }

    try:
        requests.post(ALERT_WEBHOOK, json=payload, timeout=10)
    except Exception as e:
        print("Failed to send alert:", e)


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
    "reaction": "1495638943998152774",
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
# FILTERING
# ----------------------------
def should_post(link):
    blocked_prefixes = [
        "https://www.thefantasyfootballers.com/dfs-podcast/",
        "https://www.thefantasyfootballers.com/episodes/",
        "https://www.thefantasyfootballers.com/dynasty-podcast/"
    ]

    return not any(link.startswith(p) for p in blocked_prefixes)


# ----------------------------
# TAG EXTRACTION
# ----------------------------
def extract_tag_id(link):
    try:
        path = urlparse(link).path.strip("/")
        prefix = path.split("/")[0].lower()
        return [TAG_IDS[prefix]] if prefix in TAG_IDS else []
    except:
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

    response = requests.post(WEBHOOK_URL, json=payload, timeout=10)

    if response.status_code == 429:
        retry_after = response.json().get("retry_after", 1)
        print(f"Rate limited. Retrying after {retry_after} seconds...")
        time.sleep(retry_after)
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)

    print("Discord status:", response.status_code)


# ----------------------------
# FETCH POSTS
# ----------------------------
def fetch_posts():
    response = requests.get(API_URL, params={"per_page": 5}, timeout=10)
    response.raise_for_status()
    return response.json()


# ----------------------------
# MAIN
# ----------------------------
def main():
    print("---- RUN START ----")

    state = load_failure_state()
    fail_count = state["fail_count"]
    alert_sent = state["alert_sent"]

    try:
        posts = fetch_posts()
        print("Posts fetched:", len(posts))

        seen_list, seen_set = load_seen()
        new_posts = []

        for post in posts:
            post_id = str(post.get("id"))
            title = unescape(post.get("title", {}).get("rendered", ""))
            link = post.get("link")

            if post_id not in seen_set and should_post(link):
                new_posts.append(post)

        if not new_posts:
            print("No new posts.")
            
            # If previously failing, notify recovery
            if fail_count > 0:
                send_alert("✅ RSS Bot has recovered and is working again.")

            save_failure_state(0, False)
            print("---- RUN END ----")
            return

        new_posts.reverse()

        for post in new_posts:
            post_id = str(post.get("id"))
            title = unescape(post.get("title", {}).get("rendered", "No title"))
            link = post.get("link")
            date = post.get("date")

            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            timestamp = f"<t:{int(dt.timestamp())}:F>"

            print("Posting:", title)

            send_to_discord(title, link, timestamp)

            seen_list.append(post_id)
            seen_set.add(post_id)

            time.sleep(1)

        seen_list = prune_seen(seen_list)
        save_seen(seen_list)

        # If previously failing, notify recovery
        if fail_count > 0:
            send_alert("✅ RSS Bot has recovered and is working again.")

        save_failure_state(0, False)

    except Exception as e:
        fail_count += 1

        error_msg = f"Failure #{fail_count}\n{str(e)}"
        print(error_msg)

        if not alert_sent:
            send_alert(error_msg)
            alert_sent = True

        save_failure_state(fail_count, alert_sent)

    print("---- RUN END ----")


if __name__ == "__main__":
    main()
