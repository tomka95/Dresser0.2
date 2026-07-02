"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Lock } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthField } from "@/components/auth/AuthField";
import { DSButton } from "@/components/ds";
import { updatePassword } from "@/lib/auth";

/** Coarse 0–3 strength: length, mixed case, digit/symbol. Drives the 3-segment meter. */
function passwordStrength(pw: string): number {
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/[\d\W]/.test(pw)) score++;
  return pw.length === 0 ? 0 : Math.max(1, score);
}

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const strength = useMemo(() => passwordStrength(password), [password]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    try {
      // Works on the recovery session created by the emailed reset link.
      await updatePassword(password);
      router.push("/home");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't update the password.";
      setError(
        /session/i.test(message)
          ? "This reset link has expired — request a new one from “Forgot password”."
          : message
      );
      setLoading(false);
    }
  };

  return (
    <AuthGlassCard>
      <h2 className="m-0 mb-2 text-[23px] font-bold text-white">Set new password</h2>
      <p className="m-0 mb-5 text-sm leading-relaxed text-white/[0.65]">
        Choose a strong password you&rsquo;ll remember.
      </p>

      <form onSubmit={handleSubmit}>
        <div className="space-y-3">
          <AuthField
            placeholder="New password"
            isPassword
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            startIcon={<Lock className="text-white/50" size={18} />}
          />
          <AuthField
            placeholder="Confirm password"
            isPassword
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            startIcon={<Lock className="text-white/50" size={18} />}
          />
        </div>

        {/* Strength meter — 3 segments fill mint as the password strengthens. */}
        <div className="mx-0.5 mt-3.5 flex gap-2" aria-hidden>
          {[1, 2, 3].map((seg) => (
            <div
              key={seg}
              className="h-1 flex-1 rounded-sm transition-colors"
              style={{ background: strength >= seg ? "var(--mint)" : "var(--tr-20)" }}
            />
          ))}
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-500/50 bg-red-500/10 p-3 text-center text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="mt-[18px]">
          <DSButton
            type="submit"
            variant="light"
            fullWidth
            pill
            loading={loading}
            disabled={loading || !password || !confirm}
          >
            {loading ? "Updating…" : "Update password"}
          </DSButton>
        </div>
      </form>
    </AuthGlassCard>
  );
}
