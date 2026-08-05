/* HotelSupply Connect — Common JS Module (Themeable Top Navigation) */

const API      = window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1') ? window.location.origin : 'http://localhost:8000';
const MATCHER  = `${API}/proxy/matcher`;
const NOTIFIER = `${API}/proxy/notifier`;

function getSavedTheme() {
  return localStorage.getItem('theme') || 'light';
}

function saveTheme(t) {
  localStorage.setItem('theme', t);
  document.documentElement.setAttribute('data-theme', t);
  updateThemeButtonUI();
}

function toggleTheme() {
  const current = getSavedTheme();
  const next = current === 'dark' ? 'light' : 'dark';
  saveTheme(next);
}

function updateThemeButtonUI() {
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) {
    const isDark = getSavedTheme() === 'dark';
    btn.innerHTML = isDark ? '☀️ Light' : '🌙 Dark';
  }
}

// Immediately apply saved theme on load to avoid flash
(function initTheme() {
  const theme = getSavedTheme();
  document.documentElement.setAttribute('data-theme', theme);
})();

function getSavedToken() {
  return localStorage.getItem('jwt_token');
}

function getSavedRole() {
  return localStorage.getItem('jwt_role') || 'admin';
}

function saveToken(token, role) {
  localStorage.setItem('jwt_token', token);
  localStorage.setItem('jwt_role', role);
  updateAuthUI();
}

function authHeaders(json = true) {
  const token = getSavedToken();
  const h = {};
  if (token) h['Authorization'] = `Bearer ${token}`;
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

async function ensureToken(role = 'admin') {
  if (getSavedToken()) {
    updateAuthUI();
    return getSavedToken();
  }
  return await fetchToken(role, 'admin1');
}

async function fetchToken(role = 'admin', username = 'admin1') {
  try {
    const body = new URLSearchParams({ username, role, password: 'demo123' });
    const r = await fetch(`${API}/auth/token`, { method: 'POST', body });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Auth failed');
    saveToken(d.access_token, role);
    return d.access_token;
  } catch(e) {
    console.error('Failed to get token:', e);
    return null;
  }
}

function updateAuthUI() {
  const badge = document.getElementById('user-badge-role');
  if (badge) {
    const role = getSavedRole();
    badge.textContent = role.toUpperCase();
  }
}

function toast(msg, type = 'ok') {
  let root = document.getElementById('toast-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'toast-root';
    document.body.appendChild(root);
  }
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span class="toast-dot"></span>${msg}`;
  root.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

async function fetchWithTimeout(url, opts = {}, ms = 4000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { ...opts, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(id);
  }
}

// Render modern top navigation header with Theme Toggle Button
function renderNav(activePage = 'dashboard') {
  const items = [
    { key: 'landing', label: 'Home', path: '/' },
    { key: 'dashboard', label: 'Dashboard', path: '/dashboard' },
    { key: 'orders', label: 'Requirements', path: '/orders' },
    { key: 'entities', label: 'Directory', path: '/entities-page' },
    { key: 'events', label: 'Events Stream', path: '/events-page' },
    { key: 'matcher', label: 'Matcher Engine', path: '/matcher-page' },
    { key: 'health', label: 'Health & Security', path: '/health-page' },
  ];

  const isDark = getSavedTheme() === 'dark';

  const headerHTML = `
    <header class="header-nav">
      <div class="header-container">
        <a href="/" class="brand-title">BtoB HotelSupply Connect</a>
        <nav>
          <ul class="nav-menu">
            ${items.map(i => `
              <li>
                <a href="${i.path}" class="nav-link ${activePage===i.key?'active':''}">
                  ${i.label}
                </a>
              </li>
            `).join('')}
          </ul>
        </nav>
        <div class="header-actions">
          <button id="theme-toggle-btn" class="theme-toggle" onclick="toggleTheme()" title="Toggle Dark / Light Mode">
            ${isDark ? '☀️ Light' : '🌙 Dark'}
          </button>
          <div class="pill pill-live">Live</div>
          <a href="/profile" class="role-badge" title="Click to manage Auth & Profile">
            <span class="role-dot"></span><span id="user-badge-role">${getSavedRole().toUpperCase()}</span>
          </a>
          <a href="/docs" target="_blank"><button class="btn btn-ghost btn-sm">Docs ↗</button></a>
        </div>
      </div>
    </header>
  `;

  const footerHTML = `
    <footer>
      <div class="footer-container">
        <div>© 2026 BtoB HotelSupply Connect — Event-Driven B2B Procurement Platform</div>

        <div style="display:flex;gap:16px">
          <a href="/" style="color:var(--color-text-2);text-decoration:none">Home</a>
          <a href="/dashboard" style="color:var(--color-text-2);text-decoration:none">Dashboard</a>
          <a href="/orders" style="color:var(--color-text-2);text-decoration:none">Requirements</a>
          <a href="/profile" style="color:var(--color-text-2);text-decoration:none">Auth &amp; Profile</a>
          <a href="/docs" target="_blank" style="color:var(--color-text-2);text-decoration:none">API Specs</a>
        </div>
      </div>
    </footer>
  `;

  document.body.insertAdjacentHTML('afterbegin', headerHTML);
  document.body.insertAdjacentHTML('beforeend', footerHTML);
}
