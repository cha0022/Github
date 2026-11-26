// FLOW NOTE: Loads integration status and wires admin metadata and stream preview actions.
// DEBUG NOTE: Shows automatic AniList catalog status and resolves SDK episodes/streams.
document.addEventListener('DOMContentLoaded', () => {
    const sdkForm = document.getElementById('sdkSearchForm');
    const sdkInput = document.getElementById('sdkQuery');
    const sdkProvider = document.getElementById('sdkProvider');
    const sdkResults = document.getElementById('sdkResults');
    const sdkEpisodes = document.getElementById('sdkEpisodes');
    const sdkPlayer = document.getElementById('sdkPlayer');
    const sdkVideo = document.getElementById('sdkVideo');
    const note = document.getElementById('sdkPlayerNote');
    let sdkHls = null;
    const h = (tag, cls, value) => { const el = document.createElement(tag); if (cls) el.className = cls; if (value !== undefined) el.textContent = value; return el; };

    sdkForm?.addEventListener('submit', async event => {
        event.preventDefault(); sdkEpisodes.hidden=true; sdkPlayer.hidden=true; sdkResults.replaceChildren(h('p','integration-hint','Hinahanap sa Anime-SDK…'));
        try {
            const provider=sdkProvider.value;
            const response=await fetch(`/api/anime-sdk/search?q=${encodeURIComponent(sdkInput.value.trim())}&provider=${encodeURIComponent(provider)}`);
            const payload=await response.json(); if(!response.ok) throw new Error(payload.error || 'Hindi maabot ang Anime-SDK service.');
            sdkResults.replaceChildren();
            if(!payload.items.length){sdkResults.append(h('p','integration-hint','Walang nahanap na resulta sa provider na ito.'));return;}
            payload.items.forEach(item=>{
                const card=h('article','sdk-result'); const info=h('div'); info.append(h('h3','',item.title)); info.append(h('p','',`${item.providerId || provider} · ${(item.availableLanguages || []).join(' / ') || 'language varies'}`));
                const button=h('button','', 'Load episodes'); button.type='button'; button.addEventListener('click',()=>loadEpisodes(provider,item)); card.append(info,button); sdkResults.append(card);
            });
        } catch(error){sdkResults.replaceChildren(h('p','integration-hint',error.message));}
    });

    async function loadEpisodes(provider, anime) {
        sdkEpisodes.hidden=false; sdkEpisodes.replaceChildren(h('p','integration-hint','Kinukuha ang episode list…'));
        try {
            const getEpisodes = async (source, id) => {
                const response=await fetch(`/api/anime-sdk/content?provider=${encodeURIComponent(source)}&media_id=${encodeURIComponent(id)}`);
                const payload=await response.json();
                if(!response.ok) throw new Error(payload.error || 'Hindi nakuha ang episodes.');
                return payload.items || [];
            };
            let episodeProvider=provider;
            let episodes=await getEpisodes(provider,anime.id);

            // DEBUG NOTE: Some providers return partial episode lists. Prefer a fuller exact-title match when available.
            if(episodes.length<10){
                const normalize=value=>String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
                const providers=['animeparadise','allmanga','anikoto','megaplay'].filter(item=>item!==provider);
                for(const candidate of providers){
                    try{
                        const searchResponse=await fetch(`/api/anime-sdk/search?q=${encodeURIComponent(anime.title)}&provider=${encodeURIComponent(candidate)}`);
                        const searchPayload=await searchResponse.json();
                        if(!searchResponse.ok)continue;
                        const exact=(searchPayload.items||[]).find(item=>normalize(item.title)===normalize(anime.title));
                        if(!exact)continue;
                        const candidateEpisodes=await getEpisodes(candidate,exact.id);
                        if(candidateEpisodes.length>episodes.length){episodes=candidateEpisodes;episodeProvider=candidate;}
                        if(episodes.length>=10)break;
                    }catch(_error){ /* Keep the best provider list already found. */ }
                }
            }
            sdkEpisodes.replaceChildren();
            if(episodeProvider!==provider)sdkEpisodes.append(h('p','integration-hint',`Mas kumpletong episode list mula sa ${episodeProvider}.`));
            episodes.forEach(episode=>{const button=h('button','sdk-episode-button',episode.title || `Episode ${episode.number}`);button.type='button';button.addEventListener('click',()=>loadStream(episodeProvider,episode,anime.title));sdkEpisodes.append(button);});
            if(!episodes.length)sdkEpisodes.append(h('p','integration-hint','Walang episodes para sa palabas na ito sa mga provider.'));
        } catch(error){sdkEpisodes.replaceChildren(h('p','integration-hint',error.message));}
    }

    async function loadStream(provider, episode, animeTitle) {
        sdkPlayer.hidden=false; note.textContent='Nire-resolve ang stream…'; sdkHls?.destroy(); sdkHls=null; sdkVideo.removeAttribute('src'); sdkVideo.load();
        try {
            const response=await fetch(`/api/anime-sdk/stream?provider=${encodeURIComponent(provider)}&unit_id=${encodeURIComponent(episode.id)}&language=sub&title=${encodeURIComponent(animeTitle)}&episode_number=${encodeURIComponent(episode.number)}`);
            const payload=await response.json(); if(!response.ok) throw new Error(payload.error || 'Walang stream.');
            const stream=payload.streams?.[0]; if(!stream?.sourceUrl) throw new Error('Walang available na video source.');
            sdkVideo.querySelectorAll('track').forEach(track=>track.remove());
            (stream.subtitles||[]).forEach((subtitle,index)=>{
                if(!subtitle.url)return;
                const track=document.createElement('track');
                track.kind='subtitles'; track.src=subtitle.url;
                track.srclang=subtitle.language||'en'; track.label=subtitle.label||subtitle.language||`Subtitle ${index+1}`;
                track.default=index===0; sdkVideo.append(track);
            });
            if (window.Hls?.isSupported()) {
                sdkHls=new Hls();
                sdkHls.on(Hls.Events.ERROR,(_event,data)=>{
                    if(data.fatal)note.textContent=`Hindi ma-play ang stream (${data.details||'HLS error'}). Sumubok ng ibang provider.`;
                });
                sdkHls.loadSource(stream.sourceUrl); sdkHls.attachMedia(sdkVideo);
            }
            else { sdkVideo.src=stream.sourceUrl; sdkVideo.load(); }
            note.textContent=`${episode.title || 'Episode'} · ${stream.quality || 'Auto'}${payload.fallback ? ` · stream mula sa ${payload.provider}` : ''}`;
        } catch(error){note.textContent=error.message;}
    }
});
