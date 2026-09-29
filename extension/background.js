// 有条有理 · 填表插件的后台（specs/006-browser-extension）。
// 填一页：扫描（engine/scan.js）→ 问本地服务这一页填什么（POST /api/ext/plan）→ 填写（engine/fill.js）→ 没填上的标红（engine/mark.js）。
// 判断全在本地服务里（和 Agent 用的是同一套规则）；这里不调用任何 AI。

const API = 'http://127.0.0.1:8000';
const DEFAULT_SETTINGS = { autoHosts: [], ackHosts: [], sensitive: false, trackByHost: {} };
const MAX_AUTO_PER_URL = 2; // 同一个网址 60 秒内最多自动填 2 轮（页面刷新后出现新格子时补一轮）
// 选了某个选项才冒出来的格子（"有没有……"选了 Yes、选了"已婚"才出现配偶一栏）：
// 填完等一下再扫一遍，有新的能填就接着填，一次最多 3 轮；之后页面上再冒出新格子，由 engine/watch.js 通知再填。
const MAX_ROUNDS = 3;
const SETTLE_MS = 800;
const MAX_WATCH_FILLS = 30; // 同一个标签页、同一个网址，由"冒出新格子"触发的补填最多这么多次，防止来回刷新的页面没完没了
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 侧边栏只在点了插件图标的那个标签页里显示（2026-09-29 项目主：不要在所有网页上都显示）。
// 全局先关掉；点图标时只给当前标签页打开。setOptions 和 open 都不能 await 在前面，否则丢掉"用户点击"的标记。
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(() => {});
chrome.sidePanel.setOptions({ enabled: false }).catch(() => {});
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.setOptions({ tabId: tab.id, path: 'sidepanel.html', enabled: true });
  chrome.sidePanel.open({ tabId: tab.id });
});

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

// 这个网站关联的"这件事"（spec 007）：侧边栏选过就用选的（"" 表示不关联）；没选过按网址猜
async function trackFor(host, settings) {
  const chosen = (settings.trackByHost || {})[host];
  if (chosen !== undefined) return chosen || null;
  try {
    return (await api('/api/ext/tracks?host=' + encodeURIComponent(host))).guess || null;
  } catch (e) {
    return null;
  }
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

  // filled 各轮相加；选项对不上 / 找不到的格子每一轮都会再数一次，只看最后一轮
  const total = { filled: 0, skipped: 0, gone: 0, already: 0 };
  const trackId = await trackFor(host, settings);
  let last = null;
  for (let k = 0; k < MAX_ROUNDS; k++) {
    if (k) await sleep(SETTLE_MS);
    const round = await fillOnce(tabId, settings, trackId);
    if (round.error) {
      if (!last) return round;
      break;
    }
    last = round;
    total.filled += round.counts.filled || 0;
    total.skipped = round.counts.skipped || 0;
    total.gone = round.counts.gone || 0;
    total.rounds = k + 1;
    if (!round.counts.filled) break; // 这一轮什么都没填，不会再冒出新格子
  }
  // 之后页面上再冒出新格子（用户自己点了某个选项）：watch.js 通知后台再填一次
  await run(tabId, { files: ['engine/watch.js'], world: 'ISOLATED' }).catch(() => {});
  return finish(tabId, tab, host, policy, total, last);
}

// 扫描 → 计划 → 填写 → 标红，一轮
async function fillOnce(tabId, settings, trackId) {
  let scanText;
  try {
    await run(tabId, { files: ['engine/scan.js'] });
    scanText = await run(tabId, { func: () => { const t = window.__paScanText; delete window.__paScanText; return t; } });
  } catch (e) {
    return { error: 'no_permission' };
  }

  let plan;
  try {
    plan = await api('/api/ext/plan', { scan: scanText, sensitive: settings.sensitive, track_id: trackId });
  } catch (e) {
    return { error: e.code === 'api' ? 'bad_scan' : 'offline', detail: e.message };
  }
  if (!plan.ops.length) return { counts: {}, plan, scanText, ...(await markLeftover(tabId, plan, scanText)) };

  await run(tabId, { func: (ops) => { window.__paPlan = ops; }, args: [plan.ops] });
  const counts = JSON.parse(await run(tabId, { files: ['engine/fill.js'] }));
  return { counts, plan, scanText, ...(await markLeftover(tabId, plan, scanText)) };
}

