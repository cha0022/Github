"""Flask application for the HIANIME website.

DEBUG NOTE: Database settings are loaded from .env. Existing MySQL tables are
used as-is so this app does not create or overwrite the user's database schema.
"""
# FLOW NOTE: Loads environment settings, initializes Flask and database helpers, then routes browser requests to page, account, admin, media, and Anime-SDK handlers.

from __future__ import annotations

import os
import re
import secrets
import ssl
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import bcrypt
import click
import pymysql
import requests
from dotenv import load_dotenv
from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, send_from_directory, session, stream_with_context, url_for,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename


APP_ROOT = Path(__file__).resolve().parent
load_dotenv(APP_ROOT / ".env")
configured_media_root = os.getenv("SITE_MEDIA_ROOT")
MEDIA_ROOT = Path(configured_media_root).resolve() if configured_media_root else (APP_ROOT.parent if (APP_ROOT.parent / "images").is_dir() else APP_ROOT)
IS_RENDER = os.getenv("RENDER", "").strip().lower() == "true"
ANIME_SDK_URL = os.getenv("ANIME_SDK_URL", "" if IS_RENDER else "http://127.0.0.1:3000").rstrip("/")
ANIME_SDK_TOKEN = os.getenv("ANIME_SDK_TOKEN", "")
ANIME_SDK_PUBLIC_PROXY_BASE = os.getenv("ANIME_SDK_PUBLIC_PROXY_BASE", "http://127.0.0.1:5000/proxy").rstrip("/")
ANILIST_GRAPHQL_URL = os.getenv("ANILIST_GRAPHQL_URL", "https://graphql.anilist.co").rstrip("/")
_anilist_home_slides = {"items": [], "expires_at": 0.0}
_anilist_alt_art_cache = {}
_anilist_catalog_cache = {}
_anilist_trending_cache = {}
_anilist_schedule_cache = {"expires_at": 0.0, "items": []}
_anilist_letter_page_cache = {}
_sdk_episode_cache = {}

app = Flask(__name__, template_folder="templates")
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=1024 * 1024 * 1024,  # Existing episode files may be large.
)
csrf = CSRFProtect(app)

ALLOWED_ASSET_SUFFIXES = {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".m3u8", ".ts", ".vtt"}
ANIME_STATUSES = ("Ongoing", "Completed", "Upcoming", "Hiatus")


