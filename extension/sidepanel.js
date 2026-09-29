// 有条有理 · 填表插件的侧边栏（specs/006-browser-extension）。
const API = 'http://127.0.0.1:8000';
const DEFAULT_SETTINGS = { autoHosts: [], ackHosts: [], sensitive: false };
const $ = (id) => document.getElementById(id);

let tab = null; // 当前标签页
let host = '';
let policy = null;

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}) };
}

async function saveSettings(change) {
  const s = { ...(await getSettings()), ...change };
  await chrome.storage.local.set({ settings: s });
  return s;
}

function toggleIn(list, item, on) {
  const rest = list.filter((x) => x !== item);
  return on ? [...rest, item] : rest;
}

function originPattern(url) {
  const u = new URL(url);
  return `${u.protocol}//${u.host}/*`;
}

// 这个网站的读写权限：Chrome 会弹窗让用户同意一次，之后这个网站的每一页都能填。
// 必须在点击后第一时间调用（中间先 await 别的会丢掉"用户点击"的标记）；已经同意过的直接返回 true，不再弹窗。
function ensurePermission() {
  return chrome.permissions.request({ origins: [originPattern(tab.url)] });
}

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}

// 点一项：让下面的对照清单找出相关的资料（"联系方式与住址 › 工作电话"只用最后一段）
function find(text) {
  const frame = $('helper');
  if (frame.contentWindow) frame.contentWindow.postMessage({ type: 'pa-find', text: text.split(' › ').pop() }, API);
}

function list(title, items) {
  if (!items || !items.length) return [];
  const ul = el('ul');
  items.forEach((t) => {
    const li = el('li', t, 'findable');
    li.title = '在下面的清单里找';
    li.addEventListener('click', () => find(t));
    ul.append(li);
  });
  return [el('h3', `${title}（${items.length}）`), ul];
}

const ERRORS = {
  offline: '连不上本地服务。',
  no_permission: '没有这个网站的权限。',
  needs_ack: '这个网站禁止自动化，先勾选上面的"我知道风险"。',
  not_web: '这个页面不能填。',
  bad_scan: '扫描结果有问题：',
  failed: '填写出错：',
};

let leftover = []; // 上一次"填本页"剩下的格子描述，留给"让 Agent 补填"

function showResult(r) {
  const box = $('result');
  box.replaceChildren();
  leftover = (r && r.leftover) || [];
  $('assist').hidden = !leftover.length;
  $('assist').textContent = `让 Agent 补填（${leftover.length} 格）`;
  if (!r) { box.hidden = true; return; }
  box.hidden = false;
  if (r.error) {
    box.append(el('p', (ERRORS[r.error] || '出错了：') + (r.detail || ''), 'error'));
    return;
  }
  const c = r.counts || {};
  box.append(el('div', `填了 ${c.filled || 0} 格${c.skipped ? `，${c.skipped} 格选项对不上没填` : ''}${c.gone ? `，${c.gone} 格找不到了（页面刷新过，再点一次"填本页"）` : ''}`, 'ok'));
  [
    ...list('请手动选', r.manual),
    ...list('资料里没有', r.missing),
    ...list('敏感信息没填', r.sensitive),
    ...list('格式看不出', r.needsFormat),
    ...list('没认出', r.unmatched),
  ].forEach((n) => box.append(n));
}

async function render() {
  const settings = await getSettings();
  const forbidden = policy && policy.automation === 'forbidden';
  const acked = settings.ackHosts.includes(host);
  $('policy').hidden = !forbidden;
  if (forbidden) {
    $('policy-name').textContent = policy.name;
    $('policy-clause').textContent = policy.clause;
    $('policy-consequence').textContent = policy.consequence || '';
    $('ack').checked = acked;
  }
  const blocked = forbidden && !acked;
  $('fill').disabled = blocked;
  $('auto').disabled = blocked;
  $('auto').parentElement.classList.toggle('disabled', blocked);
  $('auto').checked = settings.autoHosts.includes(host) && !blocked;
  $('sensitive').checked = settings.sensitive;
  const key = 'result:' + tab.id;
  const saved = (await chrome.storage.session.get(key))[key];
  showResult(saved && saved.url === tab.url ? saved : null);
}

