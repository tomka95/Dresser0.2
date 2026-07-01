'use client';

import { Camera, Image, Mail, Sparkles, X } from 'lucide-react';
import { useState, useRef } from 'react';
import { Dialog, DialogContent, DialogTrigger, DialogClose } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { uploadOutfitImage } from '@/lib/api/outfit';
import { useClosetStore } from '@/stores/useClosetStore';

interface AddItemDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onGmailClick: () => void;
  onPhotoClick: () => void;
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export function AddItemDrawer({
  open,
  onOpenChange,
  onGmailClick,
  onPhotoClick
}: AddItemDrawerProps) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const fetchItems = useClosetStore((state) => state.fetchItems);

  const validateFile = (file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return 'Please select a valid image file (JPEG, PNG, or WebP)';
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File size must be less than ${MAX_FILE_SIZE / 1024 / 1024}MB`;
    }
    return null;
  };

  const handleFileSelect = async (file: File) => {
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setUploading(true);

    try {
      await uploadOutfitImage(file);
      // Refresh closet items
      await fetchItems();
      // Close drawer on success
      onOpenChange(false);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to upload image';
      setError(errorMessage);
    } finally {
      setUploading(false);
      // Clear input values
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      if (cameraInputRef.current) {
        cameraInputRef.current.value = '';
      }
    }
  };

  const handleUploadClick = () => {
    if (fileInputRef.current && !uploading) {
      fileInputRef.current.click();
    }
  };

  const handleCameraClick = () => {
    if (cameraInputRef.current && !uploading) {
      cameraInputRef.current.click();
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) {
      return;
    }
    handleFileSelect(files[0]);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent 
        className={cn(
          "fixed bottom-0 left-0 right-0 p-0 border-0 rounded-t-[30px] gap-0 max-w-[430px] mx-auto shadow-lg",
          "!translate-y-0 !top-auto",
          "data-[state=open]:slide-in-from-bottom data-[state=closed]:slide-out-to-bottom duration-300"
        )}
        style={{
          background: 'linear-gradient(180deg, rgb(10, 54, 51) 0%, rgb(10, 99, 102) 100%)',
        }}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <div className="flex flex-col px-[24px] pt-[32px] pb-[32px]">
          {/* Header */}
          <div className="flex items-center justify-between mb-[35px]">
            <h2 
              className="text-[36px] font-bold leading-[46px] text-white"
              style={{ fontFamily: 'Inter, sans-serif' }}
            >
              Add New Items
            </h2>
            <DialogClose 
              className="p-2 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-colors"
              aria-label="Close"
            >
              <X className="w-6 h-6" />
            </DialogClose>
          </div>

          {/* Hidden file inputs */}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            onChange={handleFileInputChange}
            disabled={uploading}
            className="hidden"
          />
          <input
            ref={cameraInputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            capture="environment"
            onChange={handleFileInputChange}
            disabled={uploading}
            className="hidden"
          />

          {/* Error message */}
          {error && (
            <div 
              className="mb-4 p-3 rounded-[10px] bg-white/10 backdrop-blur-md border border-white/20 text-white text-[14px] text-center"
              style={{ fontFamily: 'Inter, sans-serif' }}
            >
              {error}
            </div>
          )}

          {/* Uploading indicator */}
          {uploading && (
            <div 
              className="mb-4 p-3 rounded-[10px] bg-white/10 backdrop-blur-md border border-white/20 text-white text-[14px] text-center"
              style={{ fontFamily: 'Inter, sans-serif' }}
            >
              <div className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>Uploading and processing...</span>
              </div>
            </div>
          )}

          {/* Options Grid */}
          <div className="grid grid-cols-2 gap-4 mb-[35px]">
            {/* Camera Option */}
            <button
              onClick={handleCameraClick}
              disabled={uploading}
              className={cn(
                "flex flex-col items-center justify-center gap-3 bg-white/10 backdrop-blur-md hover:bg-white/20 active:scale-95 transition-all rounded-[10px] p-6 h-32 border border-white/20",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              style={{ fontFamily: 'Inter, sans-serif' }}
            >
              <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center">
                <Camera className="w-6 h-6 text-white" />
              </div>
              <span className="text-[14px] font-medium text-white">Take Photo</span>
            </button>

            {/* Gallery Option */}
            <button
              onClick={handleUploadClick}
              disabled={uploading}
              className={cn(
                "flex flex-col items-center justify-center gap-3 bg-white/10 backdrop-blur-md hover:bg-white/20 active:scale-95 transition-all rounded-[10px] p-6 h-32 border border-white/20",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
              style={{ fontFamily: 'Inter, sans-serif' }}
            >
              <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center">
                <Image className="w-6 h-6 text-white" />
              </div>
              <span className="text-[14px] font-medium text-white">Upload Photo</span>
            </button>
          </div>

          {/* Photo-detect Option — routes to /add-photo (Wave 1 multi-garment detect
              flow), mirroring the Gmail row's navigate-then-close pattern. */}
          <button
            onClick={() => {
              onPhotoClick();
              onOpenChange(false);
            }}
            disabled={uploading}
            className={cn(
              "flex items-center gap-4 bg-white/10 backdrop-blur-md hover:bg-white/20 active:scale-95 transition-all rounded-[10px] p-4 border border-white/20 mb-4",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            style={{ fontFamily: 'Inter, sans-serif' }}
          >
            <div className="w-10 h-10 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center shrink-0">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div className="flex flex-col items-start">
              <span className="text-[14px] font-medium text-white">Add from a photo</span>
              <span className="text-[12px] text-white/70">Detect everything you&rsquo;re wearing</span>
            </div>
          </button>

          {/* Gmail Option */}
          <button
            onClick={() => {
              onGmailClick();
              onOpenChange(false);
            }}
            disabled={uploading}
            className={cn(
              "flex items-center gap-4 bg-white/10 backdrop-blur-md hover:bg-white/20 active:scale-95 transition-all rounded-[10px] p-4 border border-white/20",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
            style={{ fontFamily: 'Inter, sans-serif' }}
          >
            <div className="w-10 h-10 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center shrink-0">
              <Mail className="w-5 h-5 text-white" />
            </div>
            <div className="flex flex-col items-start">
              <span className="text-[14px] font-medium text-white">Import from Gmail</span>
              <span className="text-[12px] text-white/70">Scan receipts for clothing items</span>
            </div>
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
