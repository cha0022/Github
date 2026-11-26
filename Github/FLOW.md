# WEBSITE V2.3 — Code flow guide

This folder is the active website copy. Start the top-level app with `start_website.bat`.

## Startup and request flow

1. Start MySQL in XAMPP. Copy `.env.example` to `.env` and set the database credentials.
2. Install Python packages once with `python -m pip install -r requirements.txt`.
3. Double-click `start_website.bat`. It checks Python and Node, installs Anime-SDK if missing, then opens Anime-SDK and Flask in separate windows.
4. Open `http://127.0.0.1:5000`. Flask receives the request, reads from MySQL or configured providers, and renders a page from `templates/`.
5. Pages load shared browser scripts and styles from `static/`; `static/site-polish.css` is the final shared visual layer for comfortable public pages and the professional admin. The landing page additionally loads `css/index.css` and `css/index-search.css`, while the catalog loads `css/user.css` and `css/user-responsive.css`. Shared navigation assets live in `includes/`. Search-result image paths are converted by Flask to `/site-assets/...` URLs so they work from nested pages too.
6. For anime lookup and playback, Flask calls Anime-SDK on port 3000. The watch page has three choices: AnimeParadise (HD-1 and default), Vidrift (HD-2), and MegaPlay (HD-3). MegaPlay playback uses its documented AniList/MAL iframe endpoints; Anime-SDK resolves it only when those IDs are unavailable.
7. Local media is read from `images/`, `videos/`, and `avatar-borders/`, unless `SITE_MEDIA_ROOT` points somewhere else.

## Folder roles

- `app.py`: active Flask app, routes, database access, and media/provider flow.
- `templates/`: active Jinja pages; Flask routes supply data and templates render shared layouts/partials.
- `static/`: active styles and browser scripts loaded by the current templates.
- `includes/`: shared navigation assets referenced where needed.
- `anime-sdk-service/`: active Node bridge for Anime-SDK providers.
- `css/`: 24 retained stylesheets in one flat folder. The landing page uses `index.css` and `index-search.css`; the catalog uses `user.css` and `user-responsive.css`; the other stylesheets are available when a page explicitly links them.

## Watch page flow

The `/watch` route loads the selected anime and episode list, resolves the chosen stream and subtitles, and fetches up to six related titles. The page places the episode rail on the left, player and source controls in the center, and related titles on the right; on small screens these stack below the player.

## Admin user and slider flow

The admin user page provides Create, Read/search, Edit, temporary Ban, timed or permanent Block, Unban/Unblock, and Delete actions. Timed restrictions store an expiry and automatically stop blocking sign-in after that time. A restricted user sees the ban end time and reason in the notification panel or login message; the admin user table shows the user's avatar with a diagonal text-only BLOCKED mark. The anime editor uploads poster, card, slider, and fallback banner images; setting a title as Featured and choosing its order controls the first slides in the homepage carousel. AniList's `bannerImage` is the first choice for hero slides, with its largest cover as fallback. `static/home.js` rejects images below the hero's minimum dimensions, tries the remaining fallbacks, and removes the slide if none are sharp enough. The homepage AniList catalog supports live search, Trending, Top, Latest, new episodes, status, and genre filters. Each result is synced into the local anime/episode catalog automatically, and the browser refreshes the feed every 15 minutes. Flask caches slider metadata for six hours and browse results for ten minutes. The script also auto-rotates slides and wires arrow, dot, touch, and browse controls.

## Per-file notes

Each hand-written Python, JavaScript, HTML, CSS, and batch file has a short `FLOW NOTE` comment explaining its role. The bundled `static/vendor/hls.min.js` is third-party minified code and is left unchanged; the watch page loads it as the HLS playback library. JSON files are package/dependency configuration, not executable source files.
