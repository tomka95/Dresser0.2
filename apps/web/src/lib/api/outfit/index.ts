/**
 * API client for outfit image upload and processing.
 */

import { getAccessToken } from '@/lib/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface OutfitImageUploadResponse {
  user_id: string;
  items_created: Array<{
    id: string;
    name: string;
    brand?: string;
    category?: string;
    sub_category?: string;
    image_url?: string;
  }>;
}

/**
 * Upload an outfit image and process it through the clothing pipeline.
 * 
 * @param file - The image file to upload
 * @returns Response containing created items
 * @throws Error if upload or processing fails
 */
export async function uploadOutfitImage(
  file: File
): Promise<OutfitImageUploadResponse> {
  const token = await getAccessToken();
  if (!token) {
    throw new Error('Authentication required. Please log in.');
  }

  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE_URL}/outfit-image`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
    body: formData,
  });

  if (!response.ok) {
    // Handle authentication errors
    if (response.status === 401 || response.status === 403) {
      throw new Error('Session expired, please log in again');
    }
    
    // Parse error response
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    if (Array.isArray(error.detail)) {
      const messages = error.detail.map((err: any) => err.msg).join(', ');
      throw new Error(messages);
    }
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Upload failed');
  }

  return response.json();
}

