const CACHE_VERSION = 2;
const CACHE_NAME = 'tamagotchi-v' + CACHE_VERSION;

const STATIC_ASSETS = [
    '/static/css/style.css',
    '/pwa/icon/192.png',
    '/pwa/icon/512.png',
];

const CACHEABLE_PATHS = [
    '/dashboard',
    '/leaderboard',
    '/graveyard',
    '/register',
];

// --- Install: pre-cache static assets ---
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// --- Activate: clean old caches, claim clients ---
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

// --- Fetch: network-first for pages, cache-first for static assets ---
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    if (event.request.method !== 'GET') return;

    // Static assets: cache-first
    if (STATIC_ASSETS.includes(url.pathname) || url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(event.request).then((cached) => {
                if (cached) return cached;
                return fetch(event.request).then((response) => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    }
                    return response;
                });
            })
        );
        return;
    }

    // HTML pages: network-first, fall back to cache
    if (event.request.headers.get('Accept')?.includes('text/html') &&
        CACHEABLE_PATHS.some((p) => url.pathname === p || url.pathname.startsWith(p + '/'))) {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    }
                    return response;
                })
                .catch(() => caches.match(event.request))
        );
        return;
    }
});

// --- Push notifications ---
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch {
        data = { title: 'GitHub Tamagotchi', body: event.data ? event.data.text() : '' };
    }

    const title = data.title || 'GitHub Tamagotchi';
    const options = {
        body: data.body || 'Your pet needs attention!',
        icon: data.icon || '/pwa/icon/192.png',
        badge: '/pwa/icon/192.png',
        data: { url: data.url || '/' },
        tag: data.tag || 'tamagotchi-alert',
        renotify: true,
        requireInteraction: false,
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

// --- Notification click: focus or open the target URL ---
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = event.notification.data?.url || '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
            for (const client of windowClients) {
                if (client.url.includes(targetUrl) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});

// --- Periodic background sync: check pet health ---
self.addEventListener('periodicsync', (event) => {
    if (event.tag === 'check-pet-health') {
        event.waitUntil(checkPetHealth());
    }
});

async function checkPetHealth() {
    try {
        const response = await fetch('/api/v1/me/pets?per_page=100');
        if (!response.ok) return;

        const data = await response.json();
        const pets = data.pets || [];

        for (const pet of pets) {
            if (pet.is_dead) continue;

            if (pet.health <= 0 && pet.grace_period_started) {
                await self.registration.showNotification(
                    `⚠️ ${pet.name} is dying!`,
                    {
                        body: `${pet.name} has been at zero health. Push a commit to save it!`,
                        icon: `/api/v1/pets/${pet.repo_owner}/${pet.repo_name}/image/${pet.stage}`,
                        badge: '/pwa/icon/192.png',
                        data: { url: `/pet/${pet.repo_owner}/${pet.repo_name}` },
                        tag: `pet-${pet.repo_owner}-${pet.repo_name}-health`,
                        renotify: false,
                    }
                );
            } else if (pet.health < 40) {
                const moods = {
                    hungry: '🍖',
                    worried: '😟',
                    lonely: '😢',
                    sick: '🤒',
                };
                const emoji = moods[pet.mood] || '😔';
                await self.registration.showNotification(
                    `${emoji} ${pet.name} needs attention`,
                    {
                        body: `Health: ${pet.health}%. Your pet is ${pet.mood || 'unhappy'}.`,
                        icon: `/api/v1/pets/${pet.repo_owner}/${pet.repo_name}/image/${pet.stage}`,
                        badge: '/pwa/icon/192.png',
                        data: { url: `/pet/${pet.repo_owner}/${pet.repo_name}` },
                        tag: `pet-${pet.repo_owner}-${pet.repo_name}-health`,
                        renotify: false,
                    }
                );
            }
        }
    } catch {
        // Network error or not authenticated — silently ignore
    }
}
