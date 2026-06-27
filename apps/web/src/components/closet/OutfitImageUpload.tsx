'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { uploadOutfitImage } from '@/lib/api/outfit';
import { useClosetStore } from '@/stores/useClosetStore';

type UploadState = 'idle' | 'uploading' | 'processing' | 'success' | 'error';

export function OutfitImageUpload() {
  const [uploadState, setUploadState] = useState<UploadState>('idle');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
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

  const clearInput = useCallback(() => {
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  const handleFileSelect = useCallback((file: File, allowReplace: boolean = true) => {
    const isProcessing = uploadState === 'uploading' || uploadState === 'processing';
    
    // Block file selection during processing
    if (isProcessing) {
      setWarning('Upload in progress. Please wait...');
      // Clear any selection attempt
      clearInput();
      return;
    }

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setWarning(null);
      setSelectedFile(null);
      setPreviewUrl(null);
      clearInput();
      return;
    }

    // If file already selected and we're in idle, replace it (single image only)
    if (selectedFile && allowReplace) {
      // Clean up previous preview URL
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    }

    setError(null);
    setWarning(null);
    setSelectedFile(file);
    
    // Create preview URL
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
  }, [uploadState, selectedFile, previewUrl, clearInput]);

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) {
      return;
    }

    // Single file only - take first file
    const file = files[0];
    
    // If multiple files were selected, show warning but still process first file
    if (files.length > 1) {
      setWarning('Only one image at a time. Using the first file.');
    }
    
    // handleFileSelect checks uploadState internally to determine if replacement is allowed
    handleFileSelect(file, true);
    
    // Clear input value after handling to allow re-selecting same file
    clearInput();
  };

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    const files = e.dataTransfer.files;
    if (files.length === 0) {
      return;
    }

    // Single file only - take first file
    const file = files[0];
    
    // If multiple files were dropped, show warning but still process first file
    if (files.length > 1) {
      setWarning('Only one image at a time. Using the first file.');
    }
    
    handleFileSelect(file, uploadState === 'idle');
  }, [handleFileSelect, uploadState]);

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleRemove = () => {
    // Prevent remove during processing
    if (uploadState === 'uploading' || uploadState === 'processing') {
      return;
    }

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    setSelectedFile(null);
    setPreviewUrl(null);
    setError(null);
    setWarning(null);
    clearInput();
  };

  const handleSubmit = async () => {
    if (!selectedFile) {
      setError('Please select an image file');
      return;
    }

    // Prevent double submit - early return check
    if (uploadState === 'uploading' || uploadState === 'processing') {
      return;
    }

    setUploadState('uploading');
    setError(null);
    setWarning(null);

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
        // Clean up preview URL
        if (previewUrl) {
          URL.revokeObjectURL(previewUrl);
        }
        setSelectedFile(null);
        setPreviewUrl(null);
        setError(null);
        setWarning(null);
        clearInput();
        setUploadState('idle');
      }, 3000);
    } catch (err) {
      setUploadState('error');
      const errorMessage = err instanceof Error ? err.message : 'Failed to upload and process image';
      setError(errorMessage);
      setWarning(null);
      
      // Log error in dev
      if (process.env.NODE_ENV === 'development') {
        console.error('Upload error:', err);
      }
    }
  };

  const isProcessing = uploadState === 'uploading' || uploadState === 'processing';
  const canSubmit = selectedFile && uploadState === 'idle' && !error;

  // Clear warning after 5 seconds
  useEffect(() => {
    if (warning) {
      const timer = setTimeout(() => {
        setWarning(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [warning]);

  return (
    <div className="border rounded-lg p-6 bg-white">
      <h2 className="text-xl font-semibold mb-4">Upload Outfit Photo</h2>

      {/* Errors/warnings render in both the empty and file-selected states so
          validation feedback (invalid type/size) is visible immediately, before
          a file is accepted. */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 rounded-lg p-3 text-sm mb-4">
          {error}
        </div>
      )}

      {warning && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg p-3 text-sm mb-4">
          {warning}
        </div>
      )}

      {!selectedFile ? (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            isProcessing
              ? 'border-gray-200 cursor-not-allowed bg-gray-50'
              : 'border-gray-300 cursor-pointer hover:border-gray-400'
          }`}
          onClick={() => {
            if (!isProcessing) {
              fileInputRef.current?.click();
            }
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            onChange={handleFileInputChange}
            disabled={isProcessing}
            className="hidden"
          />
          <div className="space-y-2">
            <p className={`${isProcessing ? 'text-gray-400' : 'text-gray-600'}`}>
              {isProcessing ? 'Upload in progress...' : 'Drag & drop an image here, or click to select'}
            </p>
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
                  disabled={isProcessing}
                  className="absolute top-2 right-2 bg-red-500 text-white rounded-full w-8 h-8 flex items-center justify-center hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
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

          <div className="flex gap-2">
            {uploadState === 'idle' && (
              <>
                <Button
                  onClick={() => {
                    if (!isProcessing) {
                      fileInputRef.current?.click();
                    }
                  }}
                  variant="outline"
                  disabled={isProcessing}
                  className="flex-1"
                >
                  Replace
                </Button>
                <Button
                  onClick={handleSubmit}
                  disabled={!canSubmit || isProcessing}
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
                disabled={isProcessing}
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

