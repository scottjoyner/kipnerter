const issuer = process.env.KIPNERTER_OIDC_ISSUER?.replace(/\/$/, "");
const configured = Boolean(issuer && process.env.KIPNERTER_OIDC_CLIENT_ID && process.env.KIPNERTER_OIDC_CLIENT_SECRET);

export const authOptions = {
  providers: configured ? [{
    id: "tailnet-identity",
    name: "Tailscale identity",
    type: "oauth",
    wellKnown: `${issuer}/.well-known/openid-configuration`,
    clientId: process.env.KIPNERTER_OIDC_CLIENT_ID,
    clientSecret: process.env.KIPNERTER_OIDC_CLIENT_SECRET,
    idToken: true,
    checks: ["pkce", "state"],
    authorization: { params: { scope: "openid profile email" } },
    profile(profile) {
      return {
        id: profile.sub,
        name: profile.name || profile.preferred_username || profile.email,
        email: profile.email,
        image: profile.picture || null
      };
    }
  }] : [],
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  pages: { signIn: "/chat" },
  callbacks: {
    async signIn({ profile }) {
      if (!profile?.email || profile.email_verified !== true) return false;
      const allowed = (process.env.KIPNERTER_ALLOWED_EMAILS || "")
        .split(",").map(x => x.trim().toLowerCase()).filter(Boolean);
      return allowed.includes(profile.email.toLowerCase());
    }
  }
};
