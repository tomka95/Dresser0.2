/**
 * Basic test for OutfitImageUpload component state transitions.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { OutfitImageUpload } from '../OutfitImageUpload';
import { uploadOutfitImage } from '@/lib/api/outfit';
import { useClosetStore } from '@/stores/useClosetStore';

// Mock dependencies
jest.mock('@/lib/api/outfit');
jest.mock('@/stores/useClosetStore');
jest.mock('@/lib/auth/storage', () => ({
  getAccessToken: () => 'mock-token',
}));

const mockUploadOutfitImage = uploadOutfitImage as jest.MockedFunction<typeof uploadOutfitImage>;
const mockFetchItems = jest.fn();

describe('OutfitImageUpload', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useClosetStore as unknown as jest.Mock).mockReturnValue({
      fetchItems: mockFetchItems,
    });
  });

  it('renders upload area when no file is selected', () => {
    render(<OutfitImageUpload />);
    expect(screen.getByText(/Drag & drop an image here/i)).toBeInTheDocument();
  });

  it('validates file type and shows error for invalid files', async () => {
    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      const invalidFile = new File(['content'], 'test.txt', { type: 'text/plain' });
      Object.defineProperty(fileInput, 'files', {
        value: [invalidFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText(/valid image file/i)).toBeInTheDocument();
      });
    }
  });

  it('validates file size and shows error for files >10MB', async () => {
    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      // Create a file larger than 10MB
      const largeFile = new File([new ArrayBuffer(11 * 1024 * 1024)], 'large.jpg', { type: 'image/jpeg' });
      Object.defineProperty(fileInput, 'files', {
        value: [largeFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText(/File size must be less than/i)).toBeInTheDocument();
      });
    }
  });

  it('shows preview and process button when valid file is selected', async () => {
    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      const validFile = new File(['content'], 'test.jpg', { type: 'image/jpeg' });
      Object.defineProperty(fileInput, 'files', {
        value: [validFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText('Process')).toBeInTheDocument();
      });
    }
  });

  it('calls upload API and refreshes closet exactly once on successful upload', async () => {
    mockUploadOutfitImage.mockResolvedValue({
      user_id: '123',
      items_created: [{ id: '1', name: 'Test Item' }],
    });

    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      const validFile = new File(['content'], 'test.jpg', { type: 'image/jpeg' });
      Object.defineProperty(fileInput, 'files', {
        value: [validFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText('Process')).toBeInTheDocument();
      });
      
      fireEvent.click(screen.getByText('Process'));
      
      await waitFor(() => {
        expect(mockUploadOutfitImage).toHaveBeenCalledTimes(1);
        expect(mockUploadOutfitImage).toHaveBeenCalledWith(validFile);
      });
      
      // Wait for fetchItems to be called
      await waitFor(() => {
        expect(mockFetchItems).toHaveBeenCalledTimes(1);
      });
    }
  });

  it('prevents double submit while processing', async () => {
    // Create a promise that we can control
    let resolveUpload: (value: any) => void;
    const uploadPromise = new Promise((resolve) => {
      resolveUpload = resolve;
    });
    
    mockUploadOutfitImage.mockReturnValue(uploadPromise as any);

    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      const validFile = new File(['content'], 'test.jpg', { type: 'image/jpeg' });
      Object.defineProperty(fileInput, 'files', {
        value: [validFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText('Process')).toBeInTheDocument();
      });
      
      // Click Process button twice rapidly
      const processButton = screen.getByText('Process');
      fireEvent.click(processButton);
      fireEvent.click(processButton);
      
      // Should only be called once
      await waitFor(() => {
        expect(mockUploadOutfitImage).toHaveBeenCalledTimes(1);
      });
      
      // Resolve the promise
      resolveUpload!({
        user_id: '123',
        items_created: [],
      });
    }
  });

  it('shows error message on upload failure', async () => {
    mockUploadOutfitImage.mockRejectedValue(new Error('Upload failed'));

    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      const validFile = new File(['content'], 'test.jpg', { type: 'image/jpeg' });
      Object.defineProperty(fileInput, 'files', {
        value: [validFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText('Process')).toBeInTheDocument();
      });
      
      fireEvent.click(screen.getByText('Process'));
      
      await waitFor(() => {
        expect(screen.getByText(/Upload failed/i)).toBeInTheDocument();
      });
    }
  });

  it('shows auth error message on 401 response', async () => {
    const authError = new Error('Session expired, please log in again');
    mockUploadOutfitImage.mockRejectedValue(authError);

    render(<OutfitImageUpload />);
    const fileInput = document.querySelector('input[type="file"]');
    
    if (fileInput) {
      const validFile = new File(['content'], 'test.jpg', { type: 'image/jpeg' });
      Object.defineProperty(fileInput, 'files', {
        value: [validFile],
        writable: false,
      });
      
      fireEvent.change(fileInput);
      
      await waitFor(() => {
        expect(screen.getByText('Process')).toBeInTheDocument();
      });
      
      fireEvent.click(screen.getByText('Process'));
      
      await waitFor(() => {
        expect(screen.getByText(/Session expired, please log in again/i)).toBeInTheDocument();
      });
    }
  });
});

