/**
 * API functions for outfit image upload.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface UploadOutfitImageResponse {
  user_id: string;
  items_created: Array<{
    id: string;
    name: string;
    [key: string]: unknown;
  }>;
}

/**
 * Upload an outfit image and process it through the clothing pipeline.
 * @param file - The image file to upload
 * @returns Response with user_id and items_created array
 */
export async function uploadOutfitImage(file: File): Promise<UploadOutfitImageResponse> {
  // Get the Supabase access token from the current session
  const { getAccessToken } = await import('@/lib/auth');
  const token = await getAccessToken();

  if (!token) {
    throw new Error('Session expired, please log in again');
  }

  // Create FormData for file upload
  const formData = new FormData();
  formData.append('file', file);

  // Make API request
  const response = await fetch(`${API_BASE_URL}/outfit-image`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: formData,
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Session expired, please log in again');
    }
    const errorData = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(errorData.detail || `Upload failed with status ${response.status}`);
  }

  return response.json();
}
