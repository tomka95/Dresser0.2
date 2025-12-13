'use client';

import { useState, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { uploadOutfitImage } from '@/lib/api/outfit';
import { useClosetStore } from '@/stores/useClosetStore';

type UploadState = 'idle' | 'uploading' | 'processing' | 'success' | 'error';

export function OutfitImageUpload() {
  const [uploadState, setUploadState] = useState<UploadState>('idle');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const fetchItems = useClosetStore((state) => state.fetchItems);

  const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
  const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];

  const validateFile = (file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return 'Please upload a valid image file (JPEG, PNG, or WebP)';
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File size must be less than ${MAX_FILE_SIZE / 1024 / 1024}MB`;
    }
    return null;
  };

  const handleFileSelect = useCallback((file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setSelectedFile(null);
      setPreviewUrl(null);
      return;
    }

    setError(null);
    setSelectedFile(file);
    
    // Create preview URL
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
  }, []);

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    const file = e.dataTransfer.files[0];
    if (file) {
      handleFileSelect(file);
    }
  }, [handleFileSelect]);

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleRemove = () => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    setSelectedFile(null);
    setPreviewUrl(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleSubmit = async () => {
    if (!selectedFile) {
      setError('Please select an image file');
      return;
    }

    // Prevent double submit
    if (uploadState === 'uploading' || uploadState === 'processing') {
      return;
    }

    setUploadState('uploading');
    setError(null);

    try {
      const response = await uploadOutfitImage(selectedFile);
      
      setUploadState('processing');
      
      // Wait a moment to show processing state
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Refresh closet items exactly once
      await fetchItems();
      
      setUploadState('success');
      
      // Log success in dev
      if (process.env.NODE_ENV === 'development') {
        console.log('Upload successful:', response);
      }
      
      // Clear selection after success (keep success message visible briefly)
      setTimeout(() => {
        handleRemove();
        setUploadState('idle');
      }, 3000);
    } catch (err) {
      setUploadState('error');
      const errorMessage = err instanceof Error ? err.message : 'Failed to upload and process image';
      setError(errorMessage);
      
      // Log error in dev
      if (process.env.NODE_ENV === 'development') {
        console.error('Upload error:', err);
      }
    }
  };

  const isProcessing = uploadState === 'uploading' || uploadState === 'processing';
  const canSubmit = selectedFile && uploadState === 'idle' && !error;

  return (
    <div className="border rounded-lg p-6 bg-white">
      <h2 className="text-xl font-semibold mb-4">Upload Outfit Photo</h2>
      
      {!selectedFile ? (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:border-gray-400 transition-colors"
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            onChange={handleFileInputChange}
            className="hidden"
          />
          <div className="space-y-2">
            <p className="text-gray-600">Drag & drop an image here, or click to select</p>
            <p className="text-sm text-gray-500">JPEG, PNG, or WebP (max 10MB)</p>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {previewUrl && (
            <div className="relative">
              <img
                src={previewUrl}
                alt="Preview"
                className="w-full max-h-64 object-contain rounded-lg border"
              />
              {uploadState === 'idle' && (
                <button
                  onClick={handleRemove}
                  className="absolute top-2 right-2 bg-red-500 text-white rounded-full w-8 h-8 flex items-center justify-center hover:bg-red-600"
                  aria-label="Remove image"
                >
                  ×
                </button>
              )}
            </div>
          )}
          
          {uploadState === 'success' && (
            <div className="bg-green-50 border border-green-200 text-green-800 rounded-lg p-3 text-sm">
              ✓ Successfully processed! Items added to your closet.
            </div>
          )}
          
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-800 rounded-lg p-3 text-sm">
              {error}
            </div>
          )}
          
          <div className="flex gap-2">
            {uploadState === 'idle' && (
              <>
                <Button
                  onClick={() => fileInputRef.current?.click()}
                  variant="outline"
                  className="flex-1"
                >
                  Replace
                </Button>
                <Button
                  onClick={handleSubmit}
                  disabled={!canSubmit}
                  className="flex-1"
                >
                  Process
                </Button>
              </>
            )}
            {isProcessing && (
              <div className="flex-1 text-center py-2">
                <div className="inline-flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-gray-300 border-t-black rounded-full animate-spin" />
                  <span className="text-sm text-gray-600">
                    {uploadState === 'uploading' ? 'Uploading...' : 'Processing...'}
                  </span>
                </div>
              </div>
            )}
            {uploadState === 'error' && (
              <Button
                onClick={handleSubmit}
                className="flex-1"
              >
                Try Again
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

