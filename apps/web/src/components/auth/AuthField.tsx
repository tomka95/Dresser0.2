"use client";

import React from "react";
import { Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { M } from "@/components/ds";

interface AuthFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  startIcon?: React.ReactNode;
  isPassword?: boolean;
  errorMessage?: string;
}

/**
 * Auth input row — restyled to the §1 redesign field: a translucent glass box
 * (16px radius) that focuses mint (border + soft ring) and errors red, with a
 * leading icon that tints to match the state and an inline show/hide eye for
 * passwords. Keeps the native input API (event-based onChange, isPassword,
 * errorMessage) so every page's handlers work unchanged.
 */
export const AuthField = React.forwardRef<HTMLInputElement, AuthFieldProps>(
  ({ className, startIcon, isPassword, errorMessage, onFocus, onBlur, ...props }, ref) => {
    const [showPassword, setShowPassword] = React.useState(false);
    const [focus, setFocus] = React.useState(false);
    const hasError = Boolean(errorMessage);

    const border = hasError
      ? "1px solid rgba(251,44,54,0.55)"
      : focus
        ? "1px solid rgba(75,226,214,0.55)"
        : "1px solid rgba(255,255,255,0.13)";
    const boxShadow = focus
      ? "0 0 0 3px rgba(75,226,214,0.14), inset 0 1px 0 rgba(255,255,255,0.07)"
      : hasError
        ? "0 0 0 3px rgba(251,44,54,0.10)"
        : "inset 0 1px 0 rgba(255,255,255,0.07)";
    const iconColor = hasError ? "#ff8087" : focus ? "var(--mint)" : M.faint;

    return (
      <div className="w-full">
        <div
          className="flex items-center gap-2.5"
          style={{
            minHeight: 49,
            padding: "0 17px",
            borderRadius: 16,
            background: "rgba(255,255,255,0.075)",
            border,
            boxShadow,
            transition: "all 200ms var(--ease-out)",
          }}
        >
          {startIcon && (
            <span className="flex shrink-0" style={{ color: iconColor }} aria-hidden>
              {startIcon}
            </span>
          )}
          <input
            ref={ref}
            type={isPassword && !showPassword ? "password" : props.type ?? "text"}
            aria-invalid={hasError || undefined}
            className={cn(
              "w-full flex-1 border-none bg-transparent text-white outline-none placeholder:text-white/40",
              className
            )}
            style={{ fontSize: 15, fontFamily: "var(--font-sans)", lineHeight: 1.45, height: 47 }}
            onFocus={(e) => {
              setFocus(true);
              onFocus?.(e);
            }}
            onBlur={(e) => {
              setFocus(false);
              onBlur?.(e);
            }}
            {...props}
          />
          {isPassword && (
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="flex shrink-0 items-center transition-colors hover:text-white"
              style={{ color: M.ghost }}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          )}
        </div>
        {errorMessage && (
          <p
            className="mt-[7px] flex items-center gap-1.5"
            style={{ color: "#ff9096", fontSize: 12 }}
          >
            {errorMessage}
          </p>
        )}
      </div>
    );
  }
);
AuthField.displayName = "AuthField";
