/* Feature Puzzles project page.
 *
 * Reads data/manifest.json and builds, per task, one "stage" plus a gallery.
 * The stage shows every rendering of the same scene at once: one fills the
 * frame, the rest float over it as panels you can click to swap in. All of them
 * are the same frames at the same rate, so they play as one clip -- the first
 * view is the clock and the others are nudged back onto it when they drift. */

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
};

/* Panel geometry, in percent of the stage. Mirrors the offline compositor:
 * insets stacked down the right edge with a margin and an even gap. */
const INSET = { width: 23, widthNarrow: 31, right: 1.9, top: 2.9, gap: 2.9 };

const PLAY_ICON = '<svg viewBox="0 0 12 14"><path d="M1 1l10 6-10 6z"/></svg>';
const PAUSE_ICON = '<svg viewBox="0 0 12 14"><path d="M1 1h3.4v12H1zM7.6 1H11v12H7.6z"/></svg>';

/* ── one stage: N synchronized videos in a main slot + floating slots ───── */

class Stage {
  constructor(root, stageAspect) {
    this.shell = root;
    this.stage = $('.stage', root);
    this.playBtn = $('.play', root);
    this.scrub = $('.scrub', root);
    this.read = $('.frame-read', root);
    this.panels = [];          // in display order: [main, inset, inset, ...]
    this.fps = 8;
    this.frames = 0;
    this.playing = false;
    this.defaultAspect = stageAspect;

    this.playBtn.addEventListener('click', () => this.toggle());
    this.scrub.addEventListener('input', () => {
      const t = Number(this.scrub.value);
      this.seek(t);
    });
    this._tick = this._tick.bind(this);
    requestAnimationFrame(this._tick);
    // The inset share depends on the stage's pixel width, so it is re-derived
    // whenever the window changes size.
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { if (this.panels.length) this._layout(false); }, 120);
    });
  }

  get master() { return this.panels.length ? this.panels[0].video : null; }

  /** views: [{key, label, src}], first one starts in the main slot.
   *  reference: {src, label, caption} -- a still pinned to the bottom-right,
   *  the same size as the floating panels but outside the swap order. */
  load(views, { fps, frames, aspect, poster, reference }) {
    // Detaching a <video> does not necessarily stop its download; emptying the
    // source does, which matters when the follow renders are tens of megabytes.
    this.panels.forEach(p => { p.video.pause(); p.video.removeAttribute('src'); p.video.load(); });
    this.stage.innerHTML = '';
    this.panels = [];
    this.refNode = null;
    this.fps = fps || 8;
    this.frames = frames || 0;
    const a = aspect || this.defaultAspect;
    this.stage.style.aspectRatio = String(a);
    // Cap the stage by height, not width: a wide render still spans the column,
    // a 4:3 one gets a narrower shell rather than a very tall one.
    this.shell.style.setProperty('--stage-max-w', `calc(${a} * 76vh)`);

    views.forEach((v, i) => {
      const p = el('div', 'panel');
      const video = el('video');
      video.muted = true;
      video.playsInline = true;
      video.preload = 'auto';
      video.loop = i === 0;              // the clock loops; the rest are pulled back
      // Until the first frames decode, show the finished bird's-eye result
      // rather than a black rectangle.
      if (i === 0 && poster) video.poster = poster;
      video.src = v.src;
      p.appendChild(video);
      p.appendChild(el('span', 'cap', v.label));
      p.addEventListener('click', () => {
        if (p.classList.contains('inset')) this.promote(p);
      });
      p._view = v;
      p._video = video;
      this.panels.push({ node: p, video, view: v });
      this.stage.appendChild(p);
    });

    if (reference) {
      const r = el('div', 'panel inset ref');
      const img = el('img');
      img.src = reference.src;
      img.alt = reference.label;
      r.appendChild(img);
      r.appendChild(el('span', 'cap', reference.label));
      r.addEventListener('click', () => openLightbox(reference.src, reference.caption));
      this.refNode = r;
      this.stage.appendChild(r);
    }

    // The master drives the scrubber; its metadata gives the true duration.
    const m = this.master;
    if (m) {
      m.addEventListener('loadedmetadata', () => {
        this.scrub.max = String(m.duration || 0);
        this.scrub.step = String(1 / (this.fps || 8));
        this._readout();
      });
    }
    this._layout(false);
    this.play();
  }

  /** Move `node` into the main slot; whoever was there takes its place. */
  promote(node) {
    const i = this.panels.findIndex(p => p.node === node);
    if (i <= 0) return;
    const [picked] = this.panels.splice(i, 1);
    this.panels.unshift(picked);
    // Only the current clock loops, so hand the role over with the slot.
    this.panels.forEach((p, k) => { p.video.loop = k === 0; });
    this._layout(true);
    const m = this.master;
    if (m) {
      this.scrub.max = String(m.duration || this.scrub.max);
    }
  }

  _layout(animate) {
    this.panels.forEach(({ node }, i) => {
      node.style.zIndex = String(i === 0 ? 1 : 3 + i);
      if (!animate) node.style.transition = 'none';
      if (i === 0) {
        node.className = 'panel main';
        node.style.left = node.style.top = '0%';
        node.style.width = node.style.height = '100%';
      } else {
        node.className = 'panel inset';
        // Insets are cover-cropped to the stage's own aspect, so a square-ish
        // input frame and a 16:9 render still stack as identical panels.
        // On a narrow stage they take a larger share, or they would be thumbnails.
        const w = this.stage.clientWidth < 620 ? INSET.widthNarrow : INSET.width;
        const h = w;              // percent of height == percent of width, cover-cropped
        node.style.left = `${100 - INSET.right - w}%`;
        node.style.top = `${INSET.top + (i - 1) * (h + INSET.gap)}%`;
        node.style.width = `${w}%`;
        node.style.height = `${h}%`;
      }
      if (!animate) {
        void node.offsetWidth;    // flush, so the next frame animates normally
        node.style.transition = '';
      }
    });

    if (this.refNode) {
      // Same width and height as a floating panel, but anchored to the bottom
      // of the right edge instead of stacking with them, and never swapped in.
      const w = this.stage.clientWidth < 620 ? INSET.widthNarrow : INSET.width;
      this.refNode.style.zIndex = '3';
      this.refNode.style.left = `${100 - INSET.right - w}%`;
      // Anchored by its bottom edge rather than a computed top, so the panel
      // cannot hang past the stage whatever height the aspect ratio resolves to.
      this.refNode.style.top = 'auto';
      this.refNode.style.bottom = `${INSET.top}%`;
      this.refNode.style.width = `${w}%`;
      this.refNode.style.height = `${w}%`;
    }
  }

  play() {
    this.playing = true;
    this.panels.forEach(p => p.video.play().catch(() => {}));
    this.playBtn.innerHTML = PAUSE_ICON;
  }

  pause() {
    this.playing = false;
    this.panels.forEach(p => p.video.pause());
    this.playBtn.innerHTML = PLAY_ICON;
  }

  toggle() { this.playing ? this.pause() : this.play(); }

  seek(t) {
    this.panels.forEach(p => { try { p.video.currentTime = t; } catch (_) {} });
    this._readout();
  }

  step(frames) {
    const m = this.master;
    if (!m) return;
    this.pause();
    const dt = frames / (this.fps || 8);
    this.seek(Math.max(0, Math.min((m.duration || 0) - 1e-3, m.currentTime + dt)));
  }

  _tick() {
    requestAnimationFrame(this._tick);
    const m = this.master;
    if (!m || !m.duration) return;

    const t = m.currentTime;
    for (let i = 1; i < this.panels.length; i++) {
      const v = this.panels[i].video;
      if (!v.duration) continue;
      // A follower that ran out, or drifted, is snapped back onto the clock.
      if (Math.abs(v.currentTime - t) > 0.18) {
        try { v.currentTime = Math.min(t, v.duration - 1e-3); } catch (_) {}
      }
      if (this.playing && v.paused) v.play().catch(() => {});
    }
    if (document.activeElement !== this.scrub) this.scrub.value = String(t);
    this._readout();
  }

  _readout() {
    const m = this.master;
    if (!m) return;
    const f = Math.min(this.frames || 0, Math.floor(m.currentTime * (this.fps || 8)) + 1);
    this.read.textContent = this.frames
      ? `frame ${String(f).padStart(3, ' ')} / ${this.frames}`
      : '';
  }
}

