// 有条有理 · 填表插件的侧边栏（specs/006-browser-extension）。
const API = 'http://127.0.0.1:8000';
const DEFAULT_SETTINGS = { autoHosts: [], ackHosts: [], sensitive: false, trackByHost: {} };
const $ = (id) => document.getElementById(id);

let tab = null; // 当前标签页
let host = '';
let policy = null;
let trackId = null; // 这个网站关联的"这件事"（spec 007）

function helperUrl() {
  return `${API}/fill-helper.html?embed=1${trackId ? '&track_id=' + encodeURIComponent(trackId) : ''}`;
}

// 下拉框：正在办的事；选过就用选过的，没选过用本地服务按网址猜的
async function loadTracks(settings) {
  let data = { tracks: [], guess: null };
  try {
    data = await (await fetch(`${API}/api/ext/tracks?host=${encodeURIComponent(host)}`)).json();
  } catch (e) { /* 连不上时下拉框只有"不关联" */ }
  const chosen = (settings.trackByHost || {})[host];
  trackId = chosen !== undefined ? (chosen || null) : data.guess;
  if (trackId && !data.tracks.some((t) => t.id === trackId)) trackId = null; // 办完或删掉了
  const sel = $('track');
  sel.replaceChildren(el('option', '不关联'));
  sel.firstChild.value = '';
  data.tracks.forEach((t) => {
    const o = el('option', t.title);
    o.value = t.id;
    sel.append(o);
  });
  sel.value = trackId || '';
}

$('track').addEventListener('change', async (e) => {
  const s = await getSettings();
  trackId = e.target.value || null;
  await saveSettings({ trackByHost: { ...(s.trackByHost || {}), [host]: e.target.value } });
  $('helper').src = helperUrl(); // 对照清单跟着换「这次行程」
});

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

function checkbox(checked) {
  const c = document.createElement('input');
  c.type = 'checkbox';
  c.checked = checked;
  return c;
}

// ---- 下面的两个标签页：对照清单 / Agent ----

function showTab(id) {
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === id));
  $('helper').hidden = id !== 'helper';
  $('assist-frame').hidden = id !== 'assist-frame';
}
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));

// 点一格的名字：切到对照清单，找出相关的资料（"联系方式与住址 › 工作电话"只用最后一段）
function find(text) {
  showTab('helper');
  const frame = $('helper');
  if (frame.contentWindow) frame.contentWindow.postMessage({ type: 'pa-find', text: text.split(' › ').pop() }, API);
}

// ---- 填本页的结果 ----

const ERRORS = {
  offline: '连不上本地服务。',
  no_permission: '没有这个网站的权限。',
  needs_ack: '这个网站禁止自动化，先勾选上面的"我知道风险"。',
  not_web: '这个页面不能填。',
  bad_scan: '扫描结果有问题：',
  failed: '出错了：',
};

// 插件没填上的原因 → 标签
const WHY = {
  资料里没有: ['资料里没有', 'missing'],
  敏感信息: ['敏感', ''],
  格式看不出: ['格式', 'format'],
  没认出这一格: ['没认出', ''],
};

function whyTag(why) {
  const key = Object.keys(WHY).find((k) => (why || '').startsWith(k));
  const [text, cls] = key ? WHY[key] : [why || '', ''];
  return el('span', text, 'tag ' + cls);
}

function fieldName(f) {
  return f.label || f.section || '（没有标签的格子）';
}

let leftover = []; // 上一次"填本页"剩下的格子描述，留给"让 Agent 补填"

function status(nodes) {
  const box = $('status');
  box.replaceChildren(...nodes);
  box.hidden = !nodes.length;
}

function updateAssistButton() {
  const n = [...$('left-list').querySelectorAll('input')].filter((c) => c.checked).length;
  $('assist').disabled = !n;
  $('assist').textContent = n === leftover.length ? '交给 Agent' : `交给 Agent（${n} 格）`;
}

