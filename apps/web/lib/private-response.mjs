/** A user-scoped gateway response must never survive OIDC activation or revocation.
 * This applies to errors as well as successful telemetry projections.
 * Do not cache "identity not configured" / expired-session denials in proxies.
 */
export const PRIVATE_RESPONSE_HEADERS = Object.freeze({
  "Cache-Control": "private, no-store, max-age=0",
  "Pragma": "no-cache",
  "Vary": "Cookie",
  "X-Content-Type-Options": "nosniff",
});

export function privateJson(body, status = 200) {
  return Response.json(body, { status, headers: PRIVATE_RESPONSE_HEADERS });
}
