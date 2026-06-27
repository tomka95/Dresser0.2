import { describe, it, expect } from 'vitest';
import {
  AUTH_PROVIDERS,
  enabledProviders,
  providerToSupabase,
} from '@/config/authProviders';

describe('authProviders config (provider seam)', () => {
  it('declares google and apple, in order', () => {
    expect(AUTH_PROVIDERS.map((p) => p.id)).toEqual(['google', 'apple']);
  });

  it('enables google by default', () => {
    const google = AUTH_PROVIDERS.find((p) => p.id === 'google');
    expect(google?.enabled).toBe(true);
    expect(google?.supabaseProvider).toBe('google');
  });

  it('keeps apple present but disabled until NEXT_PUBLIC_APPLE_ENABLED=true', () => {
    // Apple is the seam: present in config, hidden behind the env flag.
    const apple = AUTH_PROVIDERS.find((p) => p.id === 'apple');
    expect(apple).toBeDefined();
    expect(apple?.enabled).toBe(false);
    expect(apple?.supabaseProvider).toBe('apple');
  });

  it('only renders enabled providers (google) by default', () => {
    expect(enabledProviders().map((p) => p.id)).toEqual(['google']);
  });

  it('maps provider ids to supabase provider names', () => {
    expect(providerToSupabase('google')).toBe('google');
    expect(providerToSupabase('apple')).toBe('apple');
  });

  it('throws for an unknown provider id', () => {
    // @ts-expect-error testing the guard with an invalid id
    expect(() => providerToSupabase('myspace')).toThrow();
  });
});
