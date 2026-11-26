// FLOW NOTE: Connects community filters, sorting, reactions, and post interactions to the rendered page.
/* DEBUG NOTE: Community filters, sorting, and reactions run on this page. */
document.addEventListener('DOMContentLoaded', () => {
    const posts = [...document.querySelectorAll('.community-post')];
    const board = document.querySelector('.community-board');
    const currentUser = board?.dataset.currentUser || 'Charles';
    const empty = document.getElementById('empty');
    let activeCategory = 'all';
    let mineOnly = false;

    const filterPosts = () => {
        const query = document.getElementById('postSearch')?.value.trim().toLowerCase() || '';
        let visibleCount = 0;
        posts.forEach(post => {
            const matchesCategory = activeCategory === 'all' || post.dataset.category === activeCategory;
            const matchesAuthor = !mineOnly || post.dataset.author === currentUser;
            const matchesQuery = !query || post.innerText.toLowerCase().includes(query);
            post.hidden = !(matchesCategory && matchesAuthor && matchesQuery);
            if (!post.hidden) visibleCount += 1;
        });
        if (empty) empty.hidden = visibleCount > 0;
    };

    document.getElementById('globalSearch')?.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        document.getElementById('postSearch').value = event.currentTarget.value;
        filterPosts();
        document.getElementById('postSearch').focus();
    });

    document.querySelectorAll('.community-category').forEach(button => {
        button.addEventListener('click', () => {
            document.querySelectorAll('.community-category').forEach(item => item.classList.toggle('active', item === button));
            activeCategory = button.dataset.category;
            filterPosts();
        });
    });

    document.getElementById('postSearch')?.addEventListener('input', filterPosts);
    document.getElementById('myPosts')?.addEventListener('click', event => {
        mineOnly = !mineOnly;
        event.currentTarget.classList.toggle('active', mineOnly);
        filterPosts();
    });

    document.getElementById('sortPosts')?.addEventListener('change', event => {
        const sorted = [...posts].sort((a, b) => event.target.value === 'popular' ? Number(b.dataset.score) - Number(a.dataset.score) : 0);
        const list = document.getElementById('posts');
        sorted.forEach(post => list.insertBefore(post, empty));
    });

    document.querySelectorAll('.like').forEach(button => {
        button.addEventListener('click', () => {
            button.classList.toggle('liked');
            const count = button.querySelector('span');
            const change = button.classList.contains('liked') ? 1 : -1;
            count.textContent = String(Math.max(0, Number(count.textContent) + change));
        });
    });

    document.getElementById('createPost')?.addEventListener('click', () => {
        window.alert('Post creation is not connected to the database yet.');
    });
});
