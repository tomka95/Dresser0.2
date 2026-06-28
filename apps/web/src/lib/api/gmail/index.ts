// API client for Gmail endpoints
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface GmailConnectionStatus {
  connected: boolean;
  scope: string | null;
  connected_at: string | null;
}

/**
 * Begin the Gmail-connect OAuth flow.
 *
 * The backend builds the Google consent URL (dedicated gmail.readonly client)
 * and a signed, user-bound `state`. We never construct the consent URL or hold
 * any client secret on the frontend; we just navigate to the URL the backend
 * returns. Google then redirects back to the /gmail/oauth/callback Route Handler.
 */
export async function startGmailConnect(): Promise<void> {
  const token = await getAccessToken();
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/gmail/oauth/start`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error('Could not start Gmail connection. Please try again.');
  }

  const { url } = (await response.json()) as { url: string };
  if (!url) {
    throw new Error('Server did not return a Gmail authorization URL.');
  }
  // Full-page navigation to Google's consent screen.
  window.location.href = url;
}

/** Read whether the current user has a usable (refresh-token-bearing) Gmail connection. */
export async function fetchGmailConnectionStatus(): Promise<GmailConnectionStatus> {
  const token = await getAccessToken();
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/gmail/oauth/status`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    throw new Error('Failed to read Gmail connection status.');
  }

  return response.json();
}

export interface GmailClothingItem {
  name: string;
  store: string | null;
  price: number | null;
  image: string | null;
}

export interface ExtractClothingResponse {
  connected: boolean;
  items: GmailClothingItem[];
}

/**
 * Extract clothing items from Gmail purchase emails.
 * Requires authenticated user with Gmail access.
 * 
 * @returns Promise with connected status and array of clothing items
 * @throws Error if extraction fails or user is not authenticated
 */
export async function extractClothingFromGmail(): Promise<ExtractClothingResponse> {
  // Get the Supabase access token from the current session
  const token = await getAccessToken();
  
  if (!token) {
    throw new Error('Not authenticated. Please sign in first.');
  }

  const response = await fetch(`${API_BASE_URL}/gmail/clothing-items`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    
    // Handle FastAPI validation errors (422)
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    
    // Handle specific error cases
    if (response.status === 401 || response.status === 403) {
      throw new Error('Gmail access not granted. Please reconnect your Google account.');
    }
    
    if (response.status === 500) {
      throw new Error('Something went wrong. Please try again.');
    }
    
    throw new Error(
      typeof error.detail === 'string' 
        ? error.detail 
        : 'Failed to extract clothing items from Gmail'
    );
  }

  return response.json();
}
