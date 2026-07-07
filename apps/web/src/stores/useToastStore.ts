'use client';

import { create } from 'zustand';

export type ToastTone = 'success' | 'error' | 'info' | 'offline';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  sub?: string;
  action?: ToastAction;
  /** Auto-dismiss delay in ms. */
  duration: number;
}

export interface ToastInput {
  tone?: ToastTone;
  title: string;
  sub?: string;
  action?: ToastAction;
  /** Override auto-dismiss delay; defaults to 4000ms (8000ms with an action). */
  duration?: number;
}

interface ToastState {
  toasts: ToastItem[];
  /** Push a toast; returns its id (usable with dismiss). */
  toast: (t: ToastInput) => number;
  dismiss: (id: number) => void;
}

let nextId = 1;

/**
 * §0 · G4 — Toast store. Undo pattern:
 *   toast({ tone: 'success', title: 'Item removed', action: { label: 'Undo', onClick: restore } })
 */
export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  toast: (t) => {
    const id = nextId++;
    const duration = t.duration ?? (t.action ? 8000 : 4000);
    set((s) => ({
      toasts: [
        ...s.toasts,
        { id, tone: t.tone ?? 'info', title: t.title, sub: t.sub, action: t.action, duration },
      ],
    }));
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));
