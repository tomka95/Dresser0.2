"use client";

/**
 * ConnectGmailModal — the Gmail-connect consent dialog, on the unified §0
 * DialogFrame surface (deep-glass, centered medallion → title → copy → action
 * stack). Four designed states, unchanged in behaviour:
 *   disconnected (CTA) · connecting (spinner) · connected (success → review) · error (retry)
 *   · denied (permission declined — a calm, non-error off-ramp).
 * Connection state itself is REAL (driven by /gmail/oauth/status via the parent);
 * this component renders whichever state it's told. Props/callbacks are preserved.
 *
 * `denied` is deliberately distinct from `error`: `error` means the OAuth window
 * closed/broke and retry is the answer; `denied` means the user consciously said
 * no to inbox access — so it's amber (caution, not failure) and offers an
 * add-by-photo off-ramp plus a way to revisit permissions, never a bare "Try again".
 */

import React from "react";
import { CircleAlert, Shield } from "lucide-react";
import { Btn, DialogFrame, GmailGlyph, Spark, Thinking, type DialogTone } from "@/components/ds";
import { GoogleIcon } from "@/components/icons/GoogleIcon";

export type GmailModalState = "disconnected" | "connecting" | "connected" | "error" | "denied";

interface ConnectGmailModalProps {
  open: boolean;
  state: GmailModalState;
  /** Pending review count shown in the connected state (omit → generic copy). */
  reviewCount?: number;
  onClose: () => void;
  onConnect: () => void;
  onReview: () => void;
  /**
   * Optional handler for the `denied` state's primary off-ramp ("Add by photo
   * instead"). Falls back to onClose so existing consumers keep compiling.
   */
  onAddByPhoto?: () => void;
  /**
   * Optional handler for the `denied` state's "Review permissions" action.
   * Falls back to onConnect (re-open the Google consent) if not provided.
   */
  onReviewPermissions?: () => void;
}

export function ConnectGmailModal({
  open,
  state,
  reviewCount,
  onClose,
  onConnect,
  onReview,
  onAddByPhoto,
  onReviewPermissions,
}: ConnectGmailModalProps) {
  // The dialog can't be dismissed by outside-click / escape while connecting.
  const onOpenChange = (isOpen: boolean) => {
    if (!isOpen && state !== "connecting") onClose();
  };

  let icon: React.ReactNode;
  let iconTone: DialogTone;
  let title: string;
  let sub: string;
  let actions: React.ReactNode;

  const hasCount = typeof reviewCount === "number" && reviewCount > 0;

  switch (state) {
    case "connecting":
      icon = <Thinking size={30} />;
      iconTone = "mint";
      title = "Linking your inbox…";
      sub = "Approve read-only access in the Google window. We never see your password.";
      actions = (
        <Btn variant="ghost" fullWidth size="md" onClick={onClose}>
          Cancel
        </Btn>
      );
      break;
    case "connected":
      icon = <Spark size={26} />;
      iconTone = "mint";
      title = "Gmail connected";
      sub = hasCount
        ? `We found ${reviewCount} clothing receipt${reviewCount === 1 ? "" : "s"} to review.`
        : "Scan your inbox to find clothing purchases, then review what we detect.";
      actions = (
        <>
          <Btn variant="mint" fullWidth size="md" onClick={onReview}>
            {hasCount ? `Review ${reviewCount} item${reviewCount === 1 ? "" : "s"}` : "Review items"}
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={onClose}>
            Later
          </Btn>
        </>
      );
      break;
    case "error":
      icon = <CircleAlert size={24} />;
      iconTone = "danger";
      title = "Connection didn't stick";
      sub = "Google closed the window before finishing. Your inbox stays untouched.";
      actions = (
        <>
          <Btn variant="primary" fullWidth size="md" onClick={onConnect}>
            Try again
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={onClose}>
            Not now
          </Btn>
        </>
      );
      break;
    case "denied":
      icon = <Shield size={24} />;
      iconTone = "amber";
      title = "Permission declined";
      sub =
        "You said no to inbox access — fair. You can still add clothes by photo, or grant read-only receipts later in Settings.";
      actions = (
        <>
          <Btn variant="glass" fullWidth size="md" onClick={onAddByPhoto ?? onClose}>
            Add by photo instead
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={onReviewPermissions ?? onConnect}>
            Review permissions
          </Btn>
        </>
      );
      break;
    case "disconnected":
    default:
      icon = <GmailGlyph size={24} />;
      iconTone = "mint";
      title = "Connect Gmail";
      sub =
        "Tailor reads order receipts — only receipts — and hangs what you bought in your closet. Read-only, revoke anytime.";
      actions = (
        <>
          <Btn variant="primary" fullWidth size="md" icon={<GoogleIcon className="h-[17px] w-[17px]" />} onClick={onConnect}>
            Continue with Google
          </Btn>
          <Btn variant="ghost" fullWidth size="md" onClick={onClose}>
            Not now
          </Btn>
        </>
      );
      break;
  }

  return (
    <DialogFrame open={open} onOpenChange={onOpenChange} icon={icon} iconTone={iconTone} title={title} sub={sub}>
      <div className="mt-[18px] flex flex-col gap-2">{actions}</div>
    </DialogFrame>
  );
}