def get_db():
    """Open one database connection per request; close it in teardown below."""
    if "db" not in g:
        connection_options = dict(
            host=os.getenv("DB_HOST", "" if IS_RENDER else "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "4000" if IS_RENDER else "3306")),
            user=os.getenv("DB_USER", "" if IS_RENDER else "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "hianime" if IS_RENDER else "developer_db"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            init_command="SET time_zone = '+00:00'",
            autocommit=False,
        )
        tls_enabled = os.getenv("DB_SSL", "1" if IS_RENDER else "0").strip().lower() in {"1", "true", "yes", "on"}
        if tls_enabled:
            ca_path = os.getenv("DB_SSL_CA", "").strip() or None
            tls_context = ssl.create_default_context(cafile=ca_path)
            tls_context.check_hostname = True
            connection_options["ssl"] = tls_context
        g.db = pymysql.connect(**connection_options)
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def rows(sql, params=()):
    """DEBUG NOTE: Centralize SELECT calls so errors and cursor cleanup stay consistent."""
    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def row(sql, params=()):
    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def change(sql, params=()):
    connection = get_db()
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.lastrowid or cursor.rowcount
    connection.commit()
    return result


def verify_password_hash(candidate: str, stored_hash: str) -> bool:
    """Verify stored bcrypt and Werkzeug password hashes."""
    if not stored_hash:
        return False
    try:
        if stored_hash.startswith(("$2y$", "$2a$", "$2b$")):
            compatible_hash = stored_hash.replace("$2y$", "$2b$", 1).encode("utf-8")
            return bcrypt.checkpw(candidate.encode("utf-8"), compatible_hash)
        return check_password_hash(stored_hash, candidate)
    except (ValueError, TypeError):
        return False


def hash_password(candidate: str) -> str:
    """Create a bcrypt password hash."""
    return bcrypt.hashpw(candidate.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return row("SELECT * FROM users WHERE id=%s LIMIT 1", (user_id,))


def current_admin():
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return row("SELECT * FROM admin WHERE id=%s LIMIT 1", (admin_id,))


@app.context_processor
def shared_navigation_data():
    """Provide the unchanged shared navbar with its border choices and notification baseline."""
    # The standalone admin login has no shared site navbar; keep it available even when MySQL is down.
    if request.endpoint == "admin_login":
        return {"nav_avatar_borders": [], "nav_latest_anime_id": 0}
    border_dir = MEDIA_ROOT / "avatar-borders"
    border_files = sorted(path.name for path in border_dir.glob("*.gif")) if border_dir.is_dir() else []
    try:
        latest = row("SELECT COALESCE(MAX(id),0) AS latest_id FROM anime")
        latest_id = int((latest or {}).get("latest_id") or 0)
    except pymysql.MySQLError:
        app.logger.exception("Hindi nakuha ang latest anime ID para sa shared navigation.")
        latest_id = 0
    return {"nav_avatar_borders": border_files, "nav_latest_anime_id": latest_id}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Mag-login muna para magpatuloy.", "info")
            return redirect(url_for("home", login="1"))
        user = current_user()
        if user is None or account_is_blocked(user):
            if user:
                change("UPDATE users SET status='Offline' WHERE id=%s", (user["id"],))
            session.clear()
            flash(account_restriction_notice(user) if user else "Hindi na magagamit ang account na ito.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        if current_admin() is None:
            session.pop("admin_id", None)
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


@app.template_global("account_is_blocked")
def account_is_blocked(user):
    if not user:
        return False
    if user.get("ban_status") == "Banned":
        until = user.get("ban_until")
        return until is None or until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    return user.get("account_status") == "Deactivated" or user.get("ban_status") == "Blocked"


def account_restriction_notice(user):
    """Explain whether the current account restriction is temporary or permanent."""
    if user and user.get("ban_status") == "Banned":
        until = user.get("ban_until")
        if until:
            if not isinstance(until, datetime):
                return "Pansamantalang naka-block ang account mo kaya hindi mo muna ito magagamit."
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return f"Pansamantalang naka-block ang account mo. Hindi mo ito magagamit hanggang {until.strftime('%b %d, %Y %I:%M %p')} UTC."
        return "Pansamantalang naka-block ang account mo kaya hindi mo muna ito magagamit."
    return "Naka-block ang account mo kaya hindi mo ito magagamit. Makipag-ugnayan sa administrator."


def anime_by_id(anime_id):
    return row("SELECT * FROM anime WHERE id=%s LIMIT 1", (anime_id,))


def shared_anilist_id(anime):
    """Resolve/cache a shared AniList ID from the stored MAL mapping or SDK catalog."""
    try:
        existing = int(anime.get("anilist_id") or 0)
    except (TypeError, ValueError):
        existing = 0
    if existing:
        return existing

    mal_id = int(anime.get("mal_id") or 0)
    if not mal_id and anime.get("id"):
        try:
            mapping = row(
                "SELECT mal_id FROM anime_external_sources WHERE anime_id=%s AND source IN ('tenrai','jikan') ORDER BY source='tenrai' DESC LIMIT 1",
                (anime["id"],),
            )
            mal_id = int((mapping or {}).get("mal_id") or 0)
        except pymysql.MySQLError as error:
            app.logger.debug("MAL mapping lookup unavailable for anime %s: %s", anime.get("id"), error)

    mapped_id = 0
    if mal_id:
        try:
            data = anilist_request("query ($malId:Int){Media(idMal:$malId,type:ANIME){id}}", {"malId": mal_id}, timeout=8)
            mapped_id = int(((data.get("Media") or {}).get("id")) or 0)
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.info("AniList MAL mapping failed for MAL %s: %s", mal_id, error)

    if not mapped_id and anime.get("title"):
        try:
            normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
            wanted_title = normalize(anime["title"])
            data = anilist_request(
                "query ($search:String!){Page(perPage:5){media(search:$search,type:ANIME,isAdult:false){id title{english romaji native}}}}",
                {"search": anime["title"]}, timeout=8,
            )
            matches = (data.get("Page") or {}).get("media") or []
            exact = next((item for item in matches if wanted_title in {
                normalize((item.get("title") or {}).get("english")),
                normalize((item.get("title") or {}).get("romaji")),
                normalize((item.get("title") or {}).get("native")),
            }), None)
            mapped_id = int((exact or {}).get("id") or 0)
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.info("AniList title mapping failed for %s: %s", anime.get("title"), error)

    if mapped_id:
        anime["anilist_id"] = mapped_id
        if anime.get("id"):
            try:
                change("UPDATE anime SET anilist_id=%s WHERE id=%s", (mapped_id, anime["id"]))
            except pymysql.MySQLError as error:
                app.logger.warning("Could not cache AniList ID %s for anime %s: %s", mapped_id, anime.get("id"), error)
    return mapped_id


def shared_mal_id(anime, episode=None):
    """Resolve the Tenrai/MAL id from its saved mapping or linked AniList record."""
    try:
        mal_id = int(anime.get("mal_id") or 0)
    except (TypeError, ValueError):
        mal_id = 0
    if not mal_id and anime.get("id"):
        try:
            mapped = row(
                "SELECT mal_id FROM anime_external_sources WHERE anime_id=%s AND source IN ('tenrai','jikan') "
                "ORDER BY source='tenrai' DESC LIMIT 1",
                (anime["id"],),
            )
            mal_id = int((mapped or {}).get("mal_id") or 0)
        except pymysql.MySQLError as error:
            app.logger.debug("MAL mapping lookup unavailable for anime %s: %s", anime.get("id"), error)
    if not mal_id and episode:
        match = re.match(r"^sdk-(?:tenrai|mal):(\d+)$", str(episode.get("video") or ""), re.I)
        if match:
            mal_id = int(match.group(1))
    if not mal_id and anime.get("anilist_id"):
        try:
            data = anilist_request(
                "query ($id:Int){Media(id:$id,type:ANIME){idMal}}",
                {"id": int(anime["anilist_id"])}, timeout=8,
            )
            mal_id = int(((data.get("Media") or {}).get("idMal")) or 0)
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.info("MAL id lookup failed for anime %s: %s", anime.get("title"), error)
    return mal_id


def sync_anime_genres(anime_id, genre_names):
    """Keep the text genre column and relational genre map in sync."""
    names = list(dict.fromkeys(name.strip() for name in genre_names if name.strip()))
    change("DELETE FROM anime_genre_map WHERE anime_id=%s", (anime_id,))
    for name in names:
        genre = row("SELECT id FROM anime_genres WHERE name=%s LIMIT 1", (name,))
        genre_id = genre["id"] if genre else change("INSERT INTO anime_genres (name) VALUES (%s)", (name,))
        change("INSERT INTO anime_genre_map (anime_id,genre_id) VALUES (%s,%s)", (anime_id, genre_id))


def anime_sections(genre_id=None):
    """Build catalog groups from the existing anime table."""
    if genre_id:
        featured = rows("SELECT DISTINCT a.* FROM anime a JOIN anime_genre_map gm ON gm.anime_id=a.id WHERE a.featured=1 AND gm.genre_id=%s ORDER BY a.featured_order ASC,a.id DESC LIMIT 8", (genre_id,))
        latest = rows("SELECT DISTINCT a.* FROM anime a JOIN anime_genre_map gm ON gm.anime_id=a.id WHERE gm.genre_id=%s ORDER BY a.created_at DESC,a.id DESC LIMIT 24", (genre_id,))
        groups = {
            status.lower(): rows("SELECT DISTINCT a.* FROM anime a JOIN anime_genre_map gm ON gm.anime_id=a.id WHERE a.status=%s AND gm.genre_id=%s ORDER BY a.created_at DESC,a.id DESC LIMIT 18", (status, genre_id))
            for status in ANIME_STATUSES
        }
    else:
        featured = rows("SELECT * FROM anime WHERE featured=1 ORDER BY featured_order ASC, id DESC LIMIT 8")
        latest = rows("SELECT * FROM anime ORDER BY created_at DESC, id DESC LIMIT 24")
        groups = {
            status.lower(): rows("SELECT * FROM anime WHERE status=%s ORDER BY created_at DESC, id DESC LIMIT 18", (status,))
            for status in ANIME_STATUSES
        }
    genres = rows("SELECT id,name FROM anime_genres ORDER BY name ASC")
    return featured, latest, groups, genres


def anilist_request(query, variables=None, timeout=12):
    """Send a bounded GraphQL request to AniList and return its data object."""
    response = requests.post(
        ANILIST_GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "HIANIME/2.3"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError("AniList GraphQL returned an error")
    return payload.get("data") or {}


ANILIST_HERO_FIELDS = "id idMal title { english romaji native } description bannerImage coverImage { extraLarge large } averageScore episodes status startDate { year month day } endDate { year month day } genres"

ANILIST_GENRES = (
    "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy", "Hentai",
    "Horror", "Mahou Shoujo", "Mecha", "Music", "Mystery", "Psychological",
    "Romance", "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller",
)

def anilist_catalog_items(search="", sort="POPULARITY_DESC", genre="", status="", page=1, per_page=12):
    """Search or browse AniList and cache compact catalog rows for the public site."""
    allowed_sorts = {"POPULARITY_DESC", "TRENDING_DESC", "START_DATE_DESC", "END_DATE_DESC", "UPDATED_AT_DESC", "ID_DESC", "TITLE_ROMAJI", "SCORE_DESC", "SEARCH_MATCH"}
    allowed_statuses = {"RELEASING", "FINISHED", "NOT_YET_RELEASED", "HIATUS"}
    sort = sort if sort in allowed_sorts else "POPULARITY_DESC"
    status = status if status in allowed_statuses else ""
    genre = genre if genre in ANILIST_GENRES else ""
    page = max(1, min(int(page or 1), 100))
    per_page = int(per_page or 12)
    per_page = per_page if per_page in {5, 8, 10, 12, 20, 24} else 12
    search = str(search or "").strip()[:100]
    cache_key = (search.casefold(), sort, genre, status, page, per_page)
    cached = _anilist_catalog_cache.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        items, has_next = cached[1], cached[2]
    else:
        # Omit absent optional filters entirely. AniList treats explicit null
        # search/genre/status arguments as restrictive empty filters.
        definitions = ["$page:Int!", "$sort:[MediaSort]"]
        arguments = ["type:ANIME", "sort:$sort", "isAdult:false"]
        variables = {"page": page, "sort": [sort]}
        if search:
            definitions.append("$search:String")
            arguments.append("search:$search")
            variables["search"] = search
        if genre:
            definitions.append("$genres:[String]")
            arguments.append("genre_in:$genres")
            variables["genres"] = [genre]
        if status:
            definitions.append("$status:MediaStatus")
            arguments.append("status:$status")
            variables["status"] = status
        query = (
            f"query ({','.join(definitions)}){{Page(page:$page,perPage:{per_page}){{pageInfo{{hasNextPage}}"
            f"media({','.join(arguments)}){{{ANILIST_HERO_FIELDS}}}}}}}"
        )
        data = anilist_request(query, variables, timeout=15)
        result_page = data.get("Page") or {}
        items = result_page.get("media") or []
        has_next = bool((result_page.get("pageInfo") or {}).get("hasNextPage"))
        _anilist_catalog_cache[cache_key] = (now + 10 * 60, items, has_next)

    return items, has_next


def local_catalog_items(search="", sort="START_DATE_DESC", genre="", status="", limit=12, page=1):
    """Return saved site titles when AniList has no matching or reachable results."""
    clauses, params = [], []
    if search:
        clauses.append("title LIKE %s")
        params.append(f"%{str(search).strip()[:100]}%")
    if genre:
        clauses.append("genres LIKE %s")
        params.append(f"%{genre}%")
    status_map = {"RELEASING": "Ongoing", "FINISHED": "Completed", "NOT_YET_RELEASED": "Upcoming", "HIATUS": "Hiatus"}
    if status in status_map:
        clauses.append("status=%s")
        params.append(status_map[status])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    order = "release_date DESC,id DESC" if sort == "START_DATE_DESC" else "created_at DESC,id DESC"
    limit = max(1, min(int(limit or 12), 24))
    page = max(1, int(page or 1))
    try:
        return rows(
            "SELECT id,anilist_id,title,COALESCE(NULLIF(card_image,''),image) AS image,status,release_date,genres,description "
            "FROM anime" + where + f" ORDER BY {order} LIMIT %s OFFSET %s",
            (*params, limit, (page - 1) * limit),
        )
    except pymysql.MySQLError as error:
        app.logger.info("Local anime fallback unavailable: %s", error)
        return []


def local_catalog_payload(item):
    """Convert one saved TiDB anime row to the card format used by the site."""
    release_date = item.get("release_date")
    year = getattr(release_date, "year", None)
    if year is None and release_date:
        year = str(release_date)[:4]
    genres = [value.strip() for value in str(item.get("genres") or "").split(",") if value.strip()]
    return {
        "id": item.get("id"),
        "anime_id": item.get("id"),
        "anilist_id": item.get("anilist_id"),
        "title": item.get("title") or "Anime",
        "image": item.get("image") or "",
        "image_fallback": item.get("image") or "",
        "status": item.get("status") or "Anime",
        "score": None,
        "year": year,
        "end_year": None,
        "episodes": None,
        "genres": genres,
        "description": re.sub(r"<[^>]*>", " ", str(item.get("description") or "")).strip(),
    }


def local_home_slides(limit=10):
    """Use saved featured titles when AniList cannot provide hero slides."""
    try:
        saved = rows(
            "SELECT id,title,description,anilist_id,"
            "COALESCE(NULLIF(slider_image,''),NULLIF(banner_image,''),NULLIF(card_image,''),image) AS slider_image "
            "FROM anime WHERE featured=1 ORDER BY featured_order ASC,id DESC LIMIT %s",
            (max(1, min(int(limit or 10), 20)),),
        )
    except pymysql.MySQLError as error:
        app.logger.info("TiDB homepage fallback unavailable: %s", error)
        return []
    return [{
        "anilist": False,
        "anime_id": item.get("id"),
        "anilist_id": item.get("anilist_id"),
        "category": "Saved anime",
        "title": item.get("title") or "Anime",
        "description": re.sub(r"<[^>]*>", " ", str(item.get("description") or "")).strip(),
        "slider_image": item.get("slider_image") or "",
        "image_fallbacks": [],
        "score": None,
    } for item in saved]


@app.get("/genre/<path:genre>")
def genre_catalog(genre):
    """Render one dedicated AniList-backed page for the selected genre."""
    genre_names = list(ANILIST_GENRES)
    matched_genre = next((name for name in genre_names if name.casefold() == genre.strip().casefold()), None)
    if not matched_genre:
        abort(404)
    try:
        user = current_user()
    except pymysql.MySQLError:
        user = None
    return render_template("genre.html", user=user, genre=matched_genre, anilist_genres=genre_names)


@app.get("/catalog")
def anilist_catalog_page():
    """Show a paginated AniList collection page for a browse category or letter."""
    categories = {
        "latest": ("Latest Anime", "START_DATE_DESC", ""),
        "episodes": ("Latest Episodes", "UPDATED_AT_DESC", "RELEASING"),
        "trending": ("Trending Anime", "TRENDING_DESC", ""),
        "popular": ("Popular Anime", "POPULARITY_DESC", ""),
        "ongoing": ("Ongoing Anime", "POPULARITY_DESC", "RELEASING"),
        "hiatus": ("Anime on Hiatus", "POPULARITY_DESC", "HIATUS"),
        "upcoming": ("Upcoming Anime", "START_DATE_DESC", "NOT_YET_RELEASED"),
        "completed": ("Completed Anime", "END_DATE_DESC", "FINISHED"),
        "new": ("Recently Added Anime", "ID_DESC", ""),
    }
    category = request.args.get("category", "latest").casefold()
    if category not in categories:
        category = "latest"
    title, sort, status = categories[category]
    letter = request.args.get("letter", "").strip().upper()
    if letter and letter not in {"#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ"}:
        letter = ""
    if letter:
        title = "A–Z Anime" if letter == "#" else f"Anime starting with {letter}"
        sort = "TITLE_ROMAJI"
        status = ""
    try:
        user = current_user()
    except pymysql.MySQLError:
        user = None
    return render_template(
        "catalog.html", user=user, title=title, category=category,
        sort=sort, status=status, letter=letter,
        anilist_genres=list(ANILIST_GENRES),
    )


@app.get("/search")
def anilist_search_page():
    """Show paginated results from AniList for the full public anime library."""
    term = request.args.get("q", "").strip()[:100]
    page = max(1, request.args.get("page", 1, type=int) or 1)
    items, has_next, error = [], False, ""
    if term:
        try:
            found, has_next = anilist_catalog_items(
                search=term, sort="SEARCH_MATCH", page=page, per_page=24,
            )
            for item in found:
                cover = item.get("coverImage") or {}
                titles = item.get("title") or {}
                start_date = item.get("startDate") or {}
                state = item.get("status") or ""
                items.append({
                    "id": item.get("id"),
                    "title": titles.get("english") or titles.get("romaji") or titles.get("native") or "Anime",
                    "image": cover.get("extraLarge") or cover.get("large") or "",
                    "status": "Ongoing" if state == "RELEASING" else "Completed" if state == "FINISHED" else "Upcoming" if state == "NOT_YET_RELEASED" else "Hiatus" if state == "HIATUS" else "Anime",
                    "score": (item.get("averageScore") or 0) / 10 or None,
                    "year": start_date.get("year"),
                    "episodes": item.get("episodes"),
                    "genres": item.get("genres") or [],
                    "description": re.sub(r"<[^>]*>", " ", str(item.get("description") or "")).strip(),
                })
        except (requests.RequestException, ValueError, TypeError) as exc:
            app.logger.info("AniList full search unavailable: %s", exc)
            error = "Hindi makakonekta sa AniList ngayon. Pakisubukang muli."
    try:
        user = current_user()
    except pymysql.MySQLError:
        user = None
    return render_template("search.html", user=user, query=term, items=items, page=page, has_next=has_next, error=error)


def sync_anilist_catalog_item(item):
    """Create or refresh an AniList-backed local row and seed its known episodes."""
    anilist_id = int(item.get("id") or 0)
    titles = item.get("title") or {}
    title = titles.get("english") or titles.get("romaji") or titles.get("native")
    if not anilist_id or not title:
        return None
    cover = item.get("coverImage") or {}
    poster = cover.get("extraLarge") or cover.get("large") or item.get("bannerImage") or ""
    genres = ", ".join(item.get("genres") or [])
    year = (item.get("startDate") or {}).get("year")
    month = (item.get("startDate") or {}).get("month") or 1
    day = (item.get("startDate") or {}).get("day") or 1
    try:
        release_date = datetime(int(year), int(month), int(day)).date() if year else None
    except (TypeError, ValueError):
        release_date = None
    state = str(item.get("status") or "").upper()
    anime_status = "Ongoing" if state == "RELEASING" else "Completed" if state == "FINISHED" else "Upcoming" if state == "NOT_YET_RELEASED" else "Hiatus"
    description = re.sub(r"<[^>]*>", "", str(item.get("description") or ""))
    existing = row("SELECT id FROM anime WHERE anilist_id=%s LIMIT 1", (anilist_id,))
    if existing:
        anime_id = int(existing["id"])
    else:
        anime_id = change(
            "INSERT INTO anime (title,description,image,card_image,slider_image,banner_image,featured,featured_order,genres,status,anilist_id,release_date) "
            "VALUES (%s,%s,%s,%s,NULL,NULL,0,0,%s,%s,%s,%s)",
            (title, description, poster, poster, genres, anime_status, anilist_id, release_date),
        )
    episode_count = min(max(int(item.get("episodes") or 0), 0), 1000)
    if episode_count:
        existing_numbers = {
            int(episode.get("episode_number") or 0)
            for episode in rows("SELECT episode_number FROM episodes WHERE anime_id=%s", (anime_id,))
        }
        missing = [number for number in range(1, episode_count + 1) if number not in existing_numbers]
        if missing:
            connection = get_db()
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO episodes (anime_id,episode_number,video,duration) VALUES (%s,%s,%s,%s)",
                    [(anime_id, number, f"sdk-anilist:{anilist_id}", "") for number in missing],
                )
            connection.commit()
    return anime_id


def anilist_image(media):
    """Prefer AniList's wide banner, then use its largest cover as a last fallback."""
    cover = media.get("coverImage") or {}
    banner = media.get("bannerImage")
    fallback = cover.get("extraLarge") or cover.get("large")
    return banner or fallback, [fallback] if banner and fallback and fallback != banner else []


def get_anilist_home_slides(limit=5):
    """Return cached wide banners mixing AniList trending and fresh releases."""
    now = time.monotonic()
    cached = _anilist_home_slides["items"]
    if now < _anilist_home_slides["expires_at"]:
        return cached[:limit]

    try:
        data = anilist_request(
            f"query {{ trending:Page(page:1,perPage:20){{media(type:ANIME,sort:TRENDING_DESC,isAdult:false){{{ANILIST_HERO_FIELDS}}}}} "
            f"newReleases:Page(page:1,perPage:20){{media(type:ANIME,sort:START_DATE_DESC,status:RELEASING,isAdult:false){{{ANILIST_HERO_FIELDS}}}}} }}",
            timeout=18,
        )
        trending = ((data.get("trending") or {}).get("media") or [])
        new_releases = ((data.get("newReleases") or {}).get("media") or [])
        ranked_items = []
        for index in range(max(len(trending), len(new_releases))):
            if index < len(trending):
                ranked_items.append((trending[index], "Trending"))
            if index < len(new_releases):
                ranked_items.append((new_releases[index], "New Release"))
        slides = []
        used_ids = set()
        for item, category in ranked_items:
            # Hero slides must use AniList's wide banner artwork. A cover poster
            # is not a suitable fallback because it renders as a narrow portrait.
            image = item.get("bannerImage")
            item_id = item.get("id")
            if not image or item_id in used_ids:
                continue
            used_ids.add(item_id)
            title = (item.get("title") or {}).get("english") or (item.get("title") or {}).get("romaji") or "Featured anime"
            slides.append({
                "anilist": True,
                "anilist_id": item_id,
                "mal_id": item.get("idMal"),
                "category": category,
                "title": title,
                "description": re.sub(r"<[^>]*>", "", str(item.get("description") or "Discover this anime from the anime catalog.")),
                "slider_image": image,
                "image_fallbacks": [],
                "score": (item.get("averageScore") or 0) / 10 or None,
            })
        if slides:
            _anilist_home_slides["items"] = slides
            _anilist_home_slides["expires_at"] = now + 6 * 60 * 60
            return slides[:limit]
    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.info("AniList homepage slides unavailable: %s", error)

    _anilist_home_slides["expires_at"] = now + 5 * 60
    return cached[:limit]


def get_anilist_trending(period="day", limit=10):
    """Rank current AniList titles by their daily trend activity over a time window."""
    period = period if period in {"day", "week", "month"} else "day"
    cache = _anilist_trending_cache.get(period)
    now = time.time()
    if cache and cache[0] > now:
        return cache[1][:limit]

    window_days = {"day": 1, "week": 7, "month": 30}[period]
    query = (
        "query {Page(page:1,perPage:25){media(type:ANIME,sort:TRENDING_DESC,isAdult:false){"
        f"{ANILIST_HERO_FIELDS} trending trends(sort:DATE_DESC,page:1,perPage:30){{nodes{{date trending}}}}"
        "}}}"
    )
    data = anilist_request(query, timeout=20)
    cutoff = int(now - window_days * 86400)
    items = []
    for item in (data.get("Page") or {}).get("media") or []:
        trend_nodes = ((item.get("trends") or {}).get("nodes") or [])
        trend_score = sum(
            int(node.get("trending") or 0)
            for node in trend_nodes
            if int(node.get("date") or 0) >= cutoff
        )
        # Keep the panel populated from AniList if this selected history window
        # has no points yet; this remains AniList data, never local catalog data.
        if not trend_score:
            trend_score = int(item.get("trending") or 0)
        if not trend_score:
            continue
        titles = item.get("title") or {}
        cover = item.get("coverImage") or {}
        start_date = item.get("startDate") or {}
        status = item.get("status") or ""
        items.append({
            "id": item.get("id"),
            "anilist_id": item.get("id"),
            "title": titles.get("english") or titles.get("romaji") or titles.get("native") or "Anime",
            "image": cover.get("extraLarge") or cover.get("large") or "",
            "image_fallback": cover.get("large") or "",
            "banner": item.get("bannerImage") or "",
            "status": "Ongoing" if status == "RELEASING" else "Completed" if status == "FINISHED" else "Upcoming" if status == "NOT_YET_RELEASED" else "Hiatus" if status == "HIATUS" else "Anime",
            "score": (item.get("averageScore") or 0) / 10 or None,
            "year": start_date.get("year"),
            "episodes": item.get("episodes"),
            "trend_score": trend_score,
        })
    items.sort(key=lambda anime: (anime["trend_score"], anime.get("score") or 0), reverse=True)
    _anilist_trending_cache[period] = (now + 10 * 60, items)
    return items[:limit]


def get_anilist_schedule(limit=50):
    """Return a short-lived cache of upcoming AniList airing schedule entries."""
    now = time.time()
    if _anilist_schedule_cache["expires_at"] > now:
        return _anilist_schedule_cache["items"][:limit]
    query = (
        "query {Page(page:1,perPage:50){airingSchedules(notYetAired:true,sort:TIME){"
        "id airingAt episode media{id title{english romaji native} coverImage{extraLarge large} status}"
        "}}}"
    )
    data = anilist_request(query, timeout=18)
    latest_time = int(now + 7 * 86400)
    entries = []
    for item in (data.get("Page") or {}).get("airingSchedules") or []:
        if int(item.get("airingAt") or 0) > latest_time:
            continue
        media = item.get("media") or {}
        title_data = media.get("title") or {}
        cover = media.get("coverImage") or {}
        entries.append({
            "anilist_id": media.get("id"),
            "title": title_data.get("english") or title_data.get("romaji") or title_data.get("native") or "Anime",
            "image": cover.get("large") or cover.get("extraLarge") or "",
            "status": media.get("status") or "",
            "episode": item.get("episode"),
            "airing_at": item.get("airingAt"),
        })
    entries.sort(key=lambda entry: entry["airing_at"] or 0)
    _anilist_schedule_cache.update(expires_at=now + 10 * 60, items=entries)
    return entries[:limit]


def anilist_letter_catalog(letter, page=1, per_page=24):
    """Page through the AniList title-sorted library at an A–Z boundary."""
    letter = letter if letter in {"#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ"} else "A"
    def sort_rank(value):
        return ord(value) - 64 if value in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else 0

    cache = _anilist_letter_page_cache.get(letter)
    now = time.monotonic()
    if cache and cache[0] > now:
        first_page, last_page = cache[1], cache[2]
    else:
        target_rank = sort_rank(letter)
        info_query = (
            "query($page:Int!){Page(page:$page,perPage:24){pageInfo{lastPage}"
            "media(type:ANIME,sort:TITLE_ROMAJI,isAdult:false){title{romaji english native}}}}"
        )

        def page_titles(page_number):
            result = anilist_request(info_query, {"page": page_number}, timeout=15)
            listing = result.get("Page") or {}
            titles = listing.get("media") or []
            first = ""
            if titles:
                title_data = titles[0].get("title") or {}
                raw_title = title_data.get("romaji") or title_data.get("english") or title_data.get("native") or ""
                first = raw_title.strip()[:1].upper()
            return int((listing.get("pageInfo") or {}).get("lastPage") or 1), sort_rank(first)

        last_page, _ = page_titles(1)
        low, high, first_page = 1, last_page, last_page
        while low <= high:
            middle = (low + high) // 2
            _, first_rank = page_titles(middle)
            if first_rank >= target_rank:
                first_page = middle
                high = middle - 1
            else:
                low = middle + 1
        _anilist_letter_page_cache[letter] = (now + 6 * 60 * 60, first_page, last_page)

    raw_page = min(last_page, first_page + max(0, int(page or 1) - 1))
    query = (
        f"query($page:Int!){{Page(page:$page,perPage:{max(8, min(int(per_page or 24), 24))}){{pageInfo{{hasNextPage}}"
        f"media(type:ANIME,sort:TITLE_ROMAJI,isAdult:false){{{ANILIST_HERO_FIELDS}}}}}}}"
    )
    data = anilist_request(query, {"page": raw_page}, timeout=18)
    result_page = data.get("Page") or {}
    raw_items = result_page.get("media") or []
    def initial_matches(item):
        titles = item.get("title") or {}
        value = (titles.get("romaji") or titles.get("english") or titles.get("native") or "").strip()[:1].upper()
        is_numeric_group = not value or value not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return is_numeric_group if letter == "#" else value == letter
    items = [item for item in raw_items if initial_matches(item)]
    last_titles = raw_items[-1].get("title") or {} if raw_items else {}
    last_initial = (last_titles.get("romaji") or last_titles.get("english") or last_titles.get("native") or "").strip()[:1].upper()
    last_rank = ord(last_initial) - 64 if last_initial in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else 0
    has_next = bool((result_page.get("pageInfo") or {}).get("hasNextPage")) and (letter == "#" or last_rank <= sort_rank(letter))
    return items, has_next


def _art_image_key(value):
    if not value:
        return ""
    return Path(urlparse(str(value)).path).name.casefold()


def get_anilist_alternate_art(anime, anilist_slides):
    """Find AniList banner art for a catalog title that has no separate hero image."""
    poster_keys = {
        _art_image_key(anime.get(key))
        for key in ("image", "card_image", "slider_image", "banner_image")
        if anime.get(key)
    }
    title_key = re.sub(r"[^a-z0-9]+", " ", str(anime.get("title") or "").casefold()).strip()
    for slide in anilist_slides:
        slide_key = re.sub(r"[^a-z0-9]+", " ", str(slide.get("title") or "").casefold()).strip()
        if title_key and title_key == slide_key and _art_image_key(slide.get("slider_image")) not in poster_keys:
            return slide.get("slider_image")

    anilist_id = int(anime.get("anilist_id") or 0)
    if not anilist_id and anime.get("id"):
        try:
            mapped = row("SELECT mal_id FROM anime_external_sources WHERE anime_id=%s AND source='jikan' LIMIT 1", (anime["id"],))
            mal_id = int((mapped or {}).get("mal_id") or 0)
            if mal_id:
                data = anilist_request("query ($mal:Int){Media(idMal:$mal,type:ANIME){id}}", {"mal": mal_id}, timeout=6)
                anilist_id = int(((data.get("Media") or {}).get("id")) or 0)
        except (pymysql.MySQLError, requests.RequestException, ValueError, TypeError) as error:
            app.logger.debug("AniList ID mapping unavailable for anime %s: %s", anime.get("id"), error)

    if not anilist_id and anime.get("title"):
        try:
            data = anilist_request(
                "query ($search:String!){Page(perPage:5){media(search:$search,type:ANIME,isAdult:false){id title{english romaji native}}}}",
                {"search": anime["title"]}, timeout=8,
            )
            normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
            match = next((item for item in ((data.get("Page") or {}).get("media") or []) if title_key in {
                normalize((item.get("title") or {}).get("english")), normalize((item.get("title") or {}).get("romaji")), normalize((item.get("title") or {}).get("native")),
            }), None)
            anilist_id = int((match or {}).get("id") or 0)
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.info("AniList title lookup for hero art failed (%s): %s", anime.get("title"), error)

    if not anilist_id:
        return None
    cached = _anilist_alt_art_cache.get(anilist_id)
    if cached and cached[0] > time.monotonic():
        return cached[1] if _art_image_key(cached[1]) not in poster_keys else None

    try:
        data = anilist_request(
            f"query ($id:Int){{Media(id:$id,type:ANIME){{{ANILIST_HERO_FIELDS}}}}}",
            {"id": anilist_id}, timeout=8,
        )
        item = data.get("Media") or {}
        image, _fallbacks = anilist_image(item)
        if image and _art_image_key(image) not in poster_keys:
            _anilist_alt_art_cache[anilist_id] = (time.monotonic() + 6 * 60 * 60, image)
            anime["anilist_id"] = anilist_id
            if anime.get("id"):
                try:
                    change("UPDATE anime SET anilist_id=%s WHERE id=%s", (anilist_id, anime["id"]))
                except pymysql.MySQLError:
                    pass
            return image
    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.info("AniList alternate art unavailable for AniList %s: %s", anilist_id, error)
    _anilist_alt_art_cache[anilist_id] = (time.monotonic() + 15 * 60, None)
    return None


def get_episode_skip(episode, anime):
    """Use saved ranges when available, then fetch AniSkip ranges for saved or SDK episodes."""
    episode_id = int(episode.get("id") or 0)
    manual = row(
        "SELECT intro_start,intro_end,outro_start,outro_end FROM episode_skip_segments WHERE episode_id=%s",
        (episode_id,),
    ) if episode_id else None
    if manual and any(manual.get(key) is not None for key in ("intro_start", "intro_end", "outro_start", "outro_end")):
        return manual
    cached = row("SELECT * FROM episode_skip_api_cache WHERE episode_id=%s", (episode_id,)) if episode_id else None
    cached_has_ranges = cached and any(
        cached.get(key) is not None
        for key in ("intro_start", "intro_end", "outro_start", "outro_end")
    )
    # A previous lookup may have run before the MAL mapping was available.
    # Only trust an empty cache when it records which MAL ID was checked.
    if cached and cached.get("checked_at") and (cached_has_ranges or cached.get("mal_id")):
        return cached
    metadata = {}
    if anime.get("anilist_id"):
        try:
            metadata = anilist_request(
                "query ($id:Int){Media(id:$id,type:ANIME){idMal duration}}",
                {"id": int(anime["anilist_id"])}, timeout=4,
            ).get("Media") or {}
        except (requests.RequestException, ValueError):
            metadata = {}
    mal_id = int(anime.get("mal_id") or 0)
    episode_video = str(episode.get("video") or "")
    sdk_mal_match = re.match(r"^sdk-mal:(\d+)$", episode_video, re.I)
    if not mal_id and sdk_mal_match:
        mal_id = int(sdk_mal_match.group(1))
    if not mal_id and anime.get("id"):
        try:
            mapping = row(
                "SELECT mal_id FROM anime_external_sources WHERE anime_id=%s AND source='jikan' LIMIT 1",
                (anime["id"],),
            )
            mal_id = int((mapping or {}).get("mal_id") or 0)
        except pymysql.MySQLError as error:
            app.logger.debug("MAL skip-time mapping unavailable for anime %s: %s", anime.get("id"), error)
    mal_id = mal_id or int(metadata.get("idMal") or 0)
    duration = float(metadata.get("duration") or 0) * 60
    found = {"intro_start": None, "intro_end": None, "outro_start": None, "outro_end": None}
    if mal_id:
        try:
            response = requests.get(
                f"https://api.aniskip.com/v2/skip-times/{mal_id}/{int(episode['episode_number'])}",
                params={"episodeLength": duration, "types": ["op", "ed", "mixed-op", "mixed-ed"]},
                timeout=4,
            )
            payload = response.json() if response.ok else {}
            for item in payload.get("results", []):
                interval = item.get("interval") or {}
                start, end = interval.get("startTime"), interval.get("endTime")
                kind = str(item.get("skipType", "")).lower()
                if start is None or end is None or float(end) <= float(start):
                    continue
                key = "intro" if kind in ("op", "mixed-op") else "outro" if kind in ("ed", "mixed-ed") else None
                if key and found[key + "_start"] is None:
                    found[key + "_start"], found[key + "_end"] = float(start), float(end)
        except (requests.RequestException, ValueError, TypeError):
            pass
    if episode_id:
        try:
            change(
                "INSERT INTO episode_skip_api_cache (episode_id,mal_id,intro_start,intro_end,outro_start,outro_end) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE mal_id=VALUES(mal_id),intro_start=VALUES(intro_start),intro_end=VALUES(intro_end),outro_start=VALUES(outro_start),outro_end=VALUES(outro_end),checked_at=CURRENT_TIMESTAMP",
                (episode_id, mal_id or None, found["intro_start"], found["intro_end"], found["outro_start"], found["outro_end"]),
            )
        except pymysql.MySQLError:
            app.logger.exception("Hindi naisulat ang AniSkip cache.")
    return found


def resolve_site_asset(relative_path):
    """Serve only browser-safe files from the configured site media folder."""
    safe_path = Path(relative_path)
    if safe_path.is_absolute() or ".." in safe_path.parts or safe_path.suffix.lower() not in ALLOWED_ASSET_SUFFIXES:
        abort(404)
    target = (MEDIA_ROOT / safe_path).resolve()
    if MEDIA_ROOT not in target.parents or not target.is_file():
        abort(404)
    return send_from_directory(target.parent, target.name)


@app.template_global("media_url")
def media_url(value):
    """Keep external media URLs working; serve local media through the safe allowlist."""
    path = str(value or "").strip()
    if path.startswith(("https://", "http://")):
        return path
    return url_for("site_asset", asset_path=path)


def anime_sdk_get(path, params=None, timeout=35):
    """Call the optional local Node HTTP bridge for anime-sdk."""
    headers = {"Authorization": f"Bearer {ANIME_SDK_TOKEN}"} if ANIME_SDK_TOKEN else {}
    response = requests.get(f"{ANIME_SDK_URL}/{path.lstrip('/')}", params=params or {}, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def localize_sdk_proxy_urls(value):
    """Keep SDK proxy links same-origin when Flask runs on a non-default port."""
    local_proxy = f"{request.host_url.rstrip('/')}/proxy"
    proxy_bases = {ANIME_SDK_PUBLIC_PROXY_BASE, "http://127.0.0.1:5000/proxy"}
    if isinstance(value, str):
        for base in proxy_bases:
            value = value.replace(base, local_proxy)
        return value
    if isinstance(value, list):
        return [localize_sdk_proxy_urls(item) for item in value]
    if isinstance(value, dict):
        return {key: localize_sdk_proxy_urls(item) for key, item in value.items()}
    return value


def resolve_sdk_episode_stream(title, episode_number, language="sub", preferred_provider="animeparadise", anilist_id=None, unit_id=None):
    """Find the matching episode and resolve it directly through working SDK providers."""
    if not title:
        return "", ""
    if unit_id and preferred_provider in {"animeparadise", "megaplay"}:
        try:
            payload = anime_sdk_get(
                "stream", {"provider": preferred_provider, "unitId": unit_id, "language": language}, timeout=18
            )
            streams = payload.get("streams") or []
            if payload.get("type") == "video" and streams and streams[0].get("sourceUrl"):
                return (
                    localize_sdk_proxy_urls(streams[0]["sourceUrl"]), preferred_provider,
                    localize_sdk_proxy_urls(streams[0].get("subtitles") or []),
                )
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.warning("Anime-SDK %s unit %s failed: %s", preferred_provider, unit_id, error)
        return "", "", []
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    wanted_title = normalize(title)
    # DEBUG NOTE: AnimeParadise currently resolves playable HLS for indexed titles;
    # remaining providers are fallbacks in case that catalog has no exact match.
    providers = [preferred_provider, "animeparadise", "megaplay"]
    for provider in dict.fromkeys(item for item in providers if item in {"animeparadise", "megaplay"}):
        episode = None
        try:
            search_items = anime_sdk_get("search", {"q": title, "provider": provider}, timeout=12)
            exact_matches = [item for item in search_items if normalize(item.get("title")) == wanted_title]
            if not exact_matches:
                continue
            for match in exact_matches[:2]:
                episodes = anime_sdk_get(
                    "content", {"provider": provider, "mediaId": match.get("id", "")}, timeout=12
                )
                episode = next(
                    (item for item in episodes if int(item.get("number") or 0) == int(episode_number)),
                    None,
                )
                if not episode:
                    continue
                available_languages = [str(item).lower() for item in (episode.get("availableLanguages") or [])]
                if available_languages and language not in available_languages:
                    app.logger.info(
                        "Skipping %s episode %s via %s: %s is unavailable",
                        title, episode_number, provider, language,
                    )
                    continue
                payload = anime_sdk_get(
                    "stream",
                    {"provider": provider, "unitId": episode.get("id", ""), "language": language},
                    timeout=18,
                )
                streams = payload.get("streams") or []
                if payload.get("type") == "video" and streams:
                    source_url = streams[0].get("sourceUrl", "")
                    if source_url:
                        source_url = localize_sdk_proxy_urls(source_url)
                        subtitles = localize_sdk_proxy_urls(streams[0].get("subtitles") or [])
                        app.logger.info(
                            "Resolved %s episode %s through Anime-SDK provider %s",
                            title, episode_number, provider,
                        )
                        return source_url, provider, subtitles
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.warning("Anime-SDK %s fallback failed for %s episode %s: %s", provider, title, episode_number, error)
    return "", "", []


def fetch_sdk_episode_units(title, preferred_provider="animeparadise"):
    """Merge actually available episode units across working stream providers."""
    if not title:
        return [], ""
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    wanted_title = normalize(title)
    cache_key = (wanted_title, preferred_provider)
    cached = _sdk_episode_cache.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1], cached[2]
    providers = [preferred_provider, "animeparadise", "megaplay"]
    allowed = {"animeparadise", "megaplay"}
    merged = {}
    providers_used = []
    for provider in dict.fromkeys(item for item in providers if item in allowed):
        try:
            matches = anime_sdk_get("search", {"q": title, "provider": provider}, timeout=12)
            exact_matches = [item for item in matches if normalize(item.get("title")) == wanted_title]
            for match in exact_matches[:2]:
                units = anime_sdk_get(
                    "content", {"provider": provider, "mediaId": match.get("id", "")}, timeout=12
                )
                numbered = [
                    unit for unit in units
                    if str(unit.get("number", "")).isdigit() and int(unit.get("number") or 0) > 0
                ]
                if numbered:
                    providers_used.append(provider)
                    for unit in numbered:
                        number = int(unit["number"])
                        # Keep the preferred provider's ID when both sources have
                        # the same episode; use the other source only to fill gaps.
                        merged.setdefault(number, {**unit, "number": number, "provider": provider})
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.warning("Anime-SDK catalog lookup failed for %s via %s: %s", title, provider, error)
    if merged:
        app.logger.info("Loaded %s merged SDK episodes for %s", len(merged), title)
        selected_provider = preferred_provider if preferred_provider in providers_used else providers_used[0]
        result = [merged[number] for number in sorted(merged)]
        _sdk_episode_cache[cache_key] = (now + 5 * 60, result, selected_provider)
        return result, selected_provider
    return [], ""


def ensure_anime_source_table():
    """Create the external metadata mapping table needed for imported catalog titles."""
    change(
        "CREATE TABLE IF NOT EXISTS anime_external_sources ("
        "anime_id INT NOT NULL, source VARCHAR(32) NOT NULL, mal_id INT NOT NULL, "
        "PRIMARY KEY (anime_id,source), UNIQUE KEY uq_anime_external_source (source,mal_id))"
    )


@app.get("/site-assets/<path:asset_path>")
def site_asset(asset_path):
    return resolve_site_asset(asset_path)


@app.get("/")
def index():
    term = request.args.get("search", "").strip()
    if term:
        return redirect(url_for("anilist_search_page", q=term))
    # FLOW NOTE: Send the site root to the AniList-backed homepage; the legacy
    # database-only landing page made the default URL fail whenever XAMPP was off.
    return redirect(url_for("home"))


@app.route("/home", methods=["GET", "POST"])
def home():
    # API endpoints used by the old shared navbar/search widget.
    api_action = request.args.get("user_api")
    if api_action == "search":
        term = request.args.get("q", "").strip()
        kind = request.args.get("kind", "anime")
        if not term:
            return jsonify(items=[])
        if kind == "users":
            try:
                found = rows("SELECT username,profile_picture FROM users WHERE username LIKE %s ORDER BY username ASC LIMIT 10", (f"%{term}%",))
            except pymysql.MySQLError:
                found = []
            return jsonify(items=[{"type": "user", "name": x["username"], "image": media_url(x.get("profile_picture") or "images/default-avatar.png")} for x in found])
        status = request.args.get("status", "")
        status_map = {"Ongoing": "RELEASING", "Completed": "FINISHED", "Upcoming": "NOT_YET_RELEASED", "Hiatus": "HIATUS"}
        try:
            found, has_next = anilist_catalog_items(
                search=term, sort="SEARCH_MATCH", status=status_map.get(status, ""), page=1, per_page=20,
            )
            search_results = []
            for item in found:
                titles = item.get("title") or {}
                search_results.append({
                    "type": "anime", "id": item.get("id"), "anilist_id": item.get("id"),
                    "title": titles.get("english") or titles.get("romaji") or titles.get("native") or "Anime",
                    "image": ((item.get("coverImage") or {}).get("large") or (item.get("coverImage") or {}).get("extraLarge") or ""),
                })
            return jsonify(items=search_results, has_next=has_next, source="AniList")
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.info("AniList header search unavailable: %s", error)
            return jsonify(items=[], error="Hindi maabot ang AniList ngayon. Pakisubukang muli.", source="AniList"), 503
    if api_action == "new_anime":
        since = max(0, request.args.get("since", 0, type=int))
        found = rows("SELECT id,title FROM anime WHERE id>%s ORDER BY id ASC LIMIT 10", (since,))
        return jsonify(items=found)
    if api_action:
        return jsonify(items=[], error="Unknown API request."), 400

    if request.method == "POST":
        if "login" in request.form:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = row("SELECT * FROM users WHERE username=%s LIMIT 1", (username,))
            if user and verify_password_hash(password, user.get("password", "")):
                if account_is_blocked(user):
                    flash(account_restriction_notice(user), "error")
                else:
                    session.clear()
                    session["user_id"] = user["id"]
                    session["username"] = user["username"]
                    change("UPDATE users SET status='Online' WHERE id=%s", (user["id"],))
                    return redirect(url_for("home"))
            else:
                flash("Hindi tugma ang username o password.", "error")
        elif "register" in request.form:
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            confirm_email = request.form.get("confirm_email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            if len(username) < 3:
                flash("Dapat hindi bababa sa 3 character ang username.", "error")
            elif email != confirm_email:
                flash("Hindi magkapareho ang email.", "error")
            elif password != confirm:
                flash("Hindi magkapareho ang password.", "error")
            elif not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{9,}$", password):
                flash("Kailangan ng 9+ character na may malaking/maliit na letra, numero, at simbolo.", "error")
            elif row("SELECT id FROM users WHERE username=%s OR email=%s LIMIT 1", (username, email)):
                flash("May account na gamit ang username o email na iyan.", "error")
            else:
                new_id = change(
                    "INSERT INTO users (username,email,password,status,profile_picture,account_status,ban_status,avatar_border) "
                    "VALUES (%s,%s,%s,'Online','images/default-avatar.png','Active','Active','normal-01.gif')",
                    (username, email, hash_password(password)),
                )
                session.clear()
                session["user_id"] = new_id
                session["username"] = username
                flash("Nagawa na ang account mo.", "success")
                return redirect(url_for("home"))

    # The live catalogue and hero do not depend on local catalog rows. Keep the
    # homepage available if XAMPP/MySQL is stopped; account/history features then
    # simply stay empty until the database is back.
    featured, user, continue_watching = [], None, []
    try:
        featured = rows("SELECT * FROM anime WHERE featured=1 ORDER BY featured_order ASC,id DESC LIMIT 8")
        user = current_user()
        if user:
            continue_watching = rows(
                "SELECT a.id,a.title,a.description,a.image,a.card_image,a.status,e.episode_number,wh.progress,wh.watch_time "
                "FROM watch_history wh JOIN anime a ON a.id=wh.anime_id JOIN episodes e ON e.id=wh.episode_id "
                "WHERE wh.user_id=%s ORDER BY wh.updated_at DESC LIMIT 6",
                (user["id"],),
            )
    except pymysql.MySQLError as error:
        app.logger.info("Rendering live anime homepage without local database data: %s", error)
    homepage_slides = get_anilist_home_slides(limit=10)
    return render_template("home.html", user=user, featured=featured, homepage_slides=homepage_slides, genres=[], selected_genre=None, anilist_genres=list(ANILIST_GENRES), continue_watching=continue_watching)


@app.get("/watch")
@app.get("/watch_episode")
def watch_episode():
    anime_id = request.args.get("anime_id", type=int)
    requested_anilist_id = request.args.get("anilist_id", type=int)
    episode_number = request.args.get("episode", 1, type=int)
    anime = anime_by_id(anime_id) if anime_id else None
    if anime is None and requested_anilist_id:
        try:
            existing = row("SELECT id FROM anime WHERE anilist_id=%s LIMIT 1", (requested_anilist_id,))
            anime_id = int(existing["id"]) if existing else None
            anime = anime_by_id(anime_id) if anime_id else None
            # Local TiDB fallback cards can carry a local primary key when no
            # AniList mapping exists. Resolve that ID locally before asking AniList.
            if anime is None:
                local = anime_by_id(requested_anilist_id)
                if local and not local.get("anilist_id"):
                    anime_id = requested_anilist_id
                    anime = local
            if anime is None:
                # If this ID was just displayed from AniList, reuse the cached
                # catalog record instead of making a second network request.
                # This keeps the detail page working when AniList rate-limits
                # the follow-up request from the hosting server.
                media = None
                now = time.monotonic()
                for expires_at, cached_items, _has_next in _anilist_catalog_cache.values():
                    if expires_at <= now:
                        continue
                    media = next(
                        (item for item in cached_items if int(item.get("id") or 0) == requested_anilist_id),
                        None,
                    )
                    if media:
                        break
                if media is None:
                    # Trending cards use a compact cache shape, so adapt the
                    # cached title/artwork into the fields needed by the watch page.
                    for expires_at, cached_items in _anilist_trending_cache.values():
                        if expires_at <= time.time():
                            continue
                        cached = next(
                            (item for item in cached_items if int(item.get("anilist_id") or item.get("id") or 0) == requested_anilist_id),
                            None,
                        )
                        if cached:
                            state = {"Ongoing": "RELEASING", "Completed": "FINISHED", "Upcoming": "NOT_YET_RELEASED", "Hiatus": "HIATUS"}.get(cached.get("status"), "RELEASING")
                            media = {
                                "id": requested_anilist_id,
                                "title": {"english": cached.get("title")},
                                "description": "",
                                "coverImage": {"extraLarge": cached.get("image"), "large": cached.get("image_fallback") or cached.get("image")},
                                "bannerImage": cached.get("banner") or "",
                                "genres": [],
                                "status": state,
                                "episodes": cached.get("episodes"),
                                "startDate": {"year": cached.get("year")},
                            }
                            break
                if media is None:
                    result = anilist_request(
                        f"query ($id:Int!){{Media(id:$id,type:ANIME){{{ANILIST_HERO_FIELDS}}}}}",
                        {"id": requested_anilist_id}, timeout=12,
                    )
                    media = result.get("Media")
                if media:
                    titles = media.get("title") or {}
                    cover = media.get("coverImage") or {}
                    start_date = media.get("startDate") or {}
                    state = str(media.get("status") or "").upper()
                    anime_id = 0
                    anime = {
                        "id": 0,
                        "anilist_id": int(media.get("id") or requested_anilist_id),
                        "title": titles.get("english") or titles.get("romaji") or titles.get("native") or "Anime",
                        "description": re.sub(r"<[^>]*>", "", str(media.get("description") or "")),
                        "image": cover.get("extraLarge") or cover.get("large") or media.get("bannerImage") or "",
                        "card_image": cover.get("extraLarge") or cover.get("large") or "",
                        "slider_image": media.get("bannerImage") or "",
                        "banner_image": media.get("bannerImage") or "",
                        "genres": ", ".join(media.get("genres") or []),
                        "status": "Ongoing" if state == "RELEASING" else "Completed" if state == "FINISHED" else "Upcoming" if state == "NOT_YET_RELEASED" else "Hiatus",
                        "release_date": start_date.get("year"),
                    }
        except (pymysql.MySQLError, requests.RequestException, ValueError, TypeError) as error:
            app.logger.info("Could not open AniList title %s: %s", requested_anilist_id, error)
    if anime is None:
        flash("Hindi makita ang anime na iyon.", "error")
        return redirect(url_for("home"))
    episodes = rows(
        "SELECT * FROM episodes WHERE anime_id=%s "
        "AND COALESCE(video,'') NOT LIKE 'sdk-tenrai:%%' AND COALESCE(video,'') NOT LIKE 'sdk-anilist:%%' "
        "ORDER BY episode_number ASC",
        (anime_id,),
    ) if anime_id else []
    source = request.args.get("source", "").lower()
    server = request.args.get("server", "sub").lower()
    sdk_providers = {"animeparadise", "megaplay"}
    direct_providers = {"vidrift"}
    if source not in (sdk_providers | direct_providers):
        source = ""
    requested_source = source
    sdk_catalog_anime = False
    sdk_units, catalog_provider = fetch_sdk_episode_units(
        anime.get("title", ""), source if source in sdk_providers else "animeparadise"
    )
    if sdk_units:
        sdk_episodes = [{
            "id": 0,
            "anime_id": anime_id,
            "episode_number": int(unit["number"]),
            "title": unit.get("title") or unit.get("name") or "",
            "video": f"sdk-catalog:{unit.get('provider', catalog_provider)}:{unit.get('id', '')}",
        } for unit in sdk_units]
        if source in sdk_providers or not episodes:
            episodes = sdk_episodes
            sdk_catalog_anime = True
            source = catalog_provider
        else:
            present_numbers = {int(item.get("episode_number") or 0) for item in episodes}
            episodes.extend(item for item in sdk_episodes if item["episode_number"] not in present_numbers)
            episodes.sort(key=lambda item: int(item.get("episode_number") or 0))
    episode = next((item for item in episodes if item["episode_number"] == episode_number), None)
    if episode is None and "episode" not in request.args and episodes:
        episode = episodes[0]
    episode_index = next((index for index, item in enumerate(episodes) if episode and item["episode_number"] == episode["episode_number"]), -1)
    previous_episode = episodes[episode_index - 1] if episode_index > 0 else None
    next_episode = episodes[episode_index + 1] if episode_index >= 0 and episode_index + 1 < len(episodes) else None
    video_url = (episode.get("video") or "").strip() if episode else ""
    sdk_mal_id = video_url.removeprefix("sdk-mal:") if video_url.startswith("sdk-mal:") else ""
    sdk_unit_match = re.match(r"^sdk-catalog:([^:]+):(.+)$", video_url)
    sdk_dynamic = bool(episode and (video_url == "sdk-catalog" or sdk_unit_match))
    sdk_unit_provider = sdk_unit_match.group(1) if sdk_unit_match else ""
    sdk_unit_id = sdk_unit_match.group(2) if sdk_unit_match else ""
    if sdk_unit_provider in sdk_providers:
        source = sdk_unit_provider
    if server not in {"sub", "dub"}:
        server = "sub"
    anime_anilist_id = int(anime.get("anilist_id") or 0)
    if not anime_anilist_id and (source in {"vidrift", "megaplay"} or server == "dub"):
        anime_anilist_id = shared_anilist_id(anime)
    if not source:
        source = "animeparadise"
    sdk_stream = False
    sdk_subtitles = []
    sdk_fallback = False
    sdk_attempted = bool(
        episode and source in sdk_providers
        and (sdk_mal_id or sdk_dynamic or not requested_source or requested_source in sdk_providers)
    )
    if sdk_attempted:
        saved_video_url = video_url
        video_url, resolved_source, sdk_subtitles = resolve_sdk_episode_stream(
            anime.get("title", ""), episode_number, server,
            sdk_unit_provider or source, anime_anilist_id, sdk_unit_id or None,
        )
        if resolved_source:
            sdk_fallback = bool(requested_source and resolved_source != requested_source)
            source = resolved_source
        elif saved_video_url and not sdk_dynamic:
            video_url = saved_video_url
        sdk_stream = bool(resolved_source and video_url)
    if requested_source == "megaplay" and episode and not sdk_stream:
        # MegaPlay accepts either AniList or MAL IDs; prefer `ani` to match its
        # documented example and fall back to `mal` when only Tenrai/MAL is known.
        anime_anilist_id = anime_anilist_id or shared_anilist_id(anime)
        mal_id = shared_mal_id(anime, episode)
        language_path = "dub" if server == "dub" else "sub"
        if anime_anilist_id:
            video_url = f"https://megaplay.buzz/stream/ani/{anime_anilist_id}/{episode_number}/{language_path}"
            source = "megaplay"
        elif mal_id:
            video_url = f"https://megaplay.buzz/stream/mal/{mal_id}/{episode_number}/{language_path}"
            source = "megaplay"
        else:
            video_url = ""
    if source == "vidrift" and episode:
        if anime_anilist_id:
            video_url = (
                f"https://embed.vidrift.net/embed/anilist/{anime_anilist_id}/{episode_number}"
                f"?dub={1 if server == 'dub' else 0}&fs=parent&hide=skip%2Cnext%2Cepisodes%2Cserver"
            )
        else:
            video_url = ""
    video_url = video_url.lstrip("/")
    video_path = urlparse(video_url).path.lower()
    extension = Path(video_path).suffix
    is_direct_video = extension in {".mp4", ".webm", ".ogg", ".ogv", ".m4v"}
    is_megaplay_embed = bool(re.match(r"^https://megaplay\.buzz/stream/(?:s-2|ani|mal)/", video_url, re.I))
    is_hls = extension == ".m3u8" or (sdk_stream and not is_megaplay_embed)
    player_kind = "hls" if is_hls else "video" if is_direct_video else "iframe" if video_url else "empty"
    player_url = video_url
    if episode and episode.get("id") and session.get("user_id"):
        existing_history = row("SELECT id FROM watch_history WHERE user_id=%s AND episode_id=%s ORDER BY id DESC LIMIT 1", (session["user_id"], episode["id"]))
        if existing_history:
            change("UPDATE watch_history SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (existing_history["id"],))
        else:
            change(
                "INSERT INTO watch_history (user_id,anime_id,episode_id,progress,watch_time,duration) VALUES (%s,%s,%s,0,'00:00',%s)",
                (session["user_id"], anime_id, episode["id"], episode.get("duration") or "00:00"),
            )
    skip = get_episode_skip(episode, anime) if episode else {}
    related_anime = rows(
        "SELECT id,title,card_image,image,status FROM anime WHERE id<>%s ORDER BY featured DESC,created_at DESC LIMIT 6",
        (anime_id,),
    )
    return render_template(
        "watch.html",
        anime=anime,
        related_anime=related_anime,
        episodes=episodes,
        episode=episode,
        skip=skip,
        next_episode=next_episode,
        previous_episode=previous_episode,
        player_kind=player_kind,
        player_url=player_url,
        player_origin=f"{urlparse(player_url).scheme}://{urlparse(player_url).netloc}" if player_url.startswith("http") else "",
        player_source=source,
        player_server=server,
        anime_anilist_id=anime_anilist_id,
        sdk_mal_id=sdk_mal_id,
        sdk_catalog_anime=sdk_catalog_anime,
        sdk_subtitles=sdk_subtitles,
        sdk_fallback=sdk_fallback,
        sdk_unavailable=bool(sdk_attempted and not video_url),
        sdk_language=server,
        requested_source=requested_source,
        user=current_user(),
    )


@app.post("/api/watch-progress")
@login_required
def watch_progress():
    payload = request.get_json(silent=True) or {}
    episode_id = int(payload.get("episode_id", 0))
    progress = max(0, min(100, float(payload.get("progress", 0))))
    watch_time = str(payload.get("watch_time", "00:00"))[:20]
    duration = str(payload.get("duration", "00:00"))[:20]
    episode = row("SELECT id,anime_id FROM episodes WHERE id=%s", (episode_id,))
    if not episode:
        return jsonify(ok=False, error="Episode not found."), 404
    existing = row("SELECT id FROM watch_history WHERE user_id=%s AND episode_id=%s ORDER BY id DESC LIMIT 1", (session["user_id"], episode_id))
    if existing:
        change("UPDATE watch_history SET progress=%s,watch_time=%s,duration=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s", (progress, watch_time, duration, existing["id"]))
    else:
        change("INSERT INTO watch_history (user_id,anime_id,episode_id,progress,watch_time,duration) VALUES (%s,%s,%s,%s,%s,%s)", (session["user_id"], episode["anime_id"], episode_id, progress, watch_time, duration))
    return jsonify(ok=True)


@app.get("/api/random-anime")
def random_anime():
    picked = row("SELECT id FROM anime ORDER BY RAND() LIMIT 1")
    if not picked:
        return jsonify(id=None), 404
    return jsonify(id=picked["id"])


@app.get("/community")
@app.get("/community")
def community():
    return render_template("community.html", user=current_user())


@app.get("/choose-avatar")
@login_required
def choose_avatar():
    # Only show image files in the existing anime/user image collection.
    avatar_folder = MEDIA_ROOT / "images"
    avatars = sorted(p.relative_to(MEDIA_ROOT).as_posix() for p in avatar_folder.glob("*.*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"})
    return render_template("choose_avatar.html", avatars=avatars, user=current_user(), avatar_saved=request.args.get("saved") == "1")


@app.post("/choose-avatar")
@login_required
def save_avatar():
    avatar_path = request.form.get("avatar", "")
    if not avatar_path.startswith("images/") or ".." in Path(avatar_path).parts:
        abort(400)
    if not (MEDIA_ROOT / avatar_path).is_file():
        abort(404)
    change("UPDATE users SET profile_picture=%s WHERE id=%s", (avatar_path, session["user_id"]))
    flash("Na-update ang avatar mo.", "success")
    return redirect(url_for("choose_avatar", saved=1))


@app.post("/save-avatar-border")
@login_required
@csrf.exempt
def save_avatar_border():
    origin = request.headers.get("Origin", "").rstrip("/")
    if origin and origin != request.host_url.rstrip("/"):
        abort(403)
    payload = request.get_json(silent=True) or request.form
    name = Path(str(payload.get("border", ""))).name
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.gif", name, re.I) or not (MEDIA_ROOT / "avatar-borders" / name).is_file():
        return jsonify(success=False, ok=False, message="Hindi valid ang avatar border."), 400
    change("UPDATE users SET avatar_border=%s WHERE id=%s", (name, session["user_id"]))
    return jsonify(success=True, ok=True)


@app.get("/profile")
@login_required
def profile():
    user = current_user()
    border_dir = MEDIA_ROOT / "avatar-borders"
    borders = sorted(item.name for item in border_dir.glob("*.gif")) if border_dir.is_dir() else []
    history = rows(
        "SELECT wh.*,a.title,a.card_image,a.image,e.episode_number FROM watch_history wh "
        "JOIN anime a ON a.id=wh.anime_id JOIN episodes e ON e.id=wh.episode_id "
        "WHERE wh.user_id=%s ORDER BY wh.updated_at DESC LIMIT 30",
        (session["user_id"],),
    )
    return render_template("profile.html", user=user, history=history, borders=borders)


@app.post("/profile/update")
@login_required
def update_profile():
    user = current_user()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    message = None
    if len(username) < 3:
        message = "Ang username ay dapat hindi bababa sa 3 character."
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        message = "Maglagay ng valid na email address."
    elif not verify_password_hash(current, user.get("password", "")):
        message = "Mali ang kasalukuyang password."
    elif new != confirm:
        message = "Hindi magkapareho ang bagong password."
    elif not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{9,}$", new):
        message = "Kailangan ng 9+ character na may malaking/maliit na letra, numero, at simbolo."
    elif row("SELECT id FROM users WHERE (username=%s OR email=%s) AND id<>%s LIMIT 1", (username, email, user["id"])):
        message = "May gumagamit na ng username o email na iyan."
    if message:
        flash(message, "error")
        return redirect(url_for("profile"))

    change("UPDATE users SET username=%s,email=%s,password=%s WHERE id=%s", (username, email, hash_password(new), user["id"]))
    session["username"] = username
    flash("Na-update ang profile mo.", "success")
    return redirect(url_for("profile"))


@app.post("/logout")
def logout():
    if session.get("user_id"):
        change("UPDATE users SET status='Offline' WHERE id=%s", (session["user_id"],))
    session.clear()
    return redirect(url_for("home"))


@app.route("/admin/login", methods=["GET", "POST"])
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = row("SELECT * FROM admin WHERE username=%s LIMIT 1", (username,))
        if admin and verify_password_hash(password, admin.get("password", "")):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            change("UPDATE admin SET status='Online' WHERE id=%s", (admin["id"],))
            return redirect(url_for("admin_dashboard"))
        flash("Hindi tugma ang admin username o password.", "error")
    return render_template("admin/login.html")


@app.route("/admin/dashboard", methods=["GET", "POST"])
@admin_required
def admin_dashboard():
    if request.method == "POST" and "create_admin" in request.form:
        username = request.form.get("admin_username", "").strip()
        email = request.form.get("admin_email", "").strip().lower()
        password = request.form.get("admin_password", "")
        if len(username) < 3 or not email:
            flash("Kailangan ng valid na username at email.", "error")
        elif len(password) < 12:
            flash("Gumamit ng password na hindi bababa sa 12 character.", "error")
        elif row("SELECT id FROM admin WHERE username=%s OR email=%s LIMIT 1", (username, email)):
            flash("May admin na gumagamit ng username o email na iyan.", "error")
        else:
            change("INSERT INTO admin (username,email,password,status) VALUES (%s,%s,%s,'Offline')", (username, email, hash_password(password)))
            flash("Nagawa na ang admin account.", "success")
    stats = {
        "anime": row("SELECT COUNT(*) AS n FROM anime")["n"],
        "episodes": row(
            "SELECT COUNT(*) AS n FROM episodes WHERE COALESCE(video,'') NOT LIKE 'sdk-tenrai:%%' "
            "AND COALESCE(video,'') NOT LIKE 'sdk-anilist:%%'"
        )["n"],
        "users": row("SELECT COUNT(*) AS n FROM users")["n"],
        "online": row("SELECT COUNT(*) AS n FROM users WHERE status='Online'")["n"],
    }
    return render_template("admin/dashboard.html", stats=stats, admin=current_admin())


@app.route("/admin/profile", methods=["GET", "POST"])
@app.route("/admin/profile/edit", methods=["GET", "POST"])
@admin_required
def admin_profile():
    admin = current_admin()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        if len(username) < 3:
            flash("Ang username ay dapat hindi bababa sa 3 character.", "error")
        elif not verify_password_hash(current_password, admin.get("password", "")):
            flash("Mali ang kasalukuyang password.", "error")
        elif new_password and len(new_password) < 12:
            flash("Ang bagong password ay dapat hindi bababa sa 12 character.", "error")
        elif row("SELECT id FROM admin WHERE (username=%s OR email=%s) AND id<>%s LIMIT 1", (username, email, admin["id"])):
            flash("May admin account nang gumagamit ng username o email na iyan.", "error")
        else:
            if new_password:
                change("UPDATE admin SET username=%s,email=%s,password=%s WHERE id=%s", (username, email, hash_password(new_password), admin["id"]))
            else:
                change("UPDATE admin SET username=%s,email=%s WHERE id=%s", (username, email, admin["id"]))
            session["admin_username"] = username
            flash("Na-update ang admin profile.", "success")
            return redirect(url_for("admin_profile"))
    return render_template("admin/profile.html", admin=admin)


@app.get("/admin/users")
@admin_required
def admin_users():
    # Expired temporary bans automatically return to Active.
    change(
        "UPDATE users SET account_status='Active',ban_status='Active',ban_until=NULL,ban_reason=NULL "
        "WHERE ban_status='Banned' AND ban_until IS NOT NULL AND ban_until<=UTC_TIMESTAMP()"
    )
    term = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    if status_filter == "Online":
        users = rows(
            "SELECT id,username,email,profile_picture,joined_date,status,account_status,ban_status,ban_until,ban_reason FROM users "
            "WHERE status='Online' AND (username LIKE %s OR email LIKE %s) ORDER BY id DESC LIMIT 200",
            (f"%{term}%", f"%{term}%"),
        )
    else:
        users = rows(
            "SELECT id,username,email,profile_picture,joined_date,status,account_status,ban_status,ban_until,ban_reason FROM users "
            "WHERE username LIKE %s OR email LIKE %s ORDER BY id DESC LIMIT 200",
            (f"%{term}%", f"%{term}%"),
        )
    return render_template("admin/users.html", users=users, term=term, status_filter=status_filter)


@app.get("/admin/api/active-users")
@admin_required
def admin_active_users():
    online_users = rows(
        "SELECT username,profile_picture FROM users WHERE status='Online' ORDER BY username ASC LIMIT 100"
    )
    return jsonify(users=online_users)


@app.post("/admin/users/<int:user_id>/status")
@admin_required
def admin_user_status(user_id):
    action = request.form.get("action")
    reason = request.form.get("reason", "")[:1000]
    duration_seconds = {
        "1_minute": 60,
        "1_hour": 3600,
        "1_day": 86400,
        "7_days": 604800,
        "30_days": 2592000,
        "1_year": 31536000,
    }
    if action == "ban":
        duration = request.form.get("duration", "1_day")
        if duration not in duration_seconds:
            flash("Pumili ng valid na ban duration.", "error")
            return redirect(url_for("admin_users"))
        ban_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=duration_seconds[duration])
        if not reason:
            reason = "Banned by administrator."
        change("UPDATE users SET status='Offline',account_status='Deactivated',ban_status='Banned',ban_until=%s,ban_reason=%s WHERE id=%s", (ban_until, reason, user_id))
    elif action == "unban":
        change("UPDATE users SET account_status='Active',ban_status='Active',ban_until=NULL,ban_reason=NULL WHERE id=%s", (user_id,))
    elif action == "deactivate":
        duration = request.form.get("duration", "permanent")
        if duration in duration_seconds:
            ban_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=duration_seconds[duration])
            change(
                "UPDATE users SET status='Offline',account_status='Deactivated',ban_status='Banned',ban_until=%s,ban_reason=%s WHERE id=%s",
                (ban_until, reason or "Temporarily blocked by administrator.", user_id),
            )
        elif duration == "permanent":
            change("UPDATE users SET status='Offline',account_status='Deactivated',ban_status='Blocked',ban_until=NULL,ban_reason=%s WHERE id=%s", (reason or "Permanently blocked by administrator.", user_id))
        else:
            flash("Pumili ng valid na block duration.", "error")
            return redirect(url_for("admin_users"))
    elif action == "activate":
        change("UPDATE users SET account_status='Active',ban_status='Active',ban_until=NULL,ban_reason=NULL WHERE id=%s", (user_id,))
    elif action == "update":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not username or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Ilagay ang valid na username at email.", "error")
            return redirect(url_for("admin_users"))
        duplicate = row("SELECT id FROM users WHERE (username=%s OR email=%s) AND id<>%s LIMIT 1", (username, email, user_id))
        if duplicate:
            flash("May ibang account na gumagamit ng username o email na iyan.", "error")
            return redirect(url_for("admin_users"))
        change("UPDATE users SET username=%s,email=%s WHERE id=%s", (username, email, user_id))
    elif action == "delete":
        change("DELETE FROM watch_history WHERE user_id=%s", (user_id,))
        change("DELETE FROM users WHERE id=%s", (user_id,))
    else:
        abort(400)
    flash("Na-update ang account status.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/create")
@admin_required
def admin_create_user():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if len(username) < 3:
        flash("Dapat hindi bababa sa 3 character ang username.", "error")
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        flash("Ilagay ang valid na email address.", "error")
    elif not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{9,}$", password):
        flash("Gumamit ng password na 9+ character na may malaking/maliit na letra, numero, at simbolo.", "error")
    elif row("SELECT id FROM users WHERE username=%s OR email=%s LIMIT 1", (username, email)):
        flash("May account na gumagamit ng username o email na iyan.", "error")
    else:
        change(
            "INSERT INTO users (username,email,password,status,profile_picture,account_status,ban_status,avatar_border) "
            "VALUES (%s,%s,%s,'Offline','images/default-avatar.png','Active','Active','normal-01.gif')",
            (username, email, hash_password(password)),
        )
        flash("Nagawa na ang user account.", "success")
    return redirect(url_for("admin_users"))


@app.get("/admin/anime")
@admin_required
def admin_anime():
    query = request.args.get("q", "").strip()[:100]
    anilist_page = max(1, request.args.get("page", 1, type=int) or 1)
    if query:
        items = rows(
            "SELECT * FROM anime WHERE title LIKE %s ORDER BY created_at DESC,id DESC LIMIT 500",
            (f"%{query}%",),
        )
    else:
        items = rows("SELECT * FROM anime ORDER BY created_at DESC,id DESC LIMIT 500")
    anilist_results, anilist_error, anilist_has_next = [], "", False
    if query:
        try:
            found, anilist_has_next = anilist_catalog_items(
                search=query, sort="SEARCH_MATCH", page=anilist_page, per_page=12,
            )
            for item in found:
                cover = item.get("coverImage") or {}
                titles = item.get("title") or {}
                title = titles.get("english") or titles.get("romaji") or titles.get("native") or "Anime"
                anime_id = int(item.get("id") or 0)
                existing = row("SELECT id FROM anime WHERE anilist_id=%s LIMIT 1", (anime_id,)) if anime_id else None
                anilist_results.append({
                    "anilist_id": anime_id, "title": title,
                    "image": cover.get("extraLarge") or cover.get("large") or "",
                    "status": item.get("status") or "Anime",
                    "year": (item.get("startDate") or {}).get("year"),
                    "already_added": bool(existing),
                    "existing_id": (existing or {}).get("id"),
                })
        except (requests.RequestException, ValueError, TypeError, pymysql.MySQLError) as error:
            app.logger.info("Admin AniList anime search unavailable: %s", error)
            anilist_error = "Hindi makakonekta sa AniList ngayon. Subukan ulit mamaya."
    return render_template(
        "admin/anime.html", anime_list=items, search_query=query,
        anilist_results=anilist_results, anilist_error=anilist_error,
        anilist_page=anilist_page, anilist_has_next=anilist_has_next,
    )


@app.post("/admin/anime/import-anilist")
@admin_required
def admin_import_anilist_anime():
    anilist_id = request.form.get("anilist_id", type=int)
    query = request.form.get("q", "").strip()[:100]
    if not anilist_id or anilist_id < 1:
        flash("Hindi valid ang AniList anime ID.", "error")
        return redirect(url_for("admin_anime", q=query) if query else url_for("admin_anime"))
    try:
        payload = anilist_request(
            f"query ($id:Int!){{Media(id:$id,type:ANIME){{{ANILIST_HERO_FIELDS}}}}}",
            {"id": anilist_id}, timeout=15,
        )
        item = payload.get("Media") or {}
        if not item or int(item.get("id") or 0) != anilist_id:
            flash("Hindi makita ang anime na iyan sa AniList.", "error")
        else:
            anime_id = sync_anilist_catalog_item(item)
            if anime_id:
                flash("Naidagdag o naikabit na ang anime mula AniList.", "success")
            else:
                flash("Kulang ang AniList data kaya hindi ito na-save.", "error")
    except (requests.RequestException, ValueError, TypeError, pymysql.MySQLError) as error:
        app.logger.warning("Could not import AniList anime %s: %s", anilist_id, error)
        flash("Hindi na-save ang anime. Tiyaking maayos ang AniList at database connection.", "error")
    return redirect(url_for("admin_anime", q=query) if query else url_for("admin_anime"))


@app.get("/admin/integrations")
@admin_required
def admin_integrations():
    ensure_anime_source_table()
    sdk_ready = False
    anilist_ready = False
    try:
        health = anime_sdk_get("health", timeout=3)
        sdk_ready = bool(health)
    except (requests.RequestException, ValueError):
        pass
    try:
        data = anilist_request("query {Media(id:20,type:ANIME){id}}", timeout=5)
        anilist_ready = bool((data.get("Media") or {}).get("id"))
    except (requests.RequestException, ValueError, TypeError):
        pass
    return render_template(
        "admin/integrations.html",
        sdk_ready=sdk_ready,
        anilist_ready=anilist_ready,
    )


@app.get("/api/anilist/home-slides")
def anilist_home_slides_api():
    try:
        return jsonify(items=get_anilist_home_slides(limit=10), source="AniList")
    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.info("AniList home slides unavailable: %s", error)
        return jsonify(items=local_home_slides(limit=10), source="TiDB", fallback=True)


@app.get("/api/anilist/trending")
def anilist_trending_api():
    period = request.args.get("period", "day").casefold()
    try:
        items = get_anilist_trending(period=period, limit=10)
        if items:
            return jsonify(items=items, period=period, source="AniList")
        # A successful but empty upstream response should still use saved TiDB titles.
        fallback = local_catalog_items(sort="START_DATE_DESC", limit=10, page=1)
        items = [local_catalog_payload(item) | {"trend_score": max(1, 10 - index)} for index, item in enumerate(fallback)]
        return jsonify(items=items, period=period, source="TiDB", fallback=True)
    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.info("AniList %s trending list unavailable: %s", period, error)
        fallback = local_catalog_items(sort="START_DATE_DESC", limit=10, page=1)
        items = [local_catalog_payload(item) | {"trend_score": max(1, 10 - index)} for index, item in enumerate(fallback)]
        return jsonify(items=items, period=period, source="TiDB", fallback=True)


@app.get("/api/anilist/schedule")
def anilist_schedule_api():
    try:
        return jsonify(items=get_anilist_schedule(), source="AniList")
    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.info("AniList schedule unavailable: %s", error)
        return jsonify(items=[], source="AniList", error="Hindi ma-load ang airing schedule ngayon."), 503


@app.get("/api/anilist/catalog")
def anilist_catalog_api():
    """Serve live AniList search, genre, current, upcoming, trending, and popular results."""
    search = request.args.get("q", "").strip()[:100]
    sort = request.args.get("sort", "START_DATE_DESC").upper()
    genre = request.args.get("genre", "")[:40]
    status = request.args.get("status", "").upper()
    letter = request.args.get("letter", "").strip().upper()
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("limit", 12, type=int) or 12
    source = "AniList"
    try:
        if letter in {"#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ"}:
            items, has_next = anilist_letter_catalog(letter, page=max(1, page), per_page=24)
        else:
            items, has_next = anilist_catalog_items(search, sort, genre, status, page, per_page)
        if not items:
            fallback = local_catalog_items(
                search=search, sort=sort, genre=genre, status=status,
                limit=min(per_page, 24), page=page,
            )
            if fallback:
                return jsonify(
                    items=[local_catalog_payload(item) for item in fallback],
                    page=page, has_next=False, source="TiDB", fallback=True,
                )
        output = []
        for item in items:
            image = (item.get("coverImage") or {}).get("extraLarge") or (item.get("coverImage") or {}).get("large") or ""
            anime_state = str(item.get("status") or "").upper()
            start_date = item.get("startDate") or {}
            end_date = item.get("endDate") or {}
            output.append({
                "id": item.get("id"), "anilist_id": item.get("id"),
                "title": (item.get("title") or {}).get("english") or (item.get("title") or {}).get("romaji") or (item.get("title") or {}).get("native") or "Anime",
                "image": image,
                "image_fallback": (item.get("coverImage") or {}).get("large") or "",
                "status": "Ongoing" if anime_state == "RELEASING" else "Completed" if anime_state == "FINISHED" else "Upcoming" if anime_state == "NOT_YET_RELEASED" else "Hiatus" if anime_state == "HIATUS" else "Anime",
                "score": (item.get("averageScore") or 0) / 10 or None,
                "year": start_date.get("year"),
                "end_year": end_date.get("year"),
                "episodes": item.get("episodes"),
                "genres": item.get("genres") or [],
                "description": re.sub(r"<[^>]*>", " ", str(item.get("description") or "")).strip(),
            })
        return jsonify(items=output, page=page, has_next=has_next, source=source)
    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.info("AniList catalog feed unavailable: %s", error)
        fallback = local_catalog_items(
            search=search,
            sort=sort,
            genre=genre,
            status=status,
            limit=min(per_page, 24),
            page=page,
        )
        return jsonify(
            items=[local_catalog_payload(item) for item in fallback],
            page=page,
            has_next=False,
            source="TiDB",
            fallback=True,
        )


@app.get("/api/anime-sdk/search")
@admin_required
def anime_sdk_search():
    term = request.args.get("q", "").strip()[:100]
    provider = request.args.get("provider", "anikoto")
    if provider not in {"anikoto", "animeparadise", "megaplay", "allmanga"} or len(term) < 2:
        return jsonify(items=[])
    try:
        return jsonify(items=anime_sdk_get("search", {"q": term, "provider": provider}, timeout=35))
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("Anime-SDK lookup failed: %s", error)
        return jsonify(items=[], error="Hindi maabot ang Anime-SDK service. Tiyaking naka-start ito."), 503


@app.get("/api/anime-sdk/content")
@admin_required
def anime_sdk_content():
    provider = request.args.get("provider", "anikoto")
    media_id = request.args.get("media_id", "")[:300]
    if provider not in {"anikoto", "animeparadise", "megaplay", "allmanga"} or not media_id:
        return jsonify(items=[], error="Invalid provider or anime id."), 400
    try:
        return jsonify(items=anime_sdk_get("content", {"provider": provider, "mediaId": media_id}, timeout=40))
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("Anime-SDK episode lookup failed: %s", error)
        return jsonify(items=[], error="Hindi ma-load ang episode list mula sa source."), 503


@app.get("/api/anime-sdk/stream")
@admin_required
def anime_sdk_stream():
    provider = request.args.get("provider", "anikoto")
    unit_id = request.args.get("unit_id", "")[:400]
    language = request.args.get("language", "sub")
    title = request.args.get("title", "").strip()[:200]
    episode_number = request.args.get("episode_number", type=int)
    if provider not in {"anikoto", "animeparadise", "megaplay", "allmanga"} or not unit_id or language not in {"sub", "dub", "raw"}:
        return jsonify(error="Invalid stream request."), 400
    try:
        payload = anime_sdk_get("stream", {"provider": provider, "unitId": unit_id, "language": language}, timeout=35)
        if payload.get("type") == "video" and payload.get("streams"):
            return jsonify(localize_sdk_proxy_urls(payload))
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("Anime-SDK stream lookup failed: %s", error)
    if title and episode_number and episode_number > 0:
        fallback_url, fallback_provider, fallback_subtitles = resolve_sdk_episode_stream(title, episode_number, language, provider)
        if fallback_url:
            return jsonify(type="video", provider=fallback_provider, fallback=True, streams=[{"sourceUrl": fallback_url, "isHLS": True, "quality": "auto", "language": language, "subtitles": fallback_subtitles}])
    return jsonify(error="Walang provider na may video source para sa episode na ito ngayon. May episode list, pero walang maibalik na stream link."), 503


@app.get("/proxy")
@app.get("/api/anime-sdk/proxy")
def anime_sdk_proxy():
    """Same-origin relay to the SDK's host-allowlisted, signed stream proxy."""
    target_url = request.args.get("url", "")
    if not target_url or len(target_url) > 4096:
        abort(400)
    headers = {"Authorization": f"Bearer {ANIME_SDK_TOKEN}"} if ANIME_SDK_TOKEN else {}
    try:
        upstream = requests.get(f"{ANIME_SDK_URL}/proxy", params=request.args, headers=headers, stream=True, timeout=(8, 120))
    except requests.RequestException:
        return jsonify(error="Hindi maabot ang Anime-SDK stream proxy."), 502
    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
    is_hls_manifest = "mpegurl" in content_type.lower()
    if is_hls_manifest:
        manifest = upstream.content.decode("utf-8", errors="replace")
        response = Response(localize_sdk_proxy_urls(manifest), status=upstream.status_code, content_type=content_type)
    else:
        response = Response(stream_with_context(upstream.iter_content(chunk_size=64 * 1024)), status=upstream.status_code, content_type=content_type)
    for name in (("Content-Range", "Accept-Ranges") if is_hls_manifest else ("Content-Length", "Content-Range", "Accept-Ranges")):
        if name in upstream.headers:
            response.headers[name] = upstream.headers[name]
    response.call_on_close(upstream.close)
    return response


@app.route("/admin/anime/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_anime():
    anime_id = request.values.get("id", type=int)
    anime = anime_by_id(anime_id) if anime_id else None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Kailangan ang title.", "error")
            return redirect(request.url)
        if anime_id and anime is None:
            abort(404)
        fields = {
            "description": request.form.get("description", ""),
            "status": request.form.get("status", "Ongoing"),
            "genres": ", ".join(request.form.getlist("genres")) or request.form.get("genres_text", ""),
            "featured": 1 if request.form.get("featured") else 0,
            "featured_order": request.form.get("featured_order", 0, type=int),
            "anilist_id": request.form.get("anilist_id", type=int) or None,
            "release_date": request.form.get("release_date", "").strip() or None,
        }
        if fields["status"] not in ANIME_STATUSES:
            fields["status"] = "Ongoing"
        media = {}
        for key in ("image", "card_image", "slider_image", "banner_image"):
            upload = request.files.get(key)
            if upload and upload.filename:
                if Path(upload.filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    flash("Hindi suportadong image file.", "error")
                    return redirect(request.url)
                filename = secure_filename(upload.filename)
                dest_dir = MEDIA_ROOT / "images" / "anime"
                dest_dir.mkdir(parents=True, exist_ok=True)
                stored = f"{secrets.token_hex(8)}_{filename}"
                upload.save(dest_dir / stored)
                media[key] = f"images/anime/{stored}"
        if anime_id:
            values = [title, *fields.values()]
            assignments = "title=%s,description=%s,status=%s,genres=%s,featured=%s,featured_order=%s,anilist_id=%s,release_date=%s"
            for key, value in media.items():
                assignments += f",{key}=%s"
                values.append(value)
            values.append(anime_id)
            change(f"UPDATE anime SET {assignments} WHERE id=%s", tuple(values))
            sync_anime_genres(anime_id, fields["genres"].split(","))
            flash("Na-update ang anime.", "success")
        else:
            image = media.get("image")
            if not image:
                flash("Kailangan ng poster image para sa bagong anime.", "error")
                return redirect(request.url)
            new_anime_id = change(
                "INSERT INTO anime (title,description,image,card_image,slider_image,banner_image,featured,featured_order,genres,status,anilist_id,release_date) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (title, fields["description"], image, media.get("card_image"), media.get("slider_image"), media.get("banner_image"), fields["featured"], fields["featured_order"], fields["genres"], fields["status"], fields["anilist_id"], fields["release_date"]),
            )
            sync_anime_genres(new_anime_id, fields["genres"].split(","))
            flash("Naidagdag ang anime.", "success")
        return redirect(url_for("admin_anime"))
    genres = rows("SELECT name FROM anime_genres ORDER BY name")
    return render_template("admin/anime_form.html", anime=anime, statuses=ANIME_STATUSES, genres=genres)


@app.post("/admin/anime/<int:anime_id>/delete")
@admin_required
def admin_delete_anime(anime_id):
    change("DELETE FROM watch_history WHERE anime_id=%s", (anime_id,))
    change("DELETE FROM anime_external_sources WHERE anime_id=%s", (anime_id,))
    change("DELETE FROM anime_genre_map WHERE anime_id=%s", (anime_id,))
    change("DELETE s FROM episode_skip_segments s JOIN episodes e ON e.id=s.episode_id WHERE e.anime_id=%s", (anime_id,))
    change("DELETE c FROM episode_skip_api_cache c JOIN episodes e ON e.id=c.episode_id WHERE e.anime_id=%s", (anime_id,))
    change("DELETE FROM episodes WHERE anime_id=%s", (anime_id,))
    change("DELETE FROM anime WHERE id=%s", (anime_id,))
    flash("Nabura ang anime at ang kaugnay nitong episode records.", "success")
    return redirect(url_for("admin_anime"))


@app.get("/admin/episodes")
@admin_required
def admin_episodes():
    anime_id = request.args.get("anime_id", type=int)
    anime = anime_by_id(anime_id) if anime_id else None
    episode_list = rows(
        "SELECT e.*,a.title FROM episodes e JOIN anime a ON a.id=e.anime_id "
        "WHERE (%s IS NULL OR e.anime_id=%s) "
        "AND COALESCE(e.video,'') NOT LIKE 'sdk-tenrai:%%' AND COALESCE(e.video,'') NOT LIKE 'sdk-anilist:%%' "
        "ORDER BY a.title,e.episode_number",
        (anime_id, anime_id),
    )
    anime_list = rows("SELECT id,title FROM anime ORDER BY title")
    return render_template("admin/episodes.html", episodes=episode_list, anime_list=anime_list, selected_anime=anime)


@app.post("/admin/episodes/add")
@admin_required
def admin_add_episode():
    anime_id = request.form.get("anime_id", type=int)
    number = request.form.get("episode_number", type=int)
    video_value = request.form.get("video", "").strip()
    upload = request.files.get("video_file")
    if upload and upload.filename:
        if Path(upload.filename).suffix.lower() not in {".mp4", ".webm", ".m3u8"}:
            flash("MP4, WebM, o M3U8 lang ang suportadong video.", "error")
            return redirect(url_for("admin_episodes", anime_id=anime_id))
        dest = MEDIA_ROOT / "videos" / "episodes"
        dest.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(8)}_{secure_filename(upload.filename)}"
        upload.save(dest / name)
        video_value = f"videos/episodes/{name}"
    if not anime_id or not number or not anime_by_id(anime_id) or not video_value:
        flash("Piliin ang anime, episode number, at video URL o file.", "error")
    else:
        change("INSERT INTO episodes (anime_id,episode_number,video,duration) VALUES (%s,%s,%s,%s)", (anime_id, number, video_value, request.form.get("duration", "")))
        flash("Naidagdag ang episode.", "success")
    return redirect(url_for("admin_episodes", anime_id=anime_id))


@app.post("/admin/episodes/<int:episode_id>/update")
@admin_required
def admin_update_episode(episode_id):
    episode = row("SELECT * FROM episodes WHERE id=%s", (episode_id,))
    if not episode:
        abort(404)
    number = request.form.get("episode_number", episode["episode_number"], type=int)
    duration = request.form.get("duration", "")[:20]
    video_value = request.form.get("video", "").strip()
    upload = request.files.get("video_file")
    if upload and upload.filename:
        if Path(upload.filename).suffix.lower() not in {".mp4", ".webm", ".m3u8"}:
            flash("MP4, WebM, o M3U8 lang ang suportadong video.", "error")
            return redirect(url_for("admin_episodes", anime_id=episode["anime_id"]))
        dest = MEDIA_ROOT / "videos" / "episodes"
        dest.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(8)}_{secure_filename(upload.filename)}"
        upload.save(dest / name)
        video_value = f"videos/episodes/{name}"
    if not video_value:
        video_value = episode.get("video") or ""
    change("UPDATE episodes SET episode_number=%s,duration=%s,video=%s WHERE id=%s", (number, duration, video_value, episode_id))
    # The old admin page stores opening/ending skip timestamps in this existing table.
    skip = {name: request.form.get(name, "").strip() or None for name in ("intro_start", "intro_end", "outro_start", "outro_end")}
    change(
        "INSERT INTO episode_skip_segments (episode_id,intro_start,intro_end,outro_start,outro_end) VALUES (%s,%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE intro_start=VALUES(intro_start),intro_end=VALUES(intro_end),outro_start=VALUES(outro_start),outro_end=VALUES(outro_end)",
        (episode_id, skip["intro_start"], skip["intro_end"], skip["outro_start"], skip["outro_end"]),
    )
    flash("Na-update ang episode at skip times.", "success")
    return redirect(url_for("admin_episodes", anime_id=episode["anime_id"]))


@app.get("/admin/watch")
@admin_required
def admin_watch_episode():
    anime_id = request.args.get("anime", type=int)
    episode_id = request.args.get("episode", type=int)
    item = row("SELECT e.*,a.title FROM episodes e JOIN anime a ON a.id=e.anime_id WHERE e.id=%s AND e.anime_id=%s LIMIT 1", (episode_id, anime_id))
    if not item:
        abort(404)
    return render_template("admin/watch.html", episode=item)


@app.route("/admin/complete", methods=["GET", "POST"])
@admin_required
def admin_ai_complete():
    session["ai_scan_done"] = True
    return "AI Scan Completed"


@app.get("/admin/report")
@admin_required
def admin_report():
    # This page is a placeholder until report data is available.
    return render_template("admin/report.html")


@app.get("/admin/navigation")
@admin_required
def admin_navigation_fragment():
    # This route returns the reusable admin navigation partial.
    return render_template("admin/_nav.html", page_title="Admin")


@app.post("/admin/episodes/<int:episode_id>/delete")
@admin_required
def admin_delete_episode(episode_id):
    episode = row("SELECT id,anime_id FROM episodes WHERE id=%s", (episode_id,))
    if episode:
        change("DELETE FROM watch_history WHERE episode_id=%s", (episode_id,))
        change("DELETE FROM episode_skip_segments WHERE episode_id=%s", (episode_id,))
        change("DELETE FROM episode_skip_api_cache WHERE episode_id=%s", (episode_id,))
        change("DELETE FROM episodes WHERE id=%s", (episode_id,))
        flash("Nabura ang episode.", "success")
    return redirect(url_for("admin_episodes", anime_id=episode["anime_id"] if episode else None))


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    admin_id = session.get("admin_id")
    if admin_id:
        try:
            change("UPDATE admin SET status='Offline' WHERE id=%s", (admin_id,))
        except pymysql.MySQLError:
            app.logger.exception("Hindi na-update ang admin status sa logout.")
    session.clear()
    return redirect(url_for("admin_login"))


@app.errorhandler(pymysql.MySQLError)
def database_error(error):
    # Do not show connection strings or SQL details to site visitors.
    app.logger.error("MySQL operation failed: %s", error)
    return render_template("error.html", message="Hindi makakonekta sa database. Suriin ang DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, at DB_SSL sa Render Environment."), 503


@app.cli.command("db-check")
def db_check():
    """Read-only diagnostic: confirm that the configured MySQL-compatible database is reachable."""
    result = row("SELECT DATABASE() AS db_name, COUNT(*) AS anime_count FROM anime")
    click.echo(f"Connected to {result['db_name']}; anime rows: {result['anime_count']}.")


if __name__ == "__main__":
    # Flask runs separately from Apache; XAMPP is used here for MySQL only.
    app.run(host="127.0.0.1", port=5000, debug=True)
