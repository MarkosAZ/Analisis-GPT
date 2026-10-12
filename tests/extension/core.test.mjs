import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildCapture, publicLocation, timestamp } from '../../extension/core.mjs';

const values = {
  event_id: 'fixture-1', sport: 'FOOTBALL', bookmaker: 'Fixture Book', market: 'TOTAL_GOALS',
  period: 'FULL_TIME', line_type: 'HALF_LINE', line: '2.5',
  outcome_1: 'OVER', odds_1: '1.90', outcome_2: 'UNDER', odds_2: '2.00',
};
test('optional source grants, narrow project bridge and fixed public network destinations', () => {
  const manifest = JSON.parse(readFileSync(new URL('../../extension/manifest.json', import.meta.url)));
  assert.deepEqual(manifest.permissions, ['activeTab', 'scripting', 'sidePanel', 'storage']);
  assert.equal(manifest.host_permissions, undefined);
  assert.deepEqual(manifest.optional_host_permissions, ['https://*/*']);
  assert.deepEqual(manifest.content_scripts[0].matches, ['https://markosaz.github.io/Analisis-GPT/*', 'http://127.0.0.1/*', 'http://localhost/*']);
  assert.equal(manifest.content_scripts[0].all_frames, false);
  assert.equal(manifest.externally_connectable, undefined);
  assert.equal(manifest.content_security_policy.extension_pages.match(/connect-src ([^;]+)/)[1], 'https://www.sofascore.com https://global.flashscore.ninja https://prod20392.kmianko.com');
});
test('navigation strips query and fragment; capture stores origin only', () => {
  assert.deepEqual(publicLocation('https://sports.example/football?session=private#secret'), {
    origin: 'https://sports.example', navigation: 'https://sports.example/football',
  });
  for (const url of ['http://sports.example', 'https://user:pass@sports.example',
    'https://sports.example/my-bets', 'https://sports.example/%61ccount', 'javascript:alert(1)']) {
    assert.throws(() => publicLocation(url));
  }
});
test('public allowlist and complete unchanged prices form separate observations', () => {
  const first = buildCapture('ODDS', { ...values, stake: '99', cookies: 'private' }, 'https://sports.example');
  const second = buildCapture('ODDS', values, 'https://sports.example');
  assert.notEqual(first.capture_id, second.capture_id);
  assert.deepEqual(first.record, second.record);
  assert.equal(first.record.stake, undefined);
  assert.equal(first.record.cookies, undefined);
  assert.equal(first.record.outcomes[0].decimal_odds, '1.90');
});
test('integer and quarter lines retained without silent conversion', () => {
  for (const [line_type, line] of [['INTEGER_PUSH', '3'], ['ASIAN_QUARTER', '-1.75']]) {
    const result = buildCapture('ODDS', { ...values, line_type, line }, 'https://sports.example');
    assert.equal(result.record.line, line);
    assert.equal(result.record.line_type, line_type);
  }
  assert.throws(() => buildCapture('ODDS', { ...values, line: '2.25' }, 'https://sports.example'));
});
test('three-way requires exactly three distinct valid outcomes', () => {
  const three = { ...values, line_type: 'THREE_WAY', outcome_1: 'HOME', outcome_2: 'AWAY', outcome_3: 'DRAW', odds_3: '3.2' };
  assert.equal(buildCapture('ODDS', three, 'https://sports.example').record.outcomes.length, 3);
  for (const patch of [{ odds_3: '' }, { outcome_3: 'HOME' }, { odds_3: '1' }, { odds_3: 'NaN' }]) {
    assert.throws(() => buildCapture('ODDS', { ...three, ...patch }, 'https://sports.example'));
  }
});
test('date timezone and public field checks reject ambiguous/private inputs', () => {
  assert.throws(() => timestamp('2030-06-15T20:00:00', 'start'));
  assert.throws(() => buildCapture('ODDS', { ...values, event_id: 'https://sports.example/event' }, 'https://sports.example'));
  assert.throws(() => buildCapture('ODDS', { ...values, bookmaker: '<script>bad</script>' }, 'https://sports.example'));
});
