"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RotateCw, Mail } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthField } from "@/components/auth/AuthField";
import { DSButton } from "@/components/ds";
import { resetPasswordForEmail } from "@/lib/auth";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email) {
      setError("Enter your email first");
      return;
    }
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

  // ── Sent confirmation — inline state on the same route (design spec) ──
  if (sent) {
    return (
      <AuthGlassCard>
        <div
          className="mx-auto mb-4 mt-1 flex items-center justify-center rounded-full"
          style={{ width: 56, height: 56, background: "rgba(75,226,214,0.16)", color: "var(--mint)" }}
        >
          <RotateCw size={26} />
        </div>
        <h2 className="m-0 mb-2 text-center text-[22px] font-bold text-white">Link sent</h2>
        <p className="mx-auto mb-5 max-w-[280px] text-center text-sm leading-relaxed text-white/[0.65]">
          Check <span className="font-semibold text-white">{email}</span> for a reset link. It
          expires in 30 minutes.
        </p>
        <DSButton variant="light" fullWidth pill onClick={() => router.push("/sign-in")}>
          Back to sign in
        </DSButton>
      </AuthGlassCard>
    );
  }

  return (
    <AuthGlassCard>
      <h2 className="m-0 mb-2 text-[23px] font-bold text-white">Reset password</h2>
      <p className="m-0 mb-5 text-sm leading-relaxed text-white/[0.65]">
        Enter your email and we&rsquo;ll send you a link to set a new password.
      </p>

      <form onSubmit={handleSubmit}>
        <AuthField
          placeholder="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          startIcon={<Mail className="text-white/50" size={18} />}
        />

        {error && (
          <div className="mt-3 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-center text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="mt-[18px]">
          <DSButton type="submit" variant="light" fullWidth pill loading={loading} disabled={loading || !email}>
            {loading ? "Sending…" : "Send reset link"}
          </DSButton>
        </div>
      </form>

      <p className="mb-0 mt-[18px] text-center text-[13px] text-white/60">
        <Link href="/sign-in" className="font-semibold text-white hover:underline">
          ← Back to sign in
        </Link>
      </p>
    </AuthGlassCard>
  );
}
