// API client for Gmail endpoints
import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
