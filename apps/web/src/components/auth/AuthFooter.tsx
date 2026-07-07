import Link from "next/link";
import { M } from "@/components/ds";

interface AuthFooterProps {
  text: string;
  linkText: string;
  href: string;
}

/** Centered "New here? Create an account" line beneath the auth card. */
export function AuthFooter({ text, linkText, href }: AuthFooterProps) {
  return (
    <div
      className="mt-[18px] text-center"
      style={{ color: M.faint, fontSize: 13.5 }}
    >
      {text}{" "}
      <Link href={href} className="font-semibold text-white hover:underline">
        {linkText}
      </Link>
    </div>
  );
}
