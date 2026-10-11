function visible(el) {
  const r = el.getBoundingClientRect();
  const s = window.getComputedStyle(el);
  return r.width > 20 && r.height > 10 && s.display !== "none" && s.visibility !== "hidden";
}

const roots = [
  document.querySelector("#side"),
  document.querySelector("#pane-side") ? document.querySelector("#pane-side").parentElement : null,
  document
].filter(Boolean);

for (const root of roots) {
  const fields = [...root.querySelectorAll('div[contenteditable="true"], input[type="text"]')].filter(visible);
  if (!fields.length) continue;

  const preferred = fields.find(el => {
    const text = [
      el.getAttribute("aria-label") || "",
      el.getAttribute("placeholder") || "",
      el.getAttribute("data-tab") || ""
    ].join(" ").toLowerCase();

    return /search|поиск|buscar|cerca|chercher|suchen/.test(text);
  });

  if (preferred) return preferred;
  return fields[0];
}

return null;
