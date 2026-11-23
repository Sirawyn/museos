// Small progressive enhancements. Everything works without JavaScript too.
(function () {
  // auto-submit selects / date pickers in filters
  document.querySelectorAll("[data-autosubmit]").forEach(el => el.addEventListener("change", () => el.form.submit()));

  // clickable table rows
  document.querySelectorAll("tr[data-href]").forEach(tr => tr.addEventListener("click", e => {
    if (e.target.closest("a, button, input, select, .pick")) return;
    location.href = tr.dataset.href;
  }));

  // confirm destructive forms
  document.querySelectorAll("form[data-confirm]").forEach(f => f.addEventListener("submit", e => {
    if (!window.confirm(f.dataset.confirm)) e.preventDefault();
  }));

  // instant filter on the guest list
  document.querySelectorAll("input[data-filter]").forEach(inp => inp.addEventListener("input", () => {
    const q = inp.value.trim().toLowerCase();
    document.querySelectorAll(inp.dataset.filter).forEach(el => {
      el.hidden = q && !(el.dataset.search || el.textContent).toLowerCase().includes(q);
    });
  }));

  // +/- steppers
  document.addEventListener("click", e => {
    const b = e.target.closest(".step");
    if (!b) return;
    const input = b.parentElement.querySelector("input");
    input.value = Math.max(0, (parseInt(input.value, 10) || 0) + parseInt(b.dataset.step, 10));
  });

  // one-tap check-in without reloading the page
  document.addEventListener("submit", async e => {
    const f = e.target;
    if (!f.matches("form[data-ajax]")) return;
    e.preventDefault();
    const card = f.closest(".guest");
    card && card.classList.add("busy");
    try {
      const r = await fetch(f.action, { method: "POST", body: new FormData(f), headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" });
      if (r.redirected && r.url.includes("/login")) { location.href = r.url; return; }
      if (!r.ok) throw new Error(r.status);
      const html = await r.text();
      const tmp = document.createElement("div");
      tmp.innerHTML = html.trim();
      card.replaceWith(tmp.firstElementChild);
    } catch (err) {
      card && card.classList.remove("busy");
      f.submit();
    }
  });
})();

// Weekly setup: ticking a venue highlights it; picking a host ticks it
document.querySelectorAll(".lv").forEach(box => {
  const cb = box.querySelector("input[type=checkbox]"), sel = box.querySelector("select");
  cb.addEventListener("change", () => box.classList.toggle("on", cb.checked));
  const tick = el => () => { if (el.value && !cb.checked) { cb.checked = true; box.classList.add("on"); } };
  sel.addEventListener("change", tick(sel));
  box.querySelectorAll("input[name^=dc_], input[name^=cv_], input[name^=tl_], input[name^=lc_]").forEach(el => el.addEventListener("input", tick(el)));
});

// copy-to-clipboard buttons (login link message)
document.querySelectorAll("[data-copy]").forEach(btn => btn.addEventListener("click", async () => {
  const el = document.querySelector(btn.dataset.copy);
  try { await navigator.clipboard.writeText(el.value || el.textContent); btn.textContent = "Copied"; }
  catch { el.select && el.select(); document.execCommand && document.execCommand("copy"); btn.textContent = "Copied"; }
  setTimeout(() => btn.textContent = "Copy message", 2000);
}));

// bulk delete (admins): tick rows, then "Delete selected"
document.querySelectorAll("form[data-bulk]").forEach(f => {
  const boxes = () => Array.from(document.querySelectorAll('input[name=ids][form="' + f.id + '"]'));
  const all = f.querySelector("[data-select-all]"), btn = f.querySelector("[data-bulk-delete]"), count = f.querySelector("[data-bulk-count]");
  const sync = () => {
    const n = boxes().filter(b => b.checked).length;
    count.textContent = n + " selected";
    btn.disabled = n === 0;
    btn.textContent = n ? "Delete " + n + " selected" : "Delete selected";
    all.checked = n > 0 && n === boxes().length;
    f.dataset.confirm = "Delete " + n + " " + f.dataset.singular + (n === 1 ? "" : "s") + "? This can't be undone.";
    boxes().forEach(b => b.closest("tr").classList.toggle("picked", b.checked));
  };
  all.addEventListener("change", () => { boxes().forEach(b => b.checked = all.checked); sync(); });
  document.addEventListener("change", e => { if (e.target.matches('input[name=ids]')) sync(); });
  sync();
});
