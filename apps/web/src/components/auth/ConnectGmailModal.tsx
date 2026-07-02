"use client";

/**
 * ConnectGmailModal — centered white dialog, four designed states:
 *   disconnected (CTA) · connecting (spinner) · connected (success → review) · error (retry).
 * Connection state itself is REAL (driven by /gmail/oauth/status via the parent);
 * this component renders whichever state it's told.
 */

import React from "react";
import { Check } from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { DSButton, GmailGlyph } from "@/components/ds";
import { cn } from "@/lib/utils";

export type GmailModalState = "disconnected" | "connecting" | "connected" | "error";

interface ConnectGmailModalProps {
  open: boolean;
  state: GmailModalState;
  /** Pending review count shown in the connected state (omit → generic copy). */
  reviewCount?: number;
  onClose: () => void;
  onConnect: () => void;
  onReview: () => void;
}

export function ConnectGmailModal({
  open,
  state,
  reviewCount,
  onClose,
  onConnect,
  onReview,
}: ConnectGmailModalProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent
        className={cn(
          "w-[calc(100%-48px)] max-w-[382px] rounded-3xl border-0 bg-white p-[26px]",
          "shadow-[0_30px_60px_rgba(0,0,0,0.4)]"
        )}
        onInteractOutside={(e) => state === "connecting" && e.preventDefault()}
      >
        {state === "disconnected" && (
          <>
            <div
              className="mb-[18px] flex items-center justify-center rounded-2xl"
              style={{ width: 58, height: 58, background: "var(--surface-sunken)" }}
            >
              <GmailGlyph size={30} />
            </div>
            <h3 className="m-0 mb-2 text-[21px] font-bold" style={{ color: "var(--text-strong)" }}>
              Connect Gmail
            </h3>
            <p className="m-0 mb-[22px] text-[14.5px] leading-relaxed" style={{ color: "var(--text-body)" }}>
              Tailor scans your inbox for clothing receipts and adds items automatically. We only
              read order emails — never send.
            </p>
            <DSButton variant="primary" fullWidth pill leftIcon={<GmailGlyph size={18} />} onClick={onConnect}>
              Connect Gmail
            </DSButton>
            <button
              type="button"
              onClick={onClose}
              className="mt-3.5 w-full text-center text-sm font-medium hover:opacity-70"
              style={{ color: "var(--text-muted)" }}
            >
              Maybe later
            </button>
          </>
        )}

        {state === "connecting" && (
          <>
            <div
              className="mb-5 mt-1.5 rounded-full"
              style={{
                width: 58,
                height: 58,
                border: "4px solid var(--surface-sunken)",
                borderTopColor: "var(--brand-teal)",
                animation: "tailor-spin 0.9s linear infinite",
              }}
              aria-label="Connecting"
            />
            <h3 className="m-0 mb-2 text-[21px] font-bold" style={{ color: "var(--text-strong)" }}>
              Connecting…
            </h3>
            <p className="m-0 mb-[22px] text-[14.5px] leading-relaxed" style={{ color: "var(--text-body)" }}>
              Finishing sign-in with Google. This only takes a moment.
            </p>
            <DSButton variant="outline" fullWidth pill onClick={onClose}>
              Cancel
            </DSButton>
          </>
        )}

        {state === "connected" && (
          <>
            <div
              className="mb-[18px] flex items-center justify-center rounded-full"
              style={{ width: 58, height: 58, background: "rgba(10,207,131,0.15)", color: "var(--success)" }}
            >
              <Check size={30} strokeWidth={2.6} />
            </div>
            <h3 className="m-0 mb-2 text-[21px] font-bold" style={{ color: "var(--text-strong)" }}>
              Gmail connected
            </h3>
            <p className="m-0 mb-[22px] text-[14.5px] leading-relaxed" style={{ color: "var(--text-body)" }}>
              {reviewCount && reviewCount > 0 ? (
                <>
                  We found <strong style={{ color: "var(--text-strong)" }}>{reviewCount} item{reviewCount === 1 ? "" : "s"}</strong>.
                  Review what we detected and add them to your closet.
                </>
              ) : (
                <>Scan your inbox to find clothing purchases, then review what we detect.</>
              )}
            </p>
            <DSButton variant="primary" fullWidth pill onClick={onReview}>
              {reviewCount && reviewCount > 0 ? `Review ${reviewCount} item${reviewCount === 1 ? "" : "s"}` : "Review items"}
            </DSButton>
            <button
              type="button"
              onClick={onClose}
              className="mt-3.5 w-full text-center text-sm font-medium hover:opacity-70"
              style={{ color: "var(--text-muted)" }}
            >
              Done
            </button>
          </>
        )}

        {state === "error" && (
          <>
            <div
              className="mb-[18px] flex items-center justify-center rounded-full text-[30px] font-extrabold"
              style={{ width: 58, height: 58, background: "rgba(251,44,54,0.12)", color: "var(--danger)" }}
            >
              !
            </div>
            <h3 className="m-0 mb-2 text-[21px] font-bold" style={{ color: "var(--text-strong)" }}>
              Couldn&rsquo;t connect
            </h3>
            <p className="m-0 mb-[22px] text-[14.5px] leading-relaxed" style={{ color: "var(--text-body)" }}>
              Google sign-in was cancelled or timed out. Your inbox wasn&rsquo;t accessed. Want to
              try again?
            </p>
            <DSButton variant="primary" fullWidth pill onClick={onConnect}>
              Try again
            </DSButton>
            <button
              type="button"
              onClick={onClose}
              className="mt-3.5 w-full text-center text-sm font-medium hover:opacity-70"
              style={{ color: "var(--text-muted)" }}
            >
              Maybe later
            </button>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