async function markLeftover(tabId, plan, scanText) {
  const marks = [
    ...plan.manual.map((x) => ({ i: x.i, why: '请手动选：' + x.label })),
    ...plan.missing.map((x) => ({ i: x.i, why: '资料里没有：' + x.label })),
    ...plan.sensitive.map((x) => ({ i: x.i, why: '敏感信息，没有自动填：' + x.label })),
    ...plan.needs_format.map((x) => ({ i: x.i, why: '格式看不出，请手动填：' + x.label })),
    ...plan.unmatched.map((x) => ({ i: x.i, why: '没认出这一格' })),
  ];
  await run(tabId, { func: (m) => { window.__paMarks = m; }, args: [marks] });
  await run(tabId, { files: ['engine/mark.js'] });

  // 留给"让 Agent 补填"的格子描述（不含页面上的值）；"请手动选"的是会刷新页面的下拉框，不交给 Agent
  const leftover = await describeLeftover(tabId, scanText, marks.filter((m) => !plan.manual.some((x) => x.i === m.i)));
  return { leftover };
}

async function finish(tabId, tab, host, policy, counts, round) {
  const { plan, leftover } = round;
  const result = {
    host, url: tab.url, at: Date.now(), counts, policy, leftover,
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

const KINDS = { t: 'text', d: 'date', a: 'textarea', s: 'select', r: 'radio' };

// 剩下格子的描述：扫描结果里的标签 / 小节 / 名字 + 没填的原因 + 下拉框、单选的选项文字（最多 80 项）
async function describeLeftover(tabId, scanText, marks) {
  const scan = JSON.parse(scanText);
  const rows = new Map(scan.f.map((r) => [r[0], r]));
  const ids = marks.map((m) => m.i).filter((i) => rows.has(i)).slice(0, 60);
  const options = await run(tabId, {
    func: (list) => {
      const clip = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 60);
      const out = {};
      for (const i of list) {
        const els = [...document.querySelectorAll(`[data-pa-i="${i}"]`)];
        if (!els.length) continue;
        if (els[0].tagName === 'SELECT') {
          out[i] = [...els[0].options].map((o) => clip(o.text)).filter(Boolean).slice(0, 80);
        } else if (els[0].type === 'radio') {
          out[i] = els.map((r) => {
            const f = r.id && document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
            return clip((f && f.textContent) || (r.closest('label') && r.closest('label').textContent) || r.value);
          });
        }
      }
      return out;
    },
    args: [ids],
  });
  return ids.map((i) => {
    const r = rows.get(i);
    const m = marks.find((x) => x.i === i);
    return {
      i, kind: KINDS[r[1]] || r[1], label: r[2], section: scan.sections[r[3]] || '', name: r[4],
      why: m.why.split('：')[0], options: (options && options[i]) || undefined,
    };
  });
}

// Agent 交出的"哪一格填什么" → 用自带的 fill.js 填（下拉框 / 单选按选项原文找）
async function assistFill(tabId, fills) {
  const key = 'result:' + tabId;
  const last = (await chrome.storage.session.get(key))[key];
  const kinds = new Map(((last && last.leftover) || []).map((f) => [f.i, f.kind]));
  const ops = fills.filter((f) => kinds.has(f.i)).map((f) => {
    const kind = kinds.get(f.i);
    return kind === 'select' || kind === 'radio' ? { i: f.i, k: kind, c: [f.value] } : { i: f.i, k: 'text', v: f.value };
  });
  if (!ops.length) return { filled: 0, skipped: fills.length, gone: 0, already: 0 };
  await run(tabId, { func: (o) => { window.__paPlan = o; }, args: [ops] });
  return JSON.parse(await run(tabId, { files: ['engine/fill.js'] }));
}

// 清空这一页插件填过的格子（黄框）：文本框清空、下拉框回到第一项；单选不动
async function clearFilled(tabId) {
  return run(tabId, {
    func: () => {
      const MARK = '个人助手自动填写，请核对';
      let n = 0;
      document.querySelectorAll(`[title="${MARK}"]`).forEach((el) => {
        const fire = (t) => el.dispatchEvent(new Event(t, { bubbles: true }));
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, '');
          fire('input'); fire('change');
        } else if (el.tagName === 'SELECT') {
          el.selectedIndex = 0;
          fire('change');
        } else {
          return; // 单选组的外框：不动
        }
        el.style.outline = '';
        el.removeAttribute('title');
        n++;
      });
      return n;
    },
  });
}