async function refresh() {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const web = tab && tab.url && /^https?:/.test(tab.url);
  host = web ? new URL(tab.url).hostname : '';
  $('host').textContent = host;
  $('notweb').hidden = web;
  if (!web) { $('main').hidden = true; $('offline').hidden = true; return; }
  try {
    const res = await fetch(`${API}/api/ext/site-policy?host=${encodeURIComponent(host)}`);
    policy = await res.json();
    $('offline').hidden = true;
    $('main').hidden = false;
    $('helper').hidden = false;
    if (!$('helper').src) $('helper').src = `${API}/fill-helper.html`;
  } catch (e) {
    $('offline').hidden = false;
    $('main').hidden = true;
    $('helper').hidden = true;
    return;
  }
  await render();
}

$('fill').addEventListener('click', async () => {
  if (!(await ensurePermission().catch(() => false))) { showResult({ error: 'no_permission' }); return; }
  $('fill').disabled = true;
  $('fill').textContent = '填写中…';
  const r = await chrome.runtime.sendMessage({ type: 'fill', tabId: tab.id });
  $('fill').textContent = '填本页';
  $('fill').disabled = false;
  showResult(r);
});

$('clear').addEventListener('click', async () => {
  const r = await chrome.runtime.sendMessage({ type: 'clear', tabId: tab.id });
  const box = $('result');
  box.hidden = false;
  box.replaceChildren(el('div', r && !r.error ? `清空了 ${r.cleared} 格，可以再点"填本页"` : '清空失败', r && !r.error ? 'ok' : 'error'));
});

// ---- 让 Agent 补填（spec 006 第二版）：嵌入本地服务的 assist.html，它启动 Agent、把结果发回来，由插件填 ----
let pendingAssist = null;

$('assist').addEventListener('click', async () => {
  const settings = await getSettings();
  pendingAssist = { type: 'pa-assist', host, sensitive: settings.sensitive, fields: leftover };
  const frame = $('assist-frame');
  frame.hidden = false;
  frame.src = `${API}/assist.html`; // 每次重新打开，开始新的对话；页面准备好会发 pa-assist-ready
});

window.addEventListener('message', async (ev) => {
  if (ev.origin !== API || !ev.data) return;
  if (ev.data.type === 'pa-assist-ready' && pendingAssist) {
    $('assist-frame').contentWindow.postMessage(pendingAssist, API);
    pendingAssist = null;
  } else if (ev.data.type === 'pa-fills') {
    const counts = await chrome.runtime.sendMessage({ type: 'assist-fill', tabId: tab.id, fills: ev.data.fills || [] });
    const box = $('result');
    box.hidden = false;
    box.prepend(el('div', counts && !counts.error
      ? `Agent 补填了 ${counts.filled} 格${counts.skipped ? `，${counts.skipped} 格选项对不上` : ''}${counts.gone ? `，${counts.gone} 格找不到了（页面刷新过）` : ''}`
      : '补填失败', counts && !counts.error ? 'ok' : 'error'));
  }
});

$('auto').addEventListener('change', async (e) => {
  const on = e.target.checked;
  if (on && !(await ensurePermission().catch(() => false))) { e.target.checked = false; return; }
  const s = await getSettings();
  await saveSettings({ autoHosts: toggleIn(s.autoHosts, host, on) });
});

$('sensitive').addEventListener('change', (e) => saveSettings({ sensitive: e.target.checked }));

$('ack').addEventListener('change', async (e) => {
  const s = await getSettings();
  const change = { ackHosts: toggleIn(s.ackHosts, host, e.target.checked) };
  if (!e.target.checked) change.autoHosts = toggleIn(s.autoHosts, host, false); // 取消"知道风险"时一并关掉自动填
  await saveSettings(change);
  await render();
});

chrome.tabs.onActivated.addListener(refresh);
chrome.tabs.onUpdated.addListener((id, info) => { if (tab && id === tab.id && info.status === 'complete') refresh(); });
chrome.runtime.onMessage.addListener((msg) => { if (msg && msg.type === 'filled' && tab && msg.tabId === tab.id) showResult(msg.result); });

refresh();
