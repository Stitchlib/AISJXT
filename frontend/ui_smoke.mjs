import { chromium } from 'playwright';
import fs from 'fs';

const BASE = 'http://localhost:3000';
// 用临时目录规避项目内写权限被拦的问题
const SHOTS = 'F:/20260520/AISJZJRJT/frontend/smoke-shots';
try { fs.mkdirSync(SHOTS, { recursive: true }); } catch (_) {}

const consoleErrors = [];
const pageErrors = [];
const http5xx = [];   // 记录所有 >=400 的 HTTP 响应
const http4xx = [];

const browser = await chromium.launch({ args: ['--no-sandbox'] });
const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const page = await ctx.newPage();

page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => pageErrors.push(String(e)));
page.on('response', (resp) => {
  const s = resp.status();
  const url = resp.url();
  if (s >= 500) http5xx.push(`${s} ${url}`);
  else if (s >= 400) http4xx.push(`${s} ${url}`);
});

function log(...a) { console.log('[smoke]', ...a); }

function printResult(connText) {
  console.log('\n==== SMOKE RESULT ====');
  console.log('connection indicator:', connText);
  console.log('HTTP 5xx count:', http5xx.length);
  http5xx.forEach((e) => console.log('  HTTP5XX:', e));
  console.log('HTTP 4xx count:', http4xx.length);
  http4xx.slice(0, 20).forEach((e) => console.log('  HTTP4XX:', e));
  console.log('console.error count:', consoleErrors.length);
  consoleErrors.slice(0, 30).forEach((e) => console.log('  CONSOLE.ERR:', e.slice(0, 300)));
  console.log('pageerror count:', pageErrors.length);
  pageErrors.slice(0, 20).forEach((e) => console.log('  PAGEERR:', e.slice(0, 300)));
}

let connText = 'n/a';
try {
  // 1) Load login
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=AI 视觉质检系统', { timeout: 15000 });
  log('login page rendered');

  // 2) Login via the real form
  await page.fill('input[placeholder="用户名"]', 'admin');
  await page.fill('input[placeholder="密码"]', 'admin123');
  await page.click('button:has-text("登录")');
  await page.waitForURL('**/#/dashboard', { timeout: 15000 });
  log('logged in -> dashboard');
  await page.waitForTimeout(2500);

  const routes = [
    ['inspection', '实时检测'],
    ['devices', '设备管理'],
    ['models', '模型'],
    ['report', '质量'],
    ['history', '历史'],
    ['config', '系统配置'],
    ['alerts', '告警'],
    ['users', '用户'],
  ];

  let visited = 0;
  for (const [route, hint] of routes) {
    try {
      await page.goto(`${BASE}/#/${route}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(2000);
      log(`visited /#/${route} (hint: ${hint})`);
      visited++;
    } catch (e) {
      log(`ERROR visiting /#/${route}: ${e.message}`);
    }
  }

  // 3) Verify dashboard shows real data
  await page.goto(`${BASE}/#/dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  const bodyText = await page.evaluate(() => document.body.innerText);
  const hasChinese = /系统|检测|模型|摄像头|AI/.test(bodyText);
  log('dashboard body contains expected text:', hasChinese);

  // 4) Check WebSocket connection indicator text
  connText = await page.evaluate(() => document.querySelector('.conn')?.innerText || 'no-conn-el');
  log('connection indicator:', connText);

  // 5) Verify app fetch reaches real backend
  const health = await page.evaluate(async () => {
    const r = await fetch('/api/v1/system-health', { headers: { Authorization: 'Bearer ' + localStorage.getItem('aiqc_token') } });
    return r.ok ? await r.json() : null;
  });
  log('system-health via app fetch:', JSON.stringify(health).slice(0, 160));

  // 6) 额外：直接探测各 API 端点是否返回 500
  const apiProbe = await page.evaluate(async () => {
    const token = localStorage.getItem('aiqc_token');
    const h = { Authorization: 'Bearer ' + token };
    const paths = [
      '/api/v1/config',
      '/api/v1/inspection/status',
      '/api/v1/detection-results',
      '/api/v1/detection-results/statistics',
      '/api/v1/reports/summary',
      '/api/v1/alerts/events',
      '/api/v1/cameras',
      '/api/v1/model-versions',
      '/api/v1/users',
      '/api/v1/system-health',
    ];
    const out = {};
    for (const p of paths) {
      try {
        const r = await fetch(p, { headers: h });
        out[p] = r.status;
      } catch (e) { out[p] = 'ERR:' + e.message; }
    }
    return out;
  });
  log('API probe:', JSON.stringify(apiProbe));
} catch (e) {
  log('FATAL:', e.message);
} finally {
  printResult(connText);
  try { await browser.close(); } catch (_) {}
}
