// 把没填上的格子标成红色虚线框（specs/006-browser-extension）。
// 后台先把 [{i, why}] 放进 window.__paMarks，这里读完即删；格子用扫描时加的 data-pa-i 找回。
// 每次先去掉上一轮的红框（页面上冒出新格子后会再填一轮，上一轮标红的格子可能已经填上了）。
(() => {
  const items = window.__paMarks || [];
  delete window.__paMarks;
  document.querySelectorAll('[data-pa-red]').forEach((n) => {
    n.style.outline = '';
    n.removeAttribute('data-pa-red');
    if (n.title && !n.title.startsWith('个人助手')) n.removeAttribute('title');
  });
  let marked = 0;
  for (const { i, why } of items) {
    const els = [...document.querySelectorAll(`[data-pa-i="${i}"]`)];
    if (!els.length) continue;
    // 单选组标整组所在的容器，其他格子标自己
    const target = els.length > 1 ? (els[0].closest('table, fieldset') || els[0].parentElement) : els[0];
    target.style.outline = '2px dashed #c0392b';
    target.style.outlineOffset = '1px';
    target.title = why;
    target.setAttribute('data-pa-red', '');
    marked++;
  }
  return JSON.stringify({ marked });
})()
