// Pure projections: never join different events, lines, periods or snapshots.
const clean = value => String(value ?? '').trim();
const norm = value => clean(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const dayAt = value => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date(value));
function stamp(value, seconds = false) {
  if (typeof value === 'number') value *= seconds ? 1000 : 1;
  else if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(value)) throw new Error('SCHEMA_CHANGED');
  if (!Number.isFinite(new Date(value).getTime())) throw new Error('SCHEMA_CHANGED');
  return new Date(value).toISOString();
}
function distinct(records) {
  const seen = new Map();
  for (const row of records) {
    const key = [row.event_id, row.market || 'CALENDAR', row.period, row.line].join('|');
    if (seen.has(key) && JSON.stringify(seen.get(key)) !== JSON.stringify(row)) throw new Error('AMBIGUOUS_SOURCE');
    seen.set(key, row);
  }
  return [...seen.values()];
}
export function sofaRows(events, day) {
  if (!Array.isArray(events) || events.length > 10000) throw new Error('SCHEMA_CHANGED');
  const records = []; let skipped = 0;
  const statuses = { notstarted: 'SCHEDULED', postponed: 'POSTPONED', canceled: 'CANCELLED' };
  for (const event of events) {
    if (!event || !statuses[event.status?.type]) continue;
    try {
      if (typeof event.startTimestamp !== 'number') throw new Error();
      const scheduled = stamp(event.startTimestamp, true);
      if (dayAt(scheduled) !== day) continue;
      const competition = event.tournament?.uniqueTournament || event.tournament;
      if (event.tournament?.category?.sport?.slug && event.tournament.category.sport.slug !== 'football') continue;
      if ([event.id, competition?.id, event.homeTeam?.id, event.awayTeam?.id].some(value => value == null)) throw new Error();
      records.push({ event_id: clean(event.id), sport: 'FOOTBALL', competition_id: clean(competition.id), competition_name: clean(competition.name),
        home_id: clean(event.homeTeam.id), home_name: clean(event.homeTeam.name), away_id: clean(event.awayTeam.id), away_name: clean(event.awayTeam.name),
        scheduled_start_at: scheduled, status: statuses[event.status.type] });
    } catch { skipped++; }
  }
  return { records: distinct(records), skipped };
}
export function flashRows(feed, day) {
  if (typeof feed !== 'string' || !feed.includes('÷')) throw new Error('SCHEMA_CHANGED');
  const records = []; let competition = null; let skipped = 0;
  for (const block of feed.split('~')) {
    const row = {};
    for (const field of block.split('¬')) {
      const at = field.indexOf('÷'); if (at <= 0) continue;
      const key = field.slice(0, at); const value = field.slice(at + 1);
      if (Object.hasOwn(row, key) && row[key] !== value) throw new Error('AMBIGUOUS_SOURCE');
      row[key] = value;
    }
    if (row.ZA) { competition = { id: row.ZEE || row.ZC, name: row.ZA }; continue; }
    if (!row.AA) continue;
    const status = row.AC === '4' ? 'POSTPONED' : row.AC === '5' ? 'CANCELLED' : row.AB === '1' ? 'SCHEDULED' : null;
    if (!status) continue;
    try {
      if (!/^\d+$/.test(row.AD || '') || !competition?.id || !row.PX || !row.PY) throw new Error();
      const scheduled = stamp(Number(row.AD), true); if (dayAt(scheduled) !== day) continue;
      records.push({ event_id: row.AA, sport: 'FOOTBALL', competition_id: competition.id, competition_name: competition.name,
        home_id: row.PX, home_name: clean(row.AE), away_id: row.PY, away_name: clean(row.AF), scheduled_start_at: scheduled, status });
    } catch { skipped++; }
  }
  return { records: distinct(records), skipped };
}
function marketRow(eventId, market, bookmaker, participants = null) {
  if (!market || !Array.isArray(market.selections)) return null;
  const name = norm(market.name);
  if (market.period != null && !['full_time', 'full time', 'ft', 'partido', 'match'].includes(norm(market.period))) return null;
  const selections = market.selections;
  const result = { event_id: clean(eventId), sport: 'FOOTBALL', bookmaker, period: 'FULL_TIME' };
  let outcomes;
  if (['1x2', 'resultado del partido', 'resultado final', 'match result'].includes(name)) {
    result.market = 'MATCH_RESULT'; result.line_type = 'THREE_WAY';
    const codes = { '1': 'HOME', x: 'DRAW', '2': 'AWAY', home: 'HOME', draw: 'DRAW', away: 'AWAY', empate: 'DRAW' };
    outcomes = selections.map(selection => {
      const label = norm(selection.name);
      const team = participants?.home_name && participants?.away_name && norm(participants.home_name) !== norm(participants.away_name)
        ? label === norm(participants.home_name) ? 'HOME' : label === norm(participants.away_name) ? 'AWAY' : null : null;
      return { code: codes[label] || team, price: selection.price };
    });
    if (outcomes.length !== 3 || new Set(outcomes.map(item => item.code)).size !== 3 || outcomes.some(item => !item.code)) return null;
  } else if (['ambos equipos marcan', 'ambos equipos anotan', 'ambos anotan', 'both teams to score'].includes(name)) {
    result.market = 'BOTH_TEAMS_SCORE'; result.line_type = 'MONEYLINE';
    const codes = { si: 'YES', yes: 'YES', no: 'NO' };
    outcomes = selections.map(selection => ({ code: codes[norm(selection.name)], price: selection.price }));
    if (outcomes.length !== 2 || new Set(outcomes.map(item => item.code)).size !== 2 || outcomes.some(item => !item.code)) return null;
  } else if (['total de goles', 'goles totales', 'total goals', 'mas/menos goles', 'total de goles asiatico'].includes(name)) {
    result.market = 'TOTAL_GOALS';
    outcomes = selections.map(selection => {
      const match = norm(selection.name).match(/^(over|under|mas(?: de)?|menos(?: de)?)(?:\s*\(?([0-9]+(?:[.,][0-9]{1,2})?)\)?)?$/);
      if (!match) return {};
      const explicit = selection.line == null ? null : String(selection.line).replace(',', '.');
      const stated = match[2]?.replace(',', '.') ?? null;
      if (explicit !== null && stated !== null && Number(explicit) !== Number(stated)) return {};
      const line = stated ?? explicit;
      return { code: /^(over|mas)/.test(match[1]) ? 'OVER' : 'UNDER', price: selection.price, line };
    });
    if (outcomes.length !== 2 || !outcomes.every(item => item.code && /^\d+(?:\.\d{1,2})?$/.test(item.line || '')) ||
        outcomes[0].code === outcomes[1].code || Number(outcomes[0].line) !== Number(outcomes[1].line)) return null;
    result.line = String(Number(outcomes[0].line));
    const fraction = Math.round(Number(result.line) * 100) % 100;
    result.line_type = { 0: 'INTEGER_PUSH', 25: 'ASIAN_QUARTER', 50: 'HALF_LINE', 75: 'ASIAN_QUARTER' }[fraction];
    if (!result.line_type) return null;
  } else return null;
  const order = ['HOME', 'DRAW', 'AWAY', 'YES', 'NO', 'OVER', 'UNDER'];
  outcomes.sort((a, b) => order.indexOf(a.code) - order.indexOf(b.code));
  outcomes.forEach((item, index) => { result[`outcome_${index + 1}`] = item.code; result[`odds_${index + 1}`] = clean(item.price); });
  return result;
}
export function betanoRows(events) {
  const records = []; let skipped = 0;
  if (!Array.isArray(events) || events.length > 100) throw new Error('SCHEMA_CHANGED');
  for (const event of events) {
    if (!event || !Array.isArray(event.markets) || event.markets.length > 100) throw new Error('SCHEMA_CHANGED');
    for (const market of event.markets) { const row = marketRow(event.id, market, 'Betano Perú', event); if (row) records.push(row); else skipped++; }
  }
  return { records: distinct(records), skipped };
}
export function totalEventIds(events, day) {
  if (!Array.isArray(events) || events.length > 10000) throw new Error('SCHEMA_CHANGED');
  return [...new Set(events.filter(event => {
    try { return event.Type === 'Fixture' && !event.IsSuspended && !event.IsLive && norm(event.SportName) === 'futbol' &&
      /^[A-Za-z0-9_.-]{1,100}$/.test(clean(event._id)) && dayAt(stamp(event.StartEventDate)) === day; } catch { return false; }
  }).sort((a, b) => Date.parse(stamp(a.StartEventDate)) - Date.parse(stamp(b.StartEventDate))).map(event => clean(event._id)))].slice(0, 10);
}
export function totalRows(markets, eventIds) {
  if (!Array.isArray(markets) || markets.length > 2000) throw new Error('SCHEMA_CHANGED');
  const records = []; let skipped = 0;
  for (const market of markets) {
    if (!market || !eventIds.includes(clean(market.EventId)) || market.IsRemoved || market.IsSuspended) continue;
    if (!Array.isArray(market.Selections) || market.Selections.some(item => item.IsDisabled || item.IsRemoved)) { skipped++; continue; }
    const type = market.MarketType?._id;
    const name = { ML0: '1x2', OU0: 'total de goles' }[type];
    if (!name) { skipped++; continue; }
    const row = marketRow(market.EventId, { name, selections: market.Selections.map(item => ({
      name: type === 'ML0' ? item.OutcomeType : item.BetslipLine || item.Name,
      price: item.DisplayOdds?.Decimal ?? item.TrueOdds,
      line: item.QAParam1 === '' ? null : item.QAParam1,
    })) }, 'Apuesta Total');
    if (row) records.push(row); else skipped++;
  }
  return { records: distinct(records), skipped };
}
