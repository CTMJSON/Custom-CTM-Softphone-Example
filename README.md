# Jason's Custom CTM Softphone

A custom web app that embeds the [CallTrackingMetrics](https://www.calltrackingmetrics.com) softphone directly in your browser — no separate phone window, no switching tabs. Everything lives in one place: the phone, your live call log, your text log, and an account assessment report.

---

## What It Does

This app gives you a **desk-mode interface** inspired by CTM's own layout:

| Panel | What's there |
|---|---|
| **Left** | The CTM softphone, embedded and ready to take or make calls |
| **Right** | Live call log and text log pulled from your CTM account, plus a one-click account assessment report |

### Features at a glance

- **Embedded softphone** — logs in automatically using your CTM credentials; no separate popup required
- **Live call log** — shows caller name, phone number, agent, call summary, source, direction, status, and duration
- **Live text log** — shows inbound and outbound SMS activity
- **Click-to-call** — click the ☎ button on any row in the call log to dial that number immediately
- **Auto-refresh** — the activity log refreshes silently every 30 seconds, and instantly after any call ends
- **Account Assessment** — one click generates a full HTML report of your CTM account: routing setup, call performance, KPIs, and operational health
- **Account Assist chat** — built-in AI chat widget powered by CTM

---

## How It Works

This app is built with **Python** ([Flask](https://flask.palletsprojects.com)) and runs on your computer as a local web server. You open it in your browser at `http://localhost:8080`.

It connects to CTM in two ways:

1. **Phone embed** — uses the [CTM Phone Embed web component](https://www.calltrackingmetrics.com/developers/) to load the softphone directly in the page. Your CTM API credentials are used server-side to authenticate the phone session securely.

2. **Call & text data** — fetched from the [CTM REST API](https://www.calltrackingmetrics.com/developers/) using your API key and secret, then displayed in a styled activity log.

Your credentials never leave your machine — all API calls happen on the local server, not in the browser.

---

## Requirements

- A [CallTrackingMetrics](https://www.calltrackingmetrics.com) account with API access
- Python 3.9 or newer
- Your CTM API Key and API Secret (found in CTM under **Settings → API Keys**)

---

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/CTMJSON/Jasons-Custom-CTM-Softphone-Example.git
cd Jasons-Custom-CTM-Softphone-Example
```

**2. Create a virtual environment and install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Configure your credentials**

Copy the example config file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` and set:

```
CTM_API_KEY=your_api_key_here
CTM_API_SECRET=your_api_secret_here
DEFAULT_ACCOUNT_ID=your_account_id_here

# Who the softphone logs in as (skips the login form)
CTM_USER_EMAIL=you@yourcompany.com
CTM_USER_FIRST=Jane
CTM_USER_LAST=Smith

# Generate this with: python3 -c "import secrets; print(secrets.token_hex(32))"
FLASK_SECRET_KEY=replace_with_a_random_string
```

Your **Account ID** is the number in the URL when you're logged into CTM (e.g. `app.calltrackingmetrics.com/accounts/11774/...` → your ID is `11774`).

**4. Start the app**

```bash
source .venv/bin/activate
python app.py
```

Then open your browser to **http://localhost:8080**.

---

## Using the App

1. The softphone loads automatically in the left panel and connects to your CTM account
2. Your recent calls appear in the **Call Log** tab on the right
3. Switch to **Text Log** to see SMS activity
4. Click **☎** on any row to dial that number directly from the softphone
5. Click **Account Assessment** to generate a full report of your CTM account setup and call performance (takes ~30–60 seconds)

---

## CTM Resources

This app is built on top of CTM's public developer platform:

- [CallTrackingMetrics Developer Docs](https://www.calltrackingmetrics.com/developers/) — Phone embed component, REST API, webhooks, and more
- [CTM Phone Embed Guide](https://www.calltrackingmetrics.com/developers/) — How the softphone web component works and what events it exposes
- [CTM API Reference](https://www.calltrackingmetrics.com/developers/) — Full documentation for the calls, messages, and account endpoints used in this app
- [CTM Pricing & Plans](https://www.calltrackingmetrics.com/pricing/) — API access is available on select plans

---

## Security Notes

- Your `.env` file contains sensitive credentials and is excluded from this repo via `.gitignore` — never commit it
- All CTM API calls are made server-side (Python) so your API key and secret are never exposed in the browser
- This app is intended to run locally or on a trusted internal server — it does not include production hardening (rate limiting, HTTPS, etc.)

---

## License

MIT
