export const TELEMETRY_STALE_MS = 45000;

// A newly polled index may contain old events, but even its *observation*
// must expire in the browser if no successful update arrives.
export function snapshotExpired(lastReceivedAt, now) {
  return Number.isFinite(lastReceivedAt) &&
    lastReceivedAt > 0 && now - lastReceivedAt > TELEMETRY_STALE_MS;
}

// Each new SSE snapshot invalidates any still-pending polling fallback so a
// slow response cannot replace a newer, more authoritative observation.
export function canApplyPoll(ticket, currentGeneration, stopped) {
  return !stopped && ticket === currentGeneration;
}
