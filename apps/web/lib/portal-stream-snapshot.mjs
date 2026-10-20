/** Single bounded/allowlisted source of SSE telemetry snapshots.
 * This is a private read-only projection, never an arbitrary HTTP relay.
 */
import { readBoundedPortalSection } from "./portal-projection.mjs";

const SECTIONS = Object.freeze(["overview", "models", "nodes", "traces", "sessions"]);
const EMPTY = Object.freeze({
  overview: { integrations: [], status: "unavailable" },
  models: { models: [], status: "unavailable" },
  nodes: { nodes: [], status: "unavailable" },
  traces: { traces: [], status: "unavailable" },
  sessions: { sessions: [], status: "unavailable" },
});

export async function readSanitizedControlPlaneSnapshot(
  token, origin, stopSignal, fetcher = globalThis.fetch
) {
  const results = await Promise.all(SECTIONS.map(async section => {
    try {
      if (stopSignal?.aborted) return [section, EMPTY[section]];
      const url = new URL(`/api/v1/control-plane/${section}`, origin);
      const signal = AbortSignal.any([
        ...(stopSignal ? [stopSignal] : []),
        AbortSignal.timeout(7000),
      ]);
      const response = await fetcher(url, {
        method: "GET",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${token}`,
        },
        cache: "no-store",
        signal,
      });
      // The polling and live-stream endpoints must use the SAME projection.
      return [section, await readBoundedPortalSection(section, response)];
    } catch {
      // An independent source failure must not expose partial raw upstream data
      // or mark other feeds unavailable.
      return [section, EMPTY[section]];
    }
  }));
  return Object.fromEntries(results);
}
