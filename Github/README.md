# HIANIME Website V2.3

This repository contains the Flask website source, AniList-powered anime catalog, and optional Anime-SDK bridge.

## Run locally

1. Install Python 3.10 or newer, Node.js 20 or newer, and XAMPP MySQL if you need accounts or database-backed features.
2. Copy `.env.example` to `.env` and set your own database password and a long random `SECRET_KEY`.
3. Install Python packages with `python -m pip install -r requirements.txt`.
4. Start the website using `start_website.bat` and open `http://127.0.0.1:5000`.

The Anime-SDK dependencies are installed by the startup script the first time it runs. AniList supplies the live catalog and needs an internet connection.

## GitHub and deployment

GitHub stores this source code. GitHub Pages cannot run this Flask server or its MySQL database; deploy the Flask app and database to services that support them if you want a public live site.

## Keep credentials private

- Never commit `.env`, database exports, or uploaded user files.
- `.gitignore` excludes environment secrets, database files, generated media, and `node_modules`.
- Use a unique random `SECRET_KEY` and a database account with only the permissions the app needs.
- If a secret was ever committed, rotate it; deleting it in a later commit does not remove it from Git history.
