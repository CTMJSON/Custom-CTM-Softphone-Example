# Jason's Custom CTM Softphone

<img width="3334" height="1718" alt="image" src="https://github.com/user-attachments/assets/390f31b2-019c-4cb9-8d9d-dfea79726dd5" />

<img width="1706" height="782" alt="Screenshot 2026-04-25 at 9 12 59 PM" src="https://github.com/user-attachments/assets/bc99ffaa-2566-4d46-abe5-1e65abc42c97" />





A custom web app that embeds the [CallTrackingMetrics](https://www.calltrackingmetrics.com) softphone directly in your browser. The goal is a fast proof of concept: clone the repo, run the Flask app, paste your CTM credentials into the setup screen, and see a live workspace without building a separate integration first.

---

## What It Does

This app gives you a **desk-mode interface** inspired by CTM's own layout:

| Panel | What's there |
|---|---|
| **Left** | The CTM softphone, embedded and ready to take or make calls |
| **Right** | Live call log and text log pulled from your CTM account, plus a one-click account assessment report |

### Features at a glance

- **Embedded softphone** — logs in automatically using your CTM credentials; no separate popup required
- **Agent-optimized workspace** — recent-call KPIs, searchable logs, and quick inbound/missed/outbound filters
- **Live call log** — shows caller name, phone number, agent, call summary, source, direction, status, and duration
- **Live text log** — shows inbound and outbound SMS activity
- **Click-to-call** — click the ☎ button on any row in the call log to dial that number immediately
- **Auto-refresh** — the activity log refreshes silently every 30 seconds, and instantly after any call ends
- **Account Assessment** — one click generates a full HTML report of your CTM account: routing setup, call performance, KPIs, and operational health
- **Account Assist chat** — built-in AI chat widget powered by CTM
- **POC-first setup** — no required `.env`; the setup page can remember your last demo values in the browser

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
- Your CTM Account ID (the number in the CTM URL)

---

## Fastest Demo Setup

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

**3. Start the app**

```bash
source .venv/bin/activate
python app.py
```

Then open your browser to **http://localhost:8080** and enter:

- `CTM API Key`
- `CTM API Secret`
- `CTM Account ID` or full CTM account URL
- `Work Email`
- `First Name`
- `Last Name`

That is enough to run the proof of concept.

Your **Account ID** is the number in the URL when you're logged into CTM. Example:

```text
app.calltrackingmetrics.com/accounts/11774/...  ->  account ID = 11774
```

The setup screen can also remember those values in your browser for repeat demos.

### Optional local defaults

If you want the form prefilled for repeat demos, copy `.env.example` to `.env`. This is optional; the app no longer requires it.

---

## Using the App

1. The softphone loads automatically in the left panel and connects to your CTM account.
2. Your recent calls appear in the **Call Log** tab on the right.
3. Switch to **Text Log** to see SMS activity.
4. Click **Call** or **Call Back** to load the number into the embedded CTM phone.
5. Use the header weather card for local conditions based on the machine's public IP, with the configured weather city as a fallback.
6. Use the left-side ops rail to monitor live agent availability and the scrolling weather/news feed.
7. Click **Account Assessment** to generate a full report of your CTM account setup and call performance.
8. Click **Reconfigure demo** in the header any time you want to swap credentials or agent identity.

### CTM Theme Note

The embedded CTM phone follows the CTM user's own light/dark preference. This repo applies best-effort dark-mode hints, but the actual phone theme is still controlled inside CTM rather than through the public phone embed API.

## Best POC Inputs

If you are handing this repo to a sales rep, account manager, or solutions consultant, tell them to gather these values before they start:

- CTM API key
- CTM API secret
- CTM account ID
- A valid agent email
- The first and last name they want shown in the demo

That is the minimum set required to launch the workspace.

Optional but useful:

- CTM chat token if they want the AI chat widget enabled on an account without a fallback token
- A preferred weather city and RSS feed URL for the ops rail and weather fallback

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
