/**
 * FunnelBarn analytics — typed event definitions and safe tracking helpers.
 * BugBarn client-side logging — ships warnings/errors to BugBarn logs API.
 *
 * Every tracked event is defined in FB_EVENTS. Callers use:
 *   fbTrack(FB_EVENTS.PET_FED, { owner: '…', repo: '…' })
 *
 * If the SDK fails to load or throws, a warning is sent to BugBarn.
 * Calls before the SDK is ready are queued and replayed once it loads.
 */

// ── BugBarn client-side logger ──────────────────────────────────────────────

var _bbLogQueue = [];
var _bbFlushTimer = null;

function _bbFlush() {
    var cfg = window.__bugbarn;
    if (!cfg || !cfg.endpoint || !cfg.apiKey) return;
    var batch = _bbLogQueue.splice(0);
    if (batch.length === 0) return;

    var url = cfg.endpoint.replace(/\/+$/, '') + '/api/v1/logs';
    var body = JSON.stringify({ logs: batch });
    try {
        fetch(url, {
            method: 'POST',
            headers: {
                'content-type': 'application/json',
                'x-bugbarn-api-key': cfg.apiKey,
                'x-bugbarn-project': cfg.project
            },
            body: body,
            keepalive: true
        }).catch(function() {});
    } catch (e) {}
}

function _bbEnqueue(entry) {
    _bbLogQueue.push(entry);
    if (_bbFlushTimer) clearTimeout(_bbFlushTimer);
    _bbFlushTimer = setTimeout(_bbFlush, 2000);
}

function bbLog(level, message, extra) {
    var entry = {
        timestamp: new Date().toISOString(),
        level: level,
        event: message,
        source: 'client',
        url: window.location.href,
        user_agent: navigator.userAgent
    };
    if (extra) {
        for (var k in extra) {
            if (extra.hasOwnProperty(k)) entry[k] = extra[k];
        }
    }
    _bbEnqueue(entry);
}

window.addEventListener('beforeunload', _bbFlush);

// Global error handler
window.addEventListener('error', function(e) {
    bbLog('warning', 'unhandled_error', {
        error_message: e.message,
        filename: e.filename,
        lineno: e.lineno,
        colno: e.colno
    });
});

// Global promise rejection handler
window.addEventListener('unhandledrejection', function(e) {
    bbLog('warning', 'unhandled_promise_rejection', {
        error_message: e.reason ? (e.reason.message || String(e.reason)) : 'unknown'
    });
});

// ── FunnelBarn event definitions ────────────────────────────────────────────

var FB_EVENTS = Object.freeze({
    // Auth
    LOGIN_STARTED:        'login_started',
    LOGOUT:               'logout',

    // Registration
    REPO_SELECTED:        'repo_selected',
    PET_ADOPTED:          'pet_adopted',
    REGISTRATION_COMPLETE:'registration_complete',

    // Pet actions
    PET_FED:              'pet_fed',
    PET_RESURRECTED:      'pet_resurrected',
    PET_DELETED:          'pet_deleted',

    // Social / sharing
    COMMENT_POSTED:       'comment_posted',
    LINK_COPIED:          'link_copied',
    BADGE_EMBED_COPIED:   'badge_embed_copied',
    EMBED_COPIED:         'embed_copied',
    SHARED_TWITTER:       'shared_twitter',
    MILESTONE_SHARED_TWITTER: 'milestone_shared_twitter',
    MILESTONE_LINK_COPIED:'milestone_link_copied',

    // Graveyard
    FLOWER_PLACED:        'flower_placed',
    EULOGY_SAVED:         'eulogy_saved',

    // PWA
    PWA_INSTALL_PROMPTED: 'pwa_install_prompted',
    PWA_INSTALLED:        'pwa_installed',
    PWA_INSTALL_DISMISSED:'pwa_install_dismissed',

    // Push notifications
    PUSH_SUBSCRIBED:      'push_subscribed',
    PUSH_SUBSCRIBED_ALL:  'push_subscribed_all',

    // Onboarding
    ONBOARDING_DISMISSED: 'onboarding_dismissed',

    // Pet admin
    PET_SETTINGS_SAVED:   'pet_settings_saved',
    CONTRIBUTOR_EXCLUDED:  'contributor_excluded',
    CONTRIBUTOR_UNEXCLUDED:'contributor_unexcluded',
    ADMIN_PET_RESET:      'admin_pet_reset',
    ADMIN_PET_DELETED:    'admin_pet_deleted',
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function fbPetProps(owner, repo, extra) {
    var props = { owner: owner, repo: repo };
    if (extra) {
        for (var k in extra) {
            if (extra.hasOwnProperty(k)) props[k] = extra[k];
        }
    }
    return props;
}

// SDK loads with defer — queue calls until it's ready, then replay.
var _fbQueue = [];
var _fbReady = false;
var _fbSdkExpected = false;
var _fbSdkWarnSent = false;

window.fbTrack = function(name, props) {
    if (_fbReady && window.FunnelBarn) {
        try { FunnelBarn.track(name, props); } catch(e) {
            bbLog('warning', 'funnelbarn_track_error', { event_name: name, error_message: e.message });
        }
    } else if (_fbSdkExpected) {
        _fbQueue.push({ type: 'track', name: name, props: props });
    }
};

window.fbIdentify = function(userId) {
    if (_fbReady && window.FunnelBarn) {
        try { FunnelBarn.identify(userId); } catch(e) {
            bbLog('warning', 'funnelbarn_identify_error', { error_message: e.message });
        }
    } else if (_fbSdkExpected) {
        _fbQueue.push({ type: 'identify', userId: userId });
    }
};

// Called once the page (and deferred scripts) have loaded.
// If the SDK script tag is present but FunnelBarn isn't on window, it failed.
function _fbInit() {
    _fbSdkExpected = !!document.querySelector('script[data-api-key][src*="funnelbarn"]');
    if (!_fbSdkExpected) return;

    if (window.FunnelBarn) {
        _fbReady = true;
        for (var i = 0; i < _fbQueue.length; i++) {
            var item = _fbQueue[i];
            try {
                if (item.type === 'track') FunnelBarn.track(item.name, item.props);
                else if (item.type === 'identify') FunnelBarn.identify(item.userId);
            } catch(e) {
                bbLog('warning', 'funnelbarn_replay_error', { event_name: item.name, error_message: e.message });
            }
        }
        _fbQueue = [];
    } else {
        bbLog('warning', 'funnelbarn_sdk_failed_to_load', {
            queued_events: _fbQueue.length
        });
    }
}

if (document.readyState === 'complete') {
    _fbInit();
} else {
    window.addEventListener('load', _fbInit);
}
