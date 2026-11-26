# HIANIME Website V2.3

Flask website with an AniList-powered anime catalog and an optional Anime-SDK stream bridge.

## Run locally

1. Install Python 3.10 or newer, Node.js 20 or newer, and XAMPP MySQL if you need database-backed features.
2. Copy `.env.example` to `.env`; set a private database password and a random `SECRET_KEY`.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Start the website with `start_website.bat`, then open `http://127.0.0.1:5000`.

AniList supplies the live anime catalog. The Anime-SDK bridge is optional for streaming features. The app expects the existing HIANIME MySQL tables; it does not create the full database schema automatically.

## GitHub and deployment

GitHub Pages cannot run Flask or connect to MySQL. Use Render (or another Python web service) for the Flask server and TiDB Cloud for MySQL-compatible storage.

### Render + TiDB Cloud

This repository includes a `Procfile` (`web: gunicorn app:app`). On the Render web service, use:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

Set these environment variables in Render from the TiDB Cloud **Connect** dialog:

- `DB_HOST`: TiDB public endpoint
- `DB_PORT`: `4000`
- `DB_NAME`: `hianime`
- `DB_USER`: TiDB username
- `DB_PASSWORD`: TiDB password; enter it only in Render's secret environment field
- `DB_SSL`: `1`
- `DB_SSL_CA`: optional path to TiDB's downloaded CA certificate (the system CA bundle is used if blank)
- `SECRET_KEY`: a long, unique random secret
- `COOKIE_SECURE`: `1`

The app uses TLS and verifies the database server identity whenever `DB_SSL=1`. If TiDB requires a downloaded CA file, upload it as a Render Secret File and set `DB_SSL_CA` to its path. Add the Render service's outbound IP addresses to TiDB Cloud's IP Access List. The personal IP shown in TiDB's connection dialog does not automatically allow Render; do not allow all public IPs.

Confirm the `hianime` database has the existing HIANIME tables before connecting the live service. The code uses the existing schema and does not migrate or initialize the full database automatically.

## Keep credentials private

- Never commit `.env`, database exports, passwords, or uploaded user files.
- Set `DB_PASSWORD` and `SECRET_KEY` only in Render's environment settings.
- If a secret was committed previously, rotate it; deleting it later does not remove it from Git history.