// 有条有理 · 填表插件的后台（specs/006-browser-extension）。
// 填一页：扫描（engine/scan.js）→ 问本地服务这一页填什么（POST /api/ext/plan）→ 填写（engine/fill.js）→ 没填上的标红（engine/mark.js）。
// 判断全在本地服务里（和 Agent 用的是同一套规则）；这里不调用任何 AI。

const API = 'http://127.0.0.1:8000';
const DEFAULT_SETTINGS = { autoHosts: [], ackHosts: [], sensitive: false };
const MAX_AUTO_PER_URL = 2; // 同一个网址 60 秒内最多自动填 2 轮（页面刷新后出现新格子时补一轮）

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}) };
}

function originPattern(url) {
  const u = new URL(url);
  return `${u.protocol}//${u.host}/*`;
}

async function api(path, body) {
  const res = await fetch(API + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || `HTTP ${res.status}`), { code: 'api' });
  return data;
}

async function sitePolicy(host) {
  return api('/api/ext/site-policy?host=' + encodeURIComponent(host));
}

async function run(tabId, options) {
  const [r] = await chrome.scripting.executeScript({ target: { tabId }, world: 'MAIN', ...options });
  return r && r.result;
}

// 填一页，返回给侧边栏显示的结果（不含任何个人信息的值）
async function fillTab(tabId) {
  const tab = await chrome.tabs.get(tabId);
  if (!tab.url || !/^https?:/.test(tab.url)) return { error: 'not_web' };
  const host = new URL(tab.url).hostname;
  const settings = await getSettings();

  let policy;
  try {
    policy = await sitePolicy(host);
  } catch (e) {
    return { error: 'offline' };
  }
  if (policy.automation === 'forbidden' && !settings.ackHosts.includes(host)) return { error: 'needs_ack', policy };

  let scanText;
  try {
    await run(tabId, { files: ['engine/scan.js'] });
    scanText = await run(tabId, { func: () => { const t = window.__paScanText; delete window.__paScanText; return t; } });
  } catch (e) {
    return { error: 'no_permission' };
  }

  let plan;
  try {
    plan = await api('/api/ext/plan', { scan: scanText, sensitive: settings.sensitive });
  } catch (e) {
    return { error: e.code === 'api' ? 'bad_scan' : 'offline', detail: e.message };
  }

  await run(tabId, { func: (ops) => { window.__paPlan = ops; }, args: [plan.ops] });
  const counts = JSON.parse(await run(tabId, { files: ['engine/fill.js'] }));

  const marks = [
    ...plan.manual.map((x) => ({ i: x.i, why: '请手动选：' + x.label })),
    ...plan.missing.map((x) => ({ i: x.i, why: '资料里没有：' + x.label })),
    ...plan.sensitive.map((x) => ({ i: x.i, why: '敏感信息，没有自动填：' + x.label })),
    ...plan.needs_format.map((x) => ({ i: x.i, why: '格式看不出，请手动填：' + x.label })),
    ...plan.unmatched.map((x) => ({ i: x.i, why: '没认出这一格' })),
  ];
  await run(tabId, { func: (m) => { window.__paMarks = m; }, args: [marks] });
  await run(tabId, { files: ['engine/mark.js'] });

  const result = {
    host, url: tab.url, at: Date.now(), counts, policy,
    manual: plan.manual.map((x) => x.label),
    missing: plan.missing.map((x) => x.label),
    sensitive: plan.sensitive.map((x) => x.label),
    needsFormat: plan.needs_format.map((x) => x.label),
    unmatched: plan.unmatched.map((x) => x.text).filter(Boolean),
  };
  await chrome.storage.session.set({ ['result:' + tabId]: result });
  chrome.action.setBadgeBackgroundColor({ tabId, color: '#526543' });
  chrome.action.setBadgeText({ tabId, text: counts.filled ? String(counts.filled) : '' });
  return result;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === 'fill') {
    fillTab(msg.tabId).then(sendResponse, (e) => sendResponse({ error: 'failed', detail: String(e) }));
    return true; // 异步回复
  }
  return false;
});

// 打开了"自动填"的网站：页面加载完成就填
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== 'complete' || !tab.url || !/^https?:/.test(tab.url)) return;
  const host = new URL(tab.url).hostname;
  const settings = await getSettings();
  if (!settings.autoHosts.includes(host)) return;
  if (!(await chrome.permissions.contains({ origins: [originPattern(tab.url)] }))) return;

  const key = 'auto:' + tabId;
  const prev = (await chrome.storage.session.get(key))[key];
  const now = Date.now();
  const same = prev && prev.url === tab.url && now - prev.t < 60000;
  if (same && prev.n >= MAX_AUTO_PER_URL) return;
  await chrome.storage.session.set({ [key]: { url: tab.url, t: same ? prev.t : now, n: same ? prev.n + 1 : 1 } });

  const result = await fillTab(tabId);
  chrome.runtime.sendMessage({ type: 'filled', tabId, result }).catch(() => {}); // 侧边栏没开时没人收，忽略
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(['result:' + tabId, 'auto:' + tabId]);
});
