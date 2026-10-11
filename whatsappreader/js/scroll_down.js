const main = document.querySelector("#main");
if (!main) return { success:false, reason:"no-main" };

const meta = main.querySelector('[data-pre-plain-text]');
if (!meta) return { success:false, reason:"no-message-metadata" };

const row = meta.closest('[role="row"]') || meta;
let p = row.parentElement;
let chosen = null;

while (p && p !== document.body) {
  const r = p.getBoundingClientRect();
  if (p.scrollHeight > p.clientHeight + 100 && r.height > 150) {
    chosen = p;
    break;
  }
  if (p === main) break;
  p = p.parentElement;
}

if (!chosen) {
  const candidates = [...main.querySelectorAll("div")]
    .filter(el => el.contains(meta) && el.scrollHeight > el.clientHeight + 100)
    .sort((a,b) => a.getBoundingClientRect().height - b.getBoundingClientRect().height);
  if (candidates.length) chosen = candidates[0];
}

if (!chosen) return { success:false, reason:"no-ancestor-scroll-container" };

const before = chosen.scrollTop;
const distance = Math.max(1000, Math.floor(chosen.clientHeight * 1.5));

try {
  chosen.scrollBy({ top: distance, left: 0, behavior: "instant" });
} catch {
  chosen.scrollTop = before + distance;
}

chosen.dispatchEvent(new WheelEvent("wheel", {
  deltaY: distance,
  bubbles: true,
  cancelable: true
}));
chosen.dispatchEvent(new Event("scroll", { bubbles:true }));

const remaining = chosen.scrollHeight - (chosen.scrollTop + chosen.clientHeight);

return {
  success:true,
  before,
  after:chosen.scrollTop,
  atBottom: remaining <= 5,
  clientHeight:chosen.clientHeight,
  scrollHeight:chosen.scrollHeight
};
