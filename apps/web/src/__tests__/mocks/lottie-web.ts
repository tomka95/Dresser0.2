/**
 * Test stub for lottie-web (aliased in vitest.config.mjs). jsdom has no real
 * rendering loop, and the package may not be installed yet in CI — LottieMark
 * only needs the loadAnimation surface.
 */
const lottie = {
  loadAnimation() {
    return {
      destroy() {},
      goToAndStop() {},
      play() {},
    };
  },
};

export default lottie;
