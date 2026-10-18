"use client";
import { signIn } from "next-auth/react";

export function SignInButton() {
  return <button className="console-primary" onClick={() => signIn("tailnet-identity", { callbackUrl: "/chat" })}>Sign in securely →</button>;
}
