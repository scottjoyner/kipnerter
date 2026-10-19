import { admittedIdentity, approvedTsidpProfile, parseAllowlist } from "./identity.mjs";
import { isConfiguredOrigin } from "./portal-origin.mjs";

const issuer = process.env.TSIDP_ISSUER || "";
const clientId = process.env.TSIDP_CLIENT_ID || "";
const clientSecret = process.env.TSIDP_CLIENT_SECRET || "";
const secret = process.env.NEXTAUTH_SECRET || "";
const allowedEmails = parseAllowlist(process.env.KIPNERTER_ALLOWED_EMAILS);
const allowedSubjects = parseAllowlist(process.env.KIPNERTER_ALLOWED_TSIDP_SUBJECTS);
export const authReady = Boolean(
  issuer.startsWith("https://") && clientId && clientSecret && secret.length >= 32 &&
  allowedEmails.length && allowedSubjects.length &&
  isConfiguredOrigin(process.env.KIPNERTER_ENV || "production", process.env.NEXTAUTH_URL)
);
export function isAllowed(email, subject) {
  return admittedIdentity(email, subject, allowedEmails, allowedSubjects);
}
export const authOptions = {
  secret,
  // Offline JWT sessions cannot guarantee instant IdP revocation.
  // Force a new whois-backed sign-in after at most 15 minutes.
  session: { strategy: "jwt", maxAge: 900 },
  providers: authReady ? [{
    id: "tailscale", name: "Tailscale", type: "oauth",
    wellKnown: `${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`,
    clientId, clientSecret, idToken: true,
    authorization: { params: { scope: "openid email profile" } },
    profile(profile) {
      return { id: profile.sub, email: profile.email, name: profile.name || profile.email };
    },
  }] : [],
  callbacks: {
    async signIn({ profile, user }) {
      return approvedTsidpProfile(profile, user, allowedEmails, allowedSubjects);
    },
    async session({ session, token }) {
      if (!isAllowed(session?.user?.email, token?.sub)) return null;
      return { ...session, user: { ...session.user, id: token.sub } };
    },
    async redirect({ url, baseUrl }) {
      return url.startsWith("/") ? `${baseUrl}${url}` :
        url.startsWith(`${baseUrl}/`) ? url : baseUrl;
    },
  },
};
