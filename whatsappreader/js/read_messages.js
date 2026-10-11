const limit = Number(arguments[0] || 100);

function clean(s) {
  return String(s || "").replace(/\u200e/g, "").trim();
}

const main = document.querySelector("#main");
if (!main) return [];

let rows = [...main.querySelectorAll('[role="row"]')]
  .filter(row => row.querySelector('[data-pre-plain-text]'));

if (!rows.length) {
  const metaNodes = [...main.querySelectorAll('[data-pre-plain-text]')];
  rows = metaNodes.map(meta => meta.closest('[role="row"]') || meta.parentElement).filter(Boolean);
  rows = [...new Set(rows)];
}

const mainRect = main.getBoundingClientRect();

const parsed = rows.map((row, i) => {
  const metaEl = row.matches && row.matches('[data-pre-plain-text]')
    ? row
    : row.querySelector('[data-pre-plain-text]');

  const metadata = metaEl
    ? clean(metaEl.getAttribute('data-pre-plain-text'))
    : '';

  // WhatsApp can render nested selectable-text spans. Taking the longest
  // top-level candidate avoids duplicated text in the JSON.
  let textEls = [...row.querySelectorAll('span.selectable-text')];
  textEls = textEls.filter(el =>
    !textEls.some(other => other !== el && other.contains(el))
  );

  const candidates = textEls
    .map(el => clean(el.innerText))
    .filter(Boolean);

  let text = '';
  if (candidates.length) {
    text = candidates.reduce((best, cur) => cur.length > best.length ? cur : best, '');
  }

  const hasImage = [...row.querySelectorAll('img')].some(img => {
    const r = img.getBoundingClientRect();
    return r.width >= 80 && r.height >= 60;
  });

  const anchor = metaEl || row;
  const r = anchor.getBoundingClientRect();
  const center = r.left + r.width / 2;
  const mainCenter = mainRect.left + mainRect.width / 2;
  const direction = center > mainCenter ? 'out' : 'in';

  const idNode = row.matches('[data-id]') ? row : row.querySelector('[data-id]');
  const domId = idNode ? (idNode.getAttribute('data-id') || '') : '';

  return {
    number: i + 1,
    direction,
    metadata,
    text,
    hasImage,
    domId
  };
});

return parsed.slice(-limit);
