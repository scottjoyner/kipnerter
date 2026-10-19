// Exact origins prevent staging sign-in cookies, redirect URIs or identities
// from being accidentally configured against production. Not a DNS verifier.
export function expectedAuthOrigin(environment) {
  if (environment === "production") return "https://kipnerter.com";
  if (environment === "staging") return "https://staging.kipnerter.com";
  return null;
}

export function isConfiguredOrigin(environment, configuredUrl) {
  const expected = expectedAuthOrigin(environment);
  return Boolean(expected && configuredUrl === expected);
}
