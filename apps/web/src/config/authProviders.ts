/**
 * Configuration-driven OAuth provider list.
 *
 * The sign-in / sign-up pages render their social buttons by mapping over the
 * ENABLED entries of AUTH_PROVIDERS. This is the extensibility seam:
 *
 *   Adding "Sign in with Apple" later requires NO structural/code change here —
 *   it is already present as an entry. You only:
 *     1. configure the Apple provider in the Supabase dashboard, and
 *     2. set NEXT_PUBLIC_APPLE_ENABLED=true.
 *   The Apple button then renders and routes through the same
 *   signInWithProvider('apple') -> supabase.auth.signInWithOAuth path.
 *
 * (Adding a brand-new provider that isn't here yet is also one line: append a
 *  {id, label, enabled, supabaseProvider, icon} object to the array.)
 */
import type { Provider } from '@supabase/supabase-js';

export type AuthProviderId = 'google' | 'apple';

export interface AuthProviderConfig {
  /** Stable internal id used by the UI + signInWithProvider(). */
  id: AuthProviderId;
  /** Button label. */
  label: string;
  /** Whether the button is rendered. Driven by env flags for not-yet-live providers. */
  enabled: boolean;
  /** The provider name passed to supabase.auth.signInWithOAuth(). */
  supabaseProvider: Provider;
}

// NEXT_PUBLIC_ vars are inlined at build time. Apple stays OFF until its flow is
// configured — proving the seam without implementing Apple now.
const APPLE_ENABLED =
  (process.env.NEXT_PUBLIC_APPLE_ENABLED ?? 'false').toLowerCase() === 'true';

export const AUTH_PROVIDERS: AuthProviderConfig[] = [
  {
    id: 'google',
    label: 'Continue with Google',
    enabled: true,
    supabaseProvider: 'google',
  },
  {
    id: 'apple',
    label: 'Continue with Apple',
    enabled: APPLE_ENABLED, // false by default — present-but-hidden until configured
    supabaseProvider: 'apple',
  },
];

/** Providers that should currently render as buttons. */
export function enabledProviders(): AuthProviderConfig[] {
  return AUTH_PROVIDERS.filter((p) => p.enabled);
}

/** Map an internal provider id to the supabase-js Provider name. */
export function providerToSupabase(id: AuthProviderId): Provider {
  const provider = AUTH_PROVIDERS.find((p) => p.id === id);
  if (!provider) {
    throw new Error(`Unknown auth provider: ${id}`);
  }
  return provider.supabaseProvider;
}
