import { useEffect, useState } from 'react';
import { getCurrentUser } from '@/lib/api/auth';
import { getSessionUser } from '@/lib/auth';

export function HomeHeader() {
  const [userName, setUserName] = useState("there"); // neutral default

  useEffect(() => {
    async function fetchUserDisplayName() {
      try {
        const user = await getCurrentUser();
        const name = user.display_name || user.full_name?.split(' ')[0] || "there";
        setUserName(name);
      } catch (error) {
        // A backend failure is NOT an auth failure — fall back to the Supabase
        // session user (never redirect/sign out here; the route guard owns that).
        console.error('Failed to fetch user display name from backend:', error);
        try {
          const sessionUser = await getSessionUser();
          const meta = (sessionUser?.user_metadata ?? {}) as { full_name?: string };
          setUserName(
            meta.full_name?.split(' ')[0] ||
              sessionUser?.email?.split('@')[0] ||
              "there"
          );
        } catch {
          setUserName("there");
        }
      }
    }

    fetchUserDisplayName();
  }, []);

  return (
    <div className="mb-6 pt-4">
      <h1 className="text-4xl font-bold text-white mb-2">
        Hey, {userName}!
      </h1>
      <p className="text-white/80 text-lg font-light">
        Wants to find your outfit for today?
      </p>
    </div>
  );
}
