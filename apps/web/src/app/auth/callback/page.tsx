"use client";

/**
 * Supabase OAuth / email-confirmation redirect target.
 *
 * Replaces the legacy /google/callback custom code-exchange. With the browser
 * client's detectSessionInUrl + PKCE, supabase-js automatically reads the
 * `?code=...` on this URL and exchanges it for a session. We just wait for the
 * session to materialize, then route the user onward.
 *
 * The redirect URL is the app origin + this path (`/auth/callback`), which must
 * be registered in Supabase's allowed redirect URLs (e.g. http://localhost:3000/
 * auth/callback in dev).
 */
import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getSession, onAuthStateChange } from "@/lib/auth";

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Provider returned an error (e.g. user denied consent).
    const oauthError = searchParams.get("error_description") || searchParams.get("error");
    if (oauthError) {
      setError(oauthError);
      return;
    }

    let active = true;
    const goOnward = () => {
      if (active) router.replace("/home");
    };

    // The session may already be set by the time this runs, or arrive slightly
    // later once supabase-js finishes the code exchange — handle both.
    getSession().then((session) => {
      if (session) goOnward();
    });

    const subscription = onAuthStateChange((_event, session) => {
      if (session) goOnward();
    });

    // Fallback: if no session resolves shortly, send the user to sign-in.
    const timeout = setTimeout(async () => {
      if (!active) return;
      const session = await getSession();
      if (!session) {
        router.replace("/sign-in");
      }
    }, 5000);

    return () => {
      active = false;
      subscription.unsubscribe();
      clearTimeout(timeout);
    };
  }, [router, searchParams]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black text-white px-6">
        <div className="text-center max-w-md">
          <h1 className="text-2xl font-bold mb-4 text-red-400">Authentication Failed</h1>
          <p className="text-gray-400 mb-6">{error}</p>
          <button
            onClick={() => router.push("/sign-in")}
            className="px-6 py-3 bg-white text-black rounded-xl hover:bg-gray-200 transition-colors"
          >
            Back to Sign In
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-black text-white">
      <div className="text-center">
        <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-white mb-4" />
        <p className="text-lg">Signing you in...</p>
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-black text-white">
          <div className="text-center">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-white mb-4" />
            <p className="text-lg">Loading...</p>
          </div>
        </div>
      }
    >
      <AuthCallbackContent />
    </Suspense>
  );
}
