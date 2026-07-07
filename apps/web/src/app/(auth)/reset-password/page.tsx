"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, Link2, Lock } from "lucide-react";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { Btn, StateBlock } from "@/components/ds";
import { getSession, onAuthStateChange, updatePassword } from "@/lib/auth";
import { getSupabaseClient } from "@/lib/supabase/client";

/** Coarse 0–4 strength → segment count + label, driving the 4-segment meter. */
function passwordStrength(pw: string): { score: number; label: string } {
  if (!pw) return { score: 0, label: "" };
  let score = 1;
  if (pw.length >= 8) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/[\d\W]/.test(pw)) score++;
  const label = score <= 1 ? "Weak" : score === 2 ? "Fair" : score === 3 ? "Good" : "Strong";
  return { score, label };
}

type LinkStatus = "checking" | "valid" | "invalid";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Proactively gate the form on a real recovery session, instead of only failing
  // on submit: an expired/absent link should land on a clear "request a new one" state.
  const [linkStatus, setLinkStatus] = useState<LinkStatus>("checking");

  const strength = useMemo(() => passwordStrength(password), [password]);

  // ── Recovery-session detection ──
  // A reset link opens /reset-password with the recovery grant in the URL. supabase-js
  // (detectSessionInUrl) processes the hash and fires PASSWORD_RECOVERY, establishing a
  // recovery session. PKCE-style links arrive as ?code= and need an explicit exchange.
  // We: (1) subscribe to PASSWORD_RECOVERY, (2) exchange a ?code= if present, (3) poll
  // getSession() briefly. If a session appears → valid; if the grace window elapses with
  // none → invalid (expired/tampered/opened directly).
  const settledRef = useRef(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    const settle = (status: LinkStatus) => {
      if (settledRef.current) return;
      settledRef.current = true;
      setLinkStatus(status);
    };

    const sub = onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY" || (event === "SIGNED_IN" && session)) {
        settle("valid");
      }
    });

    (async () => {
      // Already have a session (hash processed before this effect ran)?
      if (await getSession()) {
        settle("valid");
        return;
      }
      // PKCE recovery link (?code=…) — exchange it for a session.
      const code = new URLSearchParams(window.location.search).get("code");
      if (code) {
        try {
          const { error: exchErr } = await getSupabaseClient().auth.exchangeCodeForSession(code);
          if (!exchErr && (await getSession())) {
            settle("valid");
            return;
          }
        } catch {
          /* fall through to the grace window / invalid */
        }
      }
      // Give detectSessionInUrl / PASSWORD_RECOVERY a brief window to land, then give up.
      timer = setTimeout(() => settle("invalid"), 1500);
    })();

    return () => {
      sub.unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, []);

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
      if (/session/i.test(message)) {
        // The session lapsed mid-flow — fall back to the expired-link state.
        setLinkStatus("invalid");
      } else {
        setError(message);
      }
      setLoading(false);
    }
  };

  // ── Invalid / expired link landing (proactive) ──
  if (linkStatus === "invalid") {
    return (
      <AuthGlassCard>
        <StateBlock
          compact
          tone="danger"
          icon={<Link2 size={26} />}
          title="This link has expired"
          sub="Reset links work once and last 30 minutes. Request a fresh one — it only takes a second."
          cta={
            <Btn variant="primary" size="md" onClick={() => router.push("/forgot-password")}>
              Request a new link
            </Btn>
          }
          cta2={
            <Btn variant="ghost" size="md" onClick={() => router.push("/sign-in")}>
              Back to sign in
            </Btn>
          }
        />
      </AuthGlassCard>
    );
  }

  const checking = linkStatus === "checking";

  return (
    <AuthGlassCard>
      <AuthHeader title="Choose a new password" subtitle="Set a strong password you'll remember." />

      <form onSubmit={handleSubmit}>
        <div className="flex flex-col gap-3">
          <div>
            <AuthField
              placeholder="New password"
              isPassword
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={checking}
              startIcon={<Lock size={17} />}
            />
            {/* Strength meter — 4 segments fill as the password strengthens. */}
            {password && (
              <div className="mt-[9px] flex items-center gap-[5px]" aria-hidden>
                {[1, 2, 3, 4].map((seg) => (
                  <span
                    key={seg}
                    className="flex-1 rounded-sm transition-colors"
                    style={{
                      height: 3.5,
                      background:
                        strength.score >= seg
                          ? strength.score >= 3
                            ? "linear-gradient(90deg,#147f74,var(--mint))"
                            : "linear-gradient(90deg,#f0a23b,#f0b566)"
                          : "rgba(255,255,255,0.12)",
                    }}
                  />
                ))}
                <span
                  className="ml-1.5 font-semibold"
                  style={{ color: strength.score >= 3 ? "var(--mint)" : "#f0b566", fontSize: 11.5 }}
                >
                  {strength.label}
                </span>
              </div>
            )}
          </div>
          <AuthField
            placeholder="Repeat it"
            isPassword
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            disabled={checking}
            startIcon={<Lock size={17} />}
          />
        </div>

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

        <div className="mt-[18px]">
          <Btn
            type="submit"
            variant="primary"
            size="lg"
            fullWidth
            pending={loading}
            disabled={loading || checking || !password || !confirm}
          >
            Update password
          </Btn>
        </div>
      </form>
    </AuthGlassCard>
  );
}
