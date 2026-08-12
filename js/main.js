/* ═══════════════════════════════════════════════════
   JVALID FOOD REVIEWS — interactions
   ═══════════════════════════════════════════════════ */

/* All content comes from data/site.js, which scripts/update.py regenerates
   daily. Nothing here is hand-maintained — edit data/overrides.json to pin a
   category, not this file. */
const DATA = window.SITE_DATA || { profile: {}, videos: [] };
const PROFILE = DATA.profile || {};
const HANDLE = PROFILE.handle || 'jvalidfoodreviews';
const VIDEOS = (DATA.videos || []).slice();

const COUNTY_META = {
  bergen:      { name: 'Bergen County',   state: 'NJ' },
  rockland:    { name: 'Rockland County', state: 'NY' },
  westchester: { name: 'Westchester',     state: 'NY' },
  orange:      { name: 'Orange County',   state: 'NY' },
};

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

const fmt = n => n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'K' : String(n);

/* ─── Preloader ────────────────────────────────── */
window.addEventListener('load', () => {
  setTimeout(() => document.body.classList.add('is-loaded'), reduced ? 0 : 900);
});
// Safety net if load never fires
setTimeout(() => document.body.classList.add('is-loaded'), 3200);

/* ─── Fill everything that is driven by the data ─ */
const counties = [...new Set(VIDEOS.flatMap(v => v.counties || []))];

const FILL = {
  followers:      PROFILE.followers  ?? 0,
  followersPlus1: (PROFILE.followers ?? 0) + 1,
  likes:          PROFILE.likes      ?? 0,
  videoCount:     PROFILE.videoCount ?? VIDEOS.length,
  counties:       counties.length,
  shown:          VIDEOS.length,
};

$$('[data-fill]').forEach(el => {
  const v = FILL[el.dataset.fill];
  if (v !== undefined) el.textContent = v.toLocaleString();
});

// counters read their target from the same source
$$('.stat__num[data-from]').forEach(el => {
  el.dataset.count = FILL[el.dataset.from] ?? 0;
});

// "last updated" stamp, rendered in the visitor's own locale
const stamp = $('#stamp');
if (stamp && DATA.updated && DATA.updated !== 'seed') {
  const d = new Date(DATA.updated);
  if (!isNaN(d)) {
    stamp.textContent = d.toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    });
    stamp.title = d.toLocaleString();
  }
}

// menu tallies
$$('.mcard[data-cat]').forEach(card => {
  const n = VIDEOS.filter(v => v.cat === card.dataset.cat).length;
  const b = card.querySelector('.mcard__n b');
  if (b) b.textContent = n;
});

// turf table, ranked by how many reviews came out of each county
const turfList = $('#turfList');
if (turfList) {
  const rows = Object.entries(COUNTY_META)
    .map(([key, meta]) => ({
      key, ...meta,
      n: VIDEOS.filter(v => (v.counties || []).includes(key)).length,
    }))
    .filter(r => r.n > 0)
    .sort((a, b) => b.n - a.n);

  const top = rows.length ? rows[0].n : 1;
  turfList.innerHTML = rows.map((r, i) => `
    <div class="turf__row reveal" data-d="${Math.min(i, 3)}" style="--p:${Math.round((r.n / top) * 100)}%">
      <span class="turf__rank">${String(i + 1).padStart(2, '0')}</span>
      <span class="turf__name">${r.name} <i>${r.state}</i></span>
      <span class="turf__bar"><i></i></span>
      <span class="turf__n">${r.n}</span>
    </div>
  `).join('');
}

/* ─── Build the video grid ─────────────────────── */
const grid = $('#grid');

grid.innerHTML = VIDEOS.map((v, i) => `
  <article class="card" data-cat="${v.cat}" data-id="${v.id}" data-cursor="tap" tabindex="0" role="button"
           aria-label="Play review: ${v.cap.replace(/"/g, '&quot;')}">
    <div class="card__img">
      <img src="assets/thumb-${v.id}.jpg" alt="" loading="lazy" decoding="async">
    </div>
    <span class="card__rank">${String(i + 1).padStart(2, '0')}</span>
    ${v.hot ? '<span class="card__hot">🔥 BIGGEST</span>' : ''}
    <div class="card__shine"></div>
    <div class="card__play"></div>
    <div class="card__body">
      <p class="card__cap">${v.cap}</p>
      <div class="card__meta">
        <span class="card__views">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>
          </svg>
          ${fmt(v.views)}
        </span>
        <span class="card__cat">${v.label}</span>
      </div>
    </div>
  </article>
`).join('');

/* ─── Scroll reveal ────────────────────────────── */
const io = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('in');
      io.unobserve(e.target);
    }
  });
}, { threshold: 0.14, rootMargin: '0px 0px -8% 0px' });

$$('.reveal, .card, .turf__row, .pull').forEach(el => io.observe(el));

/* stagger the cards as they enter */
$$('.card').forEach((c, i) => { c.style.transitionDelay = `${(i % 5) * 70}ms`; });

/* ─── Animated counters ────────────────────────── */
const countIO = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (!e.isIntersecting) return;
    countIO.unobserve(e.target);

    const el = e.target;
    const target = +el.dataset.count;
    if (reduced) { el.textContent = target.toLocaleString(); return; }

    const dur = 1700;
    const t0 = performance.now();
    const tick = now => {
      const p = Math.min((now - t0) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 4);           // easeOutQuart
      el.textContent = Math.round(target * eased).toLocaleString();
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}, { threshold: 0.5 });

$$('[data-count]').forEach(el => countIO.observe(el));

