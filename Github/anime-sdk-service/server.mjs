// FLOW NOTE: Reads Anime-SDK settings, starts the Node service, and handles provider requests from Flask.
// DEBUG NOTE: Local Node bridge exposes anime-sdk to the Python/Flask app.
import {
  AllmangaProvider,
  AnikotoProvider,
  AnimeParadiseProvider,
  MegaPlayProvider,
  HttpClient,
  AnilistMeta,
  startServer,
} from 'anime-sdk';

const http = new HttpClient({ timeoutMs: 15_000 });
const port = Number.parseInt(process.env.ANIME_SDK_PORT || '3000', 10);
const providers = [
  new AllmangaProvider(http),
  new AnikotoProvider(http),
  new AnimeParadiseProvider(http),
  new MegaPlayProvider(http),
];
const authToken = process.env.ANIME_SDK_TOKEN;

startServer({
  providers,
  metaProviders: [new AnilistMeta(http)],
  port,
  proxy: true,
  proxyBase: process.env.ANIME_SDK_PUBLIC_PROXY_BASE || 'http://127.0.0.1:5000/proxy',
  ...(authToken ? { auth: { token: authToken } } : {}),
  proxyAllowedHosts: [
    'allmanga.to', 'allanime.day', 'allanime.site', 'mp4upload.com', 'wixmp.com',
    'anikototv.to', 'anikoto.cz', 'anikotoapi.site', 'megaplay.buzz',
    'animeparadise.moe',
  ],
});
