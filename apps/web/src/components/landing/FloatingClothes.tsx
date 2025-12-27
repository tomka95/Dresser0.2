"use client";

import { motion } from "framer-motion";
import { Shirt, Glasses, Watch, ShoppingBag, Tag } from "lucide-react";

export function FloatingClothes() {
  return (
    <div className="absolute inset-0 w-full h-full overflow-hidden" style={{ backgroundColor: 'transparent' }}>
      {/* Background Glow - stretched to fill entire container from top to bottom, overlaying header */}
      <div className="absolute inset-0 blur-3xl" style={{ background: 'radial-gradient(ellipse 100% 150% at 50% 50%, rgba(8, 75, 77, 0.15) 0%, rgba(8, 75, 77, 0.08) 30%, rgba(8, 75, 77, 0.03) 60%, transparent 100%)' }} />
      
      {/* Container for icons - positioned in center area, maintaining original layout */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="relative w-full max-w-md h-[400px]">

      {/* Floating Icons */}
      <motion.div
        animate={{
          y: [-10, 10, -10],
          rotate: [0, 5, -5, 0],
        }}
        transition={{
          duration: 6,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="absolute top-10 left-10 text-blue-400 opacity-80"
      >
        <Shirt size={64} strokeWidth={1.5} />
      </motion.div>

      <motion.div
        animate={{
          y: [15, -15, 15],
          rotate: [0, -10, 10, 0],
        }}
        transition={{
          duration: 7,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 1,
        }}
        className="absolute top-20 right-12 text-purple-400 opacity-80"
      >
        <Glasses size={48} strokeWidth={1.5} />
      </motion.div>

      <motion.div
        animate={{
          y: [-20, 20, -20],
          scale: [1, 1.1, 1],
        }}
        transition={{
          duration: 8,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 2,
        }}
        className="absolute bottom-20 left-20 text-pink-400 opacity-60"
      >
        <Watch size={40} strokeWidth={1.5} />
      </motion.div>

      <motion.div
        animate={{
          y: [10, -10, 10],
          x: [-5, 5, -5],
        }}
        transition={{
          duration: 5,
          repeat: Infinity,
          ease: "easeInOut",
          delay: 0.5,
        }}
        className="absolute bottom-10 right-24 text-cyan-400 opacity-70"
      >
        <ShoppingBag size={56} strokeWidth={1.5} />
      </motion.div>
      
      {/* Central Abstract Element to anchor the visual */}
      <motion.div 
         animate={{ 
            scale: [1, 1.05, 1],
            opacity: [0.5, 0.8, 0.5]
         }}
         transition={{
            duration: 4,
            repeat: Infinity,
            ease: "easeInOut"
         }}
         className="w-32 h-32 rounded-full blur-2xl"
         style={{ background: 'radial-gradient(circle, rgba(8, 75, 77, 0.25) 0%, rgba(8, 75, 77, 0.1) 50%, transparent 100%)' }}
      />
        </div>
      </div>
    </div>
  );
}

