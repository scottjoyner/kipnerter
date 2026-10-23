// Strict runtime identity configuration. Configuration-only: never verifies
// live issuer reachability, TLS certificates, browser sessions or access grants.
import { isConfiguredOrigin } from "./portal-origin.mjs";

// Exact private issuer: preview callbacks must not trust an arbitrary ts.net IdP.
export const PRIVATE_PREVIEW_TSIDP_ISSUER = "https://kipnerter-idp-staging.tailcb8954.ts.net";

const EMAIL = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/;
const DNS = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.ts\.net$/;

export function validatedTsidpIssuer(issuer) {
  if (typeof issuer !== "string" || issuer.length > 256 ||
      !issuer.startsWith("https://")) return null;
  try {
    const url = new URL(issuer);
    if (url.protocol !== "https:" || !DNS.test(url.hostname) ||
        url.username || url.password || url.search || url.hash ||
        !["", "/"].includes(url.pathname) || (url.port && url.port !== "443")) {
      return null;
    }
    return `https://${url.hostname}`;
  } catch {
    return null;
  }
}

export function validIdentityList(value, kind) {
  if (typeof value !== "string" || !value || value.length > 8192) return false;
  const entries = value.split(",");
  if (entries.length > 32 || entries.length === 0 ||
      new Set(entries).size !== entries.length) return false;
  return entries.every(item => {
    if (!item || item !== item.trim() || /\s/.test(item)) return false;
    if (kind === "email") return EMAIL.test(item) && item === item.toLowerCase();
    if (kind === "subject") return item.length >= 3 && item.length <= 200 &&
      [...item].every(c => c >= "!" && c <= "~");
    return false;
  });
}

export function isTsidpRuntimeReady(config) {
  if (!config || typeof config !== "object") return false;
  const issuer = validatedTsidpIssuer(config.issuer);
  if (!issuer ||
      (config.environment === "tailnet-preview" && issuer !== PRIVATE_PREVIEW_TSIDP_ISSUER) ||
      typeof config.clientId !== "string" || !config.clientId ||
      /[\r\n\x00]/.test(config.clientId) ||
      typeof config.clientSecret !== "string" || config.clientSecret.length < 16 ||
      /[\r\n\x00]/.test(config.clientSecret) ||
      typeof config.secret !== "string" || config.secret.length < 32 ||
      /[\r\n\x00]/.test(config.secret)) return false;
  return validIdentityList(config.allowedEmails, "email") &&
    validIdentityList(config.allowedSubjects, "subject") &&
    isConfiguredOrigin(config.environment, config.callbackOrigin);
}
