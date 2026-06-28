"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthProviderButtons } from "@/components/auth/AuthProviderButtons";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { Button } from "@/components/ui/button";
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
      <AuthHeader title="Welcome Back" subtitle="Sign in to continue" />

      <form onSubmit={handleSubmit} className="space-y-4">
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

        <div className="flex justify-end">
          <Link href="/forgot-password" className="text-xs text-white/70 hover:text-white transition-colors">
            Forgot password?
          </Link>
        </div>

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/50 text-red-400 text-sm text-center">
            {error}
          </div>
        )}

        <Button
          type="submit"
          disabled={isSubmitDisabled}
          className="w-full h-[46px] rounded-full bg-white text-primary hover:bg-white/90 font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Signing in..." : "Sign In"}
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

      <AuthFooter text="Don't have an account?" linkText="Sign Up" href="/sign-up" />
    </AuthGlassCard>
  );
}
