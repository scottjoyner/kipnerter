import { getServerSession } from "next-auth";
import { authOptions } from "../auth-options";

export const identityReady = Boolean(
  process.env.KIPNERTER_OIDC_ISSUER &&
  process.env.KIPNERTER_OIDC_CLIENT_ID &&
  process.env.KIPNERTER_OIDC_CLIENT_SECRET &&
  process.env.NEXTAUTH_SECRET &&
  process.env.KIPNERTER_ALLOWED_EMAILS
);

export function allowedUser(session) {
  const email = session?.user?.email?.trim().toLowerCase();
  const allowed = (process.env.KIPNERTER_ALLOWED_EMAILS || "")
    .split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  return Boolean(identityReady && email && allowed.includes(email));
}

export function operatorUser(session) {
  const email = session?.user?.email?.trim().toLowerCase();
  const allowed = (process.env.KIPNERTER_OPERATOR_EMAILS || "")
    .split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  return Boolean(allowedUser(session) && email && allowed.includes(email));
}

export async function currentSession() {
  return getServerSession(authOptions);
}
