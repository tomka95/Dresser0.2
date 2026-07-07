"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, CircleCheck, Glasses, Mail, Lock } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { Btn, Medallion, M } from "@/components/ds";
import { signUpWithPassword, signInWithProvider, resendSignUpEmail } from "@/lib/auth";
import type { AuthProviderId } from "@/config/authProviders";

/** Coarse 0–4 strength → segment count + label, matching the reset-password meter. */
function passwordStrength(pw: string): { score: number; label: string; strong: boolean } {
  if (!pw) return { score: 0, label: "", strong: false };
  let score = 1;
  if (pw.length >= 8) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/[\d\W]/.test(pw)) score++;
  const label = score <= 1 ? "Weak" : score === 2 ? "Fair" : score === 3 ? "Good" : "Strong";
  return { score, label, strong: score >= 4 };
}

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

  const strength = useMemo(() => passwordStrength(password), [password]);

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

  // ── "Check your email" — inline confirmation state on the same route ──
  if (confirmationSent) {
    return (
      <AuthGlassCard className="text-center">
        <div className="flex justify-center">
          <Medallion tone="mint" pulse icon={<Mail size={28} />} />
        </div>
        <h2
          className="m-0 mt-5 text-white"
          style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.5px" }}
        >
          Check your email
        </h2>
        <p className="mx-auto mt-2 max-w-[280px]" style={{ color: M.faint, fontSize: 14, lineHeight: 1.55 }}>
          We sent a confirmation link to
          <br />
          <span className="font-semibold text-white">{email}</span>
        </p>

        <div className="mt-[22px] flex justify-center">
          {resendState === "sent" ? (
            <span
              className="inline-flex items-center gap-[7px] font-semibold"
              style={{ color: "var(--mint)", fontSize: 13.5 }}
            >
              <CircleCheck size={16} /> Sent — check again in a minute
            </span>
          ) : (
            <Btn variant="glass" size="md" pending={resendState === "sending"} onClick={handleResend}>
              Resend email
            </Btn>
          )}
        </div>
        {resendState === "error" && (
          <p className="mt-[9px]" style={{ color: "#ff9096", fontSize: 12.5 }}>
            Couldn&rsquo;t resend — try again shortly.
          </p>
        )}

        <a href={`mailto:${email}`} className="mx-auto mt-3 block w-fit">
          <Btn variant="ghost" size="sm">
            Open email app
          </Btn>
        </a>

        <p className="mt-3.5" style={{ color: M.ghost, fontSize: 12 }}>
          Already confirmed?{" "}
          <button
            type="button"
            onClick={() => router.push("/sign-in")}
            className="font-semibold hover:underline"
            style={{ color: M.soft }}
          >
            Sign in
          </button>
        </p>
      </AuthGlassCard>
    );
  }

  return (
    <>
      <AuthGlassCard>
        <AuthHeader title="Create your account" subtitle="Sign up to get started — it takes a minute." />

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <AuthField
            placeholder="Full name"
            type="text"
            autoComplete="name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            startIcon={<Glasses size={17} />}
          />
          <AuthField
            placeholder="Email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            startIcon={<Mail size={17} />}
          />
          <div>
            <AuthField
              placeholder="Password"
              isPassword
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              startIcon={<Lock size={17} />}
            />
            {/* Live strength meter — 4 segments fill mint as the password strengthens. */}
            {password && (
              <div className="mt-[9px] flex items-center gap-[5px]" aria-hidden>
                {[1, 2, 3, 4].map((seg) => (
                  <span
                    key={seg}
                    className="flex-1 rounded-sm"
                    style={{
                      height: 3.5,
                      background:
                        strength.score >= seg
                          ? "linear-gradient(90deg,#147f74,var(--mint))"
                          : "rgba(255,255,255,0.12)",
                    }}
                  />
                ))}
                <span
                  className="ml-1.5 font-semibold"
                  style={{ color: "var(--mint)", fontSize: 11.5 }}
                >
                  {strength.label}
                </span>
              </div>
            )}
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

          <div className="mt-[6px]">
            <Btn
              type="submit"
              variant="primary"
              size="lg"
              fullWidth
              pending={loading}
              disabled={loading || pendingProvider !== null}
            >
              Create account
            </Btn>
          </div>
        </form>

        <p
          className="mx-auto mt-3 text-center"
          style={{ color: M.ghost, fontSize: 11.5, lineHeight: 1.5 }}
        >
          By continuing you agree to the <span style={{ color: M.soft }}>Terms</span> and{" "}
          <span style={{ color: M.soft }}>Privacy Policy</span>.
        </p>

        <div className="my-[17px] flex items-center gap-3">
          <span className="h-px flex-1" style={{ background: "rgba(255,255,255,0.1)" }} />
          <span className="text-[11px] font-semibold tracking-[0.12em]" style={{ color: "rgba(255,255,255,0.36)" }}>
            OR
          </span>
          <span className="h-px flex-1" style={{ background: "rgba(255,255,255,0.1)" }} />
        </div>

        <AuthProviderButtons onSelect={handleProvider} disabled={loading} pendingProvider={pendingProvider} />
      </AuthGlassCard>

      <AuthFooter text="Already have an account?" linkText="Sign in" href="/sign-in" />
    </>
  );
}
