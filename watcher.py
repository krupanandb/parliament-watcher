"""
Live Parliament (Sansad) watcher.

Polls the official sansad.in JSON APIs for Lok Sabha and Rajya Sabha,
detects anything new since the last run, and sends instant Telegram alerts.

What it watches:
  1. Sitting days           - morning alert "Parliament sits today" + live TV links
  2. Daily documents        - List of Business (agenda), Revised/Supplementary lists,
                              Bulletin-I/II, Question lists, Synopsis, Papers laid
  3. Bills                  - newly introduced bills and any status change
                              (passed in LS / passed in RS / assented / withdrawn ...)
  4. Uncorrected debates    - near-live verbatim text of the day's proceedings
  5. RS latest updates      - Zero Hour notices and other fresh RS publications

State is kept in state.json next to this file so only *new* things are alerted.

Environment variables:
  TELEGRAM_BOT_TOKEN  - from @BotFather
  TELEGRAM_CHAT_ID    - your chat id (see README)
If they are missing the script runs in dry-run mode and just prints the alerts.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Windows consoles default to a legacy codepage that cannot print emoji.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://sansad.in"
STATE_FILE = Path(__file__).parent / "state.json"
IST = timezone(timedelta(hours=5, minutes=30))

LIVE_LINKS = (
    "\n\U0001F4FA Watch live: "
    f"<a href='https://sansadtv.nic.in/live-tv'>Sansad TV</a> | "
    f"<a href='{BASE}/ls'>Lok Sabha</a> | "
    f"<a href='{BASE}/rs'>Rajya Sabha</a>"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (parliament-watcher; personal notification tool)",
    "Accept": "application/json",
}


def get_json(path, default=None):
    """GET a sansad.in API path, return parsed JSON or default on any failure."""
    url = BASE + path
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"WARN: {path} failed: {e}")
    return default


# ---------------------------------------------------------------- state ----

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8"
    )


# ------------------------------------------------------------- telegram ----

def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("DRY-RUN (no Telegram credentials). Would send:")
        print(text)
        print("-" * 60)
        return True
    # Telegram messages max 4096 chars - split on line boundaries if needed.
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    chunks.append(current)
    ok = True
    for chunk in chunks:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            if not r.json().get("ok"):
                print(f"WARN: Telegram rejected message: {r.text[:200]}")
                ok = False
            time.sleep(1)
        except Exception as e:
            print(f"WARN: Telegram send failed: {e}")
            ok = False
    return ok


# ------------------------------------------------------------- watchers ----

def current_session(state):
    """Discover the current Lok Sabha number and session number, cache in state."""
    cached = state.get("session_info", {})
    # refresh at most once a day
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if cached.get("checked") == today:
        return cached
    data = get_json("/api_ls/business/getAllLoksabhaAndSession", default=[])
    info = {"loksabha": 18, "session": 8, "checked": today}  # sensible fallback
    try:
        if isinstance(data, list) and data:
            newest = data[0]
            info["loksabha"] = int(newest.get("loksabhaNo") or 18)
            sessions = newest.get("sessions") or newest.get("sessionNo") or []
            if isinstance(sessions, list) and sessions:
                nums = []
                for s in sessions:
                    v = s.get("sessionNo") if isinstance(s, dict) else s
                    try:
                        nums.append(int(str(v).strip()))
                    except (TypeError, ValueError):
                        pass
                if nums:
                    info["session"] = max(nums)
    except Exception as e:
        print(f"WARN: could not parse session info: {e}")
    state["session_info"] = info
    return info


def check_sitting_day(state, alerts):
    """Morning alert; returns True if today is a sitting day."""
    now = datetime.now(IST)
    today_slash = now.strftime("%d/%m/%Y")
    today_key = now.strftime("%Y-%m-%d")
    data = get_json(
        f"/api_ls/ppHome/MonthlyCalendar?month={now.month}&year={now.year}&locale=en",
        default={},
    )
    session_dates = data.get("sessionDates") or []
    sitting_today = today_slash in session_dates

    def _parse(d):
        try:
            return datetime.strptime(d, "%d/%m/%Y").replace(tzinfo=IST)
        except ValueError:
            return None

    if state.get("sitting_alerted") != today_key:
        if sitting_today:
            # Sitting-day number within this month's session dates
            # (used for the "DAY N" badge on my update cards).
            day_no = len([
                d for d in (_parse(x) for x in session_dates)
                if d and d.date() <= now.date()
            ])
            alerts.append(
                f"\U0001F3DB <b>Parliament sits today</b> "
                f"({now.strftime('%d %b %Y')}) — <b>Day {day_no}</b> of the "
                "session.\n"
                "Lok Sabha and Rajya Sabha usually convene at 11:00 AM."
                + LIVE_LINKS
            )
            state["sitting_alerted"] = today_key
        else:
            # During a session period, tell the user once that today is a break.
            upcoming = sorted(
                d for d in (_parse(x) for x in session_dates)
                if d and d.date() > now.date()
            )
            recent = [
                d for d in (_parse(x) for x in session_dates)
                if d and 0 < (now.date() - d.date()).days <= 7
            ]
            if upcoming and recent:
                alerts.append(
                    f"\U0001F4C5 No sitting of Parliament today "
                    f"({now.strftime('%d %b %Y')}). "
                    f"Next sitting: <b>{upcoming[0].strftime('%d %b %Y')}</b>."
                )
                state["sitting_alerted"] = today_key
    return sitting_today


# --------------------------------------------------- live stream status ----

YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _yt_get(url):
    try:
        r = requests.get(
            url, headers=YT_HEADERS, cookies={"CONSENT": "YES+1"}, timeout=30
        )
        if r.status_code == 200 and len(r.text) > 10000:
            return r.text
    except Exception as e:
        print(f"WARN: YouTube fetch failed: {e}")
    return None


def fetch_live_feeds():
    """Return {'Lok Sabha': video_id_or_None, 'Rajya Sabha': ...} for feeds
    that are live RIGHT NOW on the official Sansad TV channel, or None if
    YouTube could not be checked at all (so callers can skip, not conclude)."""
    import re

    html = _yt_get("https://www.youtube.com/@sansadtv/streams")
    if html is None:
        return None
    ids = []
    for vid in re.findall(r'"videoId":"([\w-]{11})"', html):
        if vid not in ids:
            ids.append(vid)
    feeds = {"Lok Sabha": None, "Rajya Sabha": None}
    checked = 0
    for vid in ids[:6]:
        if checked >= 4 or all(feeds.values()):
            break
        page = _yt_get(f"https://www.youtube.com/watch?v={vid}")
        checked += 1
        if page is None:
            return None  # can't trust partial YouTube data
        if '"isLiveNow":true' not in page:
            continue
        m = re.search(r"<title>([^<]*)</title>", page)
        title = (m.group(1) if m else "").lower()
        if "lok sabha" in title and feeds["Lok Sabha"] is None:
            feeds["Lok Sabha"] = vid
        elif "rajya sabha" in title and feeds["Rajya Sabha"] is None:
            feeds["Rajya Sabha"] = vid
    return feeds


def check_live_status(state, alerts, sitting_today):
    """Alert when a House goes live (sitting started/resumed) or its stream
    ends (House adjourned). Uses two consecutive 'offline' sightings before
    declaring an adjournment, so a brief stream hiccup doesn't false-alarm."""
    if not sitting_today:
        return
    feeds = fetch_live_feeds()
    if feeds is None:
        print("WARN: YouTube unreachable, skipping live-status check.")
        return
    status = state.get("live_status", {})
    for house in ("Lok Sabha", "Rajya Sabha"):
        vid = feeds.get(house)
        prev = status.get(house, {"live": False, "off_seen": 0})
        if vid:
            if not prev["live"]:
                alerts.append(
                    f"\U0001F534 <b>{house} is LIVE</b> — the sitting has "
                    f"started/resumed.\n"
                    f"\U0001F4FA <a href='https://www.youtube.com/watch?v={vid}'>"
                    f"Watch {house} live</a>"
                )
            status[house] = {"live": True, "off_seen": 0}
        else:
            if prev["live"]:
                prev["off_seen"] = prev.get("off_seen", 0) + 1
                if prev["off_seen"] >= 2:
                    alerts.append(
                        f"⏸ <b>{house} adjourned</b> — the live stream has "
                        "ended. I keep checking every few minutes and will "
                        "alert you the moment the House reconvenes."
                    )
                    prev = {"live": False, "off_seen": 0}
                status[house] = prev
            else:
                status[house] = {"live": False, "off_seen": 0}
    state["live_status"] = status


