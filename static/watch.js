// FLOW NOTE: Connects watch page controls to episode selection, playback, subtitles, and stream fallback behavior.
/*
 * DEBUG NOTE: All episode player behavior lives here, separate from Jinja HTML.
 * Supports direct/HLS video and the configured streaming providers.
 */
document.addEventListener('DOMContentLoaded', () => {
    const video = document.getElementById('episodePlayer');
    const frame = document.getElementById('externalEpisodePlayer');
    const player = video || frame;
    const episodeFilter = document.getElementById('episodeFilter');
    const autoSkip = document.getElementById('autoSkip');
    const autoNext = document.getElementById('autoNext');
    let lastProgressSave = 0;
    let introSkipped = false;
    let outroSkipped = false;
    let latestVidriftTime = 0;
    let pendingVidriftResume = null;

    episodeFilter?.addEventListener('input', event => {
        const query = event.target.value.trim().toLowerCase();
        document.querySelectorAll('.episode-button').forEach(button => {
            const searchText = `${button.dataset.episode || ''} ${button.dataset.search || ''}`.toLowerCase();
            button.hidden = !searchText.includes(query);
        });
    });

    const episodeList = document.querySelector('.episode-list');
    document.querySelectorAll('[data-episode-view]').forEach(button => {
        button.addEventListener('click', () => {
            const view = button.dataset.episodeView;
            episodeList?.classList.toggle('is-grid', view === 'grid');
            episodeList?.classList.toggle('is-list', view === 'list');
            document.querySelectorAll('[data-episode-view]').forEach(tab => {
                const selected = tab === button;
                tab.classList.toggle('active', selected);
                tab.setAttribute('aria-pressed', String(selected));
            });
        });
    });

    if (!player) return;

    const isVidrift = frame?.dataset.playerSource === 'vidrift';
    const playerOrigin = frame?.dataset.playerOrigin || '';
    const vidriftSkipMask = document.getElementById('vidriftSkipMask');
    if (vidriftSkipMask) vidriftSkipMask.hidden = true;

    const sendToPlayer = message => {
        if (!frame || !playerOrigin) return;
        frame.contentWindow.postMessage(message, playerOrigin);
    };

    const saveProgress = (currentTime, duration) => {
        if (!player.dataset.episodeId || !duration || Date.now() - lastProgressSave < 15000) return;
        lastProgressSave = Date.now();
        fetch(player.dataset.progressUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': player.dataset.csrfToken,
            },
            body: JSON.stringify({
                episode_id: Number(player.dataset.episodeId),
                progress: (currentTime / duration) * 100,
                watch_time: String(Math.floor(currentTime)),
                duration: String(Math.floor(duration)),
            }),
        }).catch(error => console.warn('Hindi na-save ang watch progress.', error));
    };

    const skipRange = (kind, currentTime) => {
        const start = Number(player.dataset[`${kind}Start`]);
        const end = Number(player.dataset[`${kind}End`]);
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;

        const alreadySkipped = kind === 'intro' ? introSkipped : outroSkipped;
        if (autoSkip?.checked && !alreadySkipped && currentTime >= start && currentTime < end) {
            if (video) video.currentTime = end;
            else if (isVidrift) {
                sendToPlayer({type: 'vidrift:resume', currentTime: end});
                if (vidriftSkipMask) vidriftSkipMask.hidden = true;
            }
            if (kind === 'intro') introSkipped = true;
            else outroSkipped = true;
        }
        if (currentTime < start) {
            if (kind === 'intro') introSkipped = false;
            else outroSkipped = false;
        }
    };

    const updateVidriftSkipMask = currentTime => {
        if (!vidriftSkipMask || !isVidrift || !autoSkip?.checked || !Number.isFinite(Number(currentTime))) {
            if (vidriftSkipMask) vidriftSkipMask.hidden = true;
            return;
        }
        const position = Number(currentTime);
        const skipButtonExpected = ['intro', 'outro'].some(kind => {
            const start = Number(player.dataset[`${kind}Start`]);
            const end = Number(player.dataset[`${kind}End`]);
            return Number.isFinite(start) && Number.isFinite(end) && end > start && position >= start && position < end;
        });
        vidriftSkipMask.hidden = !skipButtonExpected;
    };

    const handleProgress = (currentTime, duration = 0) => {
        if (!Number.isFinite(Number(currentTime))) return;
        const position = Number(currentTime);
        if (isVidrift) latestVidriftTime = position;
        updateVidriftSkipMask(position);
        skipRange('intro', position);
        skipRange('outro', position);
        if (duration) saveProgress(position, Number(duration));
    };

    const goToNextEpisode = () => {
        const nextUrl = player.dataset.nextUrl;
        if (autoNext?.checked && nextUrl) window.location.assign(nextUrl);
    };

    if (video) {
        if (video.dataset.isHls === '1' && window.Hls && Hls.isSupported()) {
            const hls = new Hls({enableWorker: true, lowLatencyMode: false});
            hls.loadSource(video.dataset.videoSrc);
            hls.attachMedia(video);
        } else if (video.dataset.isHls === '1' && video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = video.dataset.videoSrc;
        }

        video.addEventListener('timeupdate', () => handleProgress(video.currentTime, video.duration));
        video.addEventListener('ended', goToNextEpisode);
        video.addEventListener('error', () => console.error('Unable to play video:', video.currentSrc));
    }

    if (frame) {
        const serverButtons = document.getElementById('externalServerButtons');
        const renderServers = state => {
            if (!serverButtons || !Array.isArray(state.servers)) return;
            serverButtons.replaceChildren();
            state.servers.forEach(server => {
                if (server.value == null || !server.label) return;
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `server-option${String(server.value) === String(state.server) ? ' active' : ''}`;
                button.textContent = server.label;
                button.addEventListener('click', () => sendToPlayer({type: 'vidrift:set', server: server.value}));
                serverButtons.append(button);
            });
            if (!serverButtons.childElementCount) serverButtons.textContent = 'No servers reported.';
        };

        if (isVidrift) {
            frame.addEventListener('load', () => {
                sendToPlayer({type: 'vidrift:get-state'});
                if (pendingVidriftResume !== null) {
                    sendToPlayer({type: 'vidrift:resume', currentTime: pendingVidriftResume});
                    pendingVidriftResume = null;
                }
            });
            sendToPlayer({type: 'vidrift:get-state'});
            autoSkip?.addEventListener('change', () => {
                updateVidriftSkipMask(latestVidriftTime);
                const url = new URL(frame.src);
                const hiddenControls = new Set((url.searchParams.get('hide') || '').split(',').filter(Boolean));
                if (autoSkip.checked) hiddenControls.add('skip');
                else hiddenControls.delete('skip');
                url.searchParams.set('hide', [...hiddenControls].join(','));
                pendingVidriftResume = latestVidriftTime;
                frame.src = url.toString();
            });
        }

        window.addEventListener('message', event => {
            if (event.source !== frame.contentWindow) return;

            if (isVidrift && event.origin === playerOrigin) {
                const message = event.data || {};
                if (message.type === 'vidrift:state') {
                    renderServers(message);
                    handleProgress(message.currentTime, message.duration);
                } else if (message.type === 'vidrift:progress') {
                    handleProgress(message.currentTime, message.duration);
                } else if (message.type === 'vidrift:nextup-play' && autoNext?.checked) {
                    goToNextEpisode();
                } else if (message.type === 'vidrift:episode') {
                    const selectedEpisode = Number(message.anilist?.episode ?? message.episode);
                    if (selectedEpisode > 0) {
                        const url = new URL(window.location.href);
                        url.searchParams.set('episode', String(selectedEpisode));
                        window.location.assign(url.toString());
                    }
                }
            }

            if (frame.dataset.playerOrigin === 'https://megaplay.buzz' && event.origin === frame.dataset.playerOrigin) {
                let message = event.data || {};
                if (typeof message === 'string') {
                    try { message = JSON.parse(message); } catch { return; }
                }
                if (message.channel === 'megacloud' && message.event === 'complete' && autoNext?.checked) {
                    goToNextEpisode();
                }
                if (message.channel === 'megacloud' && message.event === 'time') {
                    handleProgress(message.time, message.duration);
                }
            }

            if (frame.dataset.playerSource === 'anilink' && ['https://anilink.cc', 'https://www.anilink.cc'].includes(event.origin)) {
                const message = event.data || {};
                const payload = message.payload && typeof message.payload === 'object' ? message.payload : {};
                if (message.type === 'anilink-player:progress') {
                    handleProgress(payload.currentTime ?? payload.time, payload.duration);
                }
            }
        });
    }

    document.addEventListener('keydown', event => {
        if (event.target.matches('input, textarea, select')) return;
        if (event.key === 'ArrowLeft' && video) video.currentTime = Math.max(0, video.currentTime - 10);
        if (event.key === 'ArrowRight' && video) video.currentTime = Math.min(video.duration || video.currentTime + 10, video.currentTime + 10);
        if (event.key === ' ' && video) {
            event.preventDefault();
            if (video.paused) video.play();
            else video.pause();
        }
    });
});