/* ── section construction ───────────────────────────────────────────────── */

function stageShell({ modeToggle }) {
  const shell = el('div', 'stage-shell');

  const bar = el('div', 'stage-bar');
  const name = el('div', 'stage-name');
  name.appendChild(el('h3', null, '—'));
  name.appendChild(el('span', 'fam', ''));
  const flag = el('span', 'dyn-flag', 'Dynamic scene');
  flag.title = 'The scene moves: a person walks through it while the camera follows';
  flag.hidden = true;
  name.appendChild(flag);
  bar.appendChild(name);

  const right = el('div', 'stage-bar-right');
  if (modeToggle) {
    const seg = el('div', 'seg');
    seg.dataset.role = 'mode';
    for (const [key, label, title] of modeToggle) {
      const b = el('button', null, label);
      b.dataset.mode = key;
      b.title = title;
      seg.appendChild(b);
    }
    right.appendChild(seg);
  }
  bar.appendChild(right);
  shell.appendChild(bar);

  const stage = el('div', 'stage');
  shell.appendChild(stage);

  const transport = el('div', 'transport');
  const play = el('button', 'play');
  play.innerHTML = PLAY_ICON;
  play.setAttribute('aria-label', 'Play or pause');
  const scrub = el('input', 'scrub');
  scrub.type = 'range';
  scrub.min = '0';
  scrub.max = '1';
  scrub.step = '0.01';
  scrub.value = '0';
  scrub.setAttribute('aria-label', 'Timeline');
  transport.append(play, scrub, el('span', 'frame-read'));
  shell.appendChild(transport);

  const meta = el('div', 'meta-strip');
  shell.appendChild(meta);

  return shell;
}

