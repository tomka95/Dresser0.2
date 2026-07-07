import React from "react";
import { GoogleIcon } from "@/components/icons/GoogleIcon";
import { AppleIcon } from "@/components/icons/AppleIcon";
import { PendingDots } from "@/components/ds";
import { cn } from "@/lib/utils";
import type { AuthProviderId } from "@/config/authProviders";

const ICONS: Record<AuthProviderId, (props: { className?: string }) => React.ReactElement> = {
  google: GoogleIcon,
  apple: AppleIcon,
};

interface AuthProviderButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  providerId: AuthProviderId;
  label: string;
  loading?: boolean;
}

/**
 * A single OAuth provider button — §1 redesign: translucent white pill (47px),
 * hairline border, white label + brand glyph. Generic over provider id so the
 * same component renders Google today and Apple later (icon looked up by id).
 * `loading` swaps the label for brand dots while the OAuth redirect is in flight.
 */
export function AuthProviderButton({
  providerId,
  label,
  className,
  loading,
  disabled,
  ...props
}: AuthProviderButtonProps) {
  const Icon = ICONS[providerId];
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={cn(
        "flex w-full items-center justify-center gap-2.5",
        "font-semibold text-white transition-colors hover:bg-white/[0.11]",
        "disabled:cursor-not-allowed disabled:opacity-60",
        className
      )}
      style={{
        height: 47,
        borderRadius: 999,
        fontSize: 14.5,
        background: "rgba(255,255,255,0.07)",
        border: "1px solid rgba(255,255,255,0.15)",
        fontFamily: "var(--font-sans)",
      }}
      {...props}
    >
      {loading ? (
        <PendingDots />
      ) : (
        <>
          {Icon ? <Icon className="h-[17px] w-[17px]" /> : null}
          {label}
        </>
      )}
    </button>
  );
}
