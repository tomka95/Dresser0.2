'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { useClosetStore } from '@/stores/useClosetStore';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { Button } from '@/components/ui/button';
import { ItemImage } from '@/components/ui/ItemImage';
import { cn } from '@/lib/utils';

interface ItemDetailsPageProps {
  params: {
    id: string;
  };
}

export default function ItemDetailsPage({ params }: ItemDetailsPageProps) {
  const router = useRouter();
  const { id } = params;

  // Gate on the Supabase session (three-state: never redirects while loading).
  // Use the stable `status` boolean (not the `session` object) for effect deps so
  // a background token refresh — which yields a new session reference but keeps
  // status 'authenticated' — does not re-run the seed effect and clobber edits.
  const { status } = useRequireAuth();
  const isAuthed = status === 'authenticated';

  const fetchItem = useClosetStore((state) => state.fetchItem);
  const updateItem = useClosetStore((state) => state.updateItem);
  const isItemLoading = useClosetStore((state) => state.isItemLoading[id]);
  const error = useClosetStore((state) => state.error);
  
  // Local form state
  const [name, setName] = useState('');
  const [itemImageUrl, setItemImageUrl] = useState<string | undefined>(undefined);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
  
  // Initial data load — only once authenticated. Depends on the stable `isAuthed`
  // boolean so it seeds once and is not re-run by token refreshes.
  useEffect(() => {
    if (!isAuthed) return;
    fetchItem(id).then((item) => {
      setName(item.name);
      setItemImageUrl(item.imageUrl);
    }).catch(() => {
      // Error handled by store, component will show error view
    });
  }, [id, fetchItem, isAuthed]);

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

  // While the session is resolving (status 'loading') render nothing, and render
  // nothing while unauthenticated — the guard performs the redirect; we never
  // redirect here.
  if (!isAuthed) {
    return null;
  }

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
        {/* Image Section — shared, opaque-backed render path. */}
        <div className="aspect-square w-full rounded-lg overflow-hidden relative">
          <ItemImage src={itemImageUrl} alt={name} fit="contain" emptyLabel="No image available" />
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

