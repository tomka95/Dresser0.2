/**
 * Session-refresh middleware (@supabase/ssr).
 *
 * Runs on each matched request: rebuilds the session from cookies, refreshes the
 * access token when needed, and writes the updated session cookies onto the
 * response so both the browser and server clients always see a current session.
 * This is what keeps the session alive across navigations and reloads.
 *
 * Note: this does NOT gate routes (the client-side useRequireAuth guard still owns
 * redirects). It only keeps the session fresh.
 */
import { type NextRequest, NextResponse } from 'next/server';
import { createServerClient, type CookieOptions } from '@supabase/ssr';

// Shape @supabase/ssr passes to setAll. Annotated explicitly because the cookies
// option is a union type, so the callback params aren't contextually inferred.
type CookiesToSet = { name: string; value: string; options: CookieOptions }[];

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: CookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // IMPORTANT: revalidate via getUser() (not getSession()) so the token is
  // verified/refreshed and the refreshed cookies are flushed to the response.
  await supabase.auth.getUser();

  return response;
}

export const config = {
  // Run on all routes except Next internals and static assets.
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
};
