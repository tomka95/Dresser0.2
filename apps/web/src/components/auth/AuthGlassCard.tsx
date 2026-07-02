import { cn } from "@/lib/utils";

interface AuthGlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

/** Dark glass auth card — 22px radius, rgba(0,0,0,0.30) fill, 8px blur, hairline border. */
export function AuthGlassCard({ children, className, style, ...props }: AuthGlassCardProps) {
  return (
    <div
      className={cn("w-full rounded-[22px] p-6", className)}
      style={{
        background: "rgba(0,0,0,0.30)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        border: "1px solid var(--tr-10)",
        boxShadow: "var(--shadow-lg)",
        ...style,
      }}
      {...props}
    >
      {children}
    </div>
  );
}
