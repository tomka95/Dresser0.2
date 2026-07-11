"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CircleAlert, Mail, Lock, Hourglass, WifiOff } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { Btn } from "@/components/ds";
import { useOnline } from "@/lib/useOnline";
import { signInWithPassword, signInWithProvider } from "@/lib/auth";
import { useRedirectIfAuthenticated } from "@/lib/auth/useRedirectIfAuthenticated";
import type { AuthProviderId } from "@/config/authProviders";

/**
 * Supabase surfaces auth rate-limits as a message like "For security purposes,
 * you can only request this after N seconds" (or an "over request rate limit" /
 * "too many requests" phrasing). Detect it and, when present, pull the retry-in
 * seconds so we can run a live cooldown. Defaults to 60s when no number is given.
 */
function parseRateLimit(message: string): number | null {
  if (!/rate limit|too many|for security purposes|after \d+ second/i.test(message)) {
    return null;
  }
  const secs = message.match(/after (\d+) second/i);
  return secs ? Number(secs[1]) : 60;
}

function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function SignInPage() {
  const router = useRouter();
  // An already-signed-in visitor is bounced to the app home before the form paints.
  const { checking } = useRedirectIfAuthenticated();
  const online = useOnline();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingProvider, setPendingProvider] = useState<AuthProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Rate-limit cooldown: seconds remaining until the user may try again. null =
  // not rate-limited. A live 1s interval ticks it down; at 0 the form re-enables.
  const [cooldown, setCooldown] = useState<number | null>(null);

  // If the submit is attempted while offline, remember it and auto-fire once the
  // connection returns (see the online-reconnect effect below).
  const retryWhenOnlineRef = useRef(false);

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

  // Tick the cooldown down once a second while it's active; clear it at zero so
  // the form re-enables and the countdown banner disappears.
  useEffect(() => {
    if (cooldown === null) return;
    if (cooldown <= 0) {
      setCooldown(null);
      return;
    }
    const id = setTimeout(() => setCooldown((c) => (c === null ? null : c - 1)), 1000);
    return () => clearTimeout(id);
  }, [cooldown]);

  const attemptSignIn = useCallback(async () => {
    if (!email || !password) {
      setError("Please fill in all required fields");
      return;
    }

    // Offline: don't burn an attempt — arm an auto-retry for when we reconnect.
    if (!navigator.onLine) {
      retryWhenOnlineRef.current = true;
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await signInWithPassword({ email, password });
      // supabase-js has persisted the session; protected routes will see it.
      router.push("/home");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed. Please try again.";
      const retryIn = parseRateLimit(message);
      // Supabase returns "Email not confirmed" until the user clicks their link.
      if (retryIn !== null) {
        setCooldown(retryIn);
        setError(null);
      } else if (/email not confirmed/i.test(message)) {
        setError("Please confirm your email first — check your inbox for the link we sent.");
      } else if (/invalid login credentials/i.test(message)) {
        setError("That password doesn't match this email.");
      } else {
        setError(message);
      }
      setLoading(false);
    }
  }, [email, password, router]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void attemptSignIn();
  };

  // Auto-retry on reconnect: if a submit was attempted while offline, fire it
  // once the browser comes back online. useOnline() flips `online` on the
  // 'online' event; we consume the armed flag exactly once.
  useEffect(() => {
    if (online && retryWhenOnlineRef.current) {
      retryWhenOnlineRef.current = false;
      void attemptSignIn();
    }
  }, [online, attemptSignIn]);

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

  const rateLimited = cooldown !== null;
  // The form is locked while offline (nothing to send) or during a rate-limit
  // cooldown. Fields are disabled too so the screen reads as "wait", not "retry".
  const formDisabled = !online || rateLimited;
  const isSubmitDisabled =
    loading || pendingProvider !== null || formDisabled || !email || !password;

  // Resolve the session before rendering the form — a signed-in user is
  // redirecting, so never flash the auth form at them.
  if (checking) return null;

  return (
    <>
      <AuthGlassCard>
        <AuthHeader title="Welcome back" subtitle="Your closet's been waiting." />

        {!online && (
          <div
            className="mb-3 flex items-center gap-2 rounded-[15px] px-3.5 py-3"
            style={{
              background: "rgba(240,162,59,0.13)",
              border: "1px solid rgba(240,162,59,0.35)",
              color: "#f0b566",
            }}
            role="status"
          >
            <WifiOff size={15} className="shrink-0" />
            <span className="text-[12.8px] leading-snug">
              You&rsquo;re offline — sign-in needs a connection. We&rsquo;ll retry automatically.
            </span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <AuthField
            placeholder="Email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={formDisabled}
            startIcon={<Mail size={17} />}
          />
          <AuthField
            placeholder="Password"
            isPassword
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={formDisabled}
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
            {rateLimited ? (
              <div
                className="flex items-center gap-2 rounded-[15px] px-3.5 py-3"
                style={{
                  background: "rgba(240,162,59,0.13)",
                  border: "1px solid rgba(240,162,59,0.35)",
                  color: "#f0b566",
                }}
                role="status"
                aria-live="polite"
              >
                <Hourglass size={15} className="shrink-0" />
                <span className="text-[12.8px] leading-snug">
                  Too many attempts. You can try again in{" "}
                  <b className="tabular-nums text-white">{formatCountdown(cooldown ?? 0)}</b> — or{" "}
                  <Link href="/forgot-password" className="underline" style={{ color: "var(--mint)" }}>
                    reset your password
                  </Link>{" "}
                  now.
                </span>
              </div>
            ) : (
              <Btn type="submit" variant="primary" size="lg" fullWidth pending={loading} disabled={isSubmitDisabled}>
                Sign in
              </Btn>
            )}
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
