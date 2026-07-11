"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, CircleCheck, Mail } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { Btn, Medallion, M } from "@/components/ds";
import { resetPasswordForEmail } from "@/lib/auth";
import { useRedirectIfAuthenticated } from "@/lib/auth/useRedirectIfAuthenticated";

export default function ForgotPasswordPage() {
  const router = useRouter();
  // An already-signed-in visitor is bounced to the app home before the form paints.
  const { checking } = useRedirectIfAuthenticated();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resolve the session before rendering the form — a signed-in user is
  // redirecting, so never flash the auth form at them.
  if (checking) return null;

  const sendResetLink = async () => {
    if (!email) {
      setError("Enter your email first");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await resetPasswordForEmail(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send the reset link. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void sendResetLink();
  };

  // ── Sent confirmation — inline success state on the same route ──
  // No account enumeration: the copy is deliberately conditional ("if it has an account").
  if (sent) {
    return (
      <AuthGlassCard className="text-center">
        <div className="flex justify-center">
          <Medallion tone="mint" icon={<CircleCheck size={28} />} />
        </div>
        <h2
          className="m-0 mt-5 text-white"
          style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.5px" }}
        >
          Link on its way
        </h2>
        <p className="mx-auto mt-2 max-w-[280px]" style={{ color: M.faint, fontSize: 14, lineHeight: 1.55 }}>
          If <span className="text-white">{email}</span> has an account, a reset link is in its
          inbox. It expires in 30 minutes.
        </p>
        <a href="mailto:" className="mx-auto mt-[22px] block w-fit">
          <Btn variant="glass" size="md">
            Open mail app
          </Btn>
        </a>
        <p className="mt-3.5" style={{ color: M.ghost, fontSize: 12 }}>
          Nothing arriving?{" "}
          <button
            type="button"
            onClick={() => void sendResetLink()}
            className="hover:underline"
            style={{ color: M.soft }}
          >
            Resend
          </button>{" "}
          ·{" "}
          <button
            type="button"
            onClick={() => router.push("/sign-in")}
            className="hover:underline"
            style={{ color: M.soft }}
          >
            Back to sign in
          </button>
        </p>
      </AuthGlassCard>
    );
  }

  return (
    <AuthGlassCard>
      <AuthHeader title="Reset your password" subtitle="Enter your email and we'll send a reset link." />

      <form onSubmit={handleSubmit}>
        <AuthField
          placeholder="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          startIcon={<Mail size={17} />}
        />

        {error && (
          <div
            className="mt-3.5 flex items-center gap-2 rounded-[15px] px-3.5 py-3"
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

        <div className="mt-4">
          <Btn type="submit" variant="primary" size="lg" fullWidth pending={loading} disabled={loading || !email}>
            Send reset link
          </Btn>
        </div>
      </form>

      <div className="mt-4 text-center">
        <button
          type="button"
          onClick={() => router.push("/sign-in")}
          className="hover:opacity-80"
          style={{ color: M.faint, fontSize: 13.5 }}
        >
          Back to sign in
        </button>
      </div>
    </AuthGlassCard>
  );
}