def maybe_heartbeat(state, alerts, sitting_today):
    """On sitting days, never leave more than an hour of silence: if nothing
    was sent in the last 60 minutes, send a short status message."""
    if not sitting_today or alerts:
        return
    now = datetime.now(IST)
    if not (10 <= now.hour < 21):
        return
    last = state.get("last_msg_ts", 0)
    if time.time() - last < 3600:
        return
    status = state.get("live_status", {})

    def word(h):
        return "\U0001F534 LIVE" if status.get(h, {}).get("live") else "adjourned / not streaming"

    alerts.append(
        f"ℹ️ No new updates in the last hour "
        f"(checked {now.strftime('%I:%M %p')} IST).\n"
        f"Lok Sabha: <b>{word('Lok Sabha')}</b> | "
        f"Rajya Sabha: <b>{word('Rajya Sabha')}</b>\n"
        "Monitoring continues every ~5 minutes."
    )


def _doc_items_ls(cal):
    items = []
    for lob in cal.get("listOfBusinessUrls") or []:
        items.append((lob.get("name"), lob.get("url")))
    for key, label in [
        ("bulletin1Url", "Bulletin-I (record of proceedings)"),
        ("bulletin2Url", "Bulletin-II"),
        ("questionListUrl", "Questions List"),
        ("synopsisUrl", "Synopsis of Debate"),
        ("papersToBeLaidUrl", "Papers To Be Laid"),
    ]:
        d = cal.get(key) or {}
        if isinstance(d, dict) and d.get("url"):
            items.append((d.get("name") or label, d.get("url")))
    return items


