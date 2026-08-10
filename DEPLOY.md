# Deploy to Streamlit Community Cloud (free, no terminal)

This hosts the app at a URL you just visit — no installing, no terminal, ever.
It's free. You do this once; after that, every push to the branch auto-updates
the live site.

## One-time setup (~5 clicks)

1. Go to **https://share.streamlit.io** and click **Sign in with GitHub**
   (use the same GitHub account that owns this repo).
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `drewjhutch-ai/NFL-Model`
   - **Branch:** `claude/nfl-data-matchup-dashboard-hzoeir`
     *(or `main` once this is merged)*
   - **Main file path:** `app.py`
4. Click **Deploy**.

That's it. First build takes a few minutes (it installs everything, including a
headless browser for the coverage scrapers). When it's done you get a URL like
`https://your-app-name.streamlit.app` — bookmark it. That's your dashboard.

## What's already set up for the cloud

- **`requirements.txt`** — all Python packages (pulled automatically).
- **`packages.txt`** — installs `chromium` so the coverage scrapers can read
  JavaScript-rendered stats sites in the cloud.
- **Data** — pulls live from nflverse each hour; the sidebar **Refresh data**
  button forces an update (e.g. after a new game week).

## Adding your PFF data (optional, all in the browser)

No files to move. In the running app's **sidebar**, use **Upload PFF coverage
CSV**: export the team coverage table from PFF (ELITE/+), then drag the CSV in.
It immediately joins the blend. Click **Clear** to remove it. (The free sources
work fine without this.)

## Updating the live app later

Just push to the deployed branch — Streamlit auto-redeploys within a minute.
Nothing else to do.

## If the free scrapers come up empty in the cloud

Coverage still works — upload your PFF CSV (above) and/or check the app logs
(Streamlit Cloud → **Manage app** → logs). Share the log lines and we'll adjust
the scraper. The rest of the dashboard (rankings, matchups, blitz) is unaffected.
