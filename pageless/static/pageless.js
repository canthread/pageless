// pageless browser player: receives validated steps over SSE and assembles the page one change at a time.
(() => {
  "use strict";

  const page = document.querySelector("[data-pl-stream]");
  if (!page) return;
  const grid = page.querySelector(".pl-grid");
  const status = page.querySelector(".pl-status");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  // Pause after each event (ms) so fast model output stays watchable.
  const PACE = {
    "page.start": 0, "layout.outline": 450, "section.start": 220, "section.text": 180,
    "section.ready": 380, "layout.move": 600, "section.replace": 380, "page.done": 0, "stream.error": 0,
  };
  const EVENTS = Object.keys(PACE).filter((n) => n !== "stream.error");

  const queue = [];
  let playing = false;
  let received = false; // page.done arrived
  let source = null;

  const blockFor = (id) => grid.querySelector(`.pl-block[data-id="${CSS.escape(id)}"]`);

  function place(el, { span, order }) {
    if (span != null) el.style.setProperty("--span", span);
    if (order != null) el.style.setProperty("--order", order);
  }

  function ensureBlock(d) {
    let el = blockFor(d.id);
    if (!el) {
      el = document.createElement("div");
      el.className = "pl-block";
      el.dataset.id = d.id;
      grid.appendChild(el);
    }
    if (d.component) el.dataset.component = d.component;
    place(el, d);
    return el;
  }

  // Which block is the visitor reading? Keep it fixed on screen while others move.
  function readingAnchor() {
    if (window.scrollY < 4) return null; // at the top: let the page grow naturally
    let best = null, bestDist = Infinity;
    for (const el of grid.children) {
      const r = el.getBoundingClientRect();
      if (r.bottom <= 0 || r.top >= window.innerHeight) continue;
      const dist = Math.abs(r.top);
      if (dist < bestDist) { best = el; bestDist = dist; }
    }
    return best && { el: best, top: best.getBoundingClientRect().top };
  }

  // Apply a DOM change with FLIP animation and reading-position anchoring.
  function mutate(change) {
    const animate = !reduceMotion.matches;
    const anchor = readingAnchor();
    const blocks = [...grid.children];
    const first = new Map();
    if (animate) for (const el of blocks) first.set(el, docRect(el));

    change();

    if (anchor && anchor.el.isConnected) {
      const delta = anchor.el.getBoundingClientRect().top - anchor.top;
      if (Math.abs(delta) > 1) window.scrollBy(0, delta);
    }
    if (!animate) return;
    for (const el of grid.children) {
      const before = first.get(el);
      if (!before) {
        el.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }],
          { duration: 260, easing: "ease-out" });
        continue;
      }
      const after = docRect(el);
      const dx = before.left - after.left, dy = before.top - after.top;
      const sx = before.width / (after.width || 1), sy = before.height / (after.height || 1);
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(sx - 1) < 0.01 && Math.abs(sy - 1) < 0.01) continue;
      el.animate([
        { transformOrigin: "top left", transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
        { transformOrigin: "top left", transform: "none" },
      ], { duration: 420, easing: "cubic-bezier(.2,.7,.2,1)" });
    }
  }

  function docRect(el) {
    const r = el.getBoundingClientRect();
    return { left: r.left + window.scrollX, top: r.top + window.scrollY, width: r.width, height: r.height };
  }

  function skeleton(component) {
    const s = document.createElement("div");
    s.className = "pl-skel";
    s.innerHTML = '<div class="pl-skel__line pl-skel__line--title"></div>' +
      '<div class="pl-skel__line"></div><div class="pl-skel__line"></div><div class="pl-skel__line pl-skel__line--short"></div>';
    const label = document.createElement("span");
    label.className = "pl-skel__label";
    label.textContent = component;
    s.prepend(label);
    return s;
  }

  function finalize(el, d, cls) {
    el.classList.remove("is-wire", "is-placeholder", "is-stalled");
    el.classList.add("is-ready");
    if (cls) el.classList.add(cls);
    el.dataset.component = d.component;
    el.innerHTML = d.html; // server-rendered from validated props; all text is escaped there
  }

  const handlers = {
    "page.start"(d) {
      document.title = `${d.title} · ${d.site}`;
      status.textContent = "Composing this page…";
    },
    "layout.outline"(d) {
      mutate(() => {
        for (const s of d.sections) {
          const el = ensureBlock(s);
          el.classList.add("is-wire");
          el.replaceChildren(skeleton(s.component));
        }
      });
    },
    "section.start"(d) {
      mutate(() => {
        const el = ensureBlock(d);
        el.classList.remove("is-wire");
        el.classList.add("is-placeholder");
        if (!el.firstChild) el.replaceChildren(skeleton(d.component));
      });
    },
    "section.text"(d) {
      const el = blockFor(d.id);
      if (!el) return;
      let slot = el.querySelector(`[data-field="${CSS.escape(d.field)}"]`);
      if (!slot) {
        slot = document.createElement(d.field === "heading" ? "h2" : "p");
        slot.className = "pl-ph-text";
        slot.dataset.field = d.field;
        (el.querySelector(".pl-skel") || el).prepend(slot);
      }
      slot.textContent = d.text; // textContent: never interpreted as HTML
    },
    "section.ready"(d) { mutate(() => finalize(ensureBlock(d), d)); },
    "section.replace"(d) { mutate(() => finalize(ensureBlock(d), d, "is-fallback")); },
    "layout.move"(d) {
      mutate(() => { for (const s of d.layout) { const el = blockFor(s.id); if (el) place(el, s); } });
    },
    "page.done"() {
      for (const el of grid.querySelectorAll(".is-wire, .is-placeholder")) el.remove();
      page.setAttribute("aria-busy", "false");
      page.classList.add("is-done");
      status.textContent = "";
    },
    "stream.error"() {
      // Keep everything already placed; offer a retry for unfinished blocks.
      const unfinished = grid.querySelectorAll(".is-wire, .is-placeholder");
      page.setAttribute("aria-busy", "false");
      status.textContent = unfinished.length ? "The connection dropped before this page finished." : "";
      for (const el of unfinished) {
        el.classList.add("is-stalled");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "c-button";
        button.textContent = "Retry";
        button.addEventListener("click", () => window.location.reload());
        el.append(button);
      }
    },
  };

  function enqueue(name, data) {
    queue.push({ name, data });
    if (!playing) play();
  }

  function play() {
    const next = queue.shift();
    if (!next) { playing = false; return; }
    playing = true;
    try { handlers[next.name](next.data); } catch (err) { console.error("pageless:", next.name, err); }
    const wait = PACE[next.name] * (reduceMotion.matches ? 0.3 : 1);
    setTimeout(play, wait);
  }

  source = new EventSource(page.dataset.plStream);
  for (const name of EVENTS) {
    source.addEventListener(name, (e) => {
      if (name === "page.done") { received = true; source.close(); }
      enqueue(name, JSON.parse(e.data));
    });
  }
  source.onerror = () => {
    source.close(); // no automatic reconnect: it would restart the page from scratch
    if (!received) enqueue("stream.error", {});
  };
})();
