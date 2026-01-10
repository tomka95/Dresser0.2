import React from 'react';
import { User, Camera } from 'lucide-react';
import type { CurrentUserResponse } from '@/lib/api/auth';

interface ProfileHeaderProps {
  user: CurrentUserResponse | null;
}

export function ProfileHeader({ user }: ProfileHeaderProps) {
  // Fallback name logic: display_name -> full_name -> email local part
  const displayName = user?.display_name || user?.full_name || user?.email?.split('@')[0] || 'User';
  const email = user?.email || '';

  return (
    <div className="flex flex-col items-center pt-8 pb-8">
      {/* Avatar Container */}
      <div className="relative mb-4">
        <div className="w-[100px] h-[100px] rounded-full bg-[#147F74] flex items-center justify-center overflow-hidden border-4 border-[#147F74]">
          {user?.avatar_url ? (
            <img src={user.avatar_url} alt={displayName} className="w-full h-full object-cover" />
          ) : (
            <User className="w-12 h-12 text-white" />
          )}
        </div>
        
        {/* Edit Button Overlay */}
        <button 
          className="absolute bottom-0 right-0 w-[32px] h-[32px] bg-white rounded-full flex items-center justify-center shadow-md hover:bg-gray-100 transition-colors"
          aria-label="Edit profile picture"
        >
          <Camera className="w-5 h-5 text-[#147F74]" />
        </button>
      </div>

      {/* Name & Email */}
      <h1 className="text-3xl font-bold text-white mb-1">{displayName}</h1>
      <p className="text-base text-gray-400 font-normal">{email}</p>
    </div>
  );
}
