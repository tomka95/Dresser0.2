"use client";

import React from "react";
import { enabledProviders, type AuthProviderId } from "@/config/authProviders";
import { AuthProviderButton } from "./AuthProviderButton";

interface AuthProviderButtonsProps {
  /** Called when a provider button is clicked. */
  onSelect: (id: AuthProviderId) => void;
  /** Disable all buttons (e.g. while another auth action is in flight). */
  disabled?: boolean;
  /** Id of the provider currently mid-redirect, to show a loading state. */
  pendingProvider?: AuthProviderId | null;
}

/**
 * Renders one button per ENABLED provider from config/authProviders.
 *
 * The list is fully config-driven: enabling Apple is a config/env flag flip
 * (NEXT_PUBLIC_APPLE_ENABLED=true) — this component then renders the Apple button
 * automatically, no structural change.
 */
export function AuthProviderButtons({
  onSelect,
  disabled,
  pendingProvider,
}: AuthProviderButtonsProps) {
  const providers = enabledProviders();
  if (providers.length === 0) return null;

  return (
    <div className="flex flex-col" style={{ gap: 9 }}>
      {providers.map((provider) => (
        <AuthProviderButton
          key={provider.id}
          providerId={provider.id}
          label={provider.label}
          disabled={disabled}
          loading={pendingProvider === provider.id}
          onClick={() => onSelect(provider.id)}
        />
      ))}
    </div>
  );
}