function showResult(r) {
  leftover = (r && r.leftover) || [];
  $('left').hidden = true;
  $('left-box').hidden = true;
  if (!r) { status([]); return; }
  if (r.error) { status([el('div', (ERRORS[r.error] || '出错了：') + (r.detail || ''), 'error')]); return; }
  const c = r.counts || {};
  const parts = [`填了 ${c.filled || 0} 格`];
  if (c.skipped) parts.push(`${c.skipped} 格选项对不上`);
  if (c.gone) parts.push(`${c.gone} 格找不到了（页面刷新过，再点一次"填本页"）`);
  const lines = [el('div', parts.join('，'), 'ok')];
  if (r.manual && r.manual.length) lines.push(el('div', '请手动选（选了会刷新页面）：' + r.manual.join('、'), 'muted'));
  status(lines);

  if (!leftover.length) return;
  $('left').hidden = false;
  $('left-title').textContent = `没填上 ${leftover.length} 格`;
  $('left-toggle').textContent = '选择';
  const ul = $('left-list');
  ul.replaceChildren();
  leftover.forEach((f) => {
    const li = el('li');
    const box = checkbox(true);
    box.dataset.i = f.i;
    box.addEventListener('change', updateAssistButton);
    const name = el('span', fieldName(f), 'name findable');
    name.title = '在对照清单里找';
    name.addEventListener('click', () => find(fieldName(f)));
    const why = el('div', '', 'why');
    why.append(whyTag(f.why), f.kind === 'select' || f.kind === 'radio' ? '选择题' : '');
    li.append(box, name, why);
    ul.append(li);
  });
  updateAssistButton();
}

$('left-toggle').addEventListener('click', () => {
  const box = $('left-box');
  box.hidden = !box.hidden;
  $('left-toggle').textContent = box.hidden ? '选择' : '收起';
});

$('left-all').addEventListener('click', () => {
  const boxes = [...$('left-list').querySelectorAll('input')];
  const on = !boxes.every((b) => b.checked);
  boxes.forEach((b) => { b.checked = on; });
  updateAssistButton();
});

// ---- 存进基本信息（第三版）：读页面上已经填好的内容，和基本信息不一样的列出来，勾选后才写 ----

let suggestions = [];

function showSuggestions(r) {
  $('save').hidden = false;
  const ul = $('save-list');
  ul.replaceChildren();
  if (!r || r.error) {
    suggestions = [];
    $('save-title').textContent = '存进基本信息';
    ul.append(el('li', (ERRORS[(r && r.error)] || '出错了：') + ((r && r.detail) || ''), 'error'));
    $('save-go').hidden = true;
    return;
  }
  suggestions = r.items || [];
  $('save-title').textContent = suggestions.length ? `和基本信息不一样的 ${suggestions.length} 项` : '这一页和基本信息一致';
  $('save-go').hidden = !suggestions.length;
  suggestions.forEach((s, k) => {
    const li = el('li');
    const box = checkbox(!s.before); // 原来空着的默认勾上；要覆盖旧值的默认不勾，让用户看一眼
    box.dataset.k = k;
    box.addEventListener('change', updateSaveButton);
    const change = el('div', '', 'change');
    if (s.before) { change.append(el('del', s.before), ' → '); }
    change.append(el('ins', s.after));
    li.append(box, el('span', s.label, 'name'), change);
    ul.append(li);
  });
  updateSaveButton();
}

function updateSaveButton() {
  const n = [...$('save-list').querySelectorAll('input')].filter((c) => c.checked).length;
  $('save-go').disabled = !n;
  $('save-go').textContent = n ? `保存选中的 ${n} 项` : '勾选要保存的项';
}

$('capture').addEventListener('click', async () => {
  if (!(await ensurePermission().catch(() => false))) { showSuggestions({ error: 'no_permission' }); return; }
  $('capture').disabled = true;
  const r = await chrome.runtime.sendMessage({ type: 'capture', tabId: tab.id });
  $('capture').disabled = false;
  showSuggestions(r);
});

