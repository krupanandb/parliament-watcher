# Live Parliament Updates → Telegram

Watches the official Parliament of India website (sansad.in) and sends you an
instant **Telegram message** whenever something new happens:

- 🏛 **Sitting-day alert** each morning Parliament meets, with live TV links
- 📋 **New documents** the moment they are published for the day — List of
  Business (the agenda), Revised/Supplementary lists, Bulletin-I (record of
  what happened), Question lists, Synopsis of debates, Papers laid — for both
  Lok Sabha and Rajya Sabha
- 📜 **Bill alerts** — a new bill is introduced, or a bill's status changes
  (passed in Lok Sabha, passed in Rajya Sabha, assented, withdrawn…)
- 🗣 **Verbatim debate text** as soon as the uncorrected transcript is up
- 🏠 **Rajya Sabha latest updates** (Zero Hour notices etc.)

It runs free on **GitHub Actions** every ~5 minutes from 8 AM to 10 PM IST,
even when your computer is off. Everything it reads is public data.

---

## One-time setup (about 10 minutes)

### Step 1 — Create your Telegram bot (on your phone)

1. Open Telegram and search for **@BotFather** (the official one, blue tick).
2. Send it: `/newbot` and follow the prompts (pick any name, e.g.
   `MyParliamentBot`).
3. BotFather replies with a **token** like `1234567890:AAE-abc...`.
   Keep it — this is `TELEGRAM_BOT_TOKEN`.
4. Now open **your new bot's chat** and press **Start** (send any message).
5. Get your chat id: search for **@userinfobot**, press Start — it replies
   with your numeric **id**. That is `TELEGRAM_CHAT_ID`.

### Step 2 — Put this folder on GitHub

1. Create a free account at github.com if you don't have one.
2. Create a **new repository** (e.g. `parliament-watcher`). **Public** is
   recommended — public repos get unlimited free Actions minutes (the code
   contains no secrets; your token lives in GitHub Secrets, not in the code).
3. Upload this folder's files, or from this folder run:

   ```
   git init
   git add .
   git commit -m "Parliament watcher"
   git branch -M main
   git remote add origin https://github.com/<your-username>/parliament-watcher.git
   git push -u origin main
   ```

### Step 3 — Add your secrets on GitHub

In the repository: **Settings → Secrets and variables → Actions →
New repository secret**. Add both:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | the number from @userinfobot |

### Step 4 — Switch it on

Go to the **Actions** tab → enable workflows → open **Parliament watcher** →
**Run workflow** once to test. You should get your first Telegram messages
within a minute. After that it runs itself every ~5 minutes.

---

## Test on this PC (optional)

```
pip install -r requirements.txt
python watcher.py --force
```

Without the two environment variables set it runs in **dry-run** mode and
prints the alerts instead of sending them.

## Notes

- **First run is quiet on purpose**: it stores a baseline of existing bills
  and updates so you aren't flooded with old news. Alerts start from the
  next change onward.
- `state.json` is the watcher's memory — the workflow commits it back to the
  repository after each run. Don't edit it by hand (delete it to reset).
- GitHub schedules can lag a few minutes at peak times; typical delay from
  "published on sansad.in" to "message on your phone" is 2–10 minutes.
- Active hours are 08:00–22:00 IST (edit the cron in
  `.github/workflows/watch.yml` and the hours check in `watcher.py` to change).
