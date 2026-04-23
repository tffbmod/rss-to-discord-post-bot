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

MAX_IDS = 500

# ----------------------------
# FAIL FAST
# ----------------------------
if not WEBHOOK_URL:
    raise ValueError("DISCORD_WEBHOOK is not set")


# ----------------------------
# FAILURE TRACKING
# ----------------------------
def load_failure_state():
    if not os.path.exists(FAILURE_FILE):
        return {"fail_count": 0, "alert_sent": False}

    try:
        with open(FAILURE_FILE, "r") as f:
            return json.load(f)
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
# STATE MANAGEMENT
# ----------------------------
def load_seen():
    if not os.path.exists(STATE_FILE):
        return [], set(), set()

    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            seen_ids = data.get("seen_ids", [])
            seen_urls = data.get("seen_urls", [])
            return seen_ids, set(seen_ids), set(seen_urls)
    except:
        return [], set(), set()


def save_seen(seen_ids, seen_urls):
    tmp_file = STATE_FILE + ".tmp"

    with open(tmp_file, "w") as f:
        json.dump({
            "seen_ids": seen_ids,
            "seen_urls": list(seen_urls)
        }, f)

    os.replace(tmp_file, STATE_FILE)


# ----------------------------
# FILTERING
# ----------------------------
def should_post(link):
    if not link:
        return False

    blocked_prefixes = [
        "https://www.thefantasyfootballers.com/dfs-podcast/",
        "https://www.thefantasyfootballers.com/episodes/",
        "https://www.thefantasyfootballers.com/dynasty-podcast/"
    ]

    return not any(link.startswith(p) for p in blocked_prefixes)


# ----------------------------
# TAG EXTRACTION
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


def extract_tag_id(link):
    try:
        path = urlparse(link).path.strip("/")
        prefix = path.split("/")[0].lower()
        return [TAG_IDS[prefix]] if prefix in TAG_IDS else []
    except:
        return []


# ----------------------------
# DISCORD POST (FIXED)
# ----------------------------
def send_to_discord(title, link, timestamp):
    tags = extract_tag_id(link)

    payload = {
        "thread_name": title[:100],
        "content": f"{timestamp}\n{link}",
        "applied_tags": tags
    }

    MAX_RETRIES = 3
    attempt = 0

    while attempt < MAX_RETRIES:
        attempt += 1

        try:
            response = requests.post(WEBHOOK_URL, json=payload, timeout=10)

            # Rate limit handling
            if response.status_code == 429:
                retry_after = float(response.json().get("retry_after", 1))
                print(f"[Attempt {attempt}] Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue

            # Retry on server errors
            if 500 <= response.status_code < 600:
                print(f"[Attempt {attempt}] Discord server error {response.status_code}")
                time.sleep(2)
                continue

            # Fail immediately on client errors
            if not response.ok:
                raise Exception(f"Discord error {response.status_code}: {response.text}")

            print("Discord success:", response.status_code)
            return True  # SUCCESS

        except requests.exceptions.RequestException as e:
            print(f"[Attempt {attempt}] Network error:", e)
            time.sleep(2)

    print("Failed to send after retries.")
    return False


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

        seen_ids, seen_id_set, seen_url_set = load_seen()

        new_posts = []

        for post in posts:
            post_id = str(post.get("id"))
            link = post.get("link")

            if (
                post_id not in seen_id_set and
                link not in seen_url_set and
                should_post(link)
            ):
                new_posts.append(post)

        if not new_posts:
            print("No new posts.")

            if fail_count > 0:
                send_alert("✅ RSS Bot has recovered and is working again.")

            save_failure_state(0, False)
            print("---- RUN END ----")
            return

        # Ensure correct order
        new_posts.sort(key=lambda p: p.get("date", ""))

        updated = False

        for post in new_posts:
            post_id = str(post.get("id"))
            title = unescape(post.get("title", {}).get("rendered", "No title"))
            link = post.get("link")
            date = post.get("date")

            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                timestamp = f"<t:{int(dt.timestamp())}:F>"
            except:
                timestamp = "New post"

            print("Posting:", title)

            success = send_to_discord(title, link, timestamp)

            if success:
                seen_ids.append(post_id)
                seen_id_set.add(post_id)
                seen_url_set.add(link)
                updated = True
            else:
                print("Skipping save, will retry next run.")

            time.sleep(1)

        if len(seen_ids) > MAX_IDS:
            seen_ids = seen_ids[-MAX_IDS:]

        if updated:
            save_seen(seen_ids, seen_url_set)

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
