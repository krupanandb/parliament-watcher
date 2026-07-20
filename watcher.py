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
    now = datetime.now(IST)
    today_slash = now.strftime("%d/%m/%Y")
    today_key = now.strftime("%Y-%m-%d")
    if state.get("sitting_alerted") == today_key:
        return
    data = get_json(
        f"/api_ls/ppHome/MonthlyCalendar?month={now.month}&year={now.year}&locale=en",
        default={},
    )
    if today_slash in (data.get("sessionDates") or []):
        alerts.append(
            f"\U0001F3DB <b>Parliament sits today</b> ({now.strftime('%d %b %Y')}).\n"
            "Lok Sabha and Rajya Sabha usually convene at 11:00 AM."
            + LIVE_LINKS
        )
        state["sitting_alerted"] = today_key


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

    check_sitting_day(state, alerts)
    check_daily_documents(state, alerts)
    check_bills(state, alerts)
    check_uncorrected_debates(state, alerts)
    check_rs_latest_updates(state, alerts)

    print(f"{len(alerts)} alert(s) to send.")
    all_ok = True
    for a in alerts:
        if not send_telegram(a):
            all_ok = False
    # Save state even on partial failure; a lost alert is better than a
    # stuck one repeating forever.
    save_state(state)
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