def _doc_items_rs(cal):
    items = []
    for lob in cal.get("listOfBusinessUrls") or []:
        if lob.get("url"):
            items.append((lob.get("name") or "List of Business", lob.get("url")))
    for q in cal.get("questionListUrls") or []:
        if q.get("url"):
            items.append((q.get("name") or "Questions", q.get("url")))
    for s in cal.get("synopsisUrls") or []:
        if s.get("url"):
            items.append((s.get("name") or "Synopsis", s.get("url")))
    for key, label in [
        ("bulletin1Url", "Bulletin-I (record of proceedings)"),
        ("bulletin2Url", "Bulletin-II"),
        ("papersToBeLaidUrl", "Papers To Be Laid"),
    ]:
        d = cal.get(key) or {}
        if isinstance(d, dict) and d.get("url"):
            items.append((d.get("name") or label, d.get("url")))
    return items


def check_daily_documents(state, alerts):
    now = datetime.now(IST)
    qs = f"day={now.day}&month={now.month}&year={now.year}&locale=en"
    seen = set(state.get("seen_docs", []))
    houses = [
        ("Lok Sabha", "\U0001F3DB", get_json(f"/api_ls/ppHome/DailyCalendar?{qs}", {}), _doc_items_ls),
        ("Rajya Sabha", "\U0001F3E0", get_json(f"/api_rs/ppHome/DailyCalendar?{qs}", {}), _doc_items_rs),
    ]
    today_label = now.strftime("%d %b %Y")
    for house, icon, cal, extractor in houses:
        fresh = []
        for name, url in extractor(cal or {}):
            if not url:
                continue
            key = f"{house}|{now.strftime('%Y-%m-%d')}|{name}|{url}"
            if key not in seen:
                seen.add(key)
                fresh.append(f"• <a href='{url}'>{name}</a>")
        if fresh:
            alerts.append(
                f"{icon} <b>{house}</b> — new document(s) for {today_label}:\n"
                + "\n".join(fresh)
            )
    # keep only recent keys so the state file stays small
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    state["seen_docs"] = sorted(
        k for k in seen if k.split("|")[1] >= cutoff
    )


def _bill_fingerprint(b):
    return "|".join(
        str(b.get(k) or "")
        for k in (
            "status",
            "billPassedInLSDate",
            "billPassedInRSDate",
            "billAssentedDate",
            "referredToCommitteeDate",
        )
    )


