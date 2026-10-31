import test from 'node:test';
import assert from 'node:assert/strict';
import { clockSnapshot, serverClockSnapshot, subscribeClock } from '../lib/clock.ts';

test('exact subsecond capture time stays stable between notifications and cleans up', () => {
  const original = Date.now;
  let stopFirst, stopSecond;
  let notifications = 0;
  try {
    const instant = Date.parse('2026-10-31T00:35:13.823Z');
    Date.now = () => instant;
    stopFirst = subscribeClock(() => notifications++);
    assert.equal(clockSnapshot(), instant);
    assert.equal(serverClockSnapshot(), 0);
    Date.now = () => instant + 147;
    assert.equal(clockSnapshot(), instant); // no changing snapshot during React render
    stopSecond = subscribeClock(() => notifications++);
    assert.equal(clockSnapshot(), instant + 147);
    assert.equal(notifications, 3);
  } finally {
    stopFirst?.(); stopSecond?.(); Date.now = original;
  }
  assert.equal(clockSnapshot(), 0);
});
