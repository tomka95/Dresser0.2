"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { DSButton } from "@/components/ds";
import { Mail, Lock } from "lucide-react";
import { signInWithPassword, signInWithProvider } from "@/lib/auth";
import type { AuthProviderId } from "@/config/authProviders";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingProvider, setPendingProvider] = useState<AuthProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        setError("Incorrect email or password.");
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
    <AuthGlassCard>
      <AuthHeader title="Welcome back" subtitle="Sign in to your closet" />

      <form onSubmit={handleSubmit} className="space-y-3">
        <AuthField
          placeholder="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          startIcon={<Mail className="text-white/50" size={18} />}
        />
        <AuthField
          placeholder="Password"
          isPassword
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          startIcon={<Lock className="text-white/50" size={18} />}
        />

        <div className="flex justify-end pt-0.5">
          <Link href="/forgot-password" className="text-[13px] text-white/70 transition-colors hover:text-white">
            Forgot password?
          </Link>
        </div>

        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-center text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="pt-1">
          <DSButton type="submit" variant="light" fullWidth pill loading={loading} disabled={isSubmitDisabled}>
            {loading ? "Signing in…" : "Sign in"}
          </DSButton>
        </div>
      </form>

      <div className="my-4 flex items-center gap-3">
        <div className="h-px flex-1" style={{ background: "var(--tr-20)" }} />
        <span className="text-[11px] uppercase tracking-[0.5px] text-white/50">Or</span>
        <div className="h-px flex-1" style={{ background: "var(--tr-20)" }} />
      </div>

      <AuthProviderButtons onSelect={handleProvider} disabled={loading} pendingProvider={pendingProvider} />

      <AuthFooter text="New here?" linkText="Create account" href="/sign-up" />
    </AuthGlassCard>
  );
}
