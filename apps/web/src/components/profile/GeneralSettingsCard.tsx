import React from 'react';
import { ChevronRight } from 'lucide-react';

interface GeneralSettingsCardProps {
  onLogout: () => void;
}

export function GeneralSettingsCard({ onLogout }: GeneralSettingsCardProps) {
  const menuItems = [
    { label: 'Edit Profile', onClick: () => console.log('Edit Profile') },
    { label: 'Notifications', onClick: () => console.log('Notifications') },
    { label: 'Terms of Use', onClick: () => console.log('Terms of Use') },
    { label: 'Privacy Policy', onClick: () => console.log('Privacy Policy') },
    { label: 'Report a Bug', onClick: () => console.log('Report a Bug') },
    { label: 'Logout', onClick: onLogout, isDestructive: false }, // Destructive usually red, but design shows white/standard
  ];

  return (
    <div className="w-full px-6 mb-12">
      <h2 className="text-xl font-semibold text-white mb-4 pl-1">General</h2>
      
      <div className="bg-black/10 backdrop-blur-md border border-white/10 rounded-[24px] p-6 w-full">
        <div className="flex flex-col">
          {menuItems.map((item, index) => (
            <button
              key={item.label}
              onClick={item.onClick}
              className={`
                flex items-center justify-between w-full py-4 
                text-[16px] text-white hover:opacity-80 transition-opacity
                ${index !== menuItems.length - 1 ? 'border-b border-white/10' : ''}
              `}
            >
              <span>{item.label}</span>
              {/* No icon shown in screenshot for list items, but usually arrows imply navigation. 
                  The screenshot implies text only or text + standard list behavior.
                  However, "Logout" usually doesn't have an arrow.
                  Let's leave it as text for now as per screenshot appearance which seems simple.
              */}
            </button>
          ))}
        </div>

        {/* Contact Us Button */}
        <button className="w-full h-[48px] bg-white/5 hover:bg-white/10 rounded-[12px] flex items-center justify-center gap-1 mt-6 transition-colors group">
          <span className="text-[15px] font-medium text-white">Contact us</span>
          <ChevronRight className="w-4 h-4 text-white/70 group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>
    </div>
  );
}
