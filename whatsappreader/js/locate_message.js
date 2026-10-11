const normalizeMeta = s => String(s || "").replace(/\u200e/g, "").replace(/\s+/g, " ").trim();
const wantedMeta = normalizeMeta(arguments[0]);
const wantedText = String(arguments[1] || "").replace(/\s+/g, " ").trim();
const main = document.querySelector("#main");
if (!main) return null;

let rows = [...main.querySelectorAll('[role="row"]')]
  .filter(row => {
    const meta = row.querySelector('[data-pre-plain-text]');
    return meta && normalizeMeta(meta.getAttribute('data-pre-plain-text')) === wantedMeta;
  });

if (!rows.length) {
  const metas = [...main.querySelectorAll('[data-pre-plain-text]')]
    .filter(el => normalizeMeta(el.getAttribute('data-pre-plain-text')) === wantedMeta);
  rows = metas.map(el => el.closest('[role="row"]') || el.parentElement).filter(Boolean);
}

if (!rows.length) return null;

let row = rows[0];
if (rows.length > 1 && wantedText) {
  const byText = rows.find(r => {
    const t = String(r.innerText || "").replace(/\s+/g, " ").trim();
    return t.includes(wantedText.slice(0, Math.min(80, wantedText.length)));
  });
  if (byText) row = byText;
}

row.scrollIntoView({block:"center", inline:"nearest"});
return row;
