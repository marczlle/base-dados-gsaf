(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const indexUrl = new URL(document.querySelector('meta[name="atlas-data"]').content, location.href);
  const digits = new Intl.NumberFormat('pt-BR');
  const decimals = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
  const dateFormat = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const collator = new Intl.Collator('pt-BR');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const n = (value) => digits.format(value);
  const km = (value) => `${decimals.format(value)} km`;
  const distance = (value) => value < 1 ? `${decimals.format(value * 1000)} m` : km(value);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const plain = (value) => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const clamp = (n, low, high) => Math.max(low, Math.min(n, high));
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  const hasPoint = (e) => finite(e?.lon) && finite(e?.lat);
  const readableDate = (date) => dateFormat.format(new Date(`${date}T00:00:00Z`));
  const plural = (count, singular, plural) => `${n(count)} ${count === 1 ? singular : plural}`;
  const reasons = {
    no_coordinates: 'Sem coordenadas válidas',
    outside_distance: 'Distância acima do limite',
    country_mismatch: 'País não confirmado na camada administrativa',
    country_unverified: 'País ou região sem correspondência',
  };
  const methodLabels = {
    direct_geocode: 'Vínculo por proximidade',
    reviewed_toponym: 'Topônimo revisado',
    extended_geocode: 'Distância ampliada',
  };
  const assignmentMethod = (link) => link?.status === 'assigned' ? (link.assignment_method || 'direct_geocode') : null;
  const usesApproximation = (link) => {
    const method = assignmentMethod(link);
    return method === 'reviewed_toponym' || method === 'extended_geocode';
  };
  const methodLabel = (link) => methodLabels[assignmentMethod(link)];
  function httpsLink(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' ? url.href : null;
    } catch { return null; }
  }
  const place = (e) => e?.location || e?.state || e?.country || 'Localidade não informada';
  const pendingReason = (link) => reasons[link?.status] || 'Associação não confirmada';
  const st = {
    atlas: null, loaded: null, scale: 25, tab: 'segments', selection: null, pageSize: 26, limit: 26,
    token: 0, loading: false, searchTimer: 0, playTimer: 0, land: null,
    activeSegments: new Map(), activePath: null, eventsShown: [], pending: [], list: [], recentYear: null,
    view: { lon: 0, lat: 8, zoom: 1 }, drawn: null, frame: 0, tween: 0, width: 0, height: 0, dpr: 1,
    screenEvents: [], drag: null, pointers: new Map(), pinch: null, cache: new Map(),
  };
  const canvas = $('map');
  const ctx = canvas.getContext('2d');
  const scaleButtons = [...document.querySelectorAll('[data-scale]')];
  const tabButtons = [...document.querySelectorAll('[data-tab]')];
  const controls = [$('search'), $('quality'), $('country'), $('spatial-method'), $('year-start'), $('year-end'), $('play')];

  async function json(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function scaleJson(file) {
    const url = new URL(file, indexUrl);
    const gzip = new URL(url);
    if (!gzip.pathname.endsWith('.gz')) gzip.pathname += '.gz';
    const res = await fetch(gzip);
    if (!res.ok) return json(url);
    const data = new Uint8Array(await res.arrayBuffer());
    if (data[0] !== 0x1f || data[1] !== 0x8b) return JSON.parse(new TextDecoder().decode(data));
    if (!('DecompressionStream' in window)) return json(url);
    return new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
  }

  function msg(text, retry = null) {
    const el = $('map-message');
    el.hidden = !text;
    if (!text) return;
    el.dataset.error = !!retry;
    el.replaceChildren();
    const lead = document.createElement('span');
    if (!retry) lead.className = 'spinner';
    else lead.innerHTML = icon('info');
    el.append(lead, document.createTextNode(text));
    if (retry) {
      const btn = document.createElement('button');
      btn.type = 'button'; btn.textContent = 'Tentar de novo'; btn.onclick = retry;
      el.append(btn);
    }
  }

  function line(path, coords, closed = false) {
    if (!coords?.length) return;
    let last;
    for (const [lon, lat] of coords) {
      if (last === undefined || (!closed && Math.abs(lon - last) > 180)) path.moveTo(lon, -lat);
      else path.lineTo(lon, -lat);
      last = lon;
    }
    if (closed) path.closePath();
  }

  function landPath(geo) {
    const path = new Path2D();
    const append = (geometry) => {
      if (geometry?.type === 'Polygon') geometry.coordinates.forEach((ring) => line(path, ring, true));
      if (geometry?.type === 'MultiPolygon') geometry.coordinates.forEach((polygon) => polygon.forEach((ring) => line(path, ring, true)));
      if (geometry?.type === 'GeometryCollection') geometry.geometries.forEach(append);
    };
    if (geo.type === 'FeatureCollection') geo.features.forEach((f) => append(f.geometry));
    else append(geo.geometry || geo);
    return path;
  }

  function bounds(coords) {
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    for (const [x, y] of coords) {
      minx = Math.min(x, minx); maxx = Math.max(x, maxx);
      miny = Math.min(y, miny); maxy = Math.max(y, maxy);
    }
    return [minx, miny, maxx, maxy];
  }
  const cellSize = 8;
  const cellKey = (lon, lat) => `${Math.floor(lon / cellSize)},${Math.floor(lat / cellSize)}`;

  function prepare(raw) {
    if (!Array.isArray(raw.segments) || !Array.isArray(raw.links)) throw new Error('Formato dos segmentos inválido');
    const coast = new Path2D();
    const regionsWithData = new Path2D();
    const regionsEligible = new Path2D();
    const bins = new Map();
    const bySegment = new Map();
    for (const seg of raw.segments) {
      if (!seg.coordinates?.length) continue;
      line(coast, seg.coordinates);
      const coords = seg.coordinates;
      seg.box = bounds(coords);
      seg.center = coords[Math.floor(coords.length / 2)];
      seg.key = plain(`${seg.id} ${seg.region_id || ''}`);
      const key = cellKey(...seg.center);
      if (!bins.has(key)) bins.set(key, { path: new Path2D(), segments: [], box: [...seg.box] });
      const cell = bins.get(key);
      line(cell.path, coords);
      cell.segments.push(seg);
      const b = cell.box, s = seg.box;
      b[0] = Math.min(b[0], s[0]); b[1] = Math.min(b[1], s[1]);
      b[2] = Math.max(b[2], s[2]); b[3] = Math.max(b[3], s[3]);
      bySegment.set(seg.id, seg);
    }
    const byRegion = new Map((raw.regions || []).map((region) => [region.id, region]));
    for (const seg of bySegment.values()) {
      const region = byRegion.get(seg.region_id);
      if (region?.event_count > 0 || seg.event_count > 0) {
        line(seg.model_eligible || region?.model_eligible ? regionsEligible : regionsWithData, seg.coordinates);
      }
    }
    const links = new Map(raw.links.map((link) => [link.event_id, link]));
    const allEvents = new Map();
    const assigned = [];
    const pending = [];
    const eventSegments = new Map();
    for (const event of st.atlas.events) {
      const link = links.get(event.id);
      const enriched = { ...event, link };
      allEvents.set(event.id, enriched);
      if (link?.status === 'assigned' && bySegment.has(link.segment_id)) {
        assigned.push(enriched);
        if (!eventSegments.has(link.segment_id)) eventSegments.set(link.segment_id, []);
        eventSegments.get(link.segment_id).push(enriched);
      } else pending.push(enriched);
    }
    return { bySegment, byRegion, allEvents, assigned, pending, eventSegments, coast, regionsWithData, regionsEligible, bins };
  }

  async function switchScale(scale) {
    if (!st.atlas) return;
    const token = ++st.token;
    const file = st.atlas.files[String(scale)];
    st.loading = true;
    stop();
    scaleButtons.forEach((button) => button.setAttribute('aria-pressed', Number(button.dataset.scale) === scale));
    msg(`Carregando a costa de ${scale} km…`);
    try {
      if (!file) throw new Error('Escala não encontrada');
      if (!st.cache.has(scale)) {
        const promise = scaleJson(file).then(prepare);
        st.cache.set(scale, promise);
        promise.catch(() => st.cache.delete(scale));
      }
      const prepared = await st.cache.get(scale);
      if (token !== st.token) return;
      st.loaded = prepared;
      st.scale = scale;
      st.selection = null;
      st.loading = false;
      controls.forEach((control) => { control.disabled = false; });
      $('layer-region-label').hidden = scale !== 25 || !prepared.byRegion.size;
      msg('');
      renderMetrics();
      update(true);
    } catch (err) {
      if (token !== st.token) return;
      console.error(err);
      st.loading = false;
      if (st.loaded) scaleButtons.forEach((button) => button.setAttribute('aria-pressed', Number(button.dataset.scale) === st.scale));
      else $('results').innerHTML = `<div class="empty">${icon('info')}<p>Não foi possível carregar os segmentos.</p></div>`;
      msg('Não foi possível carregar a escala.', () => switchScale(scale));
    }
  }

  function renderMetrics() {
    const loaded = st.loaded;
    $('metric-segments').textContent = n(loaded.bySegment.size);
    $('metric-scale').textContent = `Escala de ${st.scale} km`;
    $('metric-assigned').textContent = n(loaded.assigned.length);
    const contextual = loaded.assigned.filter((e) => usesApproximation(e.link)).length;
    $('metric-assigned-note').textContent = `de ${n(st.atlas.events.length)} registros${contextual ? ` · ${n(contextual)} por aproximação` : ''}`;
    $('metric-pending').textContent = n(loaded.pending.length);
    const noCoordinates = loaded.pending.filter((e) => e.link?.status === 'no_coordinates').length;
    $('metric-pending-note').textContent = `${n(noCoordinates)} sem coordenadas válidas`;
  }

  function matches(event, filters, ignoreSearch = false) {
    return event.year >= filters.start && event.year <= filters.end &&
      (!filters.country || event.country === filters.country) &&
      (filters.quality === 'all' || event.approximate === (filters.quality === 'approximate')) &&
      (event.link?.status !== 'assigned' || filters.spatial === 'all' || usesApproximation(event.link) === (filters.spatial === 'approximate')) &&
      (ignoreSearch || !filters.query || event.key.includes(filters.query) ||
       plain(event.link?.segment_id).includes(filters.query) || plain(event.link?.candidate_segment_id).includes(filters.query));
  }

  function update(resetList = false) {
    if (!st.loaded) return;
    if (resetList) st.limit = st.pageSize;
    const start = Number($('year-start').value), end = Number($('year-end').value);
    const spatial = st.tab === 'pending' ? 'all' : $('spatial-method').value;
    const filters = { start, end, quality: $('quality').value, spatial, query: plain($('search').value), country: $('country').value };
    const modified = start !== st.atlas.years[0] || end !== st.atlas.years[1] || filters.quality !== 'all' || spatial !== 'all' || !!filters.query || !!filters.country;
    $('period-label').textContent = start === end ? String(end) : `${start} – ${end}`;
    $('year-end').setAttribute('aria-valuetext', `Até ${end}`);
    $('clear-filters').hidden = !modified;
    $('empty-label').hidden = st.tab !== 'segments';
    $('spatial-filter').hidden = st.tab === 'pending';
    st.filters = filters;
    const direct = new Set();
    if (filters.query && st.tab !== 'pending') {
      for (const seg of st.loaded.bySegment.values()) if (seg.key.includes(filters.query)) direct.add(seg.id);
    }
    const assigned = st.loaded.assigned.filter((event) => matches(event, filters, direct.has(event.link.segment_id)));
    st.pending = st.loaded.pending.filter((event) => matches(event, filters));
    st.eventsShown = assigned;
    st.activeSegments = new Map();
    for (const event of assigned) {
      const id = event.link.segment_id;
      if (!st.activeSegments.has(id)) st.activeSegments.set(id, []);
      st.activeSegments.get(id).push(event);
    }
    st.activePath = new Path2D();
    for (const id of st.activeSegments.keys()) line(st.activePath, st.loaded.bySegment.get(id)?.coordinates);
    if (st.tab === 'segments') {
      const active = Array.from(st.activeSegments, ([id, events]) => ({ seg: st.loaded.bySegment.get(id), events }));
      active.sort((a, b) => b.events.length - a.events.length || collator.compare(a.seg.id, b.seg.id));
      const includeEmpty = $('empty-segments').checked && !filters.country && spatial === 'all';
      if (includeEmpty || direct.size) {
        for (const seg of st.loaded.bySegment.values()) {
          if (!st.activeSegments.has(seg.id) && (direct.has(seg.id) || (includeEmpty && !filters.query && !seg.event_count))) active.push({ seg, events: [] });
        }
      }
      st.list = active;
    } else st.list = (st.tab === 'events' ? assigned : st.pending).slice().sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id));
    renderList(resetList);
    renderDetails();
    schedule();
  }

  function renderList(reset = false) {
    const list = $('results');
    const scroll = reset ? 0 : list.scrollTop;
    const isSegments = st.tab === 'segments';
    $('result-count').textContent = isSegments ? plural(st.list.length, 'segmento', 'segmentos') : plural(st.list.length, 'registro', 'registros');
    if (!st.list.length) {
      list.innerHTML = `<div class="empty">${icon('search')}<p>Nenhum resultado com esses filtros.</p></div>`;
      return;
    }
    const current = st.selection?.id;
    const html = st.list.slice(0, st.limit).map((row) => {
      if (isSegments) {
        const { seg, events } = row;
        const places = events.map(place).filter(Boolean);
        const label = places[0] || seg.id;
        const desc = places[0] ? `${seg.id} · ${km(seg.length_km)}` : km(seg.length_km);
        return `<button type="button" class="result-item" data-kind="segment" data-id="${esc(seg.id)}" aria-current="${seg.id === current}"><span class="item-marker">${icon('layers')}</span><span class="item-copy"><strong>${esc(label)}</strong><small>${esc(desc)}</small></span><span class="item-pill" aria-label="${plural(events.length, 'registro', 'registros')}">${n(events.length)}</span>${icon('chevron')}</button>`;
      }
      const kind = st.tab === 'pending' ? 'pending' : 'event';
      const desc = `${readableDate(row.date)} · ${kind === 'pending' ? pendingReason(row.link) : row.id}`;
      const badge = usesApproximation(row.link) ? `<span class="item-approximation">${esc(methodLabel(row.link))}</span>` : '';
      return `<button type="button" class="result-item" data-kind="${kind}" data-id="${esc(row.id)}" aria-current="${row.id === current}"><span class="item-marker">${icon(kind === 'pending' ? 'clock' : 'pin')}</span><span class="item-copy"><strong>${esc(place(row))}</strong><small>${esc(desc)}</small>${badge}</span>${icon('chevron')}</button>`;
    }).join('');
    list.innerHTML = html + (st.list.length > st.limit ? `<button type="button" class="more" data-more>Mostrar mais ${n(Math.min(st.pageSize, st.list.length - st.limit))} resultados</button>` : '');
    list.scrollTop = scroll;
  }

  function renderDetails() {
    const detail = $('details');
    const sel = st.selection;
    detail.hidden = !sel;
    $('results').classList.toggle('has-details', !!sel);
    if (!sel) return;
    const close = `<button type="button" class="close-detail" data-detail-close aria-label="Fechar detalhes">${icon('x')}</button>`;
    if (sel.kind === 'segment') {
      const seg = st.loaded.bySegment.get(sel.id);
      if (!seg) return;
      const here = st.activeSegments.get(seg.id) || [];
      const unfiltered = st.loaded.eventSegments.get(seg.id) || [];
      const region = st.loaded.byRegion.get(seg.region_id);
      const summary = here.length === unfiltered.length ? plural(unfiltered.length, 'registro', 'registros') : `${n(here.length)} de ${plural(unfiltered.length, 'registro', 'registros')} nos filtros`;
      const contextual = here.filter((e) => usesApproximation(e.link)).length;
      detail.innerHTML = `${close}<h3>${esc(seg.id)}</h3><div class="detail-chips"><span>${esc(km(seg.length_km))}</span><span>${esc(summary)}</span><span>${plural(seg.positive_days || 0, 'dia positivo', 'dias positivos')}</span>${contextual ? `<span class="spatial-chip">${n(contextual)} por aproximação</span>` : ''}</div>` +
        (region ? `<p>Região ${esc(region.id)} · ${plural(region.positive_days || 0, 'dia positivo', 'dias positivos')}. ${region.model_eligible ? 'Atinge o mínimo de 10 dias.' : 'Abaixo do mínimo de 10 dias.'}</p>` : '') +
        (here.length ? `<button type="button" class="detail-action" data-show-events="${esc(seg.id)}">Ver ataques neste segmento</button>` : '<p>Nenhum registro deste trecho está visível no recorte atual.</p>');
    } else {
      const event = st.loaded.allEvents.get(sel.id);
      if (!event) return;
      const link = event.link;
      const hasDistance = finite(link?.distance_km);
      const source = httpsLink(link?.assignment_source);
      const label = methodLabel(link);
      const assigned = link?.status === 'assigned';
      const segId = link?.segment_id || link?.candidate_segment_id;
      detail.innerHTML = `${close}<h3>${esc(place(event))}</h3><p>${esc([event.id, event.state, event.country].filter(Boolean).join(' · '))}</p><div class="detail-chips"><span>${esc(readableDate(event.date))}</span><span>${event.approximate ? 'Data aproximada' : 'Data exata'}</span>${label ? `<span${usesApproximation(link) ? ' class="spatial-chip"' : ''}>${esc(label)}</span>` : ''}</div>` +
        (hasDistance ? `<p><strong>${esc(distance(link.distance_km))}</strong> do ponto geocodificado até ${assigned ? 'o trecho associado' : 'o trecho candidato'}. Essa distância não mede a posição do ataque.</p>` : '') +
        (!assigned ? `<p class="pending-text">${esc(pendingReason(link))}</p>` : '') +
        (link?.assignment_note ? `<p>${esc(link.assignment_note)}</p>` : '') +
        (source ? `<p><a class="detail-source" href="${esc(source)}" target="_blank" rel="noopener noreferrer">Fonte da revisão geográfica ${icon('external')}</a></p>` : '') +
        (segId && st.loaded.bySegment.has(segId) ? `<button type="button" class="detail-action" data-show-segment="${esc(segId)}">${assigned ? 'Segmento associado' : 'Trecho candidato'}: ${esc(segId)}</button>` : '');
    }
  }

  function setTab(tab) {
    st.tab = tab;
    tabButtons.forEach((b) => b.setAttribute('aria-pressed', b.dataset.tab === tab));
    update(true);
  }

  function select(kind, id, focus = true) {
    st.selection = { kind, id };
    renderList();
    renderDetails();
    if (focus && kind === 'segment') {
      const seg = st.loaded.bySegment.get(id);
      if (seg?.center) fly({ lon: seg.center[0], lat: seg.center[1], zoom: Math.max(st.view.zoom, st.scale === 10 ? 115 : 76) });
    } else if (focus) {
      const e = st.loaded.allEvents.get(id);
      if (hasPoint(e)) fly({ lon: e.lon, lat: e.lat, zoom: Math.max(st.view.zoom, 48) });
    }
    schedule();
  }

  function clearFilters() {
    if (!st.atlas) return;
    stop();
    $('search').value = ''; $('quality').value = 'all'; $('country').value = ''; $('spatial-method').value = 'all';
    $('year-start').value = st.atlas.years[0]; $('year-end').value = st.atlas.years[1];
    $('empty-segments').checked = false;
    update(true);
  }

  function playUI() {
    const el = $('play');
    const title = st.playTimer ? 'Pausar linha do tempo' : 'Reproduzir linha do tempo';
    el.setAttribute('aria-label', title); el.title = title;
    el.innerHTML = icon(st.playTimer ? 'pause' : 'play');
  }
  function stop() {
    if (st.playTimer) clearInterval(st.playTimer);
    st.playTimer = 0; st.recentYear = null;
    playUI(); schedule();
  }
  function play() {
    if (!st.atlas || !st.loaded) return;
    if (st.playTimer) { stop(); return; }
    const start = Number($('year-start').value);
    const slider = $('year-end');
    const max = st.atlas.years[1];
    if (start >= max) return;
    if (Number(slider.value) >= max) slider.value = start;
    st.recentYear = Number(slider.value);
    st.playTimer = setInterval(() => {
      const next = Number(slider.value) + 1;
      if (next > max) { stop(); return; }
      slider.value = next; st.recentYear = next;
      update(true);
    }, 380);
    playUI(); update(true);
  }

  function schedule() {
    if (!st.frame) st.frame = requestAnimationFrame(draw);
  }

  function view() {
    const { lon, lat, zoom } = st.view;
    const s = Math.min(st.width / 376, st.height / 168) * zoom;
    return { s, x: st.width / 2 - lon * s, y: st.height / 2 + lat * s };
  }

  function resize() {
    const rect = $('map-frame').getBoundingClientRect();
    st.width = rect.width; st.height = rect.height;
    st.dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(rect.width * st.dpr);
    canvas.height = Math.round(rect.height * st.dpr);
    schedule();
  }

  function screenPoint(p, lon, lat) { return [p.x + lon * p.s, p.y - lat * p.s]; }

  function fly(next) {
    cancelAnimationFrame(st.tween);
    next = { lon: clamp(next.lon, -178, 178), lat: clamp(next.lat, -85, 85), zoom: clamp(next.zoom, .8, 300) };
    if (reduced.matches) { st.view = next; schedule(); return; }
    const from = { ...st.view };
    const started = performance.now();
    const duration = 440;
    const tick = (time) => {
      const t = clamp((time - started) / duration, 0, 1);
      const eased = 1 - (1 - t) ** 3;
      st.view = { lon: from.lon + (next.lon - from.lon) * eased, lat: from.lat + (next.lat - from.lat) * eased,
        zoom: from.zoom * ((next.zoom / from.zoom) ** eased) };
      schedule();
      if (t < 1) st.tween = requestAnimationFrame(tick);
      else st.tween = 0;
    };
    st.tween = requestAnimationFrame(tick);
  }

  function zoomAt(factor, x = st.width / 2, y = st.height / 2, animate = false) {
    cancelAnimationFrame(st.tween);
    const p = view(), v = st.view;
    const zoom = clamp(v.zoom * factor, .8, 300);
    const s = p.s * zoom / v.zoom;
    const lon = clamp((x - p.x) / p.s - (x - st.width / 2) / s, -178, 178);
    const lat = clamp((p.y - y) / p.s + (y - st.height / 2) / s, -85, 85);
    if (animate) fly({ lon, lat, zoom });
    else { st.view = { lon, lat, zoom }; schedule(); }
  }

  function drawGrid(p) {
    const gridStep = [0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15, 30, 45, 90].find((step) => step * p.s >= 43) || 90;
    const limits = [Math.max(-180, -p.x / p.s), Math.max(-90, (p.y - st.height) / p.s), Math.min(180, (st.width - p.x) / p.s), Math.min(90, p.y / p.s)];
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#25435786';
    ctx.beginPath();
    for (let lon = Math.ceil(limits[0] / gridStep) * gridStep; lon <= limits[2]; lon += gridStep) {
      const x = p.x + lon * p.s;
      ctx.moveTo(x, 0); ctx.lineTo(x, st.height);
    }
    for (let lat = Math.ceil(limits[1] / gridStep) * gridStep; lat <= limits[3]; lat += gridStep) {
      const y = p.y - lat * p.s;
      ctx.moveTo(0, y); ctx.lineTo(st.width, y);
    }
    ctx.stroke();
    return limits;
  }

  function drawLabels(p) {
    if (st.view.zoom > 2.1) return;
    const labels = [[-124, -15, 'PACÍFICO'], [-38, 19, 'ATLÂNTICO'], [74, -28, 'ÍNDICO']];
    ctx.font = '600 10px system-ui, sans-serif';
    ctx.fillStyle = '#749caf99';
    ctx.textAlign = 'center';
    for (const [lon, lat, name] of labels) {
      const [x, y] = screenPoint(p, lon, lat);
      ctx.fillText(name, x, y);
    }
    ctx.textAlign = 'start';
  }

  function drawEvents(p) {
    const drawn = [];
    const exact = new Path2D(), approximate = new Path2D(), recent = new Path2D(), spatial = new Path2D();
    const global = st.view.zoom < 3;
    const radius = global ? 2.45 : 3.5;
    const addCircle = (path, x, y, r) => { path.moveTo(x + r, y); path.arc(x, y, r, 0, Math.PI * 2); };
    if ($('layer-events').checked) {
      for (const e of st.eventsShown) {
        if (!hasPoint(e)) continue;
        const [x, y] = screenPoint(p, e.lon, e.lat);
        if (x < -10 || y < -10 || x > st.width + 10 || y > st.height + 10) continue;
        const isRecent = st.recentYear !== null && e.year === st.recentYear;
        addCircle(e.approximate ? approximate : exact, x, y, radius);
        const contextual = usesApproximation(e.link);
        if (contextual) addCircle(spatial, x, y, radius + 1.9);
        if (isRecent) addCircle(recent, x, y, radius + (contextual ? 4 : 2.8));
        drawn.push({ x, y, id: e.id, label: contextual ? `${place(e)} · ${methodLabel(e.link)}` : place(e) });
      }
    }
    ctx.fillStyle = global ? '#ff876fc4' : '#ffa086e0';
    ctx.fill(exact);
    ctx.strokeStyle = '#ffcf83'; ctx.lineWidth = 1.1;
    ctx.stroke(approximate);
    ctx.strokeStyle = '#c6adff'; ctx.lineWidth = 1.3;
    ctx.stroke(spatial);
    ctx.strokeStyle = '#7bf5d7'; ctx.lineWidth = 1.3;
    ctx.stroke(recent);
    st.screenEvents = drawn;
    const selected = st.selection;
    if (!selected || selected.kind === 'segment') return;
    const e = st.loaded?.allEvents.get(selected.id);
    if (!hasPoint(e)) return;
    const [x, y] = screenPoint(p, e.lon, e.lat);
    const link = e.link;
    if (finite(link?.snap_lon) && finite(link?.snap_lat) && Math.abs(link.snap_lon - e.lon) < 180) {
      const [sx, sy] = screenPoint(p, link.snap_lon, link.snap_lat);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(sx, sy);
      ctx.setLineDash([4, 3]); ctx.strokeStyle = '#fff1bdba'; ctx.stroke(); ctx.setLineDash([]);
    }
    ctx.beginPath(); ctx.arc(x, y, 8, 0, 2 * Math.PI);
    ctx.strokeStyle = '#fff0cb'; ctx.lineWidth = 1.6; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 4, 0, 2 * Math.PI);
    ctx.fillStyle = '#ffe2ab'; ctx.fill();
  }

  function draw() {
    st.frame = 0;
    if (!ctx || !st.width || !st.height) return;
    const p = view();
    st.drawn = p;
    ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
    ctx.clearRect(0, 0, st.width, st.height);
    const limits = drawGrid(p);
    ctx.save();
    ctx.translate(p.x, p.y); ctx.scale(p.s, p.s);
    if (st.land) {
      ctx.fillStyle = '#1c3445'; ctx.fill(st.land, 'evenodd');
    }
    const data = st.loaded;
    if (data) {
      ctx.strokeStyle = st.view.zoom < 2.1 ? '#60899ba0' : '#698d9ec4';
      ctx.lineWidth = (st.view.zoom < 2.1 ? .65 : 1.05) / p.s;
      if (st.view.zoom < 2.2) ctx.stroke(data.coast);
      else {
        for (const cell of data.bins.values()) {
          const b = cell.box;
          if (b[2] >= limits[0] && b[0] <= limits[2] && b[3] >= limits[1] && b[1] <= limits[3]) ctx.stroke(cell.path);
        }
      }
      if (st.scale === 25 && $('layer-regions').checked) {
        ctx.strokeStyle = '#ad92de96'; ctx.lineWidth = 3 / p.s; ctx.stroke(data.regionsWithData);
        ctx.strokeStyle = '#90b1f1'; ctx.lineWidth = 3.3 / p.s; ctx.stroke(data.regionsEligible);
      }
      if (st.activePath) {
        ctx.strokeStyle = '#67efcf'; ctx.lineWidth = (st.view.zoom < 3 ? 1.2 : 2.3) / p.s;
        ctx.stroke(st.activePath);
      }
      const selected = st.selection;
      const id = selected?.kind === 'segment' ? selected.id : data.allEvents.get(selected?.id)?.link?.segment_id;
      const coords = data.bySegment.get(id)?.coordinates;
      if (coords) {
        const path = new Path2D(); line(path, coords);
        ctx.strokeStyle = '#ddfff6'; ctx.lineCap = 'round'; ctx.lineWidth = 4.2 / p.s; ctx.stroke(path);
      }
    }
    ctx.restore();
    drawLabels(p);
    drawEvents(p);
    const oneDegree = Math.max(8, 111.32 * Math.cos(st.view.lat * Math.PI / 180));
    const target = 65 * oneDegree / p.s;
    const pow = 10 ** Math.floor(Math.log10(target));
    const barKm = pow * (target / pow >= 5 ? 5 : target / pow >= 2 ? 2 : 1);
    $('scale-bar').querySelector('span').style.width = `${barKm * p.s / oneDegree}px`;
    $('scale-bar').querySelector('b').textContent = barKm >= 1 ? km(barKm) : `${n(Math.round(barKm * 1000))} m`;
  }

  function offset(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function squaredDistance(x, y, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay;
    const t = (dx || dy) ? clamp(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy), 0, 1) : 0;
    return (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2;
  }

  function hit(x, y) {
    if (!st.loaded || !st.drawn) return null;
    let best = 53, found = null;
    for (const pin of st.screenEvents) {
      const distance = (x - pin.x) ** 2 + (y - pin.y) ** 2;
      if (distance >= best) continue;
      best = distance; found = { ...pin, kind: 'event' };
    }
    if (found) return found;
    const p = st.drawn;
    const lon = (x - p.x) / p.s, lat = (p.y - y) / p.s;
    const dx = 8 / p.s;
    for (const cell of st.loaded.bins.values()) {
      const b = cell.box;
      if (b[0] - dx > lon || b[2] + dx < lon || b[1] - dx > lat || b[3] + dx < lat) continue;
      for (const seg of cell.segments) {
        const box = seg.box;
        if (box[0] - dx > lon || box[2] + dx < lon || box[1] - dx > lat || box[3] + dx < lat) continue;
        for (let i = 1; i < seg.coordinates.length; i++) {
          const a = seg.coordinates[i - 1], b = seg.coordinates[i];
          if (Math.abs(a[0] - b[0]) > 180) continue;
          const d = squaredDistance(lon, lat, a[0], a[1], b[0], b[1]) * p.s ** 2;
          if (d < best) { best = d; found = { id: seg.id, kind: 'segment', label: seg.id }; }
        }
      }
    }
    return found;
  }

  function showTip(point, target) {
    const tip = $('map-tip');
    tip.hidden = !target;
    canvas.classList.toggle('is-hot', !!target);
    if (!target) return;
    tip.textContent = target.label;
    tip.style.left = `${clamp(point.x + 12, 8, st.width - 170)}px`;
    tip.style.top = `${clamp(point.y - 30, 6, st.height - 34)}px`;
  }

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault(); const p = offset(e);
    zoomAt(Math.exp(clamp(-e.deltaY * .0017, -.38, .38)), p.x, p.y);
  }, { passive: false });

  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const point = offset(e);
    cancelAnimationFrame(st.tween);
    st.pointers.set(e.pointerId, point);
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add('is-dragging');
    showTip(point, null);
    if (st.pointers.size >= 2) {
      const [a, b] = st.pointers.values();
      st.pinch = Math.hypot(a.x - b.x, a.y - b.y);
      st.drag = null;
    } else st.drag = { id: e.pointerId, ...point, lon: st.view.lon, lat: st.view.lat, moved: false };
  });

  let hoverTime = 0;
  canvas.addEventListener('pointermove', (e) => {
    const point = offset(e);
    if (st.pointers.has(e.pointerId)) st.pointers.set(e.pointerId, point);
    if (st.pinch && st.pointers.size >= 2) {
      const [a, b] = st.pointers.values();
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (distance > 4) zoomAt(distance / st.pinch, (a.x + b.x) / 2, (a.y + b.y) / 2);
      st.pinch = distance;
      return;
    }
    if (st.drag?.id === e.pointerId) {
      const drag = st.drag;
      const dx = point.x - drag.x, dy = point.y - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
      if (drag.moved) {
        const scale = view().s;
        st.view.lon = clamp(drag.lon - dx / scale, -178, 178);
        st.view.lat = clamp(drag.lat + dy / scale, -85, 85);
        schedule();
      }
    } else if (!st.pointers.size && e.pointerType === 'mouse' && performance.now() - hoverTime > 40) {
      hoverTime = performance.now(); showTip(point, hit(point.x, point.y));
    }
  });

  function pointerDone(e, allowClick) {
    const drag = st.drag;
    st.pointers.delete(e.pointerId);
    st.drag = null;
    if (st.pointers.size < 2) st.pinch = null;
    if (!st.pointers.size) canvas.classList.remove('is-dragging');
    if (allowClick && drag?.id === e.pointerId && !drag.moved) {
      const point = offset(e);
      const target = hit(point.x, point.y);
      if (target) select(target.kind, target.id, target.kind === 'segment' && st.view.zoom < 4);
    }
  }
  canvas.addEventListener('pointerup', (e) => pointerDone(e, true));
  canvas.addEventListener('pointercancel', (e) => pointerDone(e, false));
  canvas.addEventListener('pointerleave', () => showTip({}, null));
  canvas.addEventListener('keydown', (e) => {
    const step = 46 / view().s;
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
    if (delta) {
      e.preventDefault();
      fly({ ...st.view, lon: st.view.lon + delta[0], lat: st.view.lat + delta[1] });
    } else if (['+', '=', '-', '0'].includes(e.key)) {
      e.preventDefault();
      if (e.key === '0') fly({ lon: 0, lat: 8, zoom: 1 });
      else zoomAt(e.key === '-' ? .67 : 1.5, undefined, undefined, true);
    }
  });

  $('zoom-in').onclick = () => zoomAt(1.55, undefined, undefined, true);
  $('zoom-out').onclick = () => zoomAt(1 / 1.55, undefined, undefined, true);
  $('zoom-reset').onclick = () => fly({ lon: 0, lat: 8, zoom: 1 });
  $('search').addEventListener('input', () => {
    clearTimeout(st.searchTimer);
    st.searchTimer = setTimeout(() => update(true), 90);
  });
  $('search').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(st.searchTimer); update(true); $('results').querySelector('.result-item')?.focus(); }
  });
  for (const id of ['quality', 'country', 'spatial-method', 'empty-segments']) $(id).addEventListener('change', () => update(true));
  for (const id of ['layer-events', 'layer-regions']) $(id).addEventListener('change', schedule);
  $('year-start').addEventListener('change', () => {
    stop();
    if (Number($('year-start').value) > Number($('year-end').value)) $('year-end').value = $('year-start').value;
    update(true);
  });
  $('year-end').addEventListener('input', () => {
    stop();
    if (Number($('year-end').value) < Number($('year-start').value)) $('year-start').value = $('year-end').value;
    update(true);
  });
  $('play').onclick = play;
  $('clear-filters').onclick = clearFilters;
  scaleButtons.forEach((b) => { b.onclick = () => switchScale(Number(b.dataset.scale)); });
  tabButtons.forEach((b) => { b.onclick = () => setTab(b.dataset.tab); });
  $('results').addEventListener('click', (e) => {
    const button = e.target.closest('button');
    if (!button) return;
    if (button.hasAttribute('data-more')) {
      const firstNew = st.limit;
      st.limit += st.pageSize; renderList();
      $('results').querySelectorAll('.result-item')[firstNew]?.focus({ preventScroll: true });
      return;
    }
    if (button.dataset.id) {
      const restoreFocus = e.detail === 0;
      const id = button.dataset.id;
      select(button.dataset.kind, id);
      if (restoreFocus) [...$('results').querySelectorAll('.result-item')].find((item) => item.dataset.id === id)?.focus({ preventScroll: true });
    }
  });
  $('details').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.hasAttribute('data-detail-close')) { st.selection = null; renderDetails(); renderList(); $('results').focus(); schedule(); }
    if (b.dataset.showEvents) { $('search').value = b.dataset.showEvents; setTab('events'); $('results').focus(); }
    if (b.dataset.showSegment) { setTab('segments'); select('segment', b.dataset.showSegment); $('details').querySelector('button')?.focus(); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !$('search').disabled && !$('method').open && !e.target.closest?.('input,textarea,select,[contenteditable]')) {
      e.preventDefault(); $('search').focus();
    }
  });
  $('method-open').onclick = () => $('method').showModal();
  for (const id of ['method-close', 'method-confirm']) $(id).onclick = () => $('method').close();
  $('method').addEventListener('click', (e) => { if (e.target === $('method')) $('method').close(); });
  new ResizeObserver(resize).observe($('map-frame'));

  async function init() {
    if (!ctx) { msg('Este navegador não consegue desenhar o mapa.'); return; }
    msg('Carregando o atlas…');
    try {
      const atlas = await json(indexUrl);
      if (!Array.isArray(atlas.years) || !Array.isArray(atlas.events) || !atlas.files) throw new Error('Índice de dados inválido');
      st.atlas = atlas;
      for (const e of atlas.events) {
        e.year = Number(e.date?.slice(0, 4));
        e.approximate = e.approximate === true || e.approximate === 1 || e.approximate === '1';
        e.key = plain([e.id, e.location, e.state, e.country, e.date].filter(Boolean).join(' '));
      }
      const [min, max] = atlas.years;
      const years = $('year-start');
      const yearOptions = [];
      for (let y = min; y <= max; y++) yearOptions.push(new Option(y, y));
      years.replaceChildren(...yearOptions); years.value = min;
      const slider = $('year-end');
      slider.min = min; slider.max = max; slider.value = max;
      const ticks = Array.from(new Set([min, Math.round((min * 2 + max) / 3), Math.round((min + max * 2) / 3), max]));
      $('timeline-ticks').innerHTML = ticks.map((y) => `<span>${y}</span>`).join('');
      const countries = Array.from(new Set(atlas.events.map((e) => e.country).filter(Boolean))).sort(collator.compare);
      $('country').replaceChildren(new Option('Todos os países', ''), ...countries.map((country) => new Option(country, country)));
      $('metric-period').textContent = `${min} – ${max}`;
      $('version-label').textContent = `Dados ${atlas.version || ''} · Etapa 02`;
      $('map-credit').textContent = atlas.source || 'Natural Earth';
      if (finite(atlas.max_distance_km)) {
        const extended = finite(atlas.extended_distance_km) ? ` A distância pode chegar a ${km(atlas.extended_distance_km)} quando o topônimo é específico e a costa é compatível com o país.` : '';
        $('method-validation').textContent = `O vínculo por proximidade usa até ${km(atlas.max_distance_km)} e verifica a compatibilidade geográfica.${extended} Referências documentadas podem sustentar um vínculo quando a cartografia administrativa não representa o lugar. Os casos sem vínculo ficam em Pendências.`;
      }
      const land = atlas.land || `atlas_terra_${atlas.version}.geojson`;
      json(new URL(land, indexUrl)).then((geo) => { st.land = landPath(geo); schedule(); }).catch(() => {});
      await switchScale(25);
    } catch (err) {
      console.error(err);
      $('results').innerHTML = `<div class="empty">${icon('info')}<p>Os dados do atlas não estão disponíveis.</p></div>`;
      msg('Não foi possível abrir os dados do atlas.', init);
    }
  }

  init();
})();
