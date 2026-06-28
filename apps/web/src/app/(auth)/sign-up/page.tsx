"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { Button } from "@/components/ui/button";
import { Mail, Lock, User } from "lucide-react";
import { signUpWithPassword, signInWithProvider } from "@/lib/auth";
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

  if (confirmationSent) {
    return (
      <AuthGlassCard>
        <AuthHeader title="Check your email" subtitle="One more step" />
        <div className="space-y-4 text-center">
          <Mail className="mx-auto text-white/80" size={40} />
          <p className="text-sm text-white/80">
            We sent a confirmation link to{" "}
            <span className="font-medium text-white">{email}</span>. Click it to
            activate your account, then sign in.
          </p>
          <p className="text-xs text-white/50">
            Didn&apos;t get it? Check your spam folder, or try signing up again.
          </p>
        </div>
        <AuthFooter text="Already confirmed?" linkText="Sign In" href="/sign-in" />
      </AuthGlassCard>
    );
  }

  return (
    <AuthGlassCard>
      <AuthHeader title="Create Account" subtitle="Sign up to get started" />

      <form onSubmit={handleSubmit} className="space-y-4">
        <AuthField
          placeholder="Full Name"
          type="text"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          startIcon={<User className="text-white/50" size={20} />}
        />
        <AuthField
          placeholder="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          startIcon={<Mail className="text-white/50" size={20} />}
        />
        <AuthField
          placeholder="Password"
          isPassword
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          startIcon={<Lock className="text-white/50" size={20} />}
        />

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/50 text-red-400 text-sm text-center">
            {error}
          </div>
        )}

        <Button
          type="submit"
          disabled={loading || pendingProvider !== null}
          className="w-full h-[46px] rounded-full bg-white text-primary hover:bg-white/90 font-medium mt-2 disabled:opacity-50"
        >
          {loading ? "Creating account..." : "Sign Up"}
        </Button>
      </form>

      <div className="my-6 flex items-center gap-4">
        <div className="h-px bg-white/20 flex-1" />
        <span className="text-xs text-white/50 uppercase">Or</span>
        <div className="h-px bg-white/20 flex-1" />
      </div>

      <AuthProviderButtons
        onSelect={handleProvider}
        disabled={loading}
        pendingProvider={pendingProvider}
      />

      <AuthFooter text="Already have an account?" linkText="Sign In" href="/sign-in" />
    </AuthGlassCard>
  );
}
