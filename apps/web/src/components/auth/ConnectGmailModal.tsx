'use client';

import React from 'react';
import { Button } from '@/components/ui/button';

export type ConnectGmailStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

interface ConnectGmailModalProps {
  open: boolean;
  onClose: () => void;
  onConnect: () => void;
  onMaybeLater?: () => void;
  status?: ConnectGmailStatus;
  detectedCount?: number;
  onReview?: () => void;
  onRetry?: () => void;
}

/** Gmail glyph (envelope). */
function GmailGlyph({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path
        d="M2 6.5A1.5 1.5 0 0 1 3.5 5h17A1.5 1.5 0 0 1 22 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 17.5z"
        fill="#fff"
      />
      <path d="M3 6.5l9 6 9-6" stroke="#ea4335" strokeWidth="1.8" fill="none" />
      <path d="M22 6.7V17.5a1.5 1.5 0 0 1-1.5 1.5H18V9.2l4-2.5z" fill="#34a853" />
      <path d="M2 6.7V17.5A1.5 1.5 0 0 0 3.5 19H6V9.2L2 6.7z" fill="#4285f4" />
    </svg>
  );
}

const chipBase: React.CSSProperties = {
  width: 58,
  height: 58,
  borderRadius: 18,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  marginBottom: 18,
};

function Title({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="m-0 mb-2"
      style={{ color: 'var(--text-strong)', fontSize: 21, fontWeight: 700, letterSpacing: '-0.2px' }}
    >
      {children}
    </h2>
  );
}

function ModalBody({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 mb-6" style={{ color: 'var(--text-muted)', fontSize: 14.5, lineHeight: 1.5 }}>
      {children}
    </p>
  );
}

/**
 * Presentational Gmail-connect dialog. No API calls happen inside — the parent
 * drives `status` and wires the action callbacks.
 */
export function ConnectGmailModal({
  open,
  onClose,
  onConnect,
  onMaybeLater,
  status = 'disconnected',
  detectedCount = 0,
  onReview,
  onRetry,
}: ConnectGmailModalProps) {
  if (!open) return null;

  let body: React.ReactNode;

  if (status === 'connecting') {
    body = (
      <>
        <div
          style={{
            ...chipBase,
            borderRadius: '50%',
            border: '4px solid var(--surface-sunken)',
            borderTop: '4px solid var(--brand-teal)',
            animation: 'tailor-spin 0.9s linear infinite',
          }}
        />
        <Title>Connecting…</Title>
        <ModalBody>Finishing sign-in with Google. This only takes a moment.</ModalBody>
        <Button variant="outline" className="w-full" onClick={onClose}>
          Cancel
        </Button>
      </>
    );
  } else if (status === 'connected') {
    body = (
      <>
        <div style={{ ...chipBase, borderRadius: '50%', background: 'rgba(10,207,131,0.15)', color: 'var(--success)' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
            <path
              d="M5 13l4 4L19 7"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <Title>Gmail connected</Title>
        <ModalBody>
          We found {detectedCount} receipts. Review the items we detected and add them to your closet.
        </ModalBody>
        <Button variant="default" className="w-full mb-2" onClick={onReview}>
          Review {detectedCount} items
        </Button>
        <button
          type="button"
          onClick={onClose}
          className="w-full text-center"
          style={{ color: 'var(--text-muted)', fontSize: 15, fontWeight: 500, height: 44 }}
        >
          Done
        </button>
      </>
    );
  } else if (status === 'error') {
    body = (
      <>
        <div
          style={{
            ...chipBase,
            borderRadius: '50%',
            background: 'rgba(251,44,54,0.12)',
            color: 'var(--danger)',
            fontSize: 30,
            fontWeight: 700,
          }}
        >
          !
        </div>
        <Title>Couldn&rsquo;t connect</Title>
        <ModalBody>
          Google sign-in was cancelled or timed out. Your inbox wasn&rsquo;t accessed. Want to try again?
        </ModalBody>
        <Button variant="default" className="w-full mb-2" onClick={onRetry ?? onConnect}>
          Try again
        </Button>
        <button
          type="button"
          onClick={onClose}
          className="w-full text-center"
          style={{ color: 'var(--text-muted)', fontSize: 15, fontWeight: 500, height: 44 }}
        >
          Maybe later
        </button>
      </>
    );
  } else {
    // disconnected (default)
    body = (
      <>
        <div style={{ ...chipBase, background: 'var(--surface-sunken)' }}>
          <GmailGlyph size={26} />
        </div>
        <Title>Connect Gmail</Title>
        <ModalBody>
          Tailor scans your inbox for clothing receipts and adds items automatically. We only read order
          emails — never send.
        </ModalBody>
        <Button variant="default" className="w-full mb-2" onClick={onConnect}>
          Connect Gmail
        </Button>
        <button
          type="button"
          onClick={onMaybeLater ?? onClose}
          className="w-full text-center"
          style={{ color: 'var(--text-muted)', fontSize: 15, fontWeight: 500, height: 44 }}
        >
          Maybe later
        </button>
      </>
    );
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center px-6"
      style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className="w-full"
        style={{
          maxWidth: 360,
          background: 'var(--surface-card)',
          borderRadius: 24,
          padding: 26,
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        {body}
      </div>
    </div>
  );
}
