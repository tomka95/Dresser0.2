/**
 * Supabase SERVER client (cookie-backed via @supabase/ssr).
 *
 * For use in Route Handlers and Server Components. Reads/writes the same session
 * cookies the browser client uses, so the two stay in sync. In a Server Component
 * the cookie store is read-only and setAll throws — that's expected; middleware.ts
 * is responsible for writing refreshed cookies in that case.
 */
import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { cookies } from 'next/headers';

// Shape @supabase/ssr passes to setAll. Annotated explicitly because the cookies
// option is a union type, so the callback params aren't contextually inferred.
type CookiesToSet = { name: string; value: string; options: CookieOptions }[];

export function createSupabaseServerClient() {
  const cookieStore = cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: CookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Called from a Server Component (read-only cookies). Safe to ignore;
            // session refresh cookies are written by middleware.ts instead.
          }
        },
      },
    }
  );
}