def check_bills(state, alerts):
    data = get_json(
        "/api_rs/legislation/getBills?billType=Government&page=1&size=30"
        "&locale=en&sortOn=billIntroducedDate&sortBy=desc",
        default={},
    )
    records = (data or {}).get("records") or []
    known = state.get("bills", {})
    first_run = not known
    handled_this_run = set()
    for b in records:
        bid = f"{b.get('billNumber')}/{b.get('billYear')}"
        if bid in handled_this_run:
            continue  # API sometimes returns duplicate rows for one bill
        handled_this_run.add(bid)
        name = (b.get("billName") or "").title()
        fp = _bill_fingerprint(b)
        old = known.get(bid)
        if isinstance(old, str):  # migrate old single-fingerprint format
            old = [old]
        link = b.get("billIntroducedFile") or f"{BASE}/ls/legislation/bills"
        if old is None:
            known[bid] = [fp]
            if not first_run:
                alerts.append(
                    f"\U0001F4DC <b>New Bill introduced</b>: "
                    f"<a href='{link}'>{name}</a>\n"
                    f"House: {b.get('billIntroducedInHouse')} | "
                    f"Ministry: {(b.get('ministryName') or '').title()} | "
                    f"Status: {b.get('status')}"
                )
        elif fp not in old:
            # Only alert on a state this bill has never been seen in before.
            # (sansad.in servers are not always in sync with each other, so a
            # bill can briefly "flip back" to an older status - ignore that.)
            known[bid] = old + [fp]
            alerts.append(
                f"\U0001F4DC <b>Bill status changed</b>: "
                f"<a href='{link}'>{name}</a>\n"
                f"Status: <b>{b.get('status')}</b>"
                + (
                    f" | Passed in LS: {str(b.get('billPassedInLSDate'))[:10]}"
                    if b.get("billPassedInLSDate")
                    else ""
                )
                + (
                    f" | Passed in RS: {str(b.get('billPassedInRSDate'))[:10]}"
                    if b.get("billPassedInRSDate")
                    else ""
                )
            )
    state["bills"] = known
    if first_run and records:
        print(f"Bills baseline stored ({len(records)} bills) - no alerts on first run.")


def check_uncorrected_debates(state, alerts):
    info = current_session(state)
    ls, sess = info["loksabha"], info["session"]
    data = get_json(
        f"/api_ls/debate/uncorrected-session-dates?lsno={ls}&sessionNo={sess}&locale=en",
        default=[],
    )
    seen = set(state.get("seen_debate_dates", []))
    for d in data or []:
        date = d if isinstance(d, str) else json.dumps(d, sort_keys=True)
        if date not in seen:
            seen.add(date)
            alerts.append(
                "\U0001F5E3 <b>Lok Sabha verbatim debate text available</b> "
                f"for {date} — "
                f"<a href='{BASE}/ls/debates/text-of-debates?tab=uncorrected'>read what was said</a>"
            )
    state["seen_debate_dates"] = sorted(seen)[-30:]


def check_rs_latest_updates(state, alerts):
    data = get_json("/api_rs/ppHome/latestUpdates?locale=en", default=[])
    seen = set(state.get("seen_rs_updates", []))
    cutoff = datetime.now(IST) - timedelta(days=3)
    first_run = not seen and bool(data)
    fresh = []
    for item in data or []:
        key = str(item.get("id"))
        if key in seen:
            continue
        seen.add(key)
        if first_run:
            continue  # baseline silently
        start = str(item.get("startDate") or "")[:10]
        try:
            if datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=IST) < cutoff:
                continue  # old item, skip noise
        except ValueError:
            continue  # no usable date - treat as old, never alert on it
        title = item.get("title") or "Update"
        url = item.get("pdfFileUrl") or f"{BASE}/rs"
        fresh.append(f"• <a href='{url}'>{title}</a>")
    if fresh:
        alerts.append("\U0001F3E0 <b>Rajya Sabha</b> — latest updates:\n" + "\n".join(fresh))
    state["seen_rs_updates"] = sorted(seen, key=lambda x: -int(x) if x.isdigit() else 0)[:200]


# ----------------------------------------------------------------- main ----

def main():
    now = datetime.now(IST)
    print(f"Run at {now.strftime('%Y-%m-%d %H:%M IST')}")

    # Outside 08:00-22:00 IST nothing changes - exit quickly to save minutes.
    if not (8 <= now.hour < 22) and "--force" not in sys.argv:
        print("Outside active hours (08:00-22:00 IST), skipping.")
        return

    state = load_state()
    alerts = []

    sitting_today = check_sitting_day(state, alerts)
    check_daily_documents(state, alerts)
    check_bills(state, alerts)
    check_uncorrected_debates(state, alerts)
    check_rs_latest_updates(state, alerts)
    check_live_status(state, alerts, sitting_today)
    maybe_heartbeat(state, alerts, sitting_today)

    print(f"{len(alerts)} alert(s) to send.")
    all_ok = True
    for a in alerts:
        if not send_telegram(a):
            all_ok = False
    if alerts:
        state["last_msg_ts"] = time.time()
    # Save state even on partial failure; a lost alert is better than a
    # stuck one repeating forever.
    save_state(state)
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
