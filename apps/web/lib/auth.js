import NextAuth from "next-auth";
const issuer = process.env.TSIDP_ISSUER || "";
const clientId = process.env.TSIDP_CLIENT_ID || "";
const clientSecret = process.env.TSIDP_CLIENT_SECRET || "";
const secret = process.env.NEXTAUTH_SECRET || "";
const identities = (process.env.KIPNERTER_ALLOWED_EMAILS || "")
  .split(",").map((email) => email.trim().toLowerCase()).filter(Boolean);
export const authReady = Boolean(
  issuer.startsWith("https://") && clientId && clientSecret && secret.length >= 32 &&
  identities.length && process.env.NEXTAUTH_URL?.startsWith("https://")
);
export function isAllowed(email) {
  return Boolean(email && identities.includes(email.toLowerCase()));
}
export const authOptions = {
  secret,
  session: { strategy: "jwt", maxAge: 3600 },
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
      return profile?.email_verified === true && isAllowed(user?.email);
    },
    async session({ session }) {
      if (!isAllowed(session?.user?.email)) return null;
      return session;
    },
    async redirect({ url, baseUrl }) {
      return url.startsWith("/") ? `${baseUrl}${url}` : url.startsWith(`${baseUrl}/`) ? url : baseUrl;
    },
  },
};
