interface AuthHeaderProps {
  title: string;
  subtitle: string;
}

export function AuthHeader({ title, subtitle }: AuthHeaderProps) {
  return (
    <div className="flex flex-col items-center justify-center text-center space-y-2 mb-8">
      <h1 className="text-2xl font-semibold text-white">{title}</h1>
      <p className="text-sm text-white/70">{subtitle}</p>
    </div>
  );
}
