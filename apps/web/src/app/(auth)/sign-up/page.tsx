"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGlassCard } from "@/components/auth/AuthGlassCard";
import { AuthHeader } from "@/components/auth/AuthHeader";
import { AuthField } from "@/components/auth/AuthField";
import { AuthGoogleButton } from "@/components/auth/AuthGoogleButton";
import { AuthFooter } from "@/components/auth/AuthFooter";
import { ConnectGmailModal } from "@/components/auth/ConnectGmailModal";
import { Button } from "@/components/ui/button";
import { Mail, Lock, User } from "lucide-react";
import { signup } from "@/lib/api/auth";
import { setAuth } from "@/lib/auth/storage";
import { getGoogleOAuthUrl } from "@/config/authConfig";

export default function SignUpPage() {
  const router = useRouter();
  const [isGmailModalOpen, setIsGmailModalOpen] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleCreateAccountSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    // Validate form fields
    if (!email || !password) {
      setError("Please fill in all required fields");
      return;
    }
    // Open modal instead of submitting directly
    setIsGmailModalOpen(true);
  };

  const handleGmailConnect = () => {
    // Redirect to Google OAuth flow for Gmail connection
    const url = getGoogleOAuthUrl();
    window.location.href = url;
  };

  const handleMaybeLater = async () => {
    setIsGmailModalOpen(false);
    setError("");
    setLoading(true);

    try {
      // Proceed with email/password signup
      const result = await signup({ email, password, fullName });
      // Store auth data
      setAuth({
        access_token: result.access_token,
        token_type: result.token_type,
        user: result.user,
      });
      // Redirect to closet or onboarding
      router.push("/home");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
      setLoading(false);
    }
  };

  return (
    <>
      <AuthGlassCard>
        <AuthHeader title="Create Account" subtitle="Sign up to get started" />
        
        <form onSubmit={handleCreateAccountSubmit} className="space-y-4">
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
              disabled={loading}
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

        {/* Continue with Google - no modal, keeps existing behavior */}
        <AuthGoogleButton />

        <AuthFooter 
          text="Already have an account?" 
          linkText="Sign In" 
          href="/sign-in" 
        />
      </AuthGlassCard>

      <ConnectGmailModal
        open={isGmailModalOpen}
        onClose={() => setIsGmailModalOpen(false)}
        onConnect={handleGmailConnect}
        onMaybeLater={handleMaybeLater}
      />
    </>
  );
}
