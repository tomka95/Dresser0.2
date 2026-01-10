import { cn } from "@/lib/utils";

interface AuthGlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

export function AuthGlassCard({ children, className, ...props }: AuthGlassCardProps) {
  return (
    <div
      className={cn(
        "rounded-[22px] bg-[rgba(0,0,0,0.22)] backdrop-blur-sm p-6 w-full max-w-md border border-white/10",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
