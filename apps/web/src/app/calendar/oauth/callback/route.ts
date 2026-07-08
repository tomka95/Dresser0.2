/**
 * Calendar-connect OAuth callback — server Route Handler.
 *
 * Mirrors the Gmail-connect callback: this handler does NO secret-bearing work.
 * Google redirects the browser here with `code` + `state`; we forward them to the
 * BACKEND exchange endpoint (authenticated with the user's Supabase session
 * token), and the backend performs the code→token exchange and the encrypted
 * write to calendar_accounts.
 *
 * Security:
 *  - No token or authorization code is ever placed in a redirect URL.
 *  - We do not exchange the code here and never see calendar tokens.
 *  - On any failure we bounce to /profile with a coarse ?calendar=error flag only.
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

  const fail = () => NextResponse.redirect(`${origin}/profile?calendar=error`);

  if (oauthError || !code || !state) {
    return fail();
  }

  const supabase = createSupabaseServerClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    return NextResponse.redirect(`${origin}/sign-in`);
  }

  try {
    const response = await fetch(`${API_BASE_URL}/calendar/oauth/exchange`, {
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

  return NextResponse.redirect(`${origin}/profile?calendar=connected`);
}
