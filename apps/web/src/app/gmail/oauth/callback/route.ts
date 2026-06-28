/**
 * Gmail-connect OAuth callback — server Route Handler.
 *
 * Mirrors the Supabase login callback (/auth/callback) split: this handler does
 * NO secret-bearing work. Google redirects the browser here with `code` + `state`;
 * we forward them to the BACKEND exchange endpoint (authenticated with the user's
 * Supabase session token), and the backend performs the code→token exchange and
 * the encrypted write to google_accounts.
 *
 * Security:
 *  - No token or authorization code is ever placed in a redirect URL.
 *  - We do not exchange the code here and never see Gmail tokens.
 *  - On any failure we bounce to /profile with a coarse ?gmail=error flag only.
 */
import { NextResponse } from 'next/server';

import { createSupabaseServerClient } from '@/lib/supabase/server';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get('code');
  const state = searchParams.get('state');
  const oauthError =
    searchParams.get('error_description') ?? searchParams.get('error');

  const fail = () => NextResponse.redirect(`${origin}/profile?gmail=error`);

  // User denied consent, or Google returned an error.
  if (oauthError || !code || !state) {
    return fail();
  }

  // The backend dual-accepts the Supabase access token; read it from the session
  // cookies the @supabase/ssr server client manages.
  const supabase = createSupabaseServerClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    // No active session to bind the exchange to — send back to sign in.
    return NextResponse.redirect(`${origin}/sign-in`);
  }

  try {
    const response = await fetch(`${API_BASE_URL}/gmail/oauth/exchange`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ code, state }),
      cache: 'no-store',
    });

    if (!response.ok) {
      return fail();
    }
  } catch {
    return fail();
  }

  return NextResponse.redirect(`${origin}/profile?gmail=connected`);
}
