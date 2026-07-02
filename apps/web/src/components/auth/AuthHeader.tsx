import { cn } from "@/lib/utils";

interface AuthHeaderProps {
  title: string;
  subtitle?: string;
  /** Design default is left-aligned; success/confirmation states center. */
  align?: "left" | "center";
}

export function AuthHeader({ title, subtitle, align = "left" }: AuthHeaderProps) {
  return (
    <div className={cn(align === "center" && "text-center")}>
      <h1 className="m-0 text-[24px] font-bold text-white">{title}</h1>
      {subtitle && <p className="mb-5 mt-1 text-sm text-white/60">{subtitle}</p>}
      {!subtitle && <div className="mb-5" />}
    </div>
  );
}
