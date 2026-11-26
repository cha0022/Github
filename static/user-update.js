// FLOW NOTE: Handles user profile edit interactions and submits resulting changes to Flask routes.
// DEBUG NOTE: Password strength text follows the requirements checked by app.py.
document.addEventListener('DOMContentLoaded', () => {
    if (document.body.dataset.profileSaved === 'true') {
        window.setTimeout(() => {
            if (window.parent && window.parent !== window) window.parent.location.reload();
        }, 900);
    }
    const password = document.getElementById('password');
    const strength = document.getElementById('strength');
    if (!password || !strength) return;

    const updateStrength = () => {
        const value = password.value;
        if (!value) {
            strength.textContent = 'Password Strength';
            strength.dataset.level = '';
            return;
        }
        const valid = value.length >= 9 && /[a-z]/.test(value) && /[A-Z]/.test(value) && /\d/.test(value) && /[\W_]/.test(value);
        const score = [value.length >= 9, /[a-z]/.test(value), /[A-Z]/.test(value), /\d/.test(value), /[\W_]/.test(value)].filter(Boolean).length;
        strength.textContent = valid ? '🟢 Strong Password' : score >= 3 ? '🟡 Medium Password' : '🔴 Weak Password';
        strength.dataset.level = valid ? 'strong' : score >= 3 ? 'medium' : 'weak';
    };
    password.addEventListener('input', updateStrength);
});