function buildTask(task) {
  const section = document.getElementById(task.id);
  const wrap = el('div', 'wrap');
  section.appendChild(wrap);

  const head = el('div', 'task-head');
  head.appendChild(el('div', 'task-num', task.num));
  const headText = el('div');
  headText.appendChild(el('h2', null, task.title));
  headText.appendChild(el('p', 'lead', task.lead));
  head.appendChild(headText);
  wrap.appendChild(head);

  const isPromptable = task.id === 'promptable';
  const shell = stageShell({
    modeToggle: isPromptable
      ? [['hl', 'Highlight', 'Instance colours blended over the reconstructed colours'],
         ['seg', 'Instance', 'Flat instance colours only']]
      : null,
  });
  wrap.appendChild(shell);

  const stage = new Stage(shell, isPromptable ? 16 / 9 : 4 / 3);

  // gallery -------------------------------------------------------------
  const gHead = el('div', 'gallery-head');
  const tabs = el('div', 'tabs');
  const right = el('div', 'gallery-tools');
  const filter = el('input', 'filter');
  filter.type = 'search';
  filter.placeholder = 'Filter scenes…';
  // Two rows of six, and the rest a page away: a split of 55 scenes is a wall
  // of thumbnails otherwise.
  const pager = el('div', 'pager');
  const prev = el('button', 'pg', '‹');
  const next = el('button', 'pg', '›');
  const pageRead = el('span', 'pg-read');
  prev.title = 'Previous page';
  next.title = 'Next page';
  pager.append(prev, pageRead, next);
  right.append(pager, filter);
  gHead.append(tabs, right);
  wrap.appendChild(gHead);

  const note = el('p', 'group-note');
  wrap.appendChild(note);
  const grid = el('div', 'grid');
  grid.style.setProperty('--card-aspect', isPromptable ? '16 / 9' : '4 / 3');
  wrap.appendChild(grid);

  const state = { group: null, mode: 'hl', scene: null, page: 0 };
  const PER_PAGE = 12;

  task.groups.forEach(g => {
    const b = el('button', g.dynamic ? 'tab dyn' : 'tab');
    if (g.dynamic) b.appendChild(el('span', 'dyn-dot'));
    b.appendChild(el('span', null, g.label));
    b.appendChild(el('span', 'n', String(g.scenes.length)));
    b.disabled = g.scenes.length === 0;
    // A greyed tab is a split that has not finished rendering, not one we left out.
    if (b.disabled) b.title = 'Still rendering — re-run build_site.py to pick these up';
    b.addEventListener('click', () => selectGroup(g));
    g._tab = b;
    tabs.appendChild(b);
  });

  function selectGroup(g) {
    state.group = g;
    task.groups.forEach(x => x._tab.classList.toggle('on', x === g));
    state.page = 0;
    note.innerHTML = '';
    note.appendChild(document.createTextNode(g.note + ' '));
    if (!g.scenes.length) {
      note.appendChild(el('span', 'pending', 'Rendering — results appear here as they land.'));
    }
    renderGrid();
    if (g.scenes.length) selectScene(g.scenes[0]);
    else {
      stage.pause();
      stage.stage.innerHTML = '';
      stage.panels = [];
      const empty = el('div', 'stage-empty', 'This split is still running. Re-run build_manifest.py to pick up new scenes.');
      stage.stage.appendChild(empty);
      $('.stage-name h3', shell).textContent = '—';
      $('.stage-name .fam', shell).textContent = '';
      $('.meta-strip', shell).innerHTML = '';
    }
  }

  function renderGrid() {
    const q = filter.value.trim().toLowerCase();
    grid.innerHTML = '';
    const all = state.group.scenes.filter(
      s => !q || (s.name + ' ' + s.family + ' ' + s.id).toLowerCase().includes(q));
    if (!all.length) {
      grid.appendChild(el('div', 'empty-note', 'No scene matches that filter.'));
      pager.hidden = true;
      return;
    }
    const pages = Math.ceil(all.length / PER_PAGE);
    state.page = Math.min(Math.max(state.page, 0), pages - 1);
    pager.hidden = pages < 2;
    prev.disabled = state.page === 0;
    next.disabled = state.page >= pages - 1;
    pageRead.textContent = `${state.page + 1} / ${pages}`;
    const scenes = all.slice(state.page * PER_PAGE, (state.page + 1) * PER_PAGE);
    scenes.forEach(s => {
      const c = el('button', 'card');
      const img = el('img');
      img.src = s.poster;
      img.loading = 'lazy';
      img.alt = `Bird's-eye result for ${s.name}`;
      c.appendChild(img);
      const badge = isPromptable
        ? (s.prompts ? s.prompts.map(q => q.name).join(' + ')
           : s.stats.objects ? `${s.stats.objects} obj` : null)
        : (s.stats.instances ? `${s.stats.instances} inst` : null);
      if (badge) c.appendChild(el('span', 'cbadge', badge));
      if (s.dynamic) {
        c.classList.add('dyn');
        c.appendChild(el('span', 'dyn-tag', 'Dynamic'));
      }
      const info = el('div', 'cinfo');
      info.appendChild(el('div', 'cname', s.name));
      info.appendChild(el('div', 'cfam', s.family));
      c.appendChild(info);
      c.addEventListener('click', () => selectScene(s));
      s._card = c;
      c.classList.toggle('on', s === state.scene);
      grid.appendChild(c);
    });
  }

  function views(s) {
    if (isPromptable) {
      const m = s.modes[state.mode] || s.modes.hl;
      const bev = { key: 'bev', label: "Bird's-eye", src: m.bev };
      const follow = { key: 'follow', label: 'Follow camera', src: m.follow };
      const rgb = { key: 'rgb', label: 'Input video', src: s.rgb };
      return [bev, follow, rgb];
    }
    return [
      { key: 'bev', label: "Bird's-eye", src: s.bev },
      { key: 'follow', label: 'Follow camera', src: s.follow },
      { key: 'input', label: 'Input video', src: s.input },
    ];
  }

  function referenceOf(s) {
    if (!isPromptable || !s.reference) return null;
    if (s.dynamic) {
      return {
        src: s.reference,
        label: 'Reference view',
        caption: `First frame of ${s.name}, with the two text prompts `
               + `(${(s.prompts || []).map(q => `"${q.name}"`).join(' and ')}) `
               + `as masks. The model propagates exactly these through the other `
               + `${(s.stats.frames || 1) - 1} frames while the person moves.`,
      };
    }
    return {
      src: s.reference,
      label: 'Reference view',
      caption: `Reference view of ${s.name} — the ${s.stats.objects} disjoint SAM masks `
             + `used as prompts. Everything else on this page is the model propagating `
             + `exactly these to the other ${(s.stats.frames || 1) - 1} views.`,
    };
  }

  function selectScene(s) {
    state.scene = s;
    task.groups.forEach(g => g.scenes.forEach(x => x._card && x._card.classList.toggle('on', x === s)));
    $('.stage-name h3', shell).textContent = s.name;
    $('.stage-name .fam', shell).textContent = s.family;
    shell.classList.toggle('is-dynamic', !!s.dynamic);
    $('.stage-name .dyn-flag', shell).hidden = !s.dynamic;
    stage.load(views(s), {
      fps: s.stats.fps, frames: s.stats.frames, aspect: s.stats.aspect, poster: s.poster,
      reference: referenceOf(s),
    });
    renderMeta(s);
  }

  const QUERY_CHIP_LIMIT = 24;

  function renderMeta(s) {
    const meta = $('.meta-strip', shell);
    meta.innerHTML = '';

    const chips = el('div', 'chips');
    if (!isPromptable && s.queries && s.queries.length) {
      // The FARM scenes query their own official label set -- up to 93 classes,
      // of which a third find nothing. Listing every one buries the strip, so
      // only classes that actually landed instances are shown, busiest first,
      // and a long tail collapses into a single "+N more" chip.
      const hits = s.queries.filter(q => q.n > 0).sort((a, b) => b.n - a.n);
      const shown = hits.slice(0, QUERY_CHIP_LIMIT);
      chips.appendChild(el('span', 'chips-label',
        hits.length < s.queries.length ? `Queries ${hits.length}/${s.queries.length}` : 'Queries'));
      shown.forEach(q => {
        const c = el('span', 'chip');
        const sw = el('span', 'swatch');
        sw.style.background = q.color;
        c.append(sw, document.createTextNode(q.name + ' '));
        c.appendChild(el('b', null, String(q.n)));
        chips.appendChild(c);
      });
      if (hits.length > shown.length) {
        const rest = hits.slice(shown.length);
        const c = el('span', 'chip');
        c.title = rest.map(q => `${q.name} ${q.n}`).join(', ');
        c.appendChild(el('b', null, `+${rest.length} more`));
        chips.appendChild(c);
      }
    } else if (s.prompts) {
      chips.appendChild(el('span', 'chips-label', 'Text prompts'));
      s.prompts.forEach(q => {
        const c = el('span', 'chip');
        const sw = el('span', 'swatch');
        sw.style.background = q.color;
        c.append(sw, document.createTextNode(q.name));
        chips.appendChild(c);
      });
    } else {
      chips.appendChild(el('span', 'chips-label', 'Run'));
    }

    const add = (label, value) => {
      if (value == null) return;
      const c = el('span', 'chip');
      c.append(document.createTextNode(label + ' '));
      c.appendChild(el('b', null, String(value)));
      chips.appendChild(c);
    };
    add(s.dynamic ? 'frames' : 'views', s.stats.frames);
    add('fps', s.stats.fps);
    if (isPromptable && !s.prompts) add('prompts', s.stats.objects);
    else add('3D instances', s.stats.instances);
    meta.appendChild(chips);
  }

  // mode toggle (promptable only) ---------------------------------------
  const seg = shell.querySelector('.seg[data-role="mode"]');
  if (seg) {
    seg.querySelectorAll('button').forEach(b => {
      b.classList.toggle('on', b.dataset.mode === state.mode);
      b.addEventListener('click', () => {
        if (state.mode === b.dataset.mode) return;
        state.mode = b.dataset.mode;
        seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
        if (!state.scene) return;
        // Keep the playhead across the switch: only bev/follow change source.
        const t = stage.master ? stage.master.currentTime : 0;
        const wasPlaying = stage.playing;
        stage.load(views(state.scene), {
          fps: state.scene.stats.fps,
          frames: state.scene.stats.frames,
          aspect: state.scene.stats.aspect,
          poster: state.scene.poster,
          reference: referenceOf(state.scene),
        });
        const m = stage.master;
        const restore = () => { stage.seek(t); if (!wasPlaying) stage.pause(); };
        if (m.readyState >= 1) restore();
        else m.addEventListener('loadedmetadata', restore, { once: true });
      });
    });
  }

  filter.addEventListener('input', () => { state.page = 0; renderGrid(); });
  prev.addEventListener('click', () => { state.page--; renderGrid(); });
  next.addEventListener('click', () => { state.page++; renderGrid(); });

  const first = task.groups.find(g => g.scenes.length) || task.groups[0];
  selectGroup(first);

  return stage;
}

