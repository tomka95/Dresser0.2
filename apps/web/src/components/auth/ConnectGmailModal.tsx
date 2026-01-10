"use client";

import React from "react";
import { X } from "lucide-react";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ConnectGmailModalProps {
  open: boolean;
  onClose: () => void;
  onConnect: () => void;
  onMaybeLater: () => void;
}

export function ConnectGmailModal({
  open,
  onClose,
  onConnect,
  onMaybeLater,
}: ConnectGmailModalProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent
        className={cn(
          "bg-white rounded-[20px] w-[375px] h-[590px] px-[24px] pt-[32px] pb-[32px]",
          "shadow-lg",
          "flex flex-col items-center",
          "relative overflow-hidden",
          "border-0 p-0 max-w-[375px]",
          "gap-0"
        )}
        onInteractOutside={(e) => e.preventDefault()}
      >
        {/* Close X Icon - top-right */}
        <button
          onClick={onClose}
          className="absolute top-[32px] right-[24px] text-[#143D3F] hover:opacity-70 transition-opacity"
          aria-label="Close"
        >
          <X size={24} className="w-[24px] h-[24px]" />
        </button>

        {/* Chain Link Icon - 68x68, positioned above "Connect your Gmail to" */}
        {/* ADJUST POSITION: Change mt-[20px] to move icon/header/logo group down (higher number) or up (lower number/negative) */}
        {/* ADJUST SPACING: Change mb-[0px] to adjust distance to heading (e.g., mb-[8px], mb-[12px], mb-[16px]) */}
        <img 
          src="/auth/linking 1.jpg" 
          alt="Link icon" 
          className="w-[68px] h-[68px] mt-[48px] mb-[0px] object-contain"
        />

        {/* Heading: "Connect your Gmail to" - DO NOT MODIFY margin-bottom here, use logo margin-top instead */}
        <h2
          className="text-[28px] font-semibold leading-[36px] text-[#143D3F] text-center"
          style={{ fontFamily: 'Inter, sans-serif' }}
        >
          Connect your Gmail to
        </h2>

        {/* Logo - 144x144, positioned below "Connect your Gmail to" */}
        {/* ADJUST SPACING: Change mt-[0px] to adjust distance from heading (e.g., mt-[4px], mt-[8px], mt-[12px]) */}
        <img 
          src="/auth/logo green.png" 
          alt="Tailor" 
          className="w-[144px] h-[144px] mt-[-36px] mb-[0px] object-contain"
        />

        {/* Descriptive text block - 3 paragraphs */}
        {/* Typography: text-ms/regular - Inter 16px, 400, 22px line-height */}
        {/* ADJUST SPACING: Change mb-[40px] to adjust distance from logo to text block (e.g., mb-[32px], mb-[48px]) */}
        <div className="flex flex-col items-center max-w-[300px] mb-[40px]">
          {/* ADJUST SPACING: Change mb-[24px] to adjust spacing between paragraphs (e.g., mb-[16px], mb-[20px], mb-[28px]) */}
          <p className="text-[16px] font-normal leading-[22px] text-[#4F4F4F] text-center mb-[24px]" style={{ fontFamily: 'Inter, sans-serif' }}>
            We can automatically add items to your closet from your email receipts.
          </p>
          <p className="text-[16px] font-normal leading-[22px] text-[#4F4F4F] text-center mb-[24px]" style={{ fontFamily: 'Inter, sans-serif' }}>
            Without Gmail sync, we won't be able to import your purchases.
          </p>
          <p className="text-[16px] font-normal leading-[22px] text-[#4F4F4F] text-center" style={{ fontFamily: 'Inter, sans-serif' }}>
            You stay in control – we only scan shopping receipts.
          </p>
        </div>

        {/* "Connect Gmail" Button */}
        {/* ADJUST SPACING: Change mb-[24px] to adjust distance from text block to button (e.g., mb-[16px], mb-[32px]) */}
        <Button
          onClick={onConnect}
          className={cn(
            "w-[315px] h-[48px] rounded-[12px] bg-[#143D3F] text-white",
            "text-[18px] font-semibold leading-[24px]",
            "hover:bg-[#143D3F]/90 mb-[24px]"
          )}
          style={{ fontFamily: 'Inter, sans-serif' }}
        >
          Connect Gmail
        </Button>

        {/* "Maybe later" Link */}
        {/* Typography: text-ms/regular but medium weight - Inter 16px, 500, 22px line-height */}
        {/* ADJUST SPACING: No margin-bottom currently - add mb-[Xpx] if you want spacing below */}
        <button
          onClick={onMaybeLater}
          className="text-[16px] font-medium leading-[22px] text-[#4F4F4F] underline hover:opacity-70 transition-opacity"
          style={{ fontFamily: 'Inter, sans-serif' }}
        >
          Maybe later
        </button>
      </DialogContent>
    </Dialog>
  );
}
