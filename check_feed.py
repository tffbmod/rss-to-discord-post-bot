import json
import os
import requests
import time
from datetime import datetime
from html import unescape
from urllib.parse import urlparse
import traceback

API_URL = "https://www.thefantasyfootballers.com/wp-json/wp/v2/posts"

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
ALERT_WEBHOOK_URL = os.environ.get("DISCORD_ALERT_WEBHOOK")
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID")

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

STATE_FILE = "last_seen.json"
FAIL_STATE_FILE = "failure_state.json"

MAX_IDS = 200
PRUNE_COUNT = 20
MAX_FAILURES = 3

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
    except:
        return [], set()


def save_seen(seen_list):
    tmp_file = STATE_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump({"seen_ids": seen_list}, f)
    os.replace(tmp_file, STATE_FILE)


def prune_seen(seen_list):
    if len(seen_list) >= MAX_IDS:
        seen_list = seen_list[PRUNE_COUNT:]
    return seen_list


# ----------------------------
# FAILURE TRACKING
# ----------------------------
def load_fail_count():
    if not os.path.exists(FAIL_STATE_FILE):
        return 0
    try:
        with open(FAIL_STATE_FILE, "r") as f:
            return json.load(f).get("fail_count", 0)
    except:
        return 0


def save_fail_count(count):
    with open(FAIL_STATE_FILE, "w") as f:
        json.dump({"fail_count": count}, f)


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
        tag_id = TAG_IDS.get(prefix)

        if tag_id:
            print(f"Tag detected: {prefix}")
            return [tag_id]

        print(f"No tag match for: {prefix}")
        return []
    except:
        return []


# ----------------------------
# RETRY HELPER
# ----------------------------
def post_with_retry(url, payload, retries=3):
    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 1)
                time.sleep(retry_after)
                continue

            if response.status_code >= 500:
                time.sleep(2)
                continue

            return response

        except Exception:
            time.sleep(2)

    return None


# ----------------------------
# DISCORD POST
# ----------------------------
def send_to_discord(title, link, timestamp):
    payload = {
        "thread_name": title[:100],
        "content": f"{timestamp}\n{link}",
        "applied_tags": extract_tag_id(link)
    }

    post_with_retry(WEBHOOK_URL, payload)


# ----------------------------
# ERROR ALERT
# ----------------------------
def send_error_to_discord(error_message):
    if not ALERT_WEBHOOK_URL:
        return

    mention = f"<@{DISCORD_USER_ID}>" if DISCORD_USER_ID else ""
    run_url = ""

    if GITHUB_REPOSITORY and GITHUB_RUN_ID:
        run_url = f"https://github.com/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}"

    payload = {
        "content": (
            f"{mention} 🚨 **RSS BOT ERROR** 🚨\n\n"
            f"Run: {run_url}\n\n"
            f"```{error_message[:1500]}```"
        )
    }

    post_with_retry(ALERT_WEBHOOK_URL, payload)


# ----------------------------
# DISABLE WORKFLOW
# ----------------------------
def disable_workflow():
    if not GITHUB_REPOSITORY or not GITHUB_TOKEN:
        return

    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/workflows/rss-to-discord.yml/disable"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    try:
        requests.put(url, headers=headers, timeout=10)
    except:
        pass


# ----------------------------
# FETCH POSTS
# ----------------------------
def fetch_posts():
    try:
        r = requests.get(API_URL, params={"per_page": 10}, timeout=10)
        r.raise_for_status()
        return r.json()
    except:
        return []


# ----------------------------
# MAIN
# ----------------------------
def main():
    if not WEBHOOK_URL:
        return

    posts = fetch_posts()
    if not posts:
        return

    seen_list, seen_set = load_seen()
    new_posts = []

    for post in posts:
        post_id = str(post.get("id"))
        title = unescape(post.get("title", {}).get("rendered", ""))
        link = post.get("link")

        if post_id not in seen_set and should_post(link):
            new_posts.append(post)

    if not new_posts:
        return

    new_posts.reverse()

    for post in new_posts:
        post_id = str(post.get("id"))
        title = unescape(post.get("title", {}).get("rendered", ""))
        link = post.get("link")
        date = post.get("date")

        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            timestamp = f"<t:{int(dt.timestamp())}:F>"
        except:
            timestamp = "Unknown date"

        send_to_discord(title, link, timestamp)

        seen_list.append(post_id)
        seen_set.add(post_id)

    save_seen(prune_seen(seen_list))


# ----------------------------
# ENTRY WITH FAILURE CONTROL
# ----------------------------
if __name__ == "__main__":
    MAX_RUN_RETRIES = 2
    fail_count = load_fail_count()

    for attempt in range(MAX_RUN_RETRIES + 1):
        try:
            main()
            save_fail_count(0)
            break

        except Exception:
            error_text = traceback.format_exc()

            if attempt == MAX_RUN_RETRIES:
                fail_count += 1
                save_fail_count(fail_count)

                send_error_to_discord(
                    f"{error_text}\n\nFailure count: {fail_count}/{MAX_FAILURES}"
                )

                if fail_count >= MAX_FAILURES:
                    send_error_to_discord(
                        "🚫 Workflow disabled after repeated failures.\nPlease re-enable manually."
                    )
                    disable_workflow()

                raise
            else:
                time.sleep(5)
