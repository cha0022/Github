// FLOW NOTE: Runs shared site interactions after page load, including base navigation and common controls.
// DEBUG NOTE: Shared menu and sign-in dialogs for the Flask templates.
document.addEventListener('DOMContentLoaded', () => {
    const menuButton = document.querySelector('.menu-toggle');
    const mobileMenu = document.querySelector('.mobile-menu');
    menuButton?.addEventListener('click', () => {
        const open = mobileMenu.hidden;
        mobileMenu.hidden = !open;
        menuButton.setAttribute('aria-expanded', String(open));
    });

    const backdrop = document.getElementById('authBackdrop');
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const showAuth = (mode) => {
        if (!backdrop) return;
        backdrop.hidden = false;
        const register = mode === 'register';
        loginForm.hidden = register;
        registerForm.hidden = !register;
        backdrop.querySelector('.auth-modal')?.setAttribute('aria-labelledby', register ? 'registerTitle' : 'authTitle');
        document.querySelectorAll('[data-auth-tab]').forEach(tab => tab.classList.toggle('active', tab.dataset.authTab === mode));
        (register ? registerForm : loginForm).querySelector('input:not([type=hidden])')?.focus();
    };
    document.querySelectorAll('[data-auth-open]').forEach(button => button.addEventListener('click', () => showAuth(button.dataset.authOpen)));
    document.querySelectorAll('[data-auth-tab]').forEach(button => button.addEventListener('click', () => showAuth(button.dataset.authTab)));
    document.querySelectorAll('[data-auth-close]').forEach(button => button.addEventListener('click', () => { backdrop.hidden = true; }));
    backdrop?.addEventListener('click', event => { if (event.target === backdrop) backdrop.hidden = true; });
    if (new URLSearchParams(location.search).get('login') === '1') showAuth('login');

    document.getElementById('randomAnime')?.addEventListener('click', async () => {
        try {
            const response = await fetch('/api/random-anime');
            const result = await response.json();
            if (result.id) location.assign(`/watch?anime_id=${result.id}`);
        } catch (error) {
            console.warn('Hindi makapili ng random anime.', error);
        }
    });

    const notificationButton = document.getElementById('newAnimeToggle');
    const notificationPanel = document.getElementById('newAnimePanel');
    const notificationItems = document.getElementById('newAnimeItems');
    // The unchanged original navigation script handles notifications on the shared header.
    if (!document.querySelector('.shared-site-header') && notificationButton && notificationPanel && notificationItems) {
        const username = document.querySelector('.nav-user')?.textContent.trim() || 'user';
        const storageKey = `hianime:last-anime:${username}`;
        const lastSeen = Number(localStorage.getItem(storageKey) || 0);
        fetch(`/home?user_api=new_anime&since=${lastSeen}`)
            .then(response => response.json())
            .then(data => {
                const items = data.items || [];
                if (!items.length) {
                    notificationItems.innerHTML = '<p>No new anime yet.</p>';
                    return;
                }
                notificationItems.replaceChildren(...items.map(item => {
                    const link = document.createElement('a');
                    link.href = `/watch?anime_id=${item.id}`;
                    link.textContent = item.title;
                    return link;
                }));
                const latestId = Math.max(...items.map(item => Number(item.id)));
                const badge = document.getElementById('newAnimeBadge');
                badge.textContent = String(items.length);
                badge.hidden = false;
                notificationButton.addEventListener('click', () => {
                    const open = notificationPanel.hidden;
                    notificationPanel.hidden = !open;
                    notificationButton.setAttribute('aria-expanded', String(open));
                    if (open) {
                        localStorage.setItem(storageKey, String(latestId));
                        badge.hidden = true;
                    }
                });
            })
            .catch(error => {
                notificationItems.innerHTML = '<p>Hindi ma-load ang notifications.</p>';
                console.warn('Hindi na-load ang anime notifications.', error);
            });
    }
});
