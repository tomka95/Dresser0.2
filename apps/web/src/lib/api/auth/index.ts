// API client for the authenticated-user endpoint.
//
// Identity is now Supabase Auth: the bearer token comes from the Supabase session
// (see @/lib/auth). The backend dual-accepts Supabase JWTs and auto-provisions a
// public.users profile, so GET /auth/me works unchanged.
//
// The legacy signup/login/exchangeGoogleCode clients (which called FastAPI
// /signup, /login, /auth/google) were removed from the frontend in the Supabase
// Auth cutover. The backend endpoints themselves remain for now (retired later).
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface CurrentUserResponse {
  id: string;
  email: string;
  display_name?: string;
  full_name?: string;
  avatar_url?: string;
  gmail_sync_completed_at: string | null;
  /** Connection flags folded into /auth/me so the profile cards paint Active on first load. */
  gmail_connected?: boolean;
  calendar_connected?: boolean;
}

export async function getCurrentUser(): Promise<CurrentUserResponse> {
  const token = await getAccessToken();

  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    method: 'GET',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Failed to fetch user info');
  }

  return response.json();
}
