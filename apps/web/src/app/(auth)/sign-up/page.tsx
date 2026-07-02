"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { DSButton } from "@/components/ds";
import { Mail, Lock, User } from "lucide-react";
import { signUpWithPassword, signInWithProvider, resendSignUpEmail } from "@/lib/auth";
import type { AuthProviderId } from "@/config/authProviders";

export default function SignUpPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingProvider, setPendingProvider] = useState<AuthProviderId | null>(null);
  // Set once a confirmation email has been sent (email confirmation is ON).
  const [confirmationSent, setConfirmationSent] = useState(false);
  const [resendState, setResendState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!email || !password) {
      setError("Please fill in all required fields");
      return;
    }

    setLoading(true);
    try {
      const { needsEmailConfirmation } = await signUpWithPassword({
        email,
        password,
        fullName,
      });

      if (needsEmailConfirmation) {
        // Email confirmation is enabled: no session yet. Show "check your email".
        setConfirmationSent(true);
        setLoading(false);
      } else {
        // Confirmation disabled (not our current config) — session is active.
        router.push("/home");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
      setLoading(false);
    }
  };

  const handleProvider = async (id: AuthProviderId) => {
    setError("");
    setPendingProvider(id);
    try {
      await signInWithProvider(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-up failed. Please try again.");
      setPendingProvider(null);
    }
  };

  const handleResend = async () => {
    if (resendState === "sending") return;
    setResendState("sending");
    try {
      await resendSignUpEmail(email);
      setResendState("sent");
    } catch {
      setResendState("error");
    }
  };

  // ── "Check your email" — inline state on the same route (design spec) ──
  if (confirmationSent) {
    return (
      <AuthGlassCard>
        <div
          className="mx-auto mb-4 mt-1 flex items-center justify-center rounded-full"
          style={{ width: 56, height: 56, background: "rgba(75,226,214,0.16)", color: "var(--mint)" }}
        >
          <Mail size={26} />
        </div>
        <h2 className="m-0 mb-2 text-center text-[22px] font-bold text-white">Check your email</h2>
        <p className="mx-auto mb-5 max-w-[280px] text-center text-sm leading-relaxed text-white/[0.65]">
          We sent a confirmation link to <span className="font-semibold text-white">{email}</span>.
          Tap it to finish setting up.
        </p>
        <a href={`mailto:${email}`} className="block">
          <DSButton variant="light" fullWidth pill>
            Open email app
          </DSButton>
        </a>
        <p className="mb-0 mt-4 text-center text-[13px] text-white/60">
          Didn&rsquo;t get it?{" "}
          <button type="button" onClick={handleResend} className="font-semibold text-white hover:underline">
            {resendState === "sending" ? "Sending…" : resendState === "sent" ? "Sent again ✓" : "Resend"}
          </button>
        </p>
        {resendState === "error" && (
          <p className="mb-0 mt-2 text-center text-xs" style={{ color: "var(--danger)" }}>
            Couldn&rsquo;t resend right now — try again in a minute.
          </p>
        )}
        <AuthFooter text="Already confirmed?" linkText="Sign in" href="/sign-in" />
      </AuthGlassCard>
    );
  }

  return (
    <AuthGlassCard>
      <AuthHeader title="Create account" subtitle="Sign up to get started" />

      <form onSubmit={handleSubmit} className="space-y-3">
        <AuthField
          placeholder="Full name"
          type="text"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          startIcon={<User className="text-white/50" size={18} />}
        />
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

        {error && (
          <div className="rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-center text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="pt-1.5">
          <DSButton
            type="submit"
            variant="light"
            fullWidth
            pill
            loading={loading}
            disabled={loading || pendingProvider !== null}
          >
            {loading ? "Creating account…" : "Sign up"}
          </DSButton>
        </div>
      </form>

      <div className="my-4 flex items-center gap-3">
        <div className="h-px flex-1" style={{ background: "var(--tr-20)" }} />
        <span className="text-[11px] uppercase tracking-[0.5px] text-white/50">Or</span>
        <div className="h-px flex-1" style={{ background: "var(--tr-20)" }} />
      </div>

      <AuthProviderButtons onSelect={handleProvider} disabled={loading} pendingProvider={pendingProvider} />

      <AuthFooter text="Already have an account?" linkText="Sign in" href="/sign-in" />
    </AuthGlassCard>
  );
}
