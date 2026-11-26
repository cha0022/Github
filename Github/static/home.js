// FLOW NOTE: Loads AniList's live paginated catalog into the existing AniKoto-inspired cards and uses AniList banner art for the hero.
(() => {
    const slider = document.querySelector(".hero-slider");

    const getSlides = () => Array.from(slider.querySelectorAll(".slide:not([hidden])"));
    const getDots = () => Array.from(slider.querySelectorAll(".dots button"));
    const imageKey = (url) => {
        try {
            const parsed = new URL(url);
            return `${parsed.origin}${parsed.pathname}`.toLowerCase();
        } catch (_) { return String(url || "").split("?")[0].toLowerCase(); }
    };

    function setControlsVisible(count) {
        const show = count > 1;
        const dots = slider.querySelector(".dots");
        const previous = slider.querySelector(".hero-prev");
        const next = slider.querySelector(".hero-next");
        if (dots) dots.hidden = !show;
        if (previous) previous.hidden = !show;
        if (next) next.hidden = !show;
    }

    function syncAfterRemoval(activeIndex) {
        const slides = getSlides();
        const dots = getDots();
        if (!slides.length) {
            const fallback = slider.querySelector("[data-fallback-slide]");
            if (fallback) {
                fallback.hidden = false;
                fallback.classList.add("active");
                fallback.setAttribute("aria-hidden", "false");
                const message = fallback.querySelector(".content p");
                if (message) message.textContent = "Walang sapat na high-resolution na anime image para sa slider ngayon.";
            }
            slider.dataset.activeSlide = "0";
            setControlsVisible(0);
            return;
        }
        const nextActive = Math.max(0, Math.min(activeIndex, slides.length - 1));
        slides.forEach((slide, index) => {
            const active = index === nextActive;
            slide.classList.toggle("active", active);
            slide.setAttribute("aria-hidden", String(!active));
        });
        dots.forEach((dot, index) => {
            const active = index === nextActive;
            dot.classList.toggle("active", active);
            dot.setAttribute("aria-current", String(active));
        });
        slider.dataset.activeSlide = String(nextActive);
        setControlsVisible(slides.length);
    }

    function rejectLowQualitySlide(image) {
        const slide = image.closest(".slide");
        if (!slide || slide.hasAttribute("data-fallback-slide")) return;
        const slides = getSlides();
        const position = slides.indexOf(slide);
        if (position < 0) return;
        const activeBefore = Math.max(0, slides.findIndex((item) => item.classList.contains("active")));
        const dots = getDots();
        dots[position]?.remove();
        slide.remove();
        let nextActive = activeBefore;
        if (activeBefore === position) nextActive = Math.min(position, slides.length - 2);
        else if (activeBefore > position) nextActive = activeBefore - 1;
        syncAfterRemoval(nextActive);
    }

    function bindImageFallback(image) {
        if (image.dataset.fallbackBound) return;
        image.dataset.fallbackBound = "1";
        let fallbacks = [];
        try { fallbacks = JSON.parse(image.dataset.fallbacks || "[]"); } catch (_) { fallbacks = []; }

        const stepDown = (broken = false) => {
            const currentKey = imageKey(image.currentSrc || image.src);
            const nextIndex = fallbacks.findIndex((url) => imageKey(url) !== currentKey);
            if (nextIndex >= 0) image.src = fallbacks.splice(nextIndex, 1)[0];
            // Keep the best available image if it's a poster-sized fallback; a blurry
            // placeholder is better than deleting every slide from the carousel.
            else if (broken) rejectLowQualitySlide(image);
        };
        const inspectLoadedImage = () => {
            if (image.closest("[data-fallback-slide]")) return;
            const width = image.naturalWidth;
            const height = image.naturalHeight;
            // Try a wider fallback first, but keep the final valid artwork if AniList
            // has no trailer still for this title.
            if (width < 720 || height < 405) stepDown(false);
        };
        image.addEventListener("error", () => stepDown(true));
        image.addEventListener("load", inspectLoadedImage);
        if (image.complete) {
            if (image.naturalWidth) inspectLoadedImage();
            else stepDown(true);
        }
    }

    async function loadAniListFallback() {
        if (slider.dataset.anilistFallback !== "1") return;
        const fallback = slider.querySelector("[data-fallback-slide]");
        try {
            const response = await fetch("/api/anilist/home-slides", { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(20000) });
            if (!response.ok) throw new Error(`AniList returned ${response.status}`);
            const results = (await response.json()).items || [];
            const slides = [];
            const used = new Set();

            for (const anime of results) {
                // Only wide AniList banner art belongs in the hero carousel;
                // never substitute a portrait cover that leaves empty side bars.
                const candidates = [anime.slider_image].filter(Boolean);
                const image = candidates.find((url) => !used.has(imageKey(url)));
                if (!image) continue;
                used.add(imageKey(image));
                const imageFallbacks = candidates.filter((url) => imageKey(url) !== imageKey(image));
                slides.push({ anime, image, imageFallbacks });
                if (slides.length >= 10) break;
            }

            if (!slides.length) throw new Error("AniList did not return anime artwork.");
            const dots = slider.querySelector(".dots");
            for (const [index, item] of slides.entries()) {
                const anime = item.anime;
                const title = anime.title || "Featured anime";
                const slide = document.createElement("article");
                slide.className = `slide anilist-slide${index === 0 ? " active" : ""}`;
                slide.dataset.slide = String(index);

                const artwork = document.createElement("img");
                artwork.className = "slide-image";
                artwork.src = item.image;
                artwork.dataset.fallbacks = JSON.stringify(item.imageFallbacks);
                artwork.alt = `Anime artwork for ${title}`;
                slide.append(artwork);

                const content = document.createElement("div");
                content.className = "content";
                const category = document.createElement("span");
                category.className = "hero-category";
                category.textContent = anime.category || "Featured anime";
                const heading = document.createElement("h1");
                heading.textContent = title;
                const description = document.createElement("p");
                description.textContent = String(anime.description || "Discover this anime.").replace(/<[^>]*>/g, "").slice(0, 260);
                const source = document.createElement("span");
                source.className = "hero-source";
                source.textContent = `ANILIST${anime.score ? ` · ★ ${Number(anime.score).toFixed(2)}` : ""}`;
                const link = document.createElement("a");
                link.className = "watch-now";
                link.href = anime.anime_id
                    ? `/watch?anime_id=${encodeURIComponent(anime.anime_id)}`
                    : anime.anilist_id
                        ? `/watch?anilist_id=${encodeURIComponent(anime.anilist_id)}`
                        : "#latest-anime";
                link.textContent = "Watch Now";
                content.append(category, heading, description, source, link);
                slide.append(content);
                slider.insertBefore(slide, dots);

                const dot = document.createElement("button");
                dot.type = "button";
                dot.setAttribute("aria-label", `Show slide ${index + 1}`);
                dot.setAttribute("aria-current", String(index === 0));
                if (index === 0) dot.classList.add("active");
                dots.append(dot);
                bindImageFallback(artwork);
            }

            if (fallback) {
                const animeSlideCount = slider.querySelectorAll(".slide:not([data-fallback-slide])").length;
                if (animeSlideCount) {
                    fallback.hidden = true;
                    fallback.classList.remove("active");
                } else {
                    fallback.hidden = false;
                    fallback.classList.add("active");
                    const message = fallback.querySelector(".content p");
                    if (message) message.textContent = "Walang sapat na high-resolution na anime image para sa slider ngayon.";
                }
            }
            slider.dataset.anilistFallback = "0";
            setControlsVisible(slides.length);
        } catch (error) {
            console.warn("AniList slider fallback unavailable:", error);
            const message = fallback?.querySelector(".content p");
            if (message) message.textContent = "Hindi makakonekta sa AniList ngayon. Subukan ulit mamaya.";
        }
    }

    function initAniListFeeds() {
        const endpoint = '/api/anilist/catalog';
        const feeds = Array.from(document.querySelectorAll('[data-anilist-feed]'));
        if (!feeds.length) return;
        const params = new URLSearchParams(window.location.search);
        const allowedSorts = ['START_DATE_DESC', 'END_DATE_DESC', 'TRENDING_DESC', 'POPULARITY_DESC', 'UPDATED_AT_DESC', 'ID_DESC', 'TITLE_ROMAJI'];
        const allowedStatuses = ['RELEASING', 'FINISHED', 'NOT_YET_RELEASED', 'HIATUS'];
        const selectedSort = params.get('sort');
        const selectedStatus = params.get('status');
        const selectedGenre = params.get('genre') || '';
        const titleFor = (item) => item.title || 'Anime';
        const watchUrlFor = (item) => item.anime_id
            ? `/watch?anime_id=${encodeURIComponent(item.anime_id)}`
            : `/watch?anilist_id=${encodeURIComponent(item.anilist_id || item.id)}`;
        const makeCard = (item, index, ranked, rankOverride = null, server = '') => {
            const card = document.createElement('article');
            card.className = ranked ? 'anime-card top-anime-card' : 'anime-card';
            const link = document.createElement('a');
            link.className = 'anime-card-link';
            link.href = `${watchUrlFor(item)}${server ? `&server=${encodeURIComponent(server)}` : ''}`;
            const image = document.createElement('img');
            image.loading = 'lazy';
            image.src = item.image || item.image_fallback || '/site-assets/images/wallpaper.jpeg';
            image.alt = `Poster for ${titleFor(item)}`;
            image.addEventListener('error', () => {
                if (item.image_fallback && !image.dataset.fallbackTried) {
                    image.dataset.fallbackTried = '1';
                    image.src = item.image_fallback;
                }
                else image.hidden = true;
            });
            const status = document.createElement('span');
            status.className = 'anime-status';
            status.textContent = item.status || 'Anime';
            const title = document.createElement('h3');
            title.textContent = titleFor(item);
            const meta = document.createElement('small');
            meta.className = 'catalog-card-meta';
            meta.textContent = [item.year, item.score ? `★ ${Number(item.score).toFixed(2)}` : '', item.episodes ? `${item.episodes} eps` : ''].filter(Boolean).join(' · ');
            link.append(image, status, title, meta);
            const hover = document.createElement('span');
            hover.className = 'anime-hover-info';
            const hoverTitle = document.createElement('strong');
            hoverTitle.textContent = titleFor(item);
            const rating = document.createElement('small');
            rating.className = 'anime-hover-rating';
            rating.textContent = [item.status, item.score ? `★ ${Number(item.score).toFixed(2)}` : '', item.year].filter(Boolean).join(' · ');
            const description = document.createElement('span');
            description.className = 'anime-hover-description';
            description.textContent = (item.description || 'Tingnan ang detalye at mga available na episode ng anime.').replace(/\s+/g, ' ').slice(0, 220);
            const genres = document.createElement('small');
            genres.className = 'anime-hover-genres';
            genres.textContent = (item.genres || []).slice(0, 5).join(' · ');
            const action = document.createElement('span');
            action.className = 'anime-hover-action';
            action.textContent = '▶  Watch anime';
            hover.append(hoverTitle, rating, description);
            if (genres.textContent) hover.append(genres);
            hover.append(action);
            link.append(hover);
            if (ranked) {
                const rank = document.createElement('span');
                rank.className = 'top-anime-rank';
                rank.textContent = String(rankOverride ?? index + 1).padStart(2, '0');
                link.append(rank);
            }
            card.append(link);
            return card;
        };

        async function loadFeed(section, append = false) {
            const results = section.querySelector('.feed-results');
            const trendingPanel = section.matches('[data-anilist-trending]');
            const limit = Number(section.dataset.limit) || 12;
            const page = append ? (Number(section.dataset.page) || 1) + 1 : Math.max(1, Number(section.dataset.page) || 1);
            const query = trendingPanel
                ? new URLSearchParams({period: section.dataset.period || 'day'})
                : new URLSearchParams({sort: section.dataset.sort || 'START_DATE_DESC', page: String(page), limit: String(limit)});
            const genre = section.dataset.genre || '';
            const status = section.dataset.status || '';
            if (!trendingPanel && genre) query.set('genre', genre);
            if (!trendingPanel && status) query.set('status', status);
            if (!trendingPanel && section.dataset.letter) query.set('letter', section.dataset.letter);
            const spotlight = trendingPanel ? section.querySelector('[data-trend-spotlight]') : null;
            const moreButton = section.querySelector('[data-feed-more]');
            if (moreButton) moreButton.disabled = true;
            if (!append) {
                results.replaceChildren();
                if (section.id === 'latest-episode') results.scrollLeft = 0;
                if (spotlight) { spotlight.hidden = true; spotlight.replaceChildren(); }
                const loading = document.createElement('p');
                loading.className = 'catalog-message';
                loading.textContent = 'Loading anime cards…';
                results.append(loading);
            }
            try {
                const feedEndpoint = trendingPanel ? '/api/anilist/trending' : endpoint;
                const response = await fetch(`${feedEndpoint}?${query}`, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(20000) });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'AniList is unavailable.');
                if (!append) results.replaceChildren();
                if (!payload.items?.length) {
                    if (spotlight) spotlight.hidden = true;
                    if (!append) {
                        const empty = document.createElement('p');
                        empty.className = 'catalog-message';
                        empty.textContent = 'Walang available na anime cards ngayon.';
                        results.append(empty);
                    }
                    if (moreButton) moreButton.hidden = true;
                    return;
                }
                const ranked = section.classList.contains('top-anime-panel');
                const pageItems = [...payload.items];
                if (section.dataset.randomize === '1') {
                    for (let i = pageItems.length - 1; i > 0; i -= 1) {
                        const j = Math.floor(Math.random() * (i + 1));
                        [pageItems[i], pageItems[j]] = [pageItems[j], pageItems[i]];
                    }
                }
                if (trendingPanel) {
                    const [featured, ...rest] = pageItems;
                    if (featured && spotlight) {
                        spotlight.href = watchUrlFor(featured);
                        const image = document.createElement('img');
                        image.src = featured.image || featured.image_fallback || '/site-assets/images/wallpaper.jpeg';
                        image.alt = `Poster for ${titleFor(featured)}`;
                        image.loading = 'lazy';
                        image.addEventListener('error', () => {
                            if (featured.image_fallback && !image.dataset.fallbackTried) {
                                image.dataset.fallbackTried = '1';
                                image.src = featured.image_fallback;
                            }
                            else image.hidden = true;
                        });
                        const detail = document.createElement('span');
                        detail.className = 'trending-spotlight-copy';
                        const rank = document.createElement('small');
                        rank.className = 'trending-spotlight-rank';
                        rank.textContent = `#1 MOST TRENDING · ${String(section.dataset.period || 'day').toUpperCase()}`;
                        const title = document.createElement('strong');
                        title.textContent = titleFor(featured);
                        const meta = document.createElement('small');
                        meta.className = 'trending-spotlight-meta';
                        meta.textContent = [featured.status, featured.year, featured.score ? `★ ${Number(featured.score).toFixed(2)}` : ''].filter(Boolean).join(' · ');
                        detail.append(rank, title, meta);
                        spotlight.replaceChildren(image, detail);
                        spotlight.hidden = false;
                    }
                    rest.forEach((item, index) => results.append(makeCard(item, index, true, index + 2)));
                } else {
                    pageItems.forEach((item, index) => results.append(makeCard(item, index, ranked, null, section.dataset.server || '')));
                }
                section.dataset.page = String(page);
                if (moreButton) moreButton.hidden = !payload.has_next;
                const pager = section.querySelector('[data-catalog-pagination]');
                if (pager) {
                    const previous = pager.querySelector('[data-page-prev]');
                    const next = pager.querySelector('[data-page-next]');
                    const label = pager.querySelector('[data-page-label]');
                    if (previous) previous.disabled = page <= 1;
                    if (next) next.disabled = !payload.has_next;
                    if (label) label.textContent = `Page ${page}`;
                    pager.hidden = !payload.items.length && page <= 1;
                }
            } catch (error) {
                console.warn('AniList feed could not load:', error);
                if (!append) {
                    results.replaceChildren();
                    const note = document.createElement('p');
                    note.className = 'catalog-message';
                    note.textContent = 'Hindi ma-load ang anime cards ngayon. Subukan ulit mamaya.';
                    results.append(note);
                }
                if (moreButton) moreButton.hidden = true;
            } finally {
                if (moreButton) moreButton.disabled = false;
            }
        }

        const latestFeed = document.querySelector('#latest-anime[data-anilist-feed]');
        if (latestFeed) {
            if (allowedSorts.includes(selectedSort)) latestFeed.dataset.sort = selectedSort;
            if (allowedStatuses.includes(selectedStatus)) latestFeed.dataset.status = selectedStatus;
            latestFeed.dataset.genre = selectedGenre;
            const heading = latestFeed.querySelector('header h2');
            if (heading && selectedGenre) heading.textContent = `${selectedGenre} Anime`;
        }
        feeds.forEach((section) => {
            const moreButton = section.querySelector('[data-feed-more]');
            moreButton?.addEventListener('click', () => loadFeed(section, true));
            const pager = section.querySelector('[data-catalog-pagination]');
            pager?.querySelector('[data-page-prev]')?.addEventListener('click', () => {
                section.dataset.page = String(Math.max(1, (Number(section.dataset.page) || 1) - 1));
                loadFeed(section);
            });
            pager?.querySelector('[data-page-next]')?.addEventListener('click', () => {
                section.dataset.page = String((Number(section.dataset.page) || 1) + 1);
                loadFeed(section);
            });
            loadFeed(section);
        });
        const latestEpisode = document.querySelector('#latest-episode[data-anilist-feed]');
        latestEpisode?.querySelectorAll('[data-episode-scroll]')?.forEach((button) => {
            button.addEventListener('click', () => {
                const results = latestEpisode.querySelector('.feed-results');
                if (!results) return;
                const direction = button.dataset.episodeScroll === 'left' ? -1 : 1;
                results.scrollBy({left: direction * Math.max(results.clientWidth * 0.82, 240), behavior: 'smooth'});
            });
        });
        latestEpisode?.querySelectorAll('[data-episode-filter]')?.forEach((button) => {
            button.addEventListener('click', () => {
                latestEpisode.querySelectorAll('[data-episode-filter]').forEach((tab) => tab.classList.toggle('active', tab === button));
                const filter = button.dataset.episodeFilter;
                latestEpisode.dataset.server = filter === 'sub' || filter === 'dub' ? filter : '';
                latestEpisode.dataset.sort = filter === 'trending' ? 'TRENDING_DESC' : filter === 'random' ? 'POPULARITY_DESC' : 'UPDATED_AT_DESC';
                latestEpisode.dataset.status = filter === 'trending' || filter === 'random' ? '' : 'RELEASING';
                latestEpisode.dataset.randomize = filter === 'random' ? '1' : '0';
                latestEpisode.dataset.page = '1';
                loadFeed(latestEpisode);
            });
        });
        const trendingPanel = document.querySelector('[data-anilist-trending]');
        if (trendingPanel) {
            trendingPanel.querySelectorAll('[data-trend-period]').forEach((button) => {
                button.addEventListener('click', () => {
                    trendingPanel.dataset.period = button.dataset.trendPeriod;
                    trendingPanel.querySelectorAll('[data-trend-period]').forEach((tab) => {
                        const selected = tab === button;
                        tab.classList.toggle('active', selected);
                        tab.setAttribute('aria-selected', String(selected));
                    });
                    loadFeed(trendingPanel);
                });
            });
            loadFeed(trendingPanel);
        }
        window.setInterval(() => {
            if (!document.hidden) {
                feeds.forEach(loadFeed);
                if (trendingPanel) loadFeed(trendingPanel);
            }
        }, 15 * 60 * 1000);
        initAiringSchedule();
    }

    function initAiringSchedule() {
        const section = document.querySelector('[data-anilist-schedule]');
        if (!section) return;
        const dayNav = section.querySelector('[data-schedule-days]');
        const items = section.querySelector('[data-schedule-items]');
        const nowLabel = section.querySelector('[data-schedule-now]');
        const dayKey = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        const days = Array.from({length: 7}, (_, offset) => {
            const date = new Date();
            date.setHours(0, 0, 0, 0);
            date.setDate(date.getDate() + offset);
            return date;
        });
        if (nowLabel) nowLabel.textContent = `Now · ${new Date().toLocaleString()}`;
        fetch('/api/anilist/schedule', {headers: {Accept: 'application/json'}, signal: AbortSignal.timeout(20000)})
            .then(async (response) => {
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Schedule unavailable');
                const scheduleItems = payload.items || [];
                const renderDay = (selectedDate) => {
                    const selectedKey = dayKey(selectedDate);
                    dayNav.querySelectorAll('[data-schedule-day]').forEach((button) => button.classList.toggle('active', button.dataset.scheduleDay === selectedKey));
                    items.replaceChildren();
                    const entries = scheduleItems.filter((entry) => dayKey(new Date(Number(entry.airing_at) * 1000)) === selectedKey);
                    if (!entries.length) {
                        const empty = document.createElement('p');
                        empty.className = 'catalog-message';
                        empty.textContent = 'Walang naka-schedule na episode sa araw na ito.';
                        items.append(empty);
                        return;
                    }
                    entries.forEach((entry) => {
                        const row = document.createElement('a');
                        row.className = 'schedule-item';
                        row.href = `/watch?anilist_id=${encodeURIComponent(entry.anilist_id)}&episode=${encodeURIComponent(entry.episode || 1)}`;
                        const time = document.createElement('time');
                        time.dateTime = new Date(Number(entry.airing_at) * 1000).toISOString();
                        time.textContent = new Date(Number(entry.airing_at) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
                        const image = document.createElement('img');
                        image.src = entry.image || '/site-assets/images/wallpaper.jpeg';
                        image.alt = '';
                        image.loading = 'lazy';
                        const title = document.createElement('strong');
                        title.textContent = entry.title;
                        const episode = document.createElement('small');
                        episode.textContent = `Episode ${entry.episode}`;
                        row.append(time, image, title, episode);
                        items.append(row);
                    });
                };
                dayNav.replaceChildren();
                days.forEach((date, index) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.dataset.scheduleDay = dayKey(date);
                    button.setAttribute('aria-label', date.toLocaleDateString());
                    const weekday = document.createElement('strong');
                    weekday.textContent = index === 0 ? 'Today' : date.toLocaleDateString([], {weekday: 'short'});
                    const dateText = document.createElement('small');
                    dateText.textContent = date.toLocaleDateString([], {month: 'short', day: 'numeric'});
                    button.append(weekday, dateText);
                    button.addEventListener('click', () => renderDay(date));
                    dayNav.append(button);
                });
                renderDay(days[0]);
            })
            .catch((error) => {
                console.warn('AniList airing schedule could not load:', error);
                items.replaceChildren();
                const note = document.createElement('p');
                note.className = 'catalog-message';
                note.textContent = 'Hindi ma-load ang schedule ngayon. Subukan ulit mamaya.';
                items.append(note);
            });
    }

    function initCarousel() {
        slider.querySelectorAll(".slide-image").forEach(bindImageFallback);
        const previous = slider.querySelector(".hero-prev");
        const next = slider.querySelector(".hero-next");
        let timer = null;

        function activeIndex() {
            const slides = getSlides();
            const active = slides.findIndex((slide) => slide.classList.contains("active"));
            return active >= 0 ? active : 0;
        }
        function showSlide(requestedIndex) {
            const slides = getSlides();
            const dots = getDots();
            if (!slides.length) return;
            const index = ((requestedIndex % slides.length) + slides.length) % slides.length;
            slides.forEach((slide, i) => {
                const active = i === index;
                slide.classList.toggle("active", active);
                slide.setAttribute("aria-hidden", String(!active));
            });
            dots.forEach((dot, i) => {
                const active = i === index;
                dot.classList.toggle("active", active);
                dot.setAttribute("aria-current", String(active));
            });
            slider.dataset.activeSlide = String(index);
        }
        function stopTimer() {
            if (timer) window.clearInterval(timer);
            timer = null;
        }
        function startTimer() {
            stopTimer();
            if (getSlides().length > 1 && !document.hidden) {
                timer = window.setInterval(() => showSlide(activeIndex() + 1), 5500);
            }
        }

        window.currentSlide = (number) => { showSlide(Number(number) - 1); startTimer(); };
        slider.querySelector(".dots")?.addEventListener("click", (event) => {
            const dot = event.target.closest("button");
            const index = getDots().indexOf(dot);
            if (index >= 0) { showSlide(index); startTimer(); }
        });
        previous?.addEventListener("click", () => { showSlide(activeIndex() - 1); startTimer(); });
        next?.addEventListener("click", () => { showSlide(activeIndex() + 1); startTimer(); });
        slider.addEventListener("focusin", stopTimer);
        slider.addEventListener("focusout", (event) => {
            if (!slider.contains(event.relatedTarget)) startTimer();
        });
        document.addEventListener("visibilitychange", () => document.hidden ? stopTimer() : startTimer());

        let touchStartX = null;
        slider.addEventListener("touchstart", (event) => { touchStartX = event.changedTouches[0].clientX; }, { passive: true });
        slider.addEventListener("touchend", (event) => {
            if (touchStartX === null) return;
            const distance = event.changedTouches[0].clientX - touchStartX;
            if (Math.abs(distance) > 55) showSlide(activeIndex() + (distance < 0 ? 1 : -1));
            touchStartX = null;
            startTimer();
        }, { passive: true });

        // Mouse drag for desktop; keep arrow and dot buttons available.
        let pointerStart = null;
        let pointerStartY = null;
        slider.addEventListener("pointerdown", (event) => {
            if (event.pointerType !== "mouse" || event.button !== 0 || event.target.closest("button, a")) return;
            pointerStart = event.clientX;
            pointerStartY = event.clientY;
            stopTimer();
            slider.setPointerCapture(event.pointerId);
        });
        slider.addEventListener("pointerup", (event) => {
            if (pointerStart === null) return;
            const distanceX = event.clientX - pointerStart;
            const distanceY = event.clientY - pointerStartY;
            if (Math.abs(distanceX) > 55 && Math.abs(distanceX) > Math.abs(distanceY)) {
                showSlide(activeIndex() + (distanceX < 0 ? 1 : -1));
                event.preventDefault();
            }
            pointerStart = null;
            pointerStartY = null;
            startTimer();
        });
        slider.addEventListener("pointercancel", () => {
            pointerStart = null;
            pointerStartY = null;
            startTimer();
        });

        syncAfterRemoval(activeIndex());
        startTimer();
    }

    initAniListFeeds();
    if (slider) loadAniListFallback().finally(initCarousel);
})();
