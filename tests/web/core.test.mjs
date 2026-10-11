import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateSnapshot, filterCycles, latestCycles, localDay, dayTarget } from '../../web/core.mjs';

const demo = () => JSON.parse(readFileSync(new URL('../../web/demo.json', import.meta.url)));
test('demo and empty public snapshots have separate explicit provenance', () => {
  assert.equal(validateSnapshot(demo()).data_kind, 'SYNTHETIC');
  assert.equal(validateSnapshot(JSON.parse(readFileSync(new URL('../../web/public.json', import.meta.url)))).data_kind, 'PUBLIC');
});
test('calendar uses latest cycle while history preserves postponement', () => {
  const data = demo();
  assert.equal(latestCycles(data.cycles).length, 5);
  assert.equal(filterCycles(data).length, 5);
  assert.equal(filterCycles(data, { view: 'historial' }).length, 6);
  assert.equal(filterCycles(data, { view: 'seguimiento' }).length, 3);
  const football = filterCycles(data, { sport: 'FOOTBALL' });
  assert.equal(football.length, 2);
  assert.equal(football.find(item => item.home === 'Costa FC').cycle_number, 2);
});
test('search and today/tomorrow use Lima, including a UTC date boundary', () => {
  assert.equal(localDay('2030-06-16T01:00:00Z'), '2030-06-15');
  assert.equal(dayTarget('TODAY', new Date('2030-06-16T01:00:00Z')), '2030-06-15');
  assert.equal(dayTarget('TOMORROW', new Date('2030-06-16T01:00:00Z')), '2030-06-16');
  assert.equal(filterCycles(demo(), { search: 'costa' }).length, 1);
  assert.equal(filterCycles(demo(), { date: 'TODAY' }, new Date('2030-06-16T01:00:00Z')).length, 4);
});
test('unknown and private fields are rejected rather than rendered', () => {
  for (const key of ['real_bet', 'stake', 'token', 'raw_refs']) {
    const data = demo(); data.cycles[0][key] = 'private';
    assert.throws(() => validateSnapshot(data));
  }
  const data = demo(); data.cycles[0].home = '<img src=x onerror=alert(1)>';
  assert.throws(() => validateSnapshot(data));
});
test('broken cycles, duplicate IDs and temporal contradictions are rejected', () => {
  for (const modify of [
    data => data.cycles.push(data.cycles[0]),
    data => data.cycles.splice(0, 1),
    data => data.cycles[1].cycle_number = 1,
    data => data.cycles[0].last_observed_at = '2031-01-01T00:00:00Z',
    data => data.cycles[0].scheduled_start_at = '2030-02-30T00:00:00Z',
  ]) { const data = demo(); modify(data); assert.throws(() => validateSnapshot(data)); }
});
