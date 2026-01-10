"use client";

import React from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Eye, EyeOff } from "lucide-react";

interface AuthFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  startIcon?: React.ReactNode;
  isPassword?: boolean;
  errorMessage?: string;
}

export const AuthField = React.forwardRef<HTMLInputElement, AuthFieldProps>(
  ({ className, startIcon, isPassword, errorMessage, ...props }, ref) => {
    const [showPassword, setShowPassword] = React.useState(false);

    const togglePassword = () => setShowPassword(!showPassword);

    return (
      <div className="w-full relative">
        <div className="relative">
          <Input
            ref={ref}
            type={isPassword && !showPassword ? "password" : "text"}
            startIcon={startIcon}
            error={!!errorMessage}
            className={cn(
              "h-[52px] rounded-full bg-white/10 border-white/20 text-white placeholder:text-white/50 focus-visible:ring-white/30 hover:border-white/30 transition-colors",
              errorMessage && "border-red-400 focus-visible:ring-red-400",
              className
            )}
            {...props}
          />
          {isPassword && (
            <button
              type="button"
              onClick={togglePassword}
              className="absolute right-[15px] top-1/2 -translate-y-1/2 text-white/50 hover:text-white transition-colors"
            >
              {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          )}
        </div>
        {errorMessage && (
          <p className="mt-1 text-xs text-red-400 pl-4">{errorMessage}</p>
        )}
      </div>
    );
  }
);
AuthField.displayName = "AuthField";