/* ── lightbox ───────────────────────────────────────────────────────────── */

function openLightbox(src, caption) {
  const lb = $('#lightbox');
  $('#lb-img').src = src;
  $('#lb-cap').textContent = caption || '';
  lb.hidden = false;
}
function closeLightbox() { $('#lightbox').hidden = true; $('#lb-img').src = ''; }

/* ── boot ───────────────────────────────────────────────────────────────── */

fetch('data/manifest.json', { cache: 'no-store' })
  .then(r => {
    if (!r.ok) throw new Error(`manifest.json: HTTP ${r.status}`);
    return r.json();
  })
  .then(manifest => {
    const stages = [];
    manifest.tasks.forEach((task, i) => {
      task.num = String(i + 1).padStart(2, '0');
      stages.push(buildTask(task));
    });

    const n = manifest.tasks.reduce(
      (a, t) => a + t.groups.reduce((b, g) => b + g.scenes.length, 0), 0);
    $('#build-stamp').textContent =
      `${n} scenes · manifest built ${manifest.generated.replace('T', ' ')}`;

    // Space and the arrow keys drive whichever stage is on screen.
    document.addEventListener('keydown', e => {
      if (/^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
      if (e.key === 'Escape') { closeLightbox(); return; }
      const live = stages.find(s => {
        const r = s.stage.getBoundingClientRect();
        return r.top < window.innerHeight * 0.65 && r.bottom > window.innerHeight * 0.2;
      });
      if (!live) return;
      if (e.code === 'Space') { e.preventDefault(); live.toggle(); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); live.step(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); live.step(-1); }
    });
  })
  .catch(err => {
    document.querySelectorAll('.task').forEach(s => {
      const w = el('div', 'wrap');
      w.appendChild(el('div', 'empty-note',
        `Could not load data/manifest.json (${err.message}). Run "python build_manifest.py", ` +
        `and serve this directory over HTTP rather than opening the file directly.`));
      s.appendChild(w);
    });
  });

$('#lb-close').addEventListener('click', closeLightbox);
$('#lightbox').addEventListener('click', e => { if (e.target.id === 'lightbox') closeLightbox(); });
