/* ═══════════════════════════════════════════════════════════════════════════
   I JUST WANT TO EAT — page logic.

   Reads window.SITE_DATA (written by scripts/update.py) and renders every
   section from it. Data is a plain assignment rather than a fetch so the page
   still works opened straight off the disk; fetch() would hit CORS on file://.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  const D = window.SITE_DATA || {};
  const posts = D.posts || [];
  const totals = D.totals || {};
  const profile = D.profile || {};
  const links = profile.links || {};

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));

  const num = (n) => Number(n || 0).toLocaleString("en-US");

  const compact = (n) =>
    n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "K" : String(n);

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const when = (sec, long = false) => {
    if (!sec) return "";
    const d = new Date(sec * 1000);
    return long
      ? `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`
      : `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  };

  /* ── reveal on scroll ─────────────────────────────────────────────────── */
  const eye = new IntersectionObserver(
    (rows) => rows.forEach((r) => {
      if (r.isIntersecting) { r.target.classList.add("seen"); eye.unobserve(r.target); }
    }),
    { rootMargin: "0px 0px -12% 0px", threshold: 0.08 }
  );
  const watch = (root = document) => $$(".reveal", root).forEach((el) => eye.observe(el));

  /* ── masthead metadata ────────────────────────────────────────────────── */
  const editionLine = () => {
    const left = $("#editionLeft");
    const right = $("#editionRight");
    if (left) left.textContent = profile.home || "New York & New Jersey";
    if (right) {
      const n = totals.archive || totals.posts || 0;
      right.textContent = n ? `No. ${num(n)}` : "—";
    }
    const stamp = $("#stamp");
    if (stamp && D.updated) {
      const d = new Date(D.updated);
      stamp.textContent = isNaN(d) ? "—" : when(d.getTime() / 1000, true);
    }
    const archive = $("#archiveLink");
    if (archive && profile.site) archive.href = profile.site + "/post";
  };

  /* ── the lede plate: his newest post with a photo ─────────────────────── */
  const lede = () => {
    const top = posts.find((p) => p.img && p.kind === "review") || posts[0];
    const fig = $("#ledePlate");
    if (!top || !fig) { fig?.remove(); return; }

    const img = $("#ledeImg");
    img.src = top.img;
    img.alt = `Photographed by Jean-Philippe Gerbi at ${top.n}`;

    const bits = [top.hood || top.areaLabel, top.cuisineLabel].filter(
      (b) => b && b !== "Other" && b !== "Elsewhere"
    );
    $("#ledeKick").textContent = bits.join(" · ") || "Latest";
    const a = $("#ledeTitle");
    a.textContent = top.t;
    a.href = top.u;
    $("#ledeDate").textContent = when(top.d, true);
  };

  /* ── ledger: count up on first sight ──────────────────────────────────── */
  const ledger = () => {
    const ig = D.instagram || {};
    const pool = {
      ...totals,
      igFollowers: ig.followers || 0,
    };

    if (ig.followers) $("#igCell")?.removeAttribute("hidden");

    $$("[data-count]").forEach((el) => {
      const target = Number(pool[el.dataset.from] || 0);
      const label = el.dataset.from === "igFollowers" ? compact(target) : num(target);
      if (!target) { el.textContent = "—"; return; }
      if (calm) { el.textContent = label; return; }

      el.textContent = "0";
      const io = new IntersectionObserver((rows) => {
        if (!rows[0].isIntersecting) return;
        io.disconnect();
        const ms = 1250;
        const t0 = performance.now();
        const step = (now) => {
          const k = Math.min(1, (now - t0) / ms);
          const eased = 1 - Math.pow(1 - k, 3);
          el.textContent = k < 1
            ? (el.dataset.from === "igFollowers"
                ? compact(Math.round(target * eased))
                : num(Math.round(target * eased)))
            : label;
          if (k < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }, { threshold: 0.4 });
      io.observe(el);
    });
  };

  /* ═══ 01 · THE REVIEWS ═══════════════════════════════════════════════ */

  // Six at a time on the desktop grid; three on a phone, where every card is a
  // full-width block and six of them is a long scroll before the button shows.
  const NARROW = matchMedia("(max-width: 720px)");
  const step = () => (NARROW.matches ? 3 : 6);

  const state = { area: "all", cuisine: "all", q: "", shown: step() };

  // Product and sponsored posts are his too, but they are not restaurant
  // reviews and they drown the grid, so they live behind their own tab.
  const feed = posts.filter((p) => p.kind !== "recipe");

  const areaTally = () => {
    const seen = new Map();
    feed.forEach((p) => {
      if (p.area === "elsewhere") return;
      const row = seen.get(p.area) || { key: p.area, label: p.areaLabel, n: 0 };
      row.n++; seen.set(p.area, row);
    });
    return [...seen.values()].sort((a, b) => b.n - a.n);
  };

  const cuisineTally = () => {
    const seen = new Map();
    feed.forEach((p) => {
      if (p.cuisine === "other" || p.kind !== "review") return;
      const row = seen.get(p.cuisine) || { key: p.cuisine, label: p.cuisineLabel, emoji: p.emoji, n: 0 };
      row.n++; seen.set(p.cuisine, row);
    });
    return [...seen.values()].sort((a, b) => b.n - a.n).slice(0, 12);
  };

  const matches = (p) => {
    if (state.area === "starred" ? !p.starred
      : state.area === "product" ? p.kind !== "product"
      : state.area !== "all" && p.area !== state.area) return false;
    if (state.area !== "product" && state.cuisine !== "all" && p.cuisine !== state.cuisine) return false;
    if (state.q) {
      const hay = `${p.t} ${p.n} ${p.areaLabel} ${p.hood} ${p.cuisineLabel}`.toLowerCase();
      if (!state.q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  };

  const cardHTML = (p, i) => {
    const bits = [];
    if (p.hood) bits.push(`<span class="pl">${esc(p.hood)}</span>`);
    else if (p.areaLabel && p.area !== "elsewhere") bits.push(`<span class="pl">${esc(p.areaLabel)}</span>`);
    if (p.cuisineLabel && p.cuisine !== "other") bits.push(esc(p.cuisineLabel));

    return `<a class="card" style="--i:${i}" href="${esc(p.u)}" target="_blank" rel="noopener">
      <span class="card__shot">
        ${p.img ? `<img src="${esc(p.img)}" alt="" loading="lazy" decoding="async">` : ""}
        ${p.starred ? `<span class="card__star">★ Starred</span>` : ""}
        ${p.kind === "product" ? `<span class="card__kind">Product</span>` : ""}
      </span>
      <span class="card__meta">${bits.join('<span class="dot">·</span>') || "On the blog"}</span>
      <span class="card__t">${esc(p.t)}</span>
      <span class="card__foot">
        <span>${esc(when(p.d))}</span>
        <span class="card__go" aria-hidden="true">Read →</span>
      </span>
    </a>`;
  };

  const paint = () => {
    const hits = feed.filter(matches);
    const slice = hits.slice(0, state.shown);
    const box = $("#cards");

    box.innerHTML = slice.length
      ? slice.map(cardHTML).join("")
      : `<div class="empty">
           <p>Nothing on the menu for that.</p>
           <span>Try another neighbourhood, or clear the search</span>
         </div>`;

    const tally = $("#tally");
    const where = state.area === "all" ? ""
      : state.area === "starred" ? " · starred rooms"
      : state.area === "product" ? " · product reviews"
      : ` · ${areaTally().find((a) => a.key === state.area)?.label || ""}`;
    tally.innerHTML = `Showing <b>${num(slice.length)}</b> of <b>${num(hits.length)}</b>${esc(where)}${
      state.q ? ` · “${esc(state.q)}”` : ""}`;

    const btn = $("#moreBtn");
    const left = hits.length - slice.length;
    btn.hidden = left <= 0;
    $("#moreLabel").textContent = `Show ${Math.min(left, step())} more`;
  };

  const buildTabs = () => {
    const areas = areaTally();
    const aBox = $("#areaTabs");
    const starred = feed.filter((p) => p.starred).length;
    const products = feed.filter((p) => p.kind === "product").length;

    const rows = [
      { key: "all", label: "Everywhere", n: feed.length },
      ...areas,
      ...(starred ? [{ key: "starred", label: "★ Starred", n: starred }] : []),
      ...(products ? [{ key: "product", label: "Products", n: products }] : []),
    ];
    aBox.innerHTML = rows.map((r) =>
      `<button class="tab${r.key === "all" ? " on" : ""}" role="tab" data-area="${esc(r.key)}"
        aria-selected="${r.key === "all"}">${esc(r.label)}<b>${r.n}</b></button>`
    ).join("");

    const cBox = $("#cuisineTabs");
    cBox.innerHTML = [{ key: "all", label: "All plates" }, ...cuisineTally()].map((r) =>
      `<button class="tab${r.key === "all" ? " on" : ""}" role="tab" data-cuisine="${esc(r.key)}"
        aria-selected="${r.key === "all"}">${r.emoji ? esc(r.emoji) + " " : ""}${esc(r.label)}</button>`
    ).join("");

    const pick = (box, attr, key) => {
      $$(".tab", box).forEach((t) => {
        const on = t.dataset[attr] === key;
        t.classList.toggle("on", on);
        t.setAttribute("aria-selected", String(on));
      });
    };

    aBox.addEventListener("click", (e) => {
      const t = e.target.closest(".tab"); if (!t) return;
      state.area = t.dataset.area; state.shown = step();
      // The cuisine filter is meaningless inside the product tab.
      if (state.area === "product") { state.cuisine = "all"; pick(cBox, "cuisine", "all"); }
      cBox.parentElement.parentElement.style.opacity = state.area === "product" ? ".4" : "";
      pick(aBox, "area", state.area);
      paint();
    });

    cBox.addEventListener("click", (e) => {
      const t = e.target.closest(".tab"); if (!t) return;
      state.cuisine = t.dataset.cuisine; state.shown = step();
      pick(cBox, "cuisine", state.cuisine);
      paint();
    });

    $("#moreBtn").addEventListener("click", () => {
      const before = $$(".card").length;
      state.shown += step();
      paint();
      // Put the first newly-revealed card in view, rather than leaving the
      // reader parked on the button they just pressed.
      $$(".card")[before]?.querySelector(".card__t")?.scrollIntoView({
        block: "center", behavior: calm ? "auto" : "smooth",
      });
    });

    // Crossing the phone/desktop line mid-session must not leave the grid
    // showing fewer cards than a single press would now add.
    NARROW.addEventListener("change", () => {
      state.shown = Math.max(state.shown, step());
      paint();
    });

    const find = $("#find");
    const clear = $("#findClear");
    let timer;
    find.addEventListener("input", () => {
      clearTimeout(timer);
      clear.hidden = !find.value;
      timer = setTimeout(() => {
        state.q = find.value.trim().toLowerCase();
        state.shown = step();
        paint();
      }, 140);
    });
    clear.addEventListener("click", () => {
      find.value = ""; clear.hidden = true; state.q = ""; state.shown = step(); paint(); find.focus();
    });

    $("#renderCount").textContent = num(feed.length);
  };

  /* ═══ SHARED: reveal-by-hiding pagination ════════════════════════════
     Used by the starred rooms, the recipes, the podcast and the beat. Rows are
     rendered once and revealed by un-hiding, rather than re-rendered on every
     press, so the fade-in never replays on rows already on screen. */
  const paginate = ({ items, btn, label, page, first, onShow }) => {
    if (!items.length || !btn) return;
    const start = first || page; // recipes open with more than they step by
    let shown = Math.min(start(), items.length);

    const apply = () => {
      items.forEach((el, i) => { el.hidden = i >= shown; });
      const left = items.length - shown;
      btn.hidden = left <= 0;
      // Leave the last label alone once the list is exhausted, so the button
      // never flashes "Show 0 more" on its way out.
      if (left > 0) label.textContent = `Show ${Math.min(left, page())} more`;
      onShow?.(shown);
    };

    btn.addEventListener("click", () => {
      const first = shown;
      shown = Math.min(shown + page(), items.length);
      apply();
      // Land on the first newly-revealed row, not on the button just pressed.
      items[first]?.scrollIntoView({ block: "center", behavior: calm ? "auto" : "smooth" });
    });

    // Crossing the phone/desktop line must not leave fewer rows on screen than
    // a single press would now add.
    NARROW.addEventListener("change", () => {
      shown = Math.min(Math.max(shown, start()), items.length);
      apply();
    });

    apply();
  };

  // Seven rows on a desktop, five on a phone, then the same again per press.
  const listPage = () => (NARROW.matches ? 5 : 7);

  /* ═══ 02 · THE STARRED ROOMS ═════════════════════════════════════════ */
  const starred = () => {
    const rows = D.michelin || [];
    const box = $("#stars-list");
    if (!rows.length) { $("#stars")?.remove(); return; }

    box.innerHTML = rows.map((r, i) =>
      `<li class="star">
        <a href="${esc(r.u)}" target="_blank" rel="noopener">
          <span class="star__n">${String(i + 1).padStart(2, "0")}</span>
          <span class="star__name">${esc(r.n)}</span>
          <span class="star__pip" aria-hidden="true">★</span>
          <span class="star__go">His write-up →</span>
        </a>
      </li>`
    ).join("");

    paginate({
      items: $$(".star", box),
      btn: $("#starMore"),
      label: $("#starMoreLabel"),
      page: listPage,
    });
  };

  /* ═══ 03 · PICK OF THE MONTH ═════════════════════════════════════════ */
  const picks = () => {
    const rows = D.picks || [];
    const rail = $("#picks-rail");
    if (!rows.length) { $("#picks")?.remove(); return; }

    // His oldest picks lost their photographs somewhere in a platform move, so
    // those get a typographic card rather than a grey rectangle.
    rail.innerHTML = rows.map((p) => {
      const yr = p.d ? new Date(p.d * 1000).getFullYear() : "";
      const tag = yr ? `<span class="pick__yr" aria-hidden="true">’${String(yr).slice(2)}</span>` : "";
      const shot = p.img
        ? `<span class="pick__shot"><img src="${esc(p.img)}" alt="" loading="lazy" decoding="async">${tag}</span>`
        : `<span class="pick__shot pick__shot--bare">
             <span class="pick__word">${esc(p.t.split(/[,(]| in | at /)[0].trim())}</span>
             <span class="pick__gone">photograph lost to the archive</span>${tag}
           </span>`;
      return `<a class="pick" href="${esc(p.u)}" target="_blank" rel="noopener">
        ${shot}
        <span class="pick__t">${esc(p.t)}</span>
        <span class="pick__m">${esc(when(p.d, true))}</span>
      </a>`;
    }).join("");

    dragScroll(rail);
  };

  /* Click-and-drag for the horizontal rails, since not everyone has a
     trackpad and a scrollbar three pixels tall is a poor target. */
  const dragScroll = (el) => {
    let down = false, x0 = 0, left0 = 0, moved = 0;
    el.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "touch") return;
      down = true; moved = 0; x0 = e.clientX; left0 = el.scrollLeft;
      el.classList.add("dragging");
    });
    const stop = () => { down = false; el.classList.remove("dragging"); };
    el.addEventListener("pointermove", (e) => {
      if (!down) return;
      const dx = e.clientX - x0;
      moved = Math.max(moved, Math.abs(dx));
      el.scrollLeft = left0 - dx;
    });
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointerleave", stop);
    el.addEventListener("click", (e) => { if (moved > 6) e.preventDefault(); }, true);
  };

  /* ═══ 04 · RECIPES ═══════════════════════════════════════════════════ */
  // Twelve cards fill the desktop grid without dominating the section; a phone
  // gets three, since each card is a full-width block there.
  const rcpFirst = () => (NARROW.matches ? 3 : 12);
  const rcpStep = () => (NARROW.matches ? 3 : 8);

  const recipes = () => {
    const rows = D.recipes || [];
    const box = $("#recipes");
    if (!rows.length) { $("#kitchen")?.remove(); return; }

    // Rendered once, then revealed by un-hiding. Re-rendering the list on every
    // press would replay the fade-in on cards the reader is already looking at.
    box.innerHTML = rows.map((r, i) =>
      `<a class="rcp reveal" href="${esc(r.u)}" target="_blank" rel="noopener">
        <span class="rcp__n">No. ${String(i + 1).padStart(2, "0")}</span>
        <span class="rcp__t">${esc(r.n)}</span>
        <span class="rcp__go">Method <span aria-hidden="true">→</span></span>
      </a>`
    ).join("");

    paginate({
      items: $$(".rcp", box),
      btn: $("#rcpMore"),
      label: $("#rcpMoreLabel"),
      page: rcpStep,
      first: rcpFirst,
      onShow: () => watch(box), // newly shown cards can now be observed and faded in
    });
  };

  /* ═══ 05 · THE BEAT ══════════════════════════════════════════════════ */
  const beat = () => {
    const rows = areaTally().filter((r) => r.key !== "elsewhere");
    const box = $("#beatBars");
    const counted = rows.reduce((s, r) => s + r.n, 0);
    $("#beatN").textContent = num(counted);

    const top = rows[0]?.n || 1;
    box.innerHTML = rows.map((r, i) => {
      const share = Math.round((r.n / counted) * 100);
      return `<li class="bar">
        <span class="bar__top">
          <span class="bar__name">${esc(r.label)}</span>
          <span class="bar__sub">${share}% of the beat</span>
        </span>
        <span class="bar__n">${num(r.n)}</span>
        <span class="bar__track"><i class="bar__fill" style="--i:${i}" data-w="${(r.n / top) * 100}"></i></span>
      </li>`;
    }).join("");

    // Bars draw themselves only once the section is on screen, and only once
    // they are actually revealed - a hidden bar filled in advance would pop up
    // already complete instead of growing.
    let armed = false;
    const draw = () => {
      if (!armed) return;
      $$(".bar", box).forEach((li) => {
        if (li.hidden) return;
        const f = li.querySelector(".bar__fill");
        if (f.dataset.drawn) return;
        f.dataset.drawn = "1";
        requestAnimationFrame(() => { f.style.width = f.dataset.w + "%"; });
      });
    };

    const io = new IntersectionObserver((r) => {
      if (!r[0].isIntersecting) return;
      io.disconnect();
      armed = true;
      draw();
    }, { threshold: 0.2 });
    io.observe(box);

    paginate({
      items: $$(".bar", box),
      btn: $("#beatMore"),
      label: $("#beatMoreLabel"),
      page: listPage,
      onShow: draw,
    });

    const chips = $("#hoodChips");
    const hoods = D.hoods || [];
    chips.innerHTML = hoods.length
      ? hoods.map((h) => `<span class="chip">${esc(h)}</span>`).join("")
      : `<span class="chip">Coming soon</span>`;

    if (links.map) $("#mapLink").href = links.map;
  };

  /* ═══ 06 · PODCAST ═══════════════════════════════════════════════════ */
  const pods = () => {
    const rows = D.podcasts || [];
    const box = $("#pods");
    if (!rows.length) { $("#studio")?.remove(); return; }

    // His episode artwork no longer resolves on the blog, so when none of it
    // loads the thumbnail column is dropped rather than filled with grey.
    const art = rows.some((p) => p.img);
    box.classList.toggle("pods--bare", !art);

    box.innerHTML = rows.map((p, i) =>
      `<li class="pod">
        <a href="${esc(p.u)}" target="_blank" rel="noopener">
          <span class="pod__n">${String(rows.length - i).padStart(2, "0")}</span>
          ${art ? `<span class="pod__shot">${p.img ? `<img src="${esc(p.img)}" alt="" loading="lazy" decoding="async">` : ""}</span>` : ""}
          <span class="pod__t">${esc(p.t)}</span>
          <span class="pod__go">Listen →</span>
        </a>
      </li>`
    ).join("");

    paginate({
      items: $$(".pod", box),
      btn: $("#podMore"),
      label: $("#podMoreLabel"),
      page: listPage,
    });
  };

  /* ═══ 07 · FOLLOW + FOOTER LINKS ═════════════════════════════════════ */
  const ICON = {
    instagram: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3.2" y="3.2" width="17.6" height="17.6" rx="5"/><circle cx="12" cy="12" r="4.1"/><circle cx="17.3" cy="6.7" r="1.15" fill="currentColor" stroke="none"/></svg>`,
    facebook: `<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M13.5 21v-8h2.7l.4-3.1h-3.1V7.9c0-.9.25-1.5 1.55-1.5h1.65V3.6c-.3 0-1.3-.1-2.45-.1-2.4 0-4.05 1.5-4.05 4.2v2.2H7.5V13h2.7v8h3.3z"/></svg>`,
    x: `<svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor"><path d="M17.6 3h3.3l-7.2 8.2L22 21h-6.6l-5.2-6.7L4.3 21H1l7.7-8.8L1.4 3H8l4.7 6.2L17.6 3zm-1.2 16h1.8L7.7 4.9H5.8L16.4 19z"/></svg>`,
    threads: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M16.4 11.4c-2.6-1.2-6.1-1-6.1 1.3 0 1.5 1.4 2.2 2.6 2 1.8-.3 2.4-2.2 2.4-4.6 0-3-1.4-4.6-3.6-4.6-1.6 0-2.8.8-3.4 2M12 3.2c5 0 8.2 3.1 8.2 8.8S17 20.8 12 20.8 3.8 17.6 3.8 12 7 3.2 12 3.2Z" stroke-linecap="round"/></svg>`,
    podcast: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="9.4" y="2.6" width="5.2" height="10.4" rx="2.6"/><path d="M5.4 11.2a6.6 6.6 0 0 0 13.2 0M12 17.8V21" stroke-linecap="round"/></svg>`,
    site: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="8.8"/><path d="M3.2 12h17.6M12 3.2c2.4 2.6 3.6 5.6 3.6 8.8s-1.2 6.2-3.6 8.8c-2.4-2.6-3.6-5.6-3.6-8.8S9.6 5.8 12 3.2Z"/></svg>`,
    map: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 21s6.4-6 6.4-10.4a6.4 6.4 0 1 0-12.8 0C5.6 15 12 21 12 21Z"/><circle cx="12" cy="10.4" r="2.4"/></svg>`,
  };

  const social = () => {
    const ig = D.instagram || {};
    const rows = [
      links.instagram && { k: "instagram", n: "Instagram", h: ig.followers ? `${compact(ig.followers)} followers` : "@ijustwant2eat", u: links.instagram },
      links.podcast && { k: "podcast", n: "The podcast", h: `${totals.podcasts || ""} episodes`.trim(), u: links.podcast },
      links.facebook && { k: "facebook", n: "Facebook", h: "", u: links.facebook },
      links.x && { k: "x", n: "X", h: "", u: links.x },
      links.threads && { k: "threads", n: "Threads", h: "", u: links.threads },
    ].filter(Boolean);

    $("#follow").innerHTML = rows.map((r) =>
      `<a class="fol" href="${esc(r.u)}" target="_blank" rel="noopener">
        ${ICON[r.k] || ""}
        <span class="fol__n">${esc(r.n)}</span>
        ${r.h ? `<span class="fol__h">${esc(r.h)}</span>` : ""}
      </a>`
    ).join("");

    const foot = [
      profile.site && { k: "site", n: "The blog", u: profile.site },
      links.instagram && { k: "instagram", n: "Instagram", u: links.instagram },
      links.podcast && { k: "podcast", n: "Podcast", u: links.podcast },
      links.map && { k: "map", n: "The map", u: links.map },
      links.contact && { k: "site", n: "Contact him", u: links.contact },
    ].filter(Boolean);

    $("#footLinks").innerHTML = foot.map((r) =>
      `<a href="${esc(r.u)}" target="_blank" rel="noopener">${ICON[r.k] || ""}${esc(r.n)}</a>`
    ).join("");
  };

  /* ═══ 08 · THE LETTER ════════════════════════════════════════════════ */
  const KEY_PLACEHOLDER = "YOUR_WEB3FORMS_ACCESS_KEY";

  const letter = () => {
    const form = $("#letterForm");
    const note = $("#letterNote");
    const send = $("#letterSend");
    if (!form) return;

    const say = (msg, cls = "") => { note.textContent = msg; note.className = "letter__note " + cls; };

    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const bad = [...form.elements].find(
        (el) => el.willValidate && el.required && !el.checkValidity()
      );
      $$("input,textarea", form).forEach((el) => el.removeAttribute("aria-invalid"));
      if (bad) {
        bad.setAttribute("aria-invalid", "true");
        bad.focus();
        say("Name, email and the restaurant, please.", "bad");
        return;
      }

      const key = form.elements.access_key.value;
      if (!key || key === KEY_PLACEHOLDER) {
        // Better to refuse loudly than to swallow a real tip into nothing.
        say("This form isn’t wired up yet — see the README for the one-minute setup.", "bad");
        return;
      }

      send.disabled = true;
      say("Sending…");
      try {
        const res = await fetch("https://api.web3forms.com/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(Object.fromEntries(new FormData(form))),
        });
        const out = await res.json();
        if (!res.ok || !out.success) throw new Error(out.message || "failed");
        form.reset();
        say("Sent. Merci — he reads every one.", "ok");
      } catch (err) {
        say("That didn’t go through. Try again, or write to him on Instagram.", "bad");
      } finally {
        send.disabled = false;
      }
    });
  };

  /* ═══ CHROME: rail, progress, quote ══════════════════════════════════ */
  const chrome = () => {
    const rail = $("#rail");
    const toggle = $("#railToggle");
    toggle?.addEventListener("click", () => {
      const open = rail.dataset.open === "true";
      rail.dataset.open = String(!open);
      toggle.setAttribute("aria-expanded", String(!open));
    });
    $$(".rail__list a").forEach((a) =>
      a.addEventListener("click", () => {
        rail.dataset.open = "false";
        toggle?.setAttribute("aria-expanded", "false");
      })
    );

    // Which section is on screen, for the index and the progress bar.
    const marks = $$(".rail__list a");
    const secs = marks.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
    const bar = $("#progressBar");
    let ticking = false;

    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const h = document.documentElement.scrollHeight - innerHeight;
        if (bar) bar.style.width = (h > 0 ? Math.min(1, scrollY / h) * 100 : 0) + "%";

        let live = -1;
        secs.forEach((s, i) => { if (s.getBoundingClientRect().top < innerHeight * 0.42) live = i; });
        marks.forEach((m, i) => m.classList.toggle("on", i === live));
        ticking = false;
      });
    };
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // Word-by-word on the pull quote.
    const q = $(".quote");
    if (q) {
      $$(".quote__t .w", q).forEach((w, i) => w.style.setProperty("--i", i));
      new IntersectionObserver((r, o) => {
        if (r[0].isIntersecting) { q.classList.add("seen"); o.disconnect(); }
      }, { threshold: 0.35 }).observe(q);
    }
  };

  /* ═══ GO ═════════════════════════════════════════════════════════════ */
  const boot = () => {
    if (!posts.length) {
      document.body.insertAdjacentHTML(
        "afterbegin",
        `<p style="font-family:var(--meta);padding:1rem var(--gut);color:var(--red)">
           data/site.js is empty — run <code>python3 scripts/update.py</code>.
         </p>`
      );
    }
    editionLine();
    lede();
    ledger();
    buildTabs();
    paint();
    starred();
    picks();
    recipes();
    beat();
    pods();
    social();
    letter();
    chrome();
    watch();
  };

  if (document.readyState === "loading") {
    addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
