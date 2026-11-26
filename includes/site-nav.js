// FLOW NOTE: Wires shared navigation controls and menu interactions used across pages.
// Shared HIANIME navigation behavior. Safe to load on pages without every control.
function toggleMenu(forceClose) {
    const menu = document.getElementById('navbar');
    const backdrop = document.getElementById('menuBackdrop');
    if (!menu || !backdrop) return;
    const button = document.querySelector('.site-menu-toggle');
    const open = typeof forceClose === 'boolean' ? forceClose : !menu.classList.contains('active');
    menu.classList.toggle('active', open);
    backdrop.classList.toggle('active', open);
    menu.setAttribute('aria-hidden', String(!open));
    if (button) {
        button.textContent = open ? '×' : '☰';
        button.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
        button.setAttribute('aria-expanded', String(open));
    }
}

function toggleSiteMenu(button) {
    toggleMenu();
}

function showMenuPanel(panelId, button) {
    document.querySelectorAll('.mega-panel').forEach(panel => panel.classList.toggle('active', panel.id === panelId));
    document.querySelectorAll('.menu-category').forEach(category => category.classList.toggle('active', category === button));
}

function showSiteMenuPanel(panelId, button) {
    showMenuPanel(panelId, button);
}

function goToRandomItem() {
    const anime = Array.from(document.querySelectorAll('.anime-card-link[href]'));
    if (anime.length) {
        window.location.href = anime[Math.floor(Math.random() * anime.length)].href;
        return;
    }
    const posts = Array.from(document.querySelectorAll('.post'));
    if (posts.length) {
        posts[Math.floor(Math.random() * posts.length)].scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
    }
    window.location.href = '/home#latest-anime';
}

function toggleSharedAccount(button, forceClose) {
    const box = button?.closest('.shared-account-box');
    const menu = box?.querySelector('.shared-account-menu');
    if (!menu) return;
    const open = forceClose === true ? false : menu.hidden;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
}

// The ban notice stays available from the navbar bell, but never auto-opens.
function toggleSharedBanNotice(forceOpen) {
    const notice = document.getElementById('sharedBanNotice');
    const bell = document.querySelector('.shared-ban-bell');
    if (!notice) return;
    const open = typeof forceOpen === 'boolean' ? forceOpen : notice.hidden;
    notice.hidden = !open;
    if (bell) bell.setAttribute('aria-expanded', String(open));
}

function openSharedAvatar() {
    const button = document.querySelector('.shared-account-box .shared-account');
    if (button) toggleSharedAccount(button, true);
    const modal = document.getElementById('sharedAvatarModal');
    if (modal) { modal.hidden = false; modal.setAttribute('aria-hidden', 'false'); }
}

function openSharedAvatarBorders() {
    const button = document.querySelector('.shared-account-box .shared-account');
    if (button) toggleSharedAccount(button, true);
    const modal = document.getElementById('sharedAvatarBordersModal');
    if (modal) { modal.hidden = false; modal.setAttribute('aria-hidden', 'false'); }
}

function closeSharedNavModals() {
    document.querySelectorAll('.shared-nav-modal').forEach(modal => {
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
    });
}

function setSharedAvatarBorder(src, save = true) {
    const box = document.querySelector('.shared-account-box');
    const userKey = box?.dataset.userKey || 'guest';
    const storageKey = 'avatar-border-v1:' + userKey;
    const frame = document.querySelector('.shared-account-box .shared-avatar-frame, .account .avatar-frame');
    const border = frame?.querySelector('.shared-avatar-border, .avatar-gif-border');
    if (border) { border.src = src || ''; border.hidden = !src; }
    document.querySelectorAll('.shared-border-option').forEach(option => {
        option.classList.toggle('selected', Boolean(src) && option.dataset.borderSrc === src);
    });
    if (!save) return;
    const borderName = src ? src.split('/').pop() : 'normal-01.gif';
    try { localStorage.setItem(storageKey, borderName.replace(/\.gif$/i, '')); } catch (e) {}
    if (box && box.dataset.borderSaveUrl) {
        fetch(box.dataset.borderSaveUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify({ border: borderName })
        }).then(response => response.json()).then(data => {
            if (!data.success) console.error('Could not save avatar border:', data.message || 'request failed');
        }).catch(error => console.error('Could not save avatar border:', error));
    }
}

