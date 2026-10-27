import test from 'node:test';
import assert from 'node:assert/strict';
import { snapshotFreshness } from '../lib/format.ts';
const now = Date.parse('2026-10-27T12:00:00Z');
const meta = (ageHours, kickoffHours, classification = 'pregame_snapshot') => ({
  generated_at: new Date(now - ageHours * 3_600_000).toISOString(),
  snapshot_classification: classification,
  games: [{ kickoff_utc: new Date(now + kickoffHours * 3_600_000).toISOString() }],
});
test('freshness uses actual kickoff proximity', () => {
  assert.equal(snapshotFreshness(meta(0.25, 2), now), 'Within refresh window');
  assert.match(snapshotFreshness(meta(2, 2), now), /^Refresh due/);
  assert.equal(snapshotFreshness(meta(5, 30), now), 'Within refresh window');
  assert.match(snapshotFreshness(meta(7, 30), now), /^Refresh due/);
  assert.equal(snapshotFreshness(meta(20, 80), now), 'Within refresh window');
  assert.match(snapshotFreshness(meta(25, 80), now), /^Refresh due/);
});
test('historical, expired, future and unavailable timestamps are explicit', () => {
  assert.equal(snapshotFreshness(meta(1, -1, 'historical_backfill'), now), 'Retrospective record');
  assert.match(snapshotFreshness(meta(2, -1), now), /^Archived snapshot/);
  assert.equal(snapshotFreshness(meta(-1, 2), now), 'Generation timestamp is in the future');
  assert.equal(snapshotFreshness({ ...meta(1, 2), generated_at: 'invalid' }, now), 'Freshness unavailable');
});
