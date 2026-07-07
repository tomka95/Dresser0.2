import { cn } from "@/lib/utils";
import { M } from "@/components/ds";

interface AuthHeaderProps {
  title: string;
  subtitle?: string;
  /** Design default is left-aligned; success/confirmation states center. */
  align?: "left" | "center";
}

/**
 * Auth card header — 25px white title with a faint one-line subtitle. Sits at
 * the top of the glass card (the white Tailor wordmark lives in the layout,
 * above the card, per the §1 redesign).
 */
export function AuthHeader({ title, subtitle, align = "left" }: AuthHeaderProps) {
  return (
    <div className={cn("mb-[22px]", align === "center" && "text-center")}>
      <h1
        className="m-0 text-white"
        style={{ fontSize: 25, fontWeight: 700, letterSpacing: "-0.6px" }}
      >
        {title}
      </h1>
      {subtitle && (
        <p
          className="m-0 mt-[5px]"
          style={{ color: M.faint, fontSize: 14, lineHeight: 1.5 }}
        >
          {subtitle}
        </p>
      )}
    </div>
  );
}
