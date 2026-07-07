import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@tailor/contracts': path.resolve(__dirname, '../../packages/contracts/src'),
      // lottie-web is a browser-only runtime dep pulled in transitively via the
      // ds/ barrel (LottieMark). jsdom can't run it and CI may not have it
      // installed — alias to a lightweight stub so unrelated tests still collect.
      'lottie-web': path.resolve(__dirname, './src/__tests__/mocks/lottie-web.ts'),
    },
  },
});

