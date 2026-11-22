/* FinMate shared helper. The Flask backend is the source of truth; the browser keeps a copy so pages work as before.
   - Universal theme synchronization (dark / light / system across all pages)
   - FM.requireLogin()  : send the visitor to login.html if there is no token
   - FM.sync*()         : save to the server (survives page navigation)
   - FM.hydrate()       : after login, copy the server's data into this browser's storage            */
(function () {
  /* ---- Universal FinMate Theme Management (Light, Dark, System) ---- */
  const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function getThemePref() {
    try { return localStorage.getItem('fm-theme') || 'system'; } catch (e) { return 'system'; }
  }
  function resolveEffective(t) {
    if (t === 'dark') return 'dark';
    if (t === 'light') return 'light';
    return (mq && mq.matches) ? 'dark' : 'light';
  }
  function applyTheme(t) {
    const eff = resolveEffective(t);
    const root = document.documentElement;
    root.setAttribute('data-eff', eff);
    root.setAttribute('data-theme', eff);
    if (eff === 'dark') root.classList.add('dark');
    else root.classList.remove('dark');
  }

  // Apply theme immediately as soon as script is parsed
  applyTheme(getThemePref());

  if (mq) {
    mq.addEventListener('change', function () {
      if (getThemePref() === 'system') applyTheme('system');
    });
  }
  window.addEventListener('storage', function (e) {
    if (e.key === 'fm-theme') applyTheme(e.newValue || 'system');
  });

  function ensureThemeCss() {
    if (!document.querySelector('link[href*="theme.css"]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'theme.css';
      document.head.appendChild(link);
    }
  }
  if (document.head) ensureThemeCss();
  else document.addEventListener('DOMContentLoaded', ensureThemeCss);

  const LOGIN = 'login.html';
  const token = () => { try { return localStorage.getItem('token'); } catch (e) { return null; } };
  const headers = () => Object.assign({ 'Content-Type': 'application/json' }, token() ? { Authorization: 'Bearer ' + token() } : {});

  const DISPLAY = { student: 'Student', salaried_employee: 'Salaried Employee', freelancer: 'Freelancer', business_owner: 'Business Owner', homemaker: 'Homemaker' };
  const TAG = { salaried_employee: 'salaried', business_owner: 'business' };   // the name each category page uses for its persona

  async function get(path) {
    const r = await fetch('/api' + path, { headers: headers() });
    if (r.status === 401) { location.replace(LOGIN); throw new Error('Not signed in'); }
    if (!r.ok) throw new Error('Server returned ' + r.status);
    return r.json();
  }

  /* ---- saving: latest value wins, sent right away or after a short pause; keepalive lets it finish even if the page changes ---- */
  const pending = {}, timers = {};
  function queue(name, path, body, delay) {
    pending[name] = { path: path, body: body };
    clearTimeout(timers[name]);
    if (delay) timers[name] = setTimeout(function () { flush(name); }, delay); else flush(name);
  }
  function flush(name) {
    const p = pending[name]; if (!p) return;
    delete pending[name]; clearTimeout(timers[name]);
    if (!token()) return;
    fetch('/api' + p.path, { method: 'PUT', headers: headers(), body: JSON.stringify(p.body), keepalive: true })
      .then(function (r) { if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) { console.warn('FinMate: could not save ' + p.path + ': ' + (j.error || r.status)); }); })
      .catch(function (e) { console.warn('FinMate: could not reach the server', e); });
  }
  window.addEventListener('pagehide', function () { Object.keys(pending).forEach(flush); });

  function clearLocal() {
    try { Object.keys(localStorage).filter(function (k) { return k.indexOf('finmate_') === 0; }).forEach(function (k) { localStorage.removeItem(k); }); } catch (e) {}
  }

  async function hydrate() {
    const res = await Promise.all([get('/funds'), get('/expenses'), get('/goals'), get('/settings').catch(() => null)]);
    const funds = res[0], expenses = res[1], goals = res[2], settings = res[3];
    clearLocal();
    const set = function (k, v) { try { localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v)); } catch (e) {} };
    if (funds.persona) set('finmate_persona', DISPLAY[funds.persona] || funds.persona);
    if (funds.minimum_monthly_funds != null) set('finmate_min_floor', String(funds.minimum_monthly_funds));
    if (funds.ui_key && funds.ui_value) set(funds.ui_key, funds.ui_value);
    if (expenses.length) set('finmate_expenses', { persona: TAG[funds.persona] || funds.persona, entries: expenses });
    if (goals.length) set('finmate_goals', goals);
    if (settings && settings.theme) {
      try { localStorage.setItem('fm-theme', settings.theme); } catch (e) {}
      applyTheme(settings.theme);
    }
  }

  // Also sync theme from server if token exists
  if (token()) {
    fetch('/api/settings', { headers: headers() })
      .then(r => r.ok ? r.json() : null)
      .then(s => {
        if (s && s.theme) {
          try { localStorage.setItem('fm-theme', s.theme); } catch (e) {}
          applyTheme(s.theme);
        }
      })
      .catch(() => {});
  }

  /* A small notice for people who have not confirmed their email yet */
  const QUIET_PAGES = ['', 'index.html', 'login.html', 'signup.html', 'forgot.html', 'reset.html', 'verify.html', 'legal.html',
    /* the set-up steps stay clear of notices */ 'persona.html', 'Efunds.html', 'Sfunds.html', 'freefunds.html', 'hfunds.html', 'buisfunds.html',
    'employee_category.html', 'student_category.html', 'freelancer_category.html', 'homemaker_category.html', 'business_category.html', 'goals.html'];
  function verifyBanner() {
    const page = location.pathname.split('/').pop();
    if (!token() || QUIET_PAGES.indexOf(page) !== -1) return;
    try { if (sessionStorage.getItem('fm_verify_dismissed')) return; } catch (e) {}
    fetch('/api/auth/status', { headers: headers() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s && !s.email_verified) showBanner(s.email); })
      .catch(function () {});
  }
  function showBanner(email) {
    const bar = document.createElement('div');
    bar.setAttribute('role', 'status');
    /* a normal strip at the very top of the page, so it never covers buttons */
    bar.style.cssText = 'display:flex;gap:.7rem;align-items:center;justify-content:center;flex-wrap:wrap;width:100%;box-sizing:border-box;' +
      'background:#fff6cc;color:#1f1a08;border-bottom:2px solid #1f1a08;padding:.55rem 1rem;font:600 14px/1.4 system-ui,Segoe UI,sans-serif;position:relative;z-index:50';
    const text = document.createElement('span');
    text.textContent = 'Please verify your email address (' + email + ').';
    const resend = document.createElement('button');
    resend.textContent = 'Resend email';
    resend.style.cssText = 'font:700 13px system-ui,sans-serif;border:2px solid #1f1a08;background:#ffc72c;color:#1f1a08;border-radius:999px;padding:.35rem .8rem;cursor:pointer';
    resend.onclick = function () {
      resend.disabled = true;
      fetch('/api/auth/resend-verification', { method: 'POST', headers: headers() })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (j) { text.textContent = j.message || j.error || 'Please try again later.'; resend.remove(); });
    };
    const close = document.createElement('button');
    close.textContent = '✕'; close.setAttribute('aria-label', 'Dismiss');
    close.style.cssText = 'border:0;background:none;font-size:16px;cursor:pointer;color:#1f1a08';
    close.onclick = function () { try { sessionStorage.setItem('fm_verify_dismissed', '1'); } catch (e) {} bar.remove(); };
    bar.appendChild(text); bar.appendChild(resend); bar.appendChild(close);
    document.body.insertBefore(bar, document.body.firstChild);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', verifyBanner); else verifyBanner();

  window.FM = {
    token: token, get: get, hydrate: hydrate, clearLocal: clearLocal, flush: flush,
    applyTheme: applyTheme, getTheme: getThemePref,
    requireLogin: function () { if (!token()) location.replace(LOGIN); },
    syncFunds: function (obj, uiKey) { queue('funds', '/funds', Object.assign({}, obj, { _ui_key: uiKey }), 0); },
    syncExpenses: function (list) { queue('expenses', '/expenses', { entries: list }, 600); },
    syncGoals: function (list) { queue('goals', '/goals', list, 0); }
  };
})();