// 存进基本信息（第三版）：扫描 → 读出格子里现在的内容（engine/read.js）→ 本地服务算出和基本信息不一样的项。
// 这里只算建议；用户在侧边栏勾选后才调用 /api/ext/capture/apply 写入。
async function captureTab(tabId) {
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
  let scanText, values;
  try {
    await run(tabId, { files: ['engine/scan.js'] });
    scanText = await run(tabId, { func: () => { const t = window.__paScanText; delete window.__paScanText; return t; } });
    values = JSON.parse(await run(tabId, { files: ['engine/read.js'] }));
  } catch (e) {
    return { error: 'no_permission' };
  }
  try {
    return await api('/api/ext/capture', { scan: scanText, values, track_id: await trackFor(host, settings) });
  } catch (e) {
    return { error: e.code === 'api' ? 'bad_scan' : 'offline', detail: e.message };
  }
}

async function applyCapture(items, trackId) {
  try {
    return await api('/api/ext/capture/apply', { items, track_id: trackId || null });
  } catch (e) {
    return { error: 'failed', detail: e.message };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const reply = (p) => { p.then(sendResponse, (e) => sendResponse({ error: 'failed', detail: String(e) })); return true; };
  if (msg && msg.type === 'fill') return reply(fillTab(msg.tabId));
  if (msg && msg.type === 'assist-fill') return reply(assistFill(msg.tabId, msg.fills || []));
  if (msg && msg.type === 'clear') return reply(clearFilled(msg.tabId).then((n) => ({ cleared: n })));
  if (msg && msg.type === 'capture') return reply(captureTab(msg.tabId));
  if (msg && msg.type === 'fields-appeared' && sender.tab) return reply(refillAppeared(sender.tab));
  if (msg && msg.type === 'capture-apply') return reply(applyCapture(msg.items || [], msg.trackId));
  return false;
});

// 页面上冒出了新格子（engine/watch.js 报告）：再填一次，结果推给侧边栏。
// watch.js 只在用过"填本页"（或自动填）的标签页里装；同一网址次数有上限。
async function refillAppeared(tab) {
  const key = 'watch:' + tab.id;
  const prev = (await chrome.storage.session.get(key))[key];
  const n = prev && prev.url === tab.url ? prev.n + 1 : 1;
  if (n > MAX_WATCH_FILLS) return { skipped: 'limit' };
  await chrome.storage.session.set({ [key]: { url: tab.url, n } });
  const result = await fillTab(tab.id);
  chrome.runtime.sendMessage({ type: 'filled', tabId: tab.id, result }).catch(() => {}); // 侧边栏没开时没人收，忽略
  return { ok: true };
}

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
  chrome.storage.session.remove(['result:' + tabId, 'auto:' + tabId, 'watch:' + tabId]);
});