function resetSharedAvatarBorder() { setSharedAvatarBorder('avatar-borders/normal-01.gif', true); }

function initSharedHeaderControls() {
    const header = document.querySelector('.shared-site-header');
    if (!header) return;

    const searchToggle = header.querySelector('#userSearchToggle');
    const searchPanel = header.querySelector('#userSearchPanel');
    const query = header.querySelector('#userSearchQuery');
    const results = header.querySelector('#userSearchResults');
    const status = header.querySelector('#userSearchStatus');
    const searchSubmit = header.querySelector('#userSearchSubmit');
    const notificationToggle = header.querySelector('#newAnimeToggle');
    const notificationPanel = header.querySelector('#newAnimePanel');
    const notificationItems = header.querySelector('#newAnimeItems');
    const badge = header.querySelector('#newAnimeBadge');
    const toast = header.querySelector('#newAnimeToast');
    const apiUrl = (params) => '/home?' + new URLSearchParams(params).toString();
    let kind = 'anime';
    let searchTimer;
    let searchRequestId = 0;
    let searchController = null;
    let toastTimer;

    const setPanel = (button, panel, open) => {
        if (!button || !panel) return;
        panel.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
    };

    if (searchToggle && searchPanel && query && results && status) {
        searchToggle.addEventListener('click', () => {
            const open = searchPanel.hidden;
            setPanel(searchToggle, searchPanel, open);
            setPanel(notificationToggle, notificationPanel, false);
            if (open) query.focus();
        });

        const search = async () => {
            const term = query.value.trim();
            searchController?.abort();
            const requestId = ++searchRequestId;
            if (!term) {
                results.innerHTML = '<p>Type an anime title, then press Enter or Search.</p>';
                return;
            }
            searchController = new AbortController();
            results.innerHTML = '<p>Searching...</p>';
            try {
                let response = await fetch(apiUrl({user_api: 'search', q: term, kind, status: status.value}), {
                    headers: {Accept: 'application/json'}, cache: 'no-store', signal: searchController.signal
                });
                let data = await response.json();
                // If the local server cannot reach AniList, query AniList from the
                // browser as a fallback so anime search still works for the user.
                if (kind === 'anime' && (!response.ok || data.error || !data.items?.length)) {
                    const statusValue = ({Ongoing: 'RELEASING', Completed: 'FINISHED', Upcoming: 'NOT_YET_RELEASED', Hiatus: 'HIATUS'})[status.value];
                    const statusDefinition = statusValue ? ', $status: MediaStatus' : '';
                    const statusArgument = statusValue ? ', status: $status' : '';
                    const variables = {search: term};
                    if (statusValue) variables.status = statusValue;
                    response = await fetch('https://graphql.anilist.co', {
                        method: 'POST',
                        headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            query: `query ($search: String!${statusDefinition}) { Page(page: 1, perPage: 20) { pageInfo { hasNextPage } media(type: ANIME, search: $search, isAdult: false, sort: SEARCH_MATCH${statusArgument}) { id title { english romaji native } coverImage { large extraLarge } } } }`,
                            variables
                        }),
                        signal: searchController.signal
                    });
                    const payload = await response.json();
                    if (!response.ok || payload.errors?.length) throw new Error('AniList request failed');
                    const page = payload.data?.Page || {};
                    data = {
                        source: 'AniList',
                        has_next: Boolean(page.pageInfo?.hasNextPage),
                        items: (page.media || []).map(item => ({
                            type: 'anime', id: item.id, anilist_id: item.id,
                            title: item.title?.english || item.title?.romaji || item.title?.native || 'Anime',
                            image: item.coverImage?.large || item.coverImage?.extraLarge || ''
                        }))
                    };
                }
                if (requestId !== searchRequestId) return;
                if (!response.ok || data.error) throw new Error(data.error || 'Search failed.');
                results.replaceChildren();
                if (!Array.isArray(data.items) || !data.items.length) {
                    const empty = document.createElement('p');
                    empty.textContent = 'No results found.';
                    results.append(empty);
                    return;
                }
                data.items.forEach(item => {
                    const link = document.createElement('a');
                    link.className = 'user-search-result';
                    link.setAttribute('aria-selected', 'false');
                    link.href = item.type === 'anime'
                        ? '/watch?anilist_id=' + encodeURIComponent(item.anilist_id || item.id)
                        : '/profile?username=' + encodeURIComponent(item.name);
                    const image = document.createElement('img');
                    const defaultAvatar = '/site-assets/images/default-avatar.png';
                    image.src = item.image || defaultAvatar;
                    image.addEventListener('error', () => {
                        if (item.type === 'user' && image.dataset.fallbackApplied !== '1') {
                            image.dataset.fallbackApplied = '1';
                            image.src = defaultAvatar;
                        } else {
                            image.hidden = true;
                        }
                    });
                    image.alt = '';
                    image.loading = 'lazy';
                    const label = document.createElement('span');
                    label.textContent = item.type === 'anime' ? item.title : item.name;
                    link.append(image, label);
                    results.append(link);
                });
                if (kind === 'anime') {
                    const allResults = document.createElement('a');
                    allResults.className = 'user-search-all';
                    allResults.href = '/search?q=' + encodeURIComponent(term);
                    allResults.textContent = 'View all AniList results →';
                    results.append(allResults);
                }
            } catch (error) {
                if (error.name === 'AbortError') return;
                results.replaceChildren();
                const message = document.createElement('p');
                message.textContent = 'Search failed. Please try again.';
                results.append(message);
            }
        };

        query.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(search, 180);
        });
        query.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                clearTimeout(searchTimer);
                search();
            }
        });
        searchSubmit?.addEventListener('click', () => {
            clearTimeout(searchTimer);
            search();
            query.focus();
        });
        query.addEventListener('keydown', event => {
            const rows = [...results.querySelectorAll('.user-search-result')];
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                if (!rows.length) return;
                const current = rows.findIndex(row => row.getAttribute('aria-selected') === 'true');
                const next = event.key === 'ArrowDown'
                    ? (current + 1) % rows.length
                    : (current <= 0 ? rows.length - 1 : current - 1);
                rows.forEach((row, index) => row.setAttribute('aria-selected', String(index === next)));
                rows[next].scrollIntoView({block: 'nearest'});
            } else if (event.key === 'Enter') {
                const selected = rows.find(row => row.getAttribute('aria-selected') === 'true');
                if (selected) {
                    event.preventDefault();
                    window.location.href = selected.href;
                }
            }
        });

        header.querySelectorAll('[data-search-kind]').forEach(button => {
            button.addEventListener('click', () => {
                kind = button.dataset.searchKind;
                header.querySelectorAll('[data-search-kind]').forEach(tab => {
                    const active = tab === button;
                    tab.classList.toggle('active', active);
                    tab.setAttribute('aria-selected', String(active));
                });
                status.disabled = kind !== 'anime';
                search();
            });
        });
        status.addEventListener('change', search);
        header.querySelector('#userSearchClear')?.addEventListener('click', () => {
            query.value = '';
            searchController?.abort();
            results.innerHTML = '<p>Type an anime title, then press Enter or Search.</p>';
            query.focus();
        });
    }

    if (notificationToggle && notificationPanel && notificationItems && badge) {
        const isBlocked = notificationToggle.dataset.banActive === '1';
        const latestId = Number(notificationToggle.dataset.latestId) || 0;
        const latestKey = 'hianimeLastSeenAnimeId';
        const banKey = 'hianimeBanNoticeSeen';
        const noticesKey = 'hianimeNewAnimeNotices';
        let notices = [];
        let lastSeen = Number(localStorage.getItem(latestKey));
        try {
            const saved = JSON.parse(localStorage.getItem(noticesKey) || '[]');
            if (Array.isArray(saved)) notices = saved;
        } catch (_) {}
        if (!Number.isFinite(lastSeen) || lastSeen < 0) {
            lastSeen = latestId;
            localStorage.setItem(latestKey, String(lastSeen));
        }

        const paint = () => {
            badge.textContent = isBlocked ? '!' : String(notices.length);
            badge.hidden = !isBlocked && notices.length === 0;
            notificationItems.replaceChildren();
            if (!notices.length) {
                const empty = document.createElement('p');
                empty.className = 'new-anime-empty';
                empty.textContent = 'No new anime yet.';
                notificationItems.append(empty);
                return;
            }
            notices.slice().reverse().forEach(item => {
                const link = document.createElement('a');
                link.className = 'new-anime-item';
                link.href = '/watch?anime_id=' + encodeURIComponent(item.id);
                link.textContent = item.title + ' was added';
                notificationItems.append(link);
            });
        };

        notificationToggle.addEventListener('click', () => {
            const open = notificationPanel.hidden;
            setPanel(notificationToggle, notificationPanel, open);
            setPanel(searchToggle, searchPanel, false);
        });
        header.querySelector('#clearNewAnime')?.addEventListener('click', () => {
            notices = [];
            localStorage.setItem(noticesKey, '[]');
            paint();
        });

        const poll = async () => {
            try {
                const response = await fetch(apiUrl({user_api: 'new_anime', since: String(lastSeen)}), {
                    headers: {Accept: 'application/json'}, cache: 'no-store'
                });
                if (!response.ok) return;
                const data = await response.json();
                const fresh = Array.isArray(data.items) ? data.items : [];
                if (!fresh.length) return;
                fresh.forEach(item => {
                    notices.push(item);
                    lastSeen = Math.max(lastSeen, Number(item.id) || 0);
                });
                notices = notices.slice(-20);
                localStorage.setItem(latestKey, String(lastSeen));
                localStorage.setItem(noticesKey, JSON.stringify(notices));
                paint();
                if (toast) {
                    toast.textContent = 'New anime uploaded: ' + fresh[fresh.length - 1].title;
                    toast.hidden = false;
                    clearTimeout(toastTimer);
                    toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
                }
            } catch (_) {}
        };

        paint();
        const seenBan = localStorage.getItem(banKey) === notificationToggle.dataset.banKey;
        if (isBlocked && !seenBan) {
            setPanel(notificationToggle, notificationPanel, true);
            localStorage.setItem(banKey, notificationToggle.dataset.banKey || 'active');
        }
        setTimeout(poll, 1200);
        setInterval(poll, 30000);
    }

    document.addEventListener('click', event => {
        if (!event.target.closest('.user-page-tools')) {
            setPanel(searchToggle, searchPanel, false);
            setPanel(notificationToggle, notificationPanel, false);
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.site-menu-toggle').forEach(button => {
        button.addEventListener('click', () => toggleMenu());
    });
    document.querySelectorAll('.quick-nav-language button').forEach(button => {
        button.addEventListener('click', () => {
            document.querySelectorAll('.quick-nav-language button').forEach(item => {
                const active = item === button;
                item.classList.toggle('active', active);
                item.setAttribute('aria-pressed', String(active));
            });
        });
    });
    initSharedHeaderControls();
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            toggleMenu(false);
            toggleSharedBanNotice(false);
            closeSharedNavModals();
            document.querySelectorAll('.shared-account-box').forEach(box => {
                const button = box.querySelector('.shared-account');
                if (button) toggleSharedAccount(button, true);
            });
        }
    });
    document.addEventListener('click', event => {
        const banBell = event.target.closest('.shared-ban-bell');
        const banBadge = event.target.closest('.shared-blocked-badge');
        const banNotice = document.getElementById('sharedBanNotice');
        if (banNotice && !banNotice.hidden && !banBell && !banBadge && !banNotice.contains(event.target)) {
            toggleSharedBanNotice(false);
        }
        document.querySelectorAll('.shared-account-box').forEach(box => {
            if (!box.contains(event.target)) {
                const button = box.querySelector('.shared-account');
                if (button) toggleSharedAccount(button, true);
            }
        });
        const option = event.target.closest('.shared-border-option');
        if (option) {
            setSharedAvatarBorder(option.dataset.borderSrc, true);
            closeSharedNavModals();
        }
        if (event.target.classList?.contains('shared-nav-modal')) closeSharedNavModals();
    });
    const box = document.querySelector('.shared-account-box');
    const userKey = box?.dataset.userKey || 'guest';
    const serverBorder = box?.dataset.avatarBorder;
    let savedId = serverBorder ? serverBorder.split('/').pop().replace(/\.gif$/i, '') : '';
    if (!savedId) {
        try { savedId = localStorage.getItem('avatar-border-v1:' + userKey) || 'normal-01'; } catch (e) { savedId = 'normal-01'; }
    }
    const option = [...document.querySelectorAll('.shared-border-option')].find(item => item.dataset.borderSrc.split('/').pop().replace(/\.gif$/i, '') === savedId);
    if (option) setSharedAvatarBorder(option.dataset.borderSrc, false);
});
