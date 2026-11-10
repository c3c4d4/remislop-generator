/* Collected on every fixture page by render.py (injected, never in the app). */
(() => {
  const out = [];
  let idx = 0;
  const px = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0; };
  const CORNERS = ["borderTopLeftRadius", "borderTopRightRadius", "borderBottomLeftRadius", "borderBottomRightRadius"];
  const radius = (s) => {
    let best = 0;
    for (const c of CORNERS) {
      const raw = s[c];
      if (raw && raw.trim().endsWith("%")) {
        best = Math.max(best, parseFloat(raw) >= 45 ? 999 : 0);
      } else {
        best = Math.max(best, px(raw));
      }
    }
    return best;
  };
  const walk = (el, depth, parent) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && s.display !== "none" &&
      s.visibility !== "hidden" && parseFloat(s.opacity) > 0.05;
    if (!visible) {
      for (const child of el.children) walk(child, depth + 1, parent);
      return;
    }
    const myIdx = idx++;
    const ownText = Array.from(el.childNodes).some(
      (n) => n.nodeType === 3 && n.textContent.trim().length > 0
    );
    out.push({
      idx: myIdx,
      parent,
      depth,
      t: el.tagName.toLowerCase(),
      sel: el.tagName.toLowerCase() +
        (el.id ? "#" + el.id : "") +
        (typeof el.className === "string" && el.className.trim()
          ? "." + el.className.trim().split(/\s+/).slice(0, 2).join(".")
          : ""),
      bg: s.backgroundColor,
      c: s.color,
      bw: px(s.borderTopWidth),
      bc: s.borderTopColor,
      br: radius(s),
      fs: px(s.fontSize),
      fw: parseInt(s.fontWeight, 10) || 400,
      ff: s.fontFamily,
      pt: px(s.paddingTop), pr: px(s.paddingRight),
      pb: px(s.paddingBottom), pl: px(s.paddingLeft),
      gap: px(s.columnGap),
      x: Math.round(r.x), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
      own_text: ownText,
      font_size_applies: ownText
    });
    for (const child of el.children) walk(child, depth + 1, myIdx);
  };
  walk(document.documentElement, 0, -1);

  const bodyBg = getComputedStyle(document.body).backgroundColor;
  const htmlBg = getComputedStyle(document.documentElement).backgroundColor;
  const transparent = (v) => !v || v === "rgba(0, 0, 0, 0)" || v === "transparent";
  const data = {
    canvas_bg: transparent(bodyBg) ? htmlBg : bodyBg,
    size: { w: window.innerWidth, h: window.innerHeight },
    doc_h: Math.round(document.documentElement.scrollHeight),
    elements: out
  };
  document.documentElement.setAttribute("data-adw", JSON.stringify(data));
})();
