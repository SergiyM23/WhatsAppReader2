const normalizeMeta = s => String(s || "").replace(/\u200e/g, "").replace(/\s+/g, " ").trim();
const wantedMeta = normalizeMeta(arguments[0]);
const wantedText = String(arguments[1] || "").replace(/\s+/g, " ").trim();
const main = document.querySelector("#main");
if (!main) return false;

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

if (!rows.length) return false;

// Timestamp + author metadata normally identifies the message precisely.
// When there is exactly one matching row, do not reject it merely because
// WhatsApp rendered the caption/text slightly differently after virtualization.
if (rows.length === 1) return true;
if (!wantedText) return true;

// Only use text as a disambiguator when multiple rows have the same metadata.
return rows.some(r => {
  const t = String(r.innerText || "").replace(/\s+/g, " ").trim();
  return t.includes(wantedText.slice(0, Math.min(80, wantedText.length)));
});
