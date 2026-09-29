// 由 scripts/build_extension.py 从 src/form_engine/read.js 生成，不要直接改这个文件。
// 通用填表引擎·读回（specs/006-browser-extension 第三版「存进基本信息」）：在扫描之后运行，
// 读出扫描标了编号（data-pa-i）的格子里现在的内容，返回 {"编号": "文字"}。只交给本机的本地服务，用来存回基本信息。
// 下拉框取选中项的文字，单选组取选中那项的文字，空的格子不返回。
(() => {
  const clip = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 500);
  const radioText = (r) => {
    const f = r.id ? document.querySelector(`label[for="${CSS.escape(r.id)}"]`) : null;
    if (f) return clip(f.textContent);
    const w = r.closest('label');
    if (w) return clip(w.textContent);
    return clip(r.value);
  };
  const out = {};
  for (const el of document.querySelectorAll('[data-pa-i]')) {
    const i = el.getAttribute('data-pa-i');
    if (i in out) continue;
    let v = '';
    if (el.type === 'radio') {
      const on = [...document.querySelectorAll(`[data-pa-i="${i}"]`)].find((r) => r.checked);
      v = on ? radioText(on) : '';
    } else if (el.tagName === 'SELECT') {
      v = el.selectedIndex > 0 ? clip(el.options[el.selectedIndex].text) : '';
    } else {
      v = clip(el.value);
    }
    if (v) out[i] = v;
  }
  return JSON.stringify(out);
})()
