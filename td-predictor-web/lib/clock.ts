// Cached exact milliseconds satisfy React's stable snapshot contract without rounding
// a newly generated artifact into the future. All freshness limits remain unchanged.
let current = 0;
let timer: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();
const update = () => {
  current = Date.now();
  for (const listener of listeners) listener();
};
export const clockSnapshot = () => current;
export const serverClockSnapshot = () => 0;
export function subscribeClock(listener: () => void) {
  listeners.add(listener);
  update();
  if (!timer) timer = setInterval(update, 1_000);
  return () => {
    listeners.delete(listener);
    if (!listeners.size && timer) {
      clearInterval(timer);
      timer = undefined;
      current = 0;
    }
  };
}
