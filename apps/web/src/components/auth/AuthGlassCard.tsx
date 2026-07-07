import { cn } from "@/lib/utils";
import { M } from "@/components/ds";

interface AuthGlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

/**
 * Auth glass card — the single card surface every auth screen sits on. Uses the
 * §0 frost material (M.glass) at a 30px radius, per the §1 redesign (design
 * ACard). All auth states — form, "check your email", "link sent" — compose it.
 */
export function AuthGlassCard({ children, className, style, ...props }: AuthGlassCardProps) {
  return (
    <div
      className={cn("mx-auto w-full max-w-[400px]", className)}
      style={{
        ...M.glass(30),
        padding: "28px 24px 26px",
        ...style,
      }}
      {...props}
    >
      {children}
    </div>
  );
}