/* ─── Filters ──────────────────────────────────── */
$$('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    $$('.chip').forEach(c => c.classList.remove('is-on'));
    chip.classList.add('is-on');

    const f = chip.dataset.filter;
    $$('.card').forEach((card, i) => {
      const show = f === 'all' || card.dataset.cat === f;
      card.classList.toggle('is-out', !show);
      if (show) {
        card.style.transitionDelay = `${(i % 5) * 45}ms`;
        card.classList.add('in');
      }
    });
  });
});

/* ─── Lightbox ─────────────────────────────────── */
const lb      = $('#lb');
const lbFrame = $('#lbFrame');
const lbCap   = $('#lbCap');
const lbLink  = $('#lbLink');
let lastFocus = null;

function openVideo(id) {
  const v = VIDEOS.find(x => x.id === id);
  if (!v) return;

  lastFocus = document.activeElement;
  lbCap.textContent  = v.cap;
  lbLink.href        = `https://www.tiktok.com/@${HANDLE}/video/${id}`;
  lbFrame.innerHTML  = `<iframe src="https://www.tiktok.com/embed/v2/${id}"
      allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
      allowfullscreen title="TikTok review"></iframe>`;

  lb.hidden = false;
  requestAnimationFrame(() => lb.classList.add('is-on'));
  document.body.style.overflow = 'hidden';
  $('#lbClose').focus();
}

function closeVideo() {
  lb.classList.remove('is-on');
  document.body.style.overflow = '';
  setTimeout(() => {
    lb.hidden = true;
    lbFrame.innerHTML = '';       // stops playback
    lastFocus?.focus();
  }, 350);
}

grid.addEventListener('click', e => {
  const card = e.target.closest('.card');
  if (card) openVideo(card.dataset.id);
});
grid.addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const card = e.target.closest('.card');
  if (!card) return;
  e.preventDefault();
  openVideo(card.dataset.id);
});

$('#lbClose').addEventListener('click', closeVideo);
lb.addEventListener('click', e => { if (e.target === lb) closeVideo(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !lb.hidden) closeVideo();
});

/* ─── Scroll progress + nav behaviour ──────────── */
const bar = $('.scrollbar-progress i');
const nav = $('#nav');
let lastY = 0, ticking = false;

function onScroll() {
  const y   = window.scrollY;
  const max = document.documentElement.scrollHeight - innerHeight;
  bar.style.width = `${max > 0 ? (y / max) * 100 : 0}%`;

  nav.classList.toggle('is-stuck', y > 40);
  nav.classList.toggle('is-hidden', y > lastY && y > 420 && lb.hidden);
  lastY = y;
  ticking = false;
}
addEventListener('scroll', () => {
  if (!ticking) { requestAnimationFrame(onScroll); ticking = true; }
}, { passive: true });
onScroll();

/* ─── Parallax on the hero floaties ────────────── */
if (!reduced && matchMedia('(hover:hover)').matches) {
  const floats = $$('.fl');
  addEventListener('mousemove', e => {
    const dx = (e.clientX / innerWidth  - 0.5) * 2;
    const dy = (e.clientY / innerHeight - 0.5) * 2;
    floats.forEach((f, i) => {
      const depth = (i % 3 + 1) * 13;
      f.style.translate = `${dx * depth}px ${dy * depth}px`;
    });
  }, { passive: true });
}

/* ─── Custom cursor ────────────────────────────── */
if (!reduced && matchMedia('(hover:hover)').matches) {
  const cur = $('.cursor');
  let cx = innerWidth / 2, cy = innerHeight / 2, tx = cx, ty = cy;

  addEventListener('mousemove', e => {
    tx = e.clientX; ty = e.clientY;
    cur.classList.add('is-live');
  }, { passive: true });

  (function loop() {
    cx += (tx - cx) * 0.19;
    cy += (ty - cy) * 0.19;
    cur.style.transform = `translate(${cx}px,${cy}px) translate(-50%,-50%)`;
    requestAnimationFrame(loop);
  })();

  document.addEventListener('mouseover', e => {
    const t = e.target.closest('[data-cursor="tap"]');
    cur.classList.toggle('is-big', !!t);
    if (t) cur.querySelector('span').textContent = t.classList.contains('card') ? 'PLAY' : 'TAP';
  });

  addEventListener('mouseleave', () => cur.classList.remove('is-live'));
}

/* ─── Magnetic buttons ─────────────────────────── */
if (!reduced && matchMedia('(hover:hover)').matches) {
  $$('[data-magnet]').forEach(el => {
    el.addEventListener('mousemove', e => {
      const r = el.getBoundingClientRect();
      const x = e.clientX - r.left - r.width / 2;
      const y = e.clientY - r.top - r.height / 2;
      el.style.translate = `${x * 0.28}px ${y * 0.36}px`;
    });
    el.addEventListener('mouseleave', () => { el.style.translate = '0px 0px'; });
  });
}

/* ─── Konami-ish easter egg: press "F" for food ── */
addEventListener('keydown', e => {
  if (e.key.toLowerCase() !== 'f' || e.target.matches('input,textarea') || !lb.hidden) return;
  const emojis = ['🍕','🍔','🍦','🌭','🥤','💩','🔥'];
  for (let i = 0; i < 18; i++) {
    const s = document.createElement('span');
    s.textContent = emojis[Math.floor(Math.random() * emojis.length)];
    s.style.cssText = `position:fixed;z-index:9400;pointer-events:none;font-size:${18 + Math.random() * 26}px;
      left:${Math.random() * 100}vw;top:-60px;transition:transform 2.6s cubic-bezier(.4,.1,.6,1),opacity 2.6s`;
    document.body.appendChild(s);
    requestAnimationFrame(() => {
      s.style.transform = `translateY(${innerHeight + 140}px) rotate(${Math.random() * 720 - 360}deg)`;
      s.style.opacity = '0';
    });
    setTimeout(() => s.remove(), 2700);
  }
});
