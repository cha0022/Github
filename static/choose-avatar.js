// FLOW NOTE: Handles avatar selection and form feedback before the profile update is submitted.
// DEBUG NOTE: After avatar save, update the account avatar in the parent page without opening the full profile.
document.addEventListener('DOMContentLoaded', () => {
    const saved = document.getElementById('avatarSavedState');
    if (saved?.dataset.avatarSaved !== '1' || window.parent === window) return;

    const selected = document.querySelector('.avatar-list input:checked + img');
    if (!selected) return;

    try {
        window.parent.document
            .querySelectorAll('.shared-account-box .profile-image')
            .forEach(image => { image.src = selected.src; });
    } catch (error) {
        console.warn('Hindi na-refresh ang avatar sa navbar.', error);
    }
});
