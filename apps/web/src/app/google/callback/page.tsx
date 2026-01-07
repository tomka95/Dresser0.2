"use client";

import { useEffect, useState, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { exchangeGoogleCode, getCurrentUser } from "@/lib/api/auth";
import { setAuth } from "@/lib/auth/storage";

function GoogleCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const hasProcessed = useRef(false);

  useEffect(() => {
    const code = searchParams.get("code");

    if (!code) {
      setError("Missing authorization code from Google.");
      setLoading(false);
      return;
    }

    // Prevent double-processing (React StrictMode or dependency changes)
    if (hasProcessed.current) {
      return;
    }
    hasProcessed.current = true;

    const handleGoogleAuth = async () => {
      try {
        const data = await exchangeGoogleCode(code);
        
        // Store authentication data
        setAuth(data);

        // Check if user has already completed Gmail sync
        try {
          const userInfo = await getCurrentUser();
          if (userInfo.gmail_sync_completed_at) {
            // Already synced, go straight to closet
            router.push("/closet");
          } else {
            // Not synced yet, go to Gmail sync
            router.push("/gmail-sync");
          }
        } catch (e) {
          // If /me fails, default to gmail-sync (safe fallback)
          console.warn("Failed to check sync status, defaulting to gmail-sync:", e);
          router.push("/gmail-sync");
        }
      } catch (e: any) {
        console.error("Google authentication error:", e);
        setError(e.message || "Failed to authenticate with Google");
      } finally {
        setLoading(false);
      }
    };

    handleGoogleAuth();
  }, [searchParams, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black text-white">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-white mb-4"></div>
          <p className="text-lg">Connecting your Google account...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black text-white px-6">
        <div className="text-center max-w-md">
          <h1 className="text-2xl font-bold mb-4 text-red-400">Authentication Failed</h1>
          <p className="text-gray-400 mb-6">{error}</p>
          <button
            onClick={() => router.push("/")}
            className="px-6 py-3 bg-white text-black rounded-xl hover:bg-gray-200 transition-colors"
          >
            Return to Home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-black text-white">
      <p>Login successful, redirecting...</p>
    </div>
  );
}

export default function GoogleCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-black text-white">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-white mb-4"></div>
            <p className="text-lg">Loading...</p>
          </div>
        </div>
      }
    >
      <GoogleCallbackContent />
    </Suspense>
  );
}

