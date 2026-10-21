// Exact origins prevent staging sign-in cookies, redirect URIs or identities
// from being accidentally configured against production. Not a DNS verifier.
// This opt-in Tailnet-only callback is not production or public staging.
// Never accept arbitrary hosts, userinfo, ports or path suffixes.
export const PRIVATE_TAILNET_PREVIEW_ORIGIN = "https://x1-370.tailcb8954.ts.net:8449";

export function expectedAuthOrigin(environment) {
  if (environment === "production") return "https://kipnerter.com";
  if (environment === "staging") return "https://staging.kipnerter.com";
  if (environment === "tailnet-preview") return PRIVATE_TAILNET_PREVIEW_ORIGIN;
  return null;
}

export function isConfiguredOrigin(environment, configuredUrl) {
  const expected = expectedAuthOrigin(environment);
  return Boolean(expected && configuredUrl === expected);
}
