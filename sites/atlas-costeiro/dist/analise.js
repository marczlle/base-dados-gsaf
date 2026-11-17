(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const number = new Intl.NumberFormat('pt-BR');
  const decimal = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
  const detail = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
  const signed = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2, signDisplay: 'exceptZero' });
  const phases = ['Lua nova', 'Crescente', 'Quarto crescente', 'Gibosa crescente', 'Lua cheia', 'Gibosa minguante', 'Quarto minguante', 'Minguante'];
  const translations = {
    AUSTRALIA: 'Austrália', BRAZIL: 'Brasil', USA: 'Estados Unidos', 'SOUTH AFRICA': 'África do Sul',
    'NEW ZEALAND': 'Nova Zelândia', 'PAPUA NEW GUINEA': 'Papua-Nova Guiné', 'NEW CALEDONIA': 'Nova Caledônia',
    'FRENCH POLYNESIA': 'Polinésia Francesa', 'UNITED KINGDOM': 'Reino Unido', MEXICO: 'México',
    BAHAMAS: 'Bahamas', 'COSTA RICA': 'Costa Rica', CANADA: 'Canadá', COLOMBIA: 'Colômbia',
    ECUADOR: 'Equador', FRANCE: 'França', SPAIN: 'Espanha', JAPAN: 'Japão', 'REUNION': 'Reunião',
  };
  const variables = {
    temperature_2m_mean: { name: 'Temperatura média', unit: '°C', color: '#f3a391' },
    precipitation_sum: { name: 'Precipitação diária', unit: 'mm', color: '#7fcbe9' },
    wind_speed_10m_mean: { name: 'Vento médio', unit: 'km/h', color: '#96ded0' },
    wind_speed_10m_max: { name: 'Vento máximo', unit: 'km/h', color: '#96ded0' },
    precipitation_previous_3d: { name: 'Chuva nos 3 dias anteriores', unit: 'mm', color: '#7fcbe9' },
    precipitation_previous_7d: { name: 'Chuva nos 7 dias anteriores', unit: 'mm', color: '#7fcbe9' },
    moon_illumination: { name: 'Iluminação lunar', unit: '%', color: '#c4afff' },
  };
  const controls = {
    country: byId('by-country'), from: byId('from-date'), to: byId('to-date'),
    group: byId('group-by'), exact: byId('exclude-reported'), metric: byId('average-metric'),
  };
  const status = byId('load-state');
  const filters = byId('filtros');
  const reset = byId('reset-filters');
  const dateLabel = (day) => day.split('-').reverse().join('/');
  const countryLabel = (country) => !country ? 'Sem país ou área informada'
    : translations[country] || country.toLocaleLowerCase('pt-BR').replace(/\b\p{L}/gu, (letter) => letter.toUpperCase());
  const formParams = new URLSearchParams(location.search);
  const chartElements = [byId('attacks-chart'), byId('averages-chart')];
  const svgNS = 'http://www.w3.org/2000/svg';

  let dataset, columns, earliest, latest, totals, comparison, comparisonIndex;
  let comparisonRevision = 0;
  const comparisonCache = new Map();

  function element(tag, className, content) {
    const result = document.createElement(tag);
    result.className = className;
    if (content !== undefined) result.textContent = content;
    return result;
  }

  function svgElement(tag, attributes = {}, content) {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function emptyChart(target, message) {
    target.replaceChildren(element('p', 'empty-chart', message));
  }

  function periods(from, to, group) {
    const years = [Number(from.slice(0, 4)), Number(to.slice(0, 4))];
    if (group === 'decade') {
      const first = Math.floor(years[0] / 10) * 10;
      const last = Math.floor(years[1] / 10) * 10;
      return Array.from({ length: (last - first) / 10 + 1 }, (_, i) => String(first + i * 10));
    }
    if (group === 'year') return Array.from({ length: years[1] - years[0] + 1 }, (_, i) => String(years[0] + i));
    const firstMonth = years[0] * 12 + Number(from.slice(5, 7)) - 1;
    const lastMonth = years[1] * 12 + Number(to.slice(5, 7)) - 1;
    return Array.from({ length: lastMonth - firstMonth + 1 }, (_, i) => {
      const month = firstMonth + i;
      return `${Math.floor(month / 12)}-${String(month % 12 + 1).padStart(2, '0')}`;
    });
  }

  function periodKey(day, group) {
    if (group === 'month') return day.slice(0, 7);
    if (group === 'decade') return String(Math.floor(Number(day.slice(0, 4)) / 10) * 10);
    return day.slice(0, 4);
  }

  function periodLabel(key, group) {
    if (group === 'month') return `${key.slice(5)}/${key.slice(0, 4)}`;
    return group === 'decade' ? `${key}–${Number(key) + 9}` : key;
  }

  function summarize(selected, from, to, group, metric) {
    const bins = new Map(periods(from, to, group).map((key) => [key, { key, total: 0 }]));
    const averages = Object.fromEntries(Object.keys(variables).map((key) => [key, { sum: 0, n: 0 }]));
    const countries = new Map();
    const byPhase = phases.map(() => 0);
    let reported = 0;
    for (const row of selected) {
      const bin = bins.get(periodKey(row[columns.date], group));
      bin.total++;
      for (const [key, value] of Object.entries(averages)) {
        if (row[columns[key]] !== null) { value.n++; value.sum += row[columns[key]]; }
      }
      const countryIndex = row[columns.country];
      countries.set(countryIndex, (countries.get(countryIndex) ?? 0) + 1);
      if (row[columns.moon_phase] !== null) byPhase[row[columns.moon_phase]]++;
      reported += row[columns.reported];
    }
    return { bins: [...bins.values()], averages, countries, byPhase, reported, count: selected.length, group, metric };
  }

  function yAxis(values, kind, key) {
    if (key === 'moon_illumination') return { min: 0, max: 100, step: 25 };
    const temperature = key === 'temperature_2m_mean';
    const minimum = temperature ? Math.min(...values) - 1 : Math.min(0, ...values);
    const maximum = temperature ? Math.max(minimum + 5, Math.max(...values) + 1) : Math.max(1, ...values);
    const raw = (maximum - minimum) / 4;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const step = Math.max(kind === 'count' ? 1 : 0, magnitude * [1, 2, 2.5, 5, 10].find((base) => base >= raw / magnitude));
    return { min: Math.floor(minimum / step) * step, max: Math.ceil(maximum / step) * step, step };
  }

  async function getComparisonScope(country) {
    if (!comparisonIndex) {
      const url = new URL(document.querySelector('meta[name="comparison-data"]').content, document.baseURI);
      comparisonIndex = fetch(url).then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const index = await response.json();
        if (index.events_version !== dataset.version || index.countries.some((label, id) => label !== dataset.countries[id])) {
          throw new Error('A comparação usa uma lista de países diferente.');
        }
        return { ...index, url };
      }).catch((error) => { comparisonIndex = undefined; throw error; });
    }
    const index = await comparisonIndex;
    const key = country || 'all';
    if (!Object.hasOwn(index.files, key)) return { fields: index.fields, rows: { without: [], with: [], exact: [] } };
    if (comparisonCache.has(key)) {
      const cached = comparisonCache.get(key);
      comparisonCache.delete(key);
      comparisonCache.set(key, cached);
      return cached;
    }
    const request = fetch(new URL(index.files[key], index.url)).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = await response.arrayBuffer();
      const magic = new Uint8Array(bytes, 0, 2);
      const payload = magic[0] === 31 && magic[1] === 139
        ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json()
        : JSON.parse(new TextDecoder().decode(bytes));
      for (const rows of Object.values(payload)) {
        for (const row of rows) row[0] = new Date(row[0] * 86400000).toISOString().slice(0, 10);
      }
      return { fields: index.fields, rows: payload };
    }).catch((error) => { if (comparisonCache.get(key) === request) comparisonCache.delete(key); throw error; });
    comparisonCache.set(key, request);
    if (comparisonCache.size > 5) comparisonCache.delete(comparisonCache.keys().next().value);
    return request;
  }

  function comparePeriods(scope, summary, from, to, exact) {
    const metric = scope.fields.indexOf(summary.metric);
    if (metric < 0) throw new Error('Variável ausente na comparação.');
    const cohort = (rows) => {
      const buckets = new Map(summary.bins.map(({ key }) => [key, { n: 0, sum: 0 }]));
      for (const row of rows) {
        const day = row[0];
        if (day > to) break;
        if (day < from) continue;
        const stat = buckets.get(periodKey(day, summary.group));
        stat.n += row[2 + metric];
        stat.sum += row[2 + scope.fields.length + metric];
      }
      return Array.from(buckets.values(), ({ n, sum }) => ({ n, value: n ? sum / n : null }));
    };
    return { with: cohort(scope.rows[exact ? 'exact' : 'with']), without: cohort(scope.rows.without) };
  }

  function renderSeries(target, summary, kind, cohorts) {
    const { bins, group, metric } = summary;
    const isCount = kind === 'count';
    const appearance = isCount ? { name: 'Ataques', unit: '', color: '#83dfcc' } : variables[metric];
    const values = isCount ? bins.map((entry) => entry.total) : cohorts.with.map((entry) => entry.value);
    const reference = isCount ? [] : cohorts.without.map((entry) => entry.value);
    const available = [...values, ...reference].filter((value) => value !== null);
    if (!available.length || (isCount && !summary.count)) {
      emptyChart(target, isCount ? 'Sem dados para este recorte.' : 'Sem dias de trechos costeiros para este recorte.');
      return;
    }
    const width = Math.max(200, target.clientWidth);
    const height = target.clientHeight || 235;
    const margin = { left: 46, top: 15, right: 14, bottom: 29 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const scale = yAxis(available, kind, isCount ? '' : metric);
    const stepX = plotW / bins.length;
    const posX = (i) => margin.left + stepX * (i + .5);
    const posY = (val) => margin.top + (scale.max - val) / (scale.max - scale.min) * plotH;
    const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, tabindex: '0', role: 'group',
      'aria-label': `${appearance.name} por período${isCount ? '' : ', com e sem registro de ataque'}. Use as setas para consultar valores.` });
    const tooltip = element('div', 'plot-tooltip');
    tooltip.hidden = true;
    tooltip.setAttribute('role', 'status');
    const grid = svgElement('g', { 'aria-hidden': 'true' });
    for (let val = scale.min; val <= scale.max + scale.step / 100; val += scale.step) {
      const y = posY(val);
      grid.append(svgElement('line', { x1: margin.left, x2: width - margin.right, y1: y, y2: y, class: 'grid' }));
      grid.append(svgElement('text', { x: margin.left - 8, y: y + 4, 'text-anchor': 'end' }, `${decimal.format(val)}${appearance.unit === '%' ? '%' : ''}`));
    }
    const maxLabels = Math.max(2, Math.floor(plotW / (group === 'year' ? 62 : 77)));
    const stride = Math.max(1, Math.ceil((bins.length - 1) / Math.max(1, maxLabels - 1)));
    const ticks = bins.length === 1 ? [0] : [...new Set([0, ...Array.from({ length: maxLabels - 2 }, (_, i) => (i + 1) * stride)
      .filter((i) => i < bins.length - stride / 2), bins.length - 1])];
    for (const index of ticks) {
      const x = Math.max(margin.left + 13, Math.min(width - margin.right - 15, posX(index)));
      grid.append(svgElement('text', { x, y: height - 7, 'text-anchor': 'middle' }, periodLabel(bins[index].key, group)));
    }
    const series = svgElement('g', { class: 'plot-series', 'aria-hidden': 'true' });
    if (isCount && bins.length <= 125) {
      const bar = Math.min(stepX * .72, 43);
      values.forEach((value, i) => {
        if (value) series.append(svgElement('rect', { x: posX(i) - bar / 2, y: posY(value), width: bar,
          height: posY(0) - posY(value), rx: Math.min(3, bar / 4), fill: appearance.color }));
      });
    }
    const line = (pointsByPeriod, color, dashed = false) => {
      let connected = false;
      const points = pointsByPeriod.map((value, i) => {
        if (value === null) { connected = false; return ''; }
        const start = !connected;
        connected = true;
        if (start && (pointsByPeriod[i + 1] === null || i === pointsByPeriod.length - 1)) {
          series.append(svgElement('circle', { cx: posX(i), cy: posY(value), r: 3, fill: color }));
        }
        return `${start ? 'M' : 'L'}${posX(i).toFixed(2)},${posY(value).toFixed(2)}`;
      }).join(' ');
      const style = { d: points, fill: 'none', stroke: color, 'stroke-width': '2.2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
      if (dashed) style['stroke-dasharray'] = '6 5';
      series.append(svgElement('path', style));
    };
    if (!isCount) {
      line(reference, '#b3c4d8', true);
      line(values, appearance.color);
    } else if (bins.length > 125) {
      line(values, appearance.color);
    }
    const guide = svgElement('line', { y1: margin.top, y2: height - margin.bottom, class: 'active-guide', visibility: 'hidden' });
    svg.append(grid, series, guide);
    let current = 0;
    const readBucket = (index) => {
      current = Math.min(bins.length - 1, Math.max(0, index));
      const entry = bins[current], value = values[current], x = posX(current);
      guide.setAttribute('x1', x);
      guide.setAttribute('x2', x);
      guide.setAttribute('visibility', 'visible');
      const observation = ({ value, n }) => value === null ? '—' : `${detail.format(value)} ${appearance.unit} (n = ${number.format(n)})`;
      if (isCount) {
        tooltip.textContent = `${periodLabel(entry.key, group)} · ${number.format(value)} ataques`;
      } else {
        const without = cohorts.without[current];
        const delta = value === null || without.value === null ? ''
          : `\nDiferença: ${signed.format(value - without.value)} ${appearance.unit === '%' ? 'p.p.' : appearance.unit}`;
        tooltip.textContent = `${periodLabel(entry.key, group)}\nCom ataque: ${observation(cohorts.with[current])}\nSem registro: ${observation(without)}${delta}`;
      }
      tooltip.style.left = `${Math.max(0, Math.min(width - Math.min(width, isCount ? 160 : 240), x + 9))}px`;
      tooltip.hidden = false;
    };
    const hide = () => { tooltip.hidden = true; guide.setAttribute('visibility', 'hidden'); };
    const point = (event) => readBucket(Math.floor(((event.clientX - svg.getBoundingClientRect().left) * width / svg.clientWidth - margin.left) / stepX));
    svg.addEventListener('pointermove', point);
    svg.addEventListener('click', point);
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('focus', () => readBucket(current));
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', (event) => {
      const positions = { ArrowLeft: current - 1, ArrowRight: current + 1, Home: 0, End: bins.length - 1 };
      if (event.key in positions) { event.preventDefault(); readBucket(positions[event.key]); }
      if (event.key === 'Escape') hide();
    });
    target.replaceChildren(svg, tooltip);
  }

  function bar(label, value, max, onClick) {
    const node = element(onClick ? 'button' : 'div', `rank-row${onClick ? '' : ' phase-row'}`);
    if (onClick) { node.type = 'button'; node.addEventListener('click', onClick); }
    const track = element('span', 'rank-track');
    track.setAttribute('aria-hidden', 'true');
    const fill = element('span', 'rank-fill');
    fill.style.width = `${max ? value / max * 100 : 0}%`;
    track.append(fill);
    node.append(element('span', 'rank-label', label), track, element('span', 'rank-value', number.format(value)));
    return node;
  }

  function refreshCharts() {
    if (!totals) return;
    renderSeries(chartElements[0], totals, 'count');
    if (comparison) renderSeries(chartElements[1], totals, 'average', comparison);
  }

  async function refreshComparison(from, to) {
    const revision = ++comparisonRevision;
    const country = controls.country.value;
    const chart = chartElements[1];
    comparison = undefined;
    byId('with-key').style.borderColor = variables[controls.metric.value].color;
    if (!comparisonCache.has(country || 'all')) emptyChart(chart, 'Carregando comparação…');
    try {
      const scope = await getComparisonScope(country);
      if (revision !== comparisonRevision) return;
      comparison = comparePeriods(scope, totals, from, to, controls.exact.checked);
      renderSeries(chart, totals, 'average', comparison);
    } catch (error) {
      if (revision !== comparisonRevision) return;
      console.error(error);
      emptyChart(chart, 'A comparação está indisponível. Recarregue a página para tentar novamente.');
    }
  }

  function refresh() {
    if (!dataset) return;
    const { country, from, to, group, exact, metric } = controls;
    const low = from.value || earliest, high = to.value || latest;
    const error = byId('filter-error');
    if (low > high || low < earliest || high > latest) {
      error.textContent = `Escolha um intervalo válido entre ${dateLabel(earliest)} e ${dateLabel(latest)}.`;
      error.hidden = false;
      return;
    }
    error.hidden = true;
    const selected = dataset.events.filter((row) => row[columns.date] >= low && row[columns.date] <= high
      && (!country.value || country.value === String(row[columns.country])) && (!exact.checked || !row[columns.reported]));
    totals = summarize(selected, low, high, group.value, metric.value);
    byId('total').textContent = number.format(totals.count);
    byId('total-context').textContent = `${number.format(totals.reported)} com data Reported`;
    for (const [id, key] of Object.entries({ temperature: 'temperature_2m_mean', precipitation: 'precipitation_sum', illumination: 'moon_illumination' })) {
      const { n, sum } = totals.averages[key];
      byId(id).textContent = n ? `${decimal.format(sum / n)} ${variables[key].unit}` : '—';
      byId(`${id}-n`).textContent = `${number.format(n)} com valor disponível`;
    }
    status.textContent = `${country.value ? countryLabel(dataset.countries[Number(country.value)]) : 'Todos os países e áreas'} · ${dateLabel(low)} a ${dateLabel(high)}`;
    const phaseN = totals.byPhase.reduce((sum, value) => sum + value, 0);
    byId('phase-coverage').textContent = `${number.format(phaseN)} de ${number.format(totals.count)} registros com fase disponível`;
    const phaseChart = byId('phases-chart');
    const phaseMax = Math.max(...totals.byPhase);
    if (phaseN) phaseChart.replaceChildren(...phases.map((name, index) => bar(name, totals.byPhase[index], phaseMax)));
    else emptyChart(phaseChart, 'Sem fase lunar neste recorte.');
    const ranking = [...totals.countries].sort((a, b) => b[1] - a[1]).slice(0, 10);
    byId('country-coverage').textContent = `${number.format(totals.countries.size)} países ou áreas no recorte · selecione uma barra para filtrar`;
    const countryChart = byId('countries-chart');
    if (ranking.length) countryChart.replaceChildren(...ranking.map(([index, value]) => bar(countryLabel(dataset.countries[index]), value, ranking[0][1], () => {
      country.value = country.value === String(index) ? '' : String(index);
      refresh();
      country.focus();
    })));
    else emptyChart(countryChart, 'Sem registros neste recorte.');
    renderSeries(chartElements[0], totals, 'count');
    refreshComparison(low, high);

    const params = new URLSearchParams();
    if (country.value) params.set('pais', dataset.countries[Number(country.value)] || 'sem-pais');
    if (low !== earliest) params.set('de', low);
    if (high !== latest) params.set('ate', high);
    if (group.value !== 'year') params.set('periodo', group.value);
    if (exact.checked) params.set('exatas', '1');
    if (metric.value !== 'temperature_2m_mean') params.set('media', metric.value);
    history.replaceState(null, '', `${location.pathname}${params.size ? `?${params}` : ''}${location.hash}`);
  }

  function loadDefaults() {
    controls.country.value = '';
    controls.from.value = earliest;
    controls.to.value = latest;
    controls.group.value = 'year';
    controls.metric.value = 'temperature_2m_mean';
    controls.exact.checked = false;
  }

  async function load() {
    try {
      const response = await fetch(document.querySelector('meta[name="analysis-data"]').content);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      dataset = await response.json();
      if (!dataset.events.length) throw new Error('Dados vazios');
      columns = Object.fromEntries(dataset.fields.map((field, index) => [field, index]));
      earliest = dataset.events[0][columns.date];
      latest = dataset.events.at(-1)[columns.date];
      const countries = dataset.countries.map((name, index) => [countryLabel(name), index]);
      countries.sort((a, b) => a[0].localeCompare(b[0], 'pt-BR'));
      for (const [name, index] of countries) controls.country.add(new Option(name, String(index)));
      for (const field of [controls.from, controls.to]) { field.min = earliest; field.max = latest; }
      loadDefaults();
      const country = formParams.get('pais');
      if (country) {
        const index = dataset.countries.indexOf(country === 'sem-pais' ? '' : country);
        if (index >= 0) controls.country.value = String(index);
      }
      for (const [field, key] of [[controls.from, 'de'], [controls.to, 'ate']]) {
        const day = formParams.get(key);
        if (day && /^\d{4}-\d{2}-\d{2}$/.test(day) && day >= earliest && day <= latest) field.value = day;
      }
      if (controls.from.value > controls.to.value) { controls.from.value = earliest; controls.to.value = latest; }
      if (['year', 'decade', 'month'].includes(formParams.get('periodo'))) controls.group.value = formParams.get('periodo');
      if (Object.hasOwn(variables, formParams.get('media'))) controls.metric.value = formParams.get('media');
      controls.exact.checked = formParams.get('exatas') === '1';
      byId('source-versions').textContent = `GSAF ${dataset.sources.spatial} · clima ${dataset.sources.climate} · lua ${dataset.sources.lunar}`;
      byId('research-results').hidden = false;
      for (const el of [...Object.values(controls), reset]) el.disabled = false;
      refresh();
    } catch (error) {
      console.error(error);
      status.textContent = 'Não foi possível carregar os dados da análise. Recarregue a página para tentar novamente.';
    }
  }

  filters.addEventListener('submit', (event) => event.preventDefault());
  for (const field of Object.values(controls)) field.addEventListener('change', refresh);
  reset.addEventListener('click', () => { loadDefaults(); refresh(); });
  const method = byId('metodologia');
  document.querySelector('.report-link').addEventListener('click', () => { method.open = true; });
  if (location.hash === '#metodologia') method.open = true;
  let lastWidth = window.innerWidth;
  window.addEventListener('resize', () => {
    if (window.innerWidth !== lastWidth) { lastWidth = window.innerWidth; refreshCharts(); }
  });
  load();
})();
