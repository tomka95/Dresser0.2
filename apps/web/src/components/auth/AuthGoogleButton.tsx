import { Button } from "@/components/ui/button";
import { GoogleIcon } from "@/components/icons/GoogleIcon";
import { cn } from "@/lib/utils";

interface AuthGoogleButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean;
}

export function AuthGoogleButton({ className, loading, ...props }: AuthGoogleButtonProps) {
  return (
    <Button
      variant="default"
      className={cn(
        "w-full h-[46px] rounded-full bg-primary text-white hover:bg-primary/90",
        className
      )}
      loading={loading}
      {...props}
    >
      <GoogleIcon className="mr-2 h-5 w-5" />
      Continue with Google
    </Button>
  );
}
