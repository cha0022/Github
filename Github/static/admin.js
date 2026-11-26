// FLOW NOTE: Adds shared admin-side browser controls and confirmation behavior to admin pages.
/* DEBUG NOTE: Admin-only confirmation prompts and page behaviors. */
document.addEventListener('DOMContentLoaded', () => {
    const imagePreviewUrls = new WeakMap();
    document.querySelectorAll('input[type="file"][data-preview-target]').forEach(input => {
        input.addEventListener('change', () => {
            const image = document.getElementById(input.dataset.previewTarget);
            const file = input.files?.[0];
            if (!image || !file) return;
            const previousUrl = imagePreviewUrls.get(image);
            if (previousUrl) URL.revokeObjectURL(previousUrl);
            const nextUrl = URL.createObjectURL(file);
            imagePreviewUrls.set(image, nextUrl);
            image.src = nextUrl;
            image.hidden = false;
        });
    });
    const createAdminToggle = document.querySelector('.ai-admin-create-toggle');
    const createAdminPanel = document.getElementById('createAdminPanel');
    createAdminToggle?.addEventListener('click', () => {
        const open = createAdminPanel.hidden;
        createAdminPanel.hidden = !open;
        createAdminToggle.setAttribute('aria-expanded', String(open));
    });
    const themeButton = document.querySelector('.admin-theme-toggle');
    const savedTheme = localStorage.getItem('admin-theme');
    if (savedTheme === 'light') document.body.classList.add('admin-light');
    document.documentElement.dataset.adminTheme = savedTheme === 'light' ? 'light' : 'dark';
    if (themeButton) themeButton.textContent = document.body.classList.contains('admin-light') ? '☀️' : '🌙';
    themeButton?.addEventListener('click', () => {
        const light = document.body.classList.toggle('admin-light');
        localStorage.setItem('admin-theme', light ? 'light' : 'dark');
        document.documentElement.dataset.adminTheme = light ? 'light' : 'dark';
        themeButton.textContent = light ? '☀️' : '🌙';
    });
    const navToggle = document.querySelector('.admin-menu-toggle');
    const navMenu = document.getElementById('adminNavMenu');
    navToggle?.addEventListener('click', () => {
        const open = navMenu.classList.toggle('is-open');
        navToggle.setAttribute('aria-expanded', String(open));
    });
    const dropdownToggle = document.querySelector('.admin-dropdown-toggle');
    const dropdownMenu = document.querySelector('.admin-dropdown-menu');
    dropdownToggle?.addEventListener('click', () => {
        const open = dropdownMenu.hidden;
        dropdownMenu.hidden = !open;
        dropdownToggle.setAttribute('aria-expanded', String(open));
    });
    const activeModal = document.getElementById('activeUsersModal');
    const activeList = document.getElementById('activeUsersList');
    const closeActiveModal = () => { if (activeModal) activeModal.hidden = true; };
    document.querySelectorAll('.active-users-open').forEach(button => button.addEventListener('click', async () => {
        activeModal.hidden = false;
        if (dropdownMenu) dropdownMenu.hidden = true;
        if (dropdownToggle) dropdownToggle.setAttribute('aria-expanded', 'false');
        activeList.replaceChildren();
        try {
            const response = await fetch('/admin/api/active-users', { headers: { 'Accept': 'application/json' } });
            if (!response.ok) throw new Error('Request failed');
            const data = await response.json();
            if (!data.users.length) { activeList.textContent = 'No users are currently online.'; return; }
            data.users.forEach(user => {
                const card = document.createElement('article'); card.className = 'active-user-card';
                const avatar = document.createElement('img'); avatar.alt = ''; avatar.src = user.profile_picture ? `/site-assets/${user.profile_picture.split('/').filter(Boolean).join('/')}` : '/site-assets/images/default-avatar.png';
                const details = document.createElement('div'); const name = document.createElement('strong'); name.textContent = user.username;
                const status = document.createElement('span'); status.className = 'active-user-status'; status.textContent = '🟢 Online';
                details.append(name, status); card.append(avatar, details); activeList.append(card);
            });
        } catch (error) { activeList.textContent = 'Hindi ma-load ang active users. Subukan ulit.'; }
    }));
    activeModal?.querySelector('.active-users-close')?.addEventListener('click', closeActiveModal);
    activeModal?.addEventListener('click', event => { if (event.target === activeModal) closeActiveModal(); });
    const actionModal = document.getElementById('userActionModal');
    const actionForm = document.getElementById('userActionForm');
    const actionValue = document.getElementById('userActionValue');
    const title = document.getElementById('userModalTitle');
    const editFields = actionModal?.querySelector('.user-edit-fields');
    const moderationFields = actionModal?.querySelector('.user-moderation-fields');
    const permanentBlockOption = moderationFields?.querySelector('[data-permanent-block]');
    const confirmCopy = actionModal?.querySelector('.user-confirm-copy');
    const submit = document.getElementById('userModalSubmit');
    const closeActionModal = () => { if (actionModal) actionModal.hidden = true; };
    document.querySelectorAll('[data-user-action]').forEach(button => button.addEventListener('click', () => {
        const mode = button.dataset.userAction;
        actionForm.action = button.dataset.actionUrl;
        actionValue.value = mode;
        editFields.hidden = mode !== 'edit';
        moderationFields.hidden = !['ban', 'deactivate'].includes(mode);
        if (permanentBlockOption) {
            permanentBlockOption.hidden = mode !== 'deactivate';
            permanentBlockOption.disabled = mode !== 'deactivate';
            if (mode === 'ban' && actionModal.querySelector('[name="duration"]').value === 'permanent') {
                actionModal.querySelector('[name="duration"]').value = '1_day';
            }
        }
        confirmCopy.hidden = !['ban', 'deactivate', 'unban', 'activate', 'delete'].includes(mode);
        document.getElementById('editUsername').value = button.dataset.username || '';
        document.getElementById('editEmail').value = button.dataset.email || '';
        const config = {
            edit: ['✎ EDIT USER', 'SAVE CHANGES', ''],
            ban: ['TEMPORARY BAN', 'CONFIRM BAN', `Pansamantalang hindi makakagamit ng account si ${button.dataset.username} sa napiling tagal.`],
            deactivate: ['BLOCK USER', 'CONFIRM BLOCK', `I-block si ${button.dataset.username} sa napiling tagal. Pumili ng Permanent block kung hindi ito dapat awtomatikong mag-expire.`],
            unban: ['REMOVE BAN', 'UNBAN USER', `Alisin ang ban kay ${button.dataset.username} at ibalik ang account sa active status?`],
            activate: ['UNBLOCK USER', 'UNBLOCK USER', `Payagan ulit si ${button.dataset.username} na magamit ang account?`],
            delete: ['▤ DELETE USER', 'DELETE USER', `Permanenteng burahin si ${button.dataset.username}? Hindi na ito maibabalik.`]
        }[mode];
        title.textContent = config[0]; submit.textContent = config[1]; confirmCopy.textContent = config[2];
        actionModal.hidden = false;
        (mode === 'edit' ? document.getElementById('editUsername') : ['ban', 'deactivate'].includes(mode) ? actionModal.querySelector('select') : submit)?.focus();
    }));
    actionModal?.querySelector('.user-modal-close')?.addEventListener('click', closeActionModal);
    actionModal?.addEventListener('click', event => { if (event.target === actionModal) closeActionModal(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeActionModal(); closeActiveModal(); } });
    document.querySelectorAll('.confirm-delete').forEach(form => {
        form.addEventListener('submit', event => {
            const message = form.dataset.confirmMessage || 'Delete this record?';
            if (!window.confirm(message)) event.preventDefault();
        });
    });
});
