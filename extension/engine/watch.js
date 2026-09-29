// 盯着页面上"选了某个选项才冒出来"的格子（specs/006-browser-extension 第三版）。
// 在插件自己的隔离环境（ISOLATED world）里运行，官网页面的脚本看不到它；只在用过"填本页"的标签页里装一次。
// 不读格子里的内容，只数格子：
// - 装的时候已经在页面上的格子都算"见过"（扫描故意跳过的勾选框、验证码也在里面，不会反复触发）；
// - 之后出现了没见过的可见格子，而且之前扫描过的格子还在（说明是同一页里冒出来的，不是整页换成了下一步），
//   等页面安静 800 毫秒后通知后台再填一次。整页换了的情况交给"打开这个网站就自动填"。
(() => {
  if (window.__paWatching) return;
  window.__paWatching = true;
  const SELECTOR = 'input:not([type=hidden]):not([type=button]):not([type=submit]), select, textarea';
  const seen = new WeakSet(document.querySelectorAll(SELECTOR));
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };
  let timer = null;
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const added = [...document.querySelectorAll(SELECTOR)].filter((el) => !seen.has(el) && !el.disabled && visible(el));
      added.forEach((el) => seen.add(el));
      const samePage = document.querySelector('[data-pa-i]') !== null;
      if (added.length && samePage) chrome.runtime.sendMessage({ type: 'fields-appeared' }).catch(() => {});
    }, 800);
  }).observe(document.body, { childList: true, subtree: true });
})();
