import assert from 'node:assert/strict';
import test from 'node:test';
import { latestGeneratedWeek } from '../lib/week-selection.ts';

test('fresh corrected Week 8 takes precedence over stale future Week 9', () => {
  assert.equal(latestGeneratedWeek({8: {generated_at: '2026-10-31T01:00:00Z'}, 9: {generated_at: '2026-10-26T22:00:00Z'}}), 8);
});
test('ties choose the higher week deterministically', () => {
  assert.equal(latestGeneratedWeek({7: {generated_at: '2026-10-26T22:00:00Z'}, 8: {generated_at: '2026-10-26T22:00:00Z'}}), 8);
});
test('unavailable or invalid dates do not manufacture a generated week', () => {
  assert.equal(latestGeneratedWeek(undefined, 1), 1);
  assert.equal(latestGeneratedWeek({9: {generated_at: 'broken'}}, 2), 2);
  assert.equal(latestGeneratedWeek({19: {generated_at: '2026-10-31T01:00:00Z'}}, 1), 1);
});