$('save-go').addEventListener('click', async () => {
  const items = [...$('save-list').querySelectorAll('input')].filter((c) => c.checked)
    .map((c) => suggestions[Number(c.dataset.k)]).map((s) => ({ path: s.path, value: s.value, action: s.action }));
  $('save-go').disabled = true;
  const r = await chrome.runtime.sendMessage({ type: 'capture-apply', items, trackId });
  $('save').hidden = true;
  status([el('div', r && !r.error ? `已存进基本信息：${r.saved} 项` : '没存上：' + ((r && r.detail) || ''), r && !r.error ? 'ok' : 'error')]);
  if (r && !r.error && $('helper').src) $('helper').src = helperUrl(); // 对照清单跟着更新
});

$('save-close').addEventListener('click', () => { $('save').hidden = true; });

// ---- 设置和页面状态 ----

async function render() {
  const settings = await getSettings();
  const forbidden = policy && policy.automation === 'forbidden';
  const acked = settings.ackHosts.includes(host);
  $('policy').hidden = !forbidden;
  $('ack-row').hidden = !forbidden;
  if (forbidden) {
    $('policy-name').textContent = policy.name;
    $('policy-clause').textContent = policy.clause;
    $('policy-consequence').textContent = policy.consequence || '';
    $('policy').open = !acked;
    $('ack').checked = acked;
  }
  const blocked = forbidden && !acked;
  $('fill').disabled = blocked;
  $('capture').disabled = blocked;
  $('auto').disabled = blocked;
  $('auto').parentElement.classList.toggle('disabled', blocked);
  $('auto').checked = settings.autoHosts.includes(host) && !blocked;
  $('sensitive').checked = settings.sensitive;
  await loadTracks(settings);
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
    $('tabs').hidden = false;
  } catch (e) {
    $('offline').hidden = false;
    $('main').hidden = true;
    $('tabs').hidden = true;
    $('helper').hidden = true;
    return;
  }
  await render();
  const url = helperUrl();
  if ($('helper').getAttribute('src') !== url) { $('helper').src = url; if ($('assist-frame').hidden) showTab('helper'); }
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
  $('left').hidden = true;
  $('left-box').hidden = true;
  status([el('div', r && !r.error ? `清空了 ${r.cleared} 格，可以再点"填本页"` : '清空失败', r && !r.error ? 'ok' : 'error')]);
});

// ---- 让 Agent 补填（spec 006 第二版）：嵌入本地服务的 assist.html，它启动 Agent、把结果发回来，由插件填 ----
let pendingAssist = null;

$('assist').addEventListener('click', async () => {
  const picked = new Set([...$('left-list').querySelectorAll('input')].filter((c) => c.checked).map((c) => Number(c.dataset.i)));
  const fields = leftover.filter((f) => picked.has(f.i));
  if (!fields.length) return;
  const settings = await getSettings();
  pendingAssist = { type: 'pa-assist', host, sensitive: settings.sensitive, fields, track_id: trackId };
  showTab('assist-frame');
  $('assist-frame').src = `${API}/assist.html`; // 每次重新打开，开始新的对话；页面准备好会发 pa-assist-ready
});

window.addEventListener('message', async (ev) => {
  if (ev.origin !== API || !ev.data) return;
  if (ev.data.type === 'pa-assist-ready' && pendingAssist) {
    $('assist-frame').contentWindow.postMessage(pendingAssist, API);
    pendingAssist = null;
  } else if (ev.data.type === 'pa-fills') {
    const counts = await chrome.runtime.sendMessage({ type: 'assist-fill', tabId: tab.id, fills: ev.data.fills || [] });
    status([el('div', counts && !counts.error
      ? `Agent 补填了 ${counts.filled} 格${counts.skipped ? `，${counts.skipped} 格选项对不上` : ''}${counts.gone ? `，${counts.gone} 格找不到了（页面刷新过）` : ''}`
      : '补填失败', counts && !counts.error ? 'ok' : 'error')]);
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
