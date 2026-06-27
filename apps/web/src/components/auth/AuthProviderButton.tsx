import React from "react";
import { Button } from "@/components/ui/button";
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
 * A single OAuth provider button. Generic over provider id so the same component
 * renders Google today and Apple later with no change (icon is looked up by id).
 */
export function AuthProviderButton({
  providerId,
  label,
  className,
  loading,
  ...props
}: AuthProviderButtonProps) {
  const Icon = ICONS[providerId];
  return (
    <Button
      type="button"
      variant="default"
      className={cn(
        "w-full h-[46px] rounded-full bg-primary text-white hover:bg-primary/90",
        className
      )}
      loading={loading}
      {...props}
    >
      {Icon ? <Icon className="mr-2 h-5 w-5" /> : null}
      {label}
    </Button>
  );
}
