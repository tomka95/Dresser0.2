import Link from "next/link";

interface AuthFooterProps {
  text: string;
  linkText: string;
  href: string;
}

export function AuthFooter({ text, linkText, href }: AuthFooterProps) {
  return (
    <div className="mt-6 text-center text-sm text-white/70">
      {text}{" "}
      <Link href={href} className="text-white font-medium hover:underline">
        {linkText}
      </Link>
    </div>
  );
}
