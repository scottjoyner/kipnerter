// Pure admission predicate, exercised with Node's native test runner.
// A tsidp email is derived from Tailscale whois, but tsidp's signed token
// currently does not emit an email_verified flag. Never trust email alone.
export function parseAllowlist(input) {
  return String(input || "").split(",").map(value => value.trim()).filter(Boolean);
}

export function admittedIdentity(email, subject, emailAllowlist, subjectAllowlist) {
  if (typeof email !== "string" || typeof subject !== "string" ||
      !email || !subject || subject.length > 256 || subject !== subject.trim()) {
    return false;
  }
  const normalizedEmail = email.trim().toLowerCase();
  if (normalizedEmail !== email.toLowerCase() || /[\s\r\n]/.test(normalizedEmail)) {
    return false;
  }
  return emailAllowlist.some(x => x.toLowerCase() === normalizedEmail) &&
    subjectAllowlist.includes(subject);
}

export function approvedTsidpProfile(profile, user, emailAllowlist, subjectAllowlist) {
  if (!profile || typeof profile !== "object" ||
      typeof profile.sub !== "string" || typeof profile.email !== "string" ||
      profile.email_verified === false) {
    return false;
  }
  if (typeof user?.email !== "string" ||
      user.email.toLowerCase() !== profile.email.toLowerCase()) {
    return false;
  }
  return admittedIdentity(profile.email, profile.sub, emailAllowlist, subjectAllowlist);
}
