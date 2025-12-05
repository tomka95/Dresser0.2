"use client";

import { motion } from "framer-motion";
import { Shirt, Glasses, Watch, ShoppingBag, Tag } from "lucide-react";

export function FloatingClothes() {
  return (
    <div className="relative w-full h-[400px] flex items-center justify-center overflow-hidden">
      {/* Background Glow */}
      <div className="absolute inset-0 bg-gradient-to-b from-blue-500/10 to-purple-500/10 blur-3xl" />

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
         className="w-32 h-32 rounded-full bg-gradient-to-tr from-blue-500/30 to-purple-500/30 blur-2xl"
      />
    </div>
  );
}

