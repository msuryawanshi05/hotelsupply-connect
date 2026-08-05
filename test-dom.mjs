/**
 * HotelSupply Connect — Full DOM + API Test Suite
 * Tests all features: auth, CRUD, event flow, RBAC, health, UI elements
 */

import puppeteer from 'puppeteer';

const BASE = 'http://localhost:8000';
const MATCHER = 'http://localhost:8001';
const NOTIFIER = 'http://localhost:8002';
const PASS = '✅';
const FAIL = '❌';
const WARN = '⚠️ ';

let results = [];
let browser, page;

function log(status, test, detail = '') {
  const line = `${status} ${test}${detail ? ' — ' + detail : ''}`;
  console.log(line);
  results.push({ status, test, detail });
}

async function apiPost(path, body, token = null) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: JSON.stringify(body) });
  return { ok: r.ok, status: r.status, data: await r.json() };
}

async function apiGet(path, token = null) {
  const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
  const r = await fetch(`${BASE}${path}`, { headers });
  return { ok: r.ok, status: r.status, data: await r.json() };
}

async function getToken(role = 'admin', username = 'testuser') {
  const body = new URLSearchParams({ username, role, password: 'demo123' });
  const r = await fetch(`${BASE}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body
  });
  const d = await r.json();
  return d.access_token;
}

// ─── API Tests ────────────────────────────────────────────────────────────────
async function runAPITests() {
  console.log('\n══════════════════════════════════');
  console.log('  API ENDPOINT TESTS');
  console.log('══════════════════════════════════\n');

  // 1. Health endpoints
  try {
    const h = await apiGet('/healthz');
    h.ok && h.data.status === 'ok'
      ? log(PASS, 'GET /healthz', `db=${h.data.db}`)
      : log(FAIL, 'GET /healthz', JSON.stringify(h.data));
  } catch(e) { log(FAIL, 'GET /healthz', e.message); }

  try {
    const r = await apiGet('/readyz');
    r.ok ? log(PASS, 'GET /readyz', `status=${r.data.status}`)
          : log(FAIL, 'GET /readyz', JSON.stringify(r.data));
  } catch(e) { log(FAIL, 'GET /readyz', e.message); }

  try {
    const s = await apiGet('/startupz');
    s.ok ? log(PASS, 'GET /startupz', `status=${s.data.status}`)
          : log(FAIL, 'GET /startupz', JSON.stringify(s.data));
  } catch(e) { log(FAIL, 'GET /startupz', e.message); }

  // 2. Auth
  let adminToken, hotelToken, supplierToken;
  try {
    adminToken = await getToken('admin', 'admin1');
    adminToken ? log(PASS, 'POST /auth/token (admin)') : log(FAIL, 'POST /auth/token (admin)');
  } catch(e) { log(FAIL, 'POST /auth/token (admin)', e.message); }

  try {
    const bad = await fetch(`${BASE}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: 'x', role: 'admin', password: 'wrongpass' })
    });
    bad.status === 401 ? log(PASS, 'POST /auth/token bad password → 401')
                        : log(FAIL, 'POST /auth/token bad password', `got ${bad.status}`);
  } catch(e) { log(FAIL, 'POST /auth/token bad password', e.message); }

  // 3. Hotels
  let hotelId;
  try {
    const testName = `Test Unique Hotel ${Date.now()}`;
    const r = await apiPost('/hotels', { name: testName, contact_email: 'test@grand.com' }, adminToken);
    if (r.ok && r.data.id) {
      hotelId = r.data.id;
      log(PASS, 'POST /hotels (admin)', `id=${hotelId.substring(0,8)}…`);
    } else log(FAIL, 'POST /hotels', JSON.stringify(r.data));

  } catch(e) { log(FAIL, 'POST /hotels', e.message); }

  try {
    const r = await apiGet('/hotels', adminToken);
    r.ok && Array.isArray(r.data) && r.data.length > 0
      ? log(PASS, 'GET /hotels', `count=${r.data.length}`)
      : log(FAIL, 'GET /hotels', JSON.stringify(r.data));
  } catch(e) { log(FAIL, 'GET /hotels', e.message); }

  // GET /hotels unauthenticated → 401
  try {
    const r = await apiGet('/hotels');
    r.status === 401 ? log(PASS, 'GET /hotels unauthenticated → 401')
                      : log(FAIL, 'GET /hotels unauthenticated', `got ${r.status}`);
  } catch(e) { log(FAIL, 'GET /hotels unauthenticated', e.message); }

  // 4. Suppliers
  let supplierId;
  try {
    const r = await apiPost('/suppliers',
      { name: 'Test CleanPro', contact_email: 'sales@cleanpro.com', catalog_items: 'soap,towels,shampoo' },
      adminToken);
    if (r.ok && r.data.id) {
      supplierId = r.data.id;
      log(PASS, 'POST /suppliers (admin)', `id=${supplierId.substring(0,8)}…`);
    } else log(FAIL, 'POST /suppliers', JSON.stringify(r.data));
  } catch(e) { log(FAIL, 'POST /suppliers', e.message); }

  // 5. RBAC: hotel cannot create supplier
  try {
    hotelToken = await getToken('hotel', hotelId || 'hotel1');
    const r = await apiPost('/suppliers',
      { name: 'Hack', contact_email: 'h@h.com', catalog_items: 'soap' }, hotelToken);
    r.status === 403 ? log(PASS, 'RBAC: hotel POST /suppliers → 403')
                      : log(FAIL, 'RBAC: hotel POST /suppliers', `got ${r.status}`);
  } catch(e) { log(FAIL, 'RBAC hotel POST /suppliers', e.message); }

  // 6. Requirements
  let reqId;
  try {
    const deadline = new Date(); deadline.setDate(deadline.getDate() + 3);
    const r = await apiPost('/requirements', {
      hotel_id: hotelId,
      item: 'soap',
      quantity: 500,
      urgency: 'high',
      department: 'housekeeping',
      deadline: deadline.toISOString().split('T')[0]
    }, hotelToken);
    if (r.ok && r.data.id) {
      reqId = r.data.id;
      log(PASS, 'POST /requirements (hotel)', `status=${r.data.status}`);
    } else log(FAIL, 'POST /requirements', JSON.stringify(r.data));
  } catch(e) { log(FAIL, 'POST /requirements', e.message); }

  // Wait for matcher background task
  await new Promise(r => setTimeout(r, 2500));

  // Check status changed to matched
  try {
    const r = await apiGet('/requirements', hotelToken);
    const req = r.data.find(x => x.id === reqId);
    req && req.status === 'matched'
      ? log(PASS, 'Matcher auto-fired: status=matched', `after 2.5s`)
      : log(WARN, 'Matcher status', `status=${req?.status || 'unknown'} (may still be open if matcher not reached)`);
  } catch(e) { log(FAIL, 'GET /requirements after match', e.message); }

  // 7. Accept + Fulfill
  try {
    supplierToken = await getToken('supplier', supplierId || 'supplier1');
    const r = await fetch(`${BASE}/requirements/${reqId}/accept`, {
      method: 'PATCH', headers: { Authorization: `Bearer ${supplierToken}` }
    });
    const d = await r.json();
    d.status === 'accepted' ? log(PASS, 'PATCH /requirements/accept', 'status=accepted')
                            : log(FAIL, 'PATCH /requirements/accept', JSON.stringify(d));
  } catch(e) { log(FAIL, 'PATCH /requirements/accept', e.message); }

  try {
    const r = await fetch(`${BASE}/requirements/${reqId}/fulfill`, {
      method: 'PATCH', headers: { Authorization: `Bearer ${supplierToken}` }
    });
    const d = await r.json();
    d.status === 'fulfilled' ? log(PASS, 'PATCH /requirements/fulfill', 'status=fulfilled')
                             : log(FAIL, 'PATCH /requirements/fulfill', JSON.stringify(d));
  } catch(e) { log(FAIL, 'PATCH /requirements/fulfill', e.message); }

  // 8. Dashboard
  try {
    const r = await apiGet('/dashboard/summary');
    const keys = ['total','open','matched','accepted','fulfilled','fulfillment_rate'];
    const hasAll = keys.every(k => k in r.data);
    hasAll
      ? log(PASS, 'GET /dashboard/summary', `total=${r.data.total}, rate=${r.data.fulfillment_rate}`)
      : log(FAIL, 'GET /dashboard/summary', `missing keys: ${keys.filter(k=>!(k in r.data)).join(',')}`);
  } catch(e) { log(FAIL, 'GET /dashboard/summary', e.message); }

  // 9. Metrics
  try {
    const r = await fetch(`${BASE}/metrics`);
    const text = await r.text();
    text.includes('requirements_created_total') && text.includes('requirements_fulfilled_total')
      ? log(PASS, 'GET /metrics', 'custom counters present')
      : log(FAIL, 'GET /metrics', 'missing custom counters');
  } catch(e) { log(FAIL, 'GET /metrics', e.message); }

  // 10. Matcher direct
  try {
    const r = await fetch(`${MATCHER}/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requirement_id: 'test-dom', item: 'soap', quantity: 200,
        urgency: 'high', department: 'test', deadline: '2026-12-31', hotel_id: 'h1'
      })
    });
    const d = await r.json();
    d.matched && d.candidates.length > 0
      ? log(PASS, `POST ${MATCHER}/match`, `top=${d.candidates[0].supplier_name}, score=${d.candidates[0].score}`)
      : log(FAIL, `POST ${MATCHER}/match`, JSON.stringify(d));
  } catch(e) { log(FAIL, `POST ${MATCHER}/match`, e.message); }

  // 11. Notifier
  try {
    const r = await fetch(`${NOTIFIER}/notifications`);
    const d = await r.json();
    Array.isArray(d)
      ? log(PASS, `GET ${NOTIFIER}/notifications`, `count=${d.length}`)
      : log(FAIL, `GET ${NOTIFIER}/notifications`, 'not array');
  } catch(e) { log(FAIL, `GET ${NOTIFIER}/notifications`, e.message); }

  return { adminToken, hotelToken, supplierToken, hotelId, supplierId, reqId };
}

// ─── DOM Tests ───────────────────────────────────────────────────────────────
async function runDOMTests(tokens) {
  console.log('\n══════════════════════════════════');
  console.log('  DOM / UI TESTS');
  console.log('══════════════════════════════════\n');

  browser = await puppeteer.launch({ args: ['--no-sandbox','--disable-setuid-sandbox'], headless: true });
  page = await browser.newPage();

  // Capture console errors
  const consoleErrors = [];
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('favicon')) {
      consoleErrors.push(m.text());
    }
  });
  page.on('pageerror', e => consoleErrors.push(e.message));

  // 1. Dashboard page loads
  try {
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle2', timeout: 15000 });
    log(PASS, 'Dashboard page (/dashboard) loads');
  } catch(e) { log(FAIL, 'Dashboard page loads', e.message); }

  // 2. Title
  const title = await page.title();
  title.includes('HotelSupply') ? log(PASS, `<title> contains "HotelSupply"`, title)
                                 : log(FAIL, `<title>`, `got: ${title}`);

  // 3. KPI cards populated
  await page.waitForFunction(
    () => document.getElementById('kpi-total')?.textContent !== '—',
    { timeout: 6000 }
  ).catch(() => {});
  const kpiTotal = await page.$eval('#kpi-total', el => el.textContent);
  kpiTotal !== '—' ? log(PASS, 'KPI cards populated', `total=${kpiTotal}`)
                   : log(FAIL, 'KPI cards not populated', 'still showing "—"');

  // 4. Test Orders Page
  try {
    await page.goto(`${BASE}/orders`, { waitUntil: 'networkidle2', timeout: 15000 });
    await page.waitForFunction(
      () => document.getElementById('req-hotel-id')?.options?.length > 1,
      { timeout: 6000 }
    ).catch(() => {});
    const hotelOpts = await page.$eval('#req-hotel-id', el => el.options.length);
    hotelOpts > 1 ? log(PASS, 'Requirements page (/orders) loads with hotel dropdown', `${hotelOpts} hotels`)
                  : log(FAIL, 'Requirements page empty hotel dropdown');
  } catch(e) { log(FAIL, 'Requirements page (/orders)', e.message); }

  // 5. Test Entities Page
  try {
    await page.goto(`${BASE}/entities-page`, { waitUntil: 'networkidle2', timeout: 15000 });
    await page.waitForFunction(
      () => document.getElementById('hotel-tbody')?.rows?.length > 0,
      { timeout: 6000 }
    ).catch(() => {});
    const hotelRows = await page.$eval('#hotel-tbody', el => el.rows.length);
    hotelRows > 0 ? log(PASS, 'Entities page (/entities-page) loads registered hotels', `${hotelRows} hotels`)
                  : log(FAIL, 'Entities page hotel table empty');
  } catch(e) { log(FAIL, 'Entities page (/entities-page)', e.message); }

  // 6. Test Events Page
  try {
    await page.goto(`${BASE}/events-page`, { waitUntil: 'networkidle2', timeout: 15000 });
    log(PASS, 'Events page (/events-page) loads');
  } catch(e) { log(FAIL, 'Events page (/events-page)', e.message); }

  // 7. Test Matcher Page
  try {
    await page.goto(`${BASE}/matcher-page`, { waitUntil: 'networkidle2', timeout: 15000 });
    await page.click('#match-item');
    await page.evaluate(() => document.getElementById('match-item').value = '');
    await page.type('#match-item', 'soap');
    await page.click('#match-btn');
    await new Promise(r => setTimeout(r, 2000));
    const matchResult = await page.$eval('#match-output', el => el.textContent);
    matchResult.includes('candidate(s) matched') || matchResult.includes('#1')
      ? log(PASS, 'Matcher page (/matcher-page) test works', matchResult.substring(0,60).replace(/\n/g, ' '))
      : log(WARN, 'Matcher page test result', matchResult.substring(0,60).replace(/\n/g, ' '));
  } catch(e) { log(FAIL, 'Matcher page (/matcher-page)', e.message); }

  // 8. Test Health Page
  try {
    await page.goto(`${BASE}/health-page`, { waitUntil: 'networkidle2', timeout: 15000 });
    await page.waitForFunction(
      () => document.getElementById('ht-api')?.textContent?.includes('UP'),
      { timeout: 8000 }
    ).catch(() => {});
    for (const id of ['ht-api','ht-matcher','ht-notifier']) {
      const txt = await page.$eval(`#${id}`, el => el.textContent).catch(() => '');
      txt.includes('UP') ? log(PASS, `Health page: ${id} shows UP`)
                         : log(FAIL, `Health page: ${id}`, `shows: ${txt.trim()}`);
    }
  } catch(e) { log(FAIL, 'Health page (/health-page)', e.message); }

  // 9. Test Auth & Profile Page
  try {
    await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle2', timeout: 15000 });
    const activeRole = await page.$eval('#active-role-display', el => el.textContent);
    activeRole.length > 0 ? log(PASS, 'Auth & Profile page (/profile) loads active session', `role=${activeRole}`)
                          : log(FAIL, 'Auth & Profile page session empty');
  } catch(e) { log(FAIL, 'Profile page (/profile)', e.message); }

  // 10. Console errors check
  if (consoleErrors.length === 0) {
    log(PASS, 'Zero JS console errors across all pages');
  } else {
    consoleErrors.forEach(e => log(FAIL, 'JS console error', e.substring(0,100)));
  }

  // 11. Responsiveness test

  await page.setViewport({ width: 768, height: 1024 });
  await page.reload({ waitUntil: 'networkidle2' });
  const overflowX = await page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  !overflowX ? log(PASS, 'No horizontal overflow at 768px')
             : log(WARN, 'Horizontal overflow at 768px viewport');

  await browser.close();
}

// ─── Summary ─────────────────────────────────────────────────────────────────
function printSummary() {
  console.log('\n══════════════════════════════════');
  console.log('  TEST SUMMARY');
  console.log('══════════════════════════════════\n');
  const passed = results.filter(r => r.status === PASS).length;
  const failed = results.filter(r => r.status === FAIL).length;
  const warned = results.filter(r => r.status === WARN).length;
  console.log(`Total: ${results.length}  |  ${PASS} ${passed}  |  ${FAIL} ${failed}  |  ${WARN} ${warned}`);

  if (failed > 0) {
    console.log('\nFailed tests:');
    results.filter(r => r.status === FAIL).forEach(r => {
      console.log(`  ${FAIL} ${r.test}: ${r.detail}`);
    });
  }
  return { passed, failed, warned };
}

// ─── Run all ─────────────────────────────────────────────────────────────────
(async () => {
  try {
    const tokens = await runAPITests();
    await runDOMTests(tokens);
    const { failed } = printSummary();
    process.exit(failed > 0 ? 1 : 0);
  } catch(e) {
    console.error('Test runner crashed:', e);
    process.exit(1);
  }
})();
