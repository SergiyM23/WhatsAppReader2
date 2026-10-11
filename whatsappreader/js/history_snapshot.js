const main = document.querySelector("#main");
if (!main) return { count: 0, earliest: "", latest: "" };

const metas = [...main.querySelectorAll('[data-pre-plain-text]')]
  .map(el => String(el.getAttribute('data-pre-plain-text') || '').replace(/\u200e/g, "").trim())
  .filter(Boolean);

return {
  count: metas.length,
  earliest: metas.length ? metas[0] : "",
  latest: metas.length ? metas[metas.length - 1] : ""
};
