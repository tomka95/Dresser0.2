'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { useClosetStore } from '@/stores/useClosetStore';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ItemDetailsPageProps {
  params: {
    id: string;
  };
}

export default function ItemDetailsPage({ params }: ItemDetailsPageProps) {
  const router = useRouter();
  const { id } = params;
  
  const fetchItem = useClosetStore((state) => state.fetchItem);
  const updateItem = useClosetStore((state) => state.updateItem);
  const isItemLoading = useClosetStore((state) => state.isItemLoading[id]);
  const error = useClosetStore((state) => state.error);
  
  // Local form state
  const [name, setName] = useState('');
  const [itemImageUrl, setItemImageUrl] = useState<string | undefined>(undefined);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
  
  // Initial data load
  useEffect(() => {
    fetchItem(id).then((item) => {
      setName(item.name);
      setItemImageUrl(item.imageUrl);
    }).catch(() => {
      // Error handled by store, component will show error view
    });
  }, [id, fetchItem]);

  // Handle saving changes
  const handleSave = async () => {
    setIsSaving(true);
    setSaveMessage(null);
    
    try {
      await updateItem(id, {
        name: name.trim(),
      });
      
      setSaveMessage({ type: 'success', text: 'Changes saved successfully' });
      
      // Hide success message after 3 seconds
      setTimeout(() => {
        setSaveMessage(null);
      }, 3000);
    } catch (err) {
      setSaveMessage({ 
        type: 'error', 
        text: err instanceof Error ? err.message : 'Failed to save changes' 
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (isItemLoading) {
    return (
      <div className="container mx-auto px-4 py-8 flex items-center justify-center min-h-[50vh]">
        <div className="text-gray-500">Loading item details...</div>
      </div>
    );
  }

  // If fetching failed (and we're not loading), show error
  if (!isItemLoading && error && !name) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Link 
          href="/closet" 
          className="inline-flex items-center text-gray-600 hover:text-black mb-6"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Closet
        </Link>
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <p className="text-red-600 mb-4">{error}</p>
          <Button onClick={() => router.push('/closet')}>Return to Closet</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <Link 
          href="/closet" 
          className="inline-flex items-center text-gray-600 hover:text-black"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to Closet
        </Link>
      </div>

      <div className="space-y-8">
        {/* Image Section */}
        <div className="aspect-square w-full bg-gray-100 rounded-lg overflow-hidden flex items-center justify-center relative">
          {itemImageUrl ? (
            <img 
              src={itemImageUrl} 
              alt={name} 
              className="w-full h-full object-contain"
            />
          ) : (
            <div className="text-gray-400">No image available</div>
          )}
        </div>

        {/* Name Edit Section */}
        <div className="space-y-2">
          <label htmlFor="name" className="block text-sm font-medium text-gray-700">
            Item Name
          </label>
          <input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full p-2 border rounded-md text-lg font-medium focus:ring-2 focus:ring-black focus:border-transparent outline-none"
            placeholder="Item name"
          />
        </div>

        {/* Save & Feedback Section */}
        <div className="pt-4 border-t sticky bottom-0 bg-white pb-4">
          <div className="flex items-center justify-between">
            <div className="flex-1 mr-4">
              {saveMessage && (
                <p className={cn(
                  "text-sm font-medium",
                  saveMessage.type === 'success' ? "text-green-600" : "text-red-600"
                )}>
                  {saveMessage.text}
                </p>
              )}
            </div>
            <Button 
              onClick={handleSave} 
              disabled={isSaving || !name.trim()}
              className="min-w-[100px]"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

