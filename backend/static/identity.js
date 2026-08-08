/* Who this browser is, for a login-free public deployment.
 *
 * The pages used to hardcode `elder-demo` / `daughter-demo`. That is fine on a
 * laptop but wrong on a public URL: every visitor lands in the same family, so
 * two people looking at once see each other's reminders and can overwrite each
 * other's tasks. `POST /v2/auth/visitor` seeds a fresh household per browser;
 * family isolation is enforced on family_id server-side, so the sandbox is real.
 *
 * Loaded as a classic script (not a module) because care.js, trust.js and
 * judge.js are classic scripts too. Classic scripts run before deferred modules,
 * so elder.js can still `await YouHuoIdentity.ready()`.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'youhuo_visitor_identity_v1';

  // Falls back to the original fixed household when the visitor endpoint is not
  // available — demo mode off, or an older server. The app then behaves exactly
  // as it did before this file existed rather than failing to load.
  const SHARED = Object.freeze({
    elderId: 'elder-demo',
    daughterId: 'daughter-demo',
    sonId: 'son-demo',
    systemId: 'system-demo',
    familyId: 'fam-demo',
    elderToken: null,
    familyToken: null,
    isolated: false,
  });

  function readCached() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && parsed.elderId ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  async function provision() {
    const cached = readCached();
    if (cached) return cached;
    let response;
    try {
      response = await fetch('/v2/auth/visitor', {method: 'POST'});
    } catch (_) {
      return SHARED;               // offline or blocked: stay usable
    }
    if (!response.ok) return SHARED;
    const data = await response.json();
    const identity = {
      elderId: data.elder_id,
      daughterId: data.daughter_id,
      sonId: data.son_id,
      // The visitor endpoint does not mint a system token; that actor exists for
      // audit attribution only, and pages that need it derive the id.
      systemId: data.elder_id.replace(/^elder-/, 'system-'),
      familyId: data.family_id,
      elderToken: data.elder_token,
      familyToken: data.family_token,
      isolated: true,
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
    } catch (_) {
      // Private browsing: the sandbox simply will not survive a reload.
    }
    return identity;
  }

  // Started eagerly so the first page render is not waiting on a round trip,
  // and memoised so five concurrent callers do not seed five households.
  const pending = provision();

  window.YouHuoIdentity = {
    ready: () => pending,
    /** Drop this browser's sandbox; the next load gets a brand new one. */
    reset() {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch (_) { /* nothing to clear */ }
    },
  };
})();
