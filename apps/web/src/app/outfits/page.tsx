'use client';

// STATUS: outfits page backed by Zustand store + mock API abstraction

import { useEffect, useMemo } from 'react';

import { track } from '@/lib/analytics';
import { useClosetStore } from '@/stores/useClosetStore';
import { useOutfitsStore } from '@/stores/useOutfitsStore';

export default function OutfitsPage() {
  const outfits = useOutfitsStore((state) => state.outfits);
  const likedOutfits = useOutfitsStore((state) => state.likedOutfits);
  const isLoading = useOutfitsStore((state) => state.isLoading);
  const error = useOutfitsStore((state) => state.error);
  const fetchOutfits = useOutfitsStore((state) => state.fetchOutfits);
  const toggleLike = useOutfitsStore((state) => state.toggleLike);

  const closetItems = useClosetStore((state) => state.items);
  const closetLoading = useClosetStore((state) => state.isLoading);
  const fetchClosetItems = useClosetStore((state) => state.fetchItems);

  useEffect(() => {
    // Track page view when component mounts
    track('outfit_suggestions_viewed', {
      outfit_count: outfits.length,
      has_recommended_items: outfits.some(
        (o) => o.recommendedItems && o.recommendedItems.length > 0
      ),
    });
  }, []);

  useEffect(() => {
    if (outfits.length === 0 && !isLoading) {
      fetchOutfits({ limit: 3 });
    }
  }, [fetchOutfits, isLoading, outfits.length]);

  useEffect(() => {
    if (closetItems.length === 0 && !closetLoading) {
      fetchClosetItems();
    }
  }, [closetItems.length, closetLoading, fetchClosetItems]);

  // Track successful outfit suggestions load
  useEffect(() => {
    if (outfits.length > 0 && !isLoading) {
      track('outfit_suggestions_loaded', {
        count: outfits.length,
        has_recommended_items: outfits.some(
          (o) => o.recommendedItems && o.recommendedItems.length > 0
        ),
        total_recommended_items: outfits.reduce(
          (sum, o) => sum + (o.recommendedItems?.length || 0),
          0
        ),
      });
    }
  }, [outfits.length, isLoading]);

  const closetMap = useMemo(
    () => new Map(closetItems.map((item) => [item.id, item])),
    [closetItems]
  );

  async function handleRegenerate() {
    track('outfit_regenerate_clicked');
    try {
      await fetchOutfits({ limit: 3 });
    } catch (error) {
      track('outfit_regenerate_failed', {
        error: error instanceof Error ? error.message : 'Unknown error',
      });
    }
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Outfit Suggestions</h1>
        <button
          onClick={handleRegenerate}
          className="px-4 py-2 bg-black text-white rounded-lg hover:bg-gray-800 disabled:opacity-50"
          disabled={isLoading}
        >
          Generate Outfit
        </button>
      </div>
      {isLoading && (
        <div className="py-4 text-sm text-gray-500">
          Generating personalized looks…
        </div>
      )}
      {error && (
        <div className="py-4 text-sm text-red-600">
          {error}. Please try again.
        </div>
      )}
      {outfits.length === 0 && !isLoading ? (
        <div className="text-center py-16">
          <p className="text-gray-600 mb-4">No outfit suggestions yet</p>
          <p className="text-sm text-gray-500">
            Generate your first AI-powered outfit suggestion
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {outfits.map((outfit) => {
            const isLiked = likedOutfits.includes(outfit.id);

            return (
              <div
                key={outfit.id}
                className="border rounded-lg p-6 hover:shadow-lg transition-shadow"
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    {outfit.name && (
                      <h3 className="text-xl font-semibold mb-1">
                        {outfit.name}
                      </h3>
                    )}
                    {outfit.occasion && (
                      <p className="text-sm text-gray-600">
                        Occasion: {outfit.occasion}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => {
                      const wasLiked = isLiked;
                      toggleLike(outfit.id);
                      // Track like/unlike action
                      track(wasLiked ? 'outfit_unliked' : 'outfit_liked', {
                        outfit_id: outfit.id,
                        has_recommended_items:
                          (outfit.recommendedItems?.length || 0) > 0,
                        occasion: outfit.occasion,
                      });
                    }}
                    className="text-sm font-medium text-gray-600 hover:text-black"
                  >
                    {isLiked ? '★ Liked' : '☆ Like'}
                  </button>
                </div>
                <div className="space-y-2">
                  {outfit.items.map((itemId) => {
                    const item = closetMap.get(itemId);

                    return (
                      <div
                        key={itemId}
                        className="flex flex-col rounded border bg-gray-50 px-3 py-2 text-sm"
                      >
                        <span className="font-medium">
                          {item?.name ?? 'Closet item'}
                        </span>
                        <span className="text-xs text-gray-500 capitalize">
                          {item?.category ?? 'unknown category'}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {outfit.recommendedItems && outfit.recommendedItems.length > 0 && (
                  <div className="mt-4 border-t pt-4">
                    <p className="text-sm font-semibold mb-2">
                      Recommended additions
                    </p>
                    <ul className="space-y-2 text-sm text-gray-600">
                      {outfit.recommendedItems.map((item) => (
                        <li key={item.id}>
                          {item.name}
                          {item.reason && (
                            <span className="text-gray-500">
                              {' '}
                              – {item.reason}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}


