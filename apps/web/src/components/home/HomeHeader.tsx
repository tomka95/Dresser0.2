import { useEffect, useState } from 'react';
import { getCurrentUser } from '@/lib/api/auth';

export function HomeHeader() {
  const [userName, setUserName] = useState("Tom"); // Default fallback

  useEffect(() => {
    async function fetchUserDisplayName() {
      try {
        const user = await getCurrentUser();
        // Use display_name from database, fallback to full_name, then to "Tom"
        const name = user.display_name || user.full_name?.split(' ')[0] || "Tom";
        setUserName(name);
      } catch (error) {
        // If API call fails, keep default "Tom"
        console.error('Failed to fetch user display name:', error);
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
