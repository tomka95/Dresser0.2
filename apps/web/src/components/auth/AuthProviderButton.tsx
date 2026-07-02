import React from "react";
import { GoogleIcon } from "@/components/icons/GoogleIcon";
import { AppleIcon } from "@/components/icons/AppleIcon";
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
 * A single OAuth provider button — design spec: transparent pill, hairline
 * white border, white label, 48px tall. Generic over provider id so the same
 * component renders Google today and Apple later (icon looked up by id).
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
        "flex h-12 w-full items-center justify-center gap-2.5 rounded-full bg-transparent",
        "text-[15px] font-semibold text-white transition-colors hover:bg-white/5",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      style={{ border: "1px solid var(--tr-20)", fontFamily: "var(--font-sans)" }}
      {...props}
    >
      {loading ? (
        <span
          className="inline-block h-4 w-4 rounded-full border-2 border-white"
          style={{ borderTopColor: "transparent", animation: "tailor-spin 0.7s linear infinite" }}
        />
      ) : Icon ? (
        <Icon className="h-[18px] w-[18px]" />
      ) : null}
      {label}
    </button>
  );
}
