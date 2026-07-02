import { create } from 'zustand';

/**
 * usePhotoPickStore — in-memory File handoff between AddItemDrawer and /add-photo.
 *
 * File objects can't cross a navigation via URL/query params, so the drawer's
 * "Take photo"/"Upload photo" options stash the picked Files here and route to
 * /add-photo, which consumes them on mount (takeFiles) and jumps straight to
 * region detection. Nothing is persisted — the Files live only in memory and the
 * store is emptied as soon as they're taken.
 */

type PhotoPickState = {
  files: File[];
  setFiles: (files: File[]) => void;
  /** Returns the stashed files and clears the store (one-shot handoff). */
  takeFiles: () => File[];
};

export const usePhotoPickStore = create<PhotoPickState>((set, get) => ({
  files: [],
  setFiles(files) {
    set({ files });
  },
  takeFiles() {
    const { files } = get();
    if (files.length > 0) set({ files: [] });
    return files;
  },
}));
