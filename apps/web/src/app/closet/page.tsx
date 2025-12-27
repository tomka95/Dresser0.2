'use client';

// STATUS: closet grid backed by Zustand store + mock API abstraction

import Link from 'next/link';
import { useEffect } from 'react';

import { track } from '@/lib/analytics';
import { useClosetStore } from '@/stores/useClosetStore';
import { OutfitImageUpload } from '@/components/closet/OutfitImageUpload';

export default function ClosetPage() {
  const items = useClosetStore((state) => state.items);
  const isLoading = useClosetStore((state) => state.isLoading);
  const error = useClosetStore((state) => state.error);
  const hasFetchedItems = useClosetStore((state) => state.hasFetchedItems);
  const fetchItems = useClosetStore((state) => state.fetchItems);
  const addItem = useClosetStore((state) => state.addItem);

  useEffect(() => {
    // Track page view when component mounts
    track('closet_viewed', { item_count: items.length });
  }, []);

  useEffect(() => {
    if (items.length === 0 && !isLoading && !error && !hasFetchedItems) {
      fetchItems();
    }
  }, [fetchItems, isLoading, items.length, error, hasFetchedItems]);

  // Track successful data load
  useEffect(() => {
    if (items.length > 0 && !isLoading) {
      track('closet_items_loaded', {
        count: items.length,
        categories: [...new Set(items.map((item) => item.category))],
      });
    }
  }, [items.length, isLoading]);

  async function handleAddSampleItem() {
    const newItem = {
      name: `Sample Item ${items.length + 1}`,
      category: 'other' as const,
      color: 'mixed tones',
      brand: 'Tailor Mock',
    };

    try {
      await addItem(newItem);
      // Track successful item addition
      track('closet_item_added', {
        category: newItem.category,
        has_image: false,
        has_brand: !!newItem.brand,
        total_items: items.length + 1,
      });
    } catch (error) {
      // Track error
      track('closet_item_add_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">My Closet</h1>
        <button
          onClick={handleAddSampleItem}
          className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 disabled:opacity-50"
          disabled={isLoading}
        >
          Add Sample Item
        </button>
      </div>
      
      <div className="mb-8">
        <OutfitImageUpload />
      </div>
      {isLoading && (
        <div className="py-4 text-sm text-gray-500">Loading closet…</div>
      )}
      {error && (
        <div className="py-4 text-sm text-red-600">
          {error}. Try refreshing the page.
        </div>
      )}
      {items.length === 0 && !isLoading ? (
        <div className="text-center py-16">
          <p className="text-gray-600 mb-4">Your closet is empty</p>
          <p className="text-sm text-gray-500">
            Start by adding your first clothing item
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {items.map((item) => (
            <Link
              key={item.id}
              href={`/closet/${item.id}`}
              className="block border rounded-lg p-4 hover:shadow-lg transition-shadow"
            >
              {item.imageUrl && (
                <img
                  src={item.imageUrl}
                  alt={item.name}
                  className="w-full aspect-square object-cover rounded mb-2"
                />
              )}
              <h3 className="font-semibold">{item.name}</h3>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}


