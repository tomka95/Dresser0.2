/**
 * OAuth / email-confirmation callback — server Route Handler.
 *
 * Replaces the old client-component callback that passively relied on
 * detectSessionInUrl. Here we exchange the PKCE `code` for a session SERVER-SIDE
 * (reading the code verifier from the cookies the browser client set during
 * signInWithOAuth), which writes the session cookies and then redirects. Because
 * the session lands in cookies, it persists across all subsequent navigations.
 *
 * signInWithOAuth / signUp use redirectTo = <origin>/auth/callback, which must be
 * registered in Supabase's allowed redirect URLs.
 */
import { NextResponse } from 'next/server';

import { createSupabaseServerClient } from '@/lib/supabase/server';

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get('code');
  // Where to land after a successful exchange (default the app home).
  const next = searchParams.get('next') ?? '/home';
  const oauthError =
    searchParams.get('error_description') ?? searchParams.get('error');

  if (oauthError) {
    return NextResponse.redirect(
      `${origin}/sign-in?error=${encodeURIComponent(oauthError)}`
    );
  }

  if (code) {
    const supabase = createSupabaseServerClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // No code, or the exchange failed — send the user back to sign in.
  return NextResponse.redirect(`${origin}/sign-in`);
}
