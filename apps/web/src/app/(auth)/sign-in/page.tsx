"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthGoogleButton } from "@/components/auth/AuthGoogleButton";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { Button } from "@/components/ui/button";
import { Mail, Lock } from "lucide-react";
import { login, getCurrentUser } from "@/lib/api/auth";
import { setAuth } from "@/lib/auth/storage";
import { getGoogleOAuthUrl } from "@/config/authConfig";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // Validate fields
      if (!email || !password) {
        setError("Please fill in all required fields");
        setLoading(false);
        return;
      }

      // Call login API
      const loginResponse = await login({ email, password });

      // Store authentication data
      setAuth({
        access_token: loginResponse.access_token,
        token_type: loginResponse.token_type,
        user: loginResponse.user,
      });

      // Get current user info to check Gmail sync status
      const userInfo = await getCurrentUser();

      // Redirect based on Gmail sync status
      // Note: The /auth/me endpoint returns gmail_sync_completed_at but not google_account info.
      // If a user has a Google account, they would typically log in via Google OAuth (which handles redirects).
      // For email/password login, if gmail_sync_completed_at is null, assume they don't have Gmail connected yet.
      if (userInfo.gmail_sync_completed_at) {
        // Gmail already connected and synced -> go to closet
        router.push("/home");
      } else {
        // Email/password user without Gmail sync -> go to closet
        // (They can connect Gmail later if needed)
        router.push("/home");
      }
      
      // Note: Loading state will be cleared when component unmounts after redirect
    } catch (err) {
      // Handle errors with user-friendly message
      const errorMessage = err instanceof Error ? err.message : "Login failed. Please try again.";
      setError(errorMessage);
      setLoading(false);
    }
  };

  const handleGoogleSignIn = () => {
    // Redirect to Google OAuth flow
    const url = getGoogleOAuthUrl();
    window.location.href = url;
  };

  const isSubmitDisabled = loading || !email || !password;

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

      <AuthGoogleButton onClick={handleGoogleSignIn} disabled={loading} />

      <AuthFooter 
        text="Don't have an account?" 
        linkText="Sign Up" 
        href="/sign-up" 
      />
    </AuthGlassCard>
  );
}
