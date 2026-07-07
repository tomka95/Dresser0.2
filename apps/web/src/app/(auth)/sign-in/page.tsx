"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CircleAlert, Mail, Lock } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { Btn } from "@/components/ds";
import { signInWithPassword, signInWithProvider } from "@/lib/auth";
import type { AuthProviderId } from "@/config/authProviders";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingProvider, setPendingProvider] = useState<AuthProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Surface an OAuth failure bounced back by /auth/callback (?error / ?error_description).
  // Previously this was silently dropped — the redirect landed here with the reason in
  // the URL and the user saw nothing. Read it once from window.location on mount (an
  // effect, not useSearchParams, so the page doesn't need a Suspense boundary) and clean
  // the query string so a refresh doesn't re-show a stale error.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("error_description") ?? params.get("error");
    if (!raw) return;
    setError(
      /access_denied|cancelled|canceled/i.test(raw)
        ? "Sign-in was interrupted. Nothing was created — try again."
        : raw
    );
    const url = new URL(window.location.href);
    url.searchParams.delete("error");
    url.searchParams.delete("error_description");
    window.history.replaceState({}, "", url.pathname + url.search);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email || !password) {
      setError("Please fill in all required fields");
      return;
    }

    setLoading(true);
    try {
      await signInWithPassword({ email, password });
      // supabase-js has persisted the session; protected routes will see it.
      router.push("/home");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed. Please try again.";
      // Supabase returns "Email not confirmed" until the user clicks their link.
      if (/email not confirmed/i.test(message)) {
        setError("Please confirm your email first — check your inbox for the link we sent.");
      } else if (/invalid login credentials/i.test(message)) {
        setError("That password doesn't match this email.");
      } else {
        setError(message);
      }
      setLoading(false);
    }
  };

  const handleProvider = async (id: AuthProviderId) => {
    setError(null);
    setPendingProvider(id);
    try {
      // Redirects the browser to the provider and back to /auth/callback.
      await signInWithProvider(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed. Please try again.");
      setPendingProvider(null);
    }
  };

  const isSubmitDisabled = loading || pendingProvider !== null || !email || !password;

  return (
    <>
      <AuthGlassCard>
        <AuthHeader title="Welcome back" subtitle="Your closet's been waiting." />

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <AuthField
            placeholder="Email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            startIcon={<Mail size={17} />}
          />
          <AuthField
            placeholder="Password"
            isPassword
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            startIcon={<Lock size={17} />}
          />

          <div className="mt-[-2px] text-right">
            <Link
              href="/forgot-password"
              className="text-[13px] font-medium transition-colors hover:opacity-80"
              style={{ color: "var(--mint)" }}
            >
              Forgot password?
            </Link>
          </div>

          {error && (
            <div
              className="flex items-center gap-2 rounded-[15px] px-3.5 py-3"
              style={{
                background: "rgba(251,44,54,0.13)",
                border: "1px solid rgba(251,44,54,0.32)",
                color: "#ff9096",
              }}
              role="alert"
            >
              <CircleAlert size={16} className="shrink-0" />
              <span className="text-[12.8px] leading-snug text-white">{error}</span>
            </div>
          )}

          <div className="mt-1">
            <Btn type="submit" variant="primary" size="lg" fullWidth pending={loading} disabled={isSubmitDisabled}>
              Sign in
            </Btn>
          </div>
        </form>

        <div className="my-[17px] flex items-center gap-3">
          <span className="h-px flex-1" style={{ background: "rgba(255,255,255,0.1)" }} />
          <span className="text-[11px] font-semibold tracking-[0.12em]" style={{ color: "rgba(255,255,255,0.36)" }}>
            OR
          </span>
          <span className="h-px flex-1" style={{ background: "rgba(255,255,255,0.1)" }} />
        </div>

        <AuthProviderButtons onSelect={handleProvider} disabled={loading} pendingProvider={pendingProvider} />
      </AuthGlassCard>

      <AuthFooter text="New here?" linkText="Create an account" href="/sign-up" />
    </>
  );
}
