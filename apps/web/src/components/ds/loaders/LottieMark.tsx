'use client';

import React, { useEffect, useRef } from 'react';

import markData from './tailor-mark.json';
import thinkingData from './tailor-thinking.json';

/* Minimal structural types so this file type-checks before `npm install`
   resolves lottie-web (the real package ships richer types). */
interface LottieAnimation {
  destroy(): void;
  goToAndStop(value: number, isFrame?: boolean): void;
  play(): void;
}
interface LottiePlayer {
  loadAnimation(params: {
    container: Element;
    renderer: 'svg';
    loop: boolean;
    autoplay: boolean;
    animationData: unknown;
  }): LottieAnimation;
}

let playerPromise: Promise<LottiePlayer | null> | null = null;
function loadPlayer(): Promise<LottiePlayer | null> {
  if (!playerPromise) {
    playerPromise =
      // @ts-ignore -- lottie-web is declared in package.json; types resolve after install.
      // @vite-ignore keeps vitest from eagerly resolving it; webpack/Next still
      // code-splits the literal specifier, and .catch guards non-browser runs.
      import(/* @vite-ignore */ 'lottie-web')
        .then((mod: { default?: LottiePlayer }) => (mod.default ?? mod) as LottiePlayer)
        .catch(() => null);
  }
  return playerPromise;
}

export interface LottieMarkProps {
  /** Parsed Lottie animation JSON. */
  data: object;
  size?: number;
  loop?: boolean;
  /** Frame to hold before playing (and the frame held under reduced motion). */
  holdFrame?: number;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * §0 · G10 — Lazy Lottie wrapper. SSR-safe (loads lottie-web in an effect),
 * plays only while on screen (IntersectionObserver, 160px margin), destroys
 * off-screen, and honors prefers-reduced-motion by holding a still frame.
 */
export function LottieMark({ data, size = 40, loop = true, holdFrame, style, className }: LottieMarkProps) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el == null) return undefined;
    let anim: LottieAnimation | null = null;
    let visible = false;
    let cancelled = false;
    const reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const start = () => {
      void loadPlayer().then((lottie) => {
        if (cancelled || !visible || anim || !lottie) return;
        anim = lottie.loadAnimation({
          container: el,
          renderer: 'svg',
          loop,
          autoplay: !reduced,
          // Lottie mutates the data it's given — hand it a private copy.
          animationData: JSON.parse(JSON.stringify(data)),
        });
        if (holdFrame != null) {
          anim.goToAndStop(holdFrame, true);
          if (!reduced) anim.play();
        }
        if (reduced && holdFrame == null) anim.goToAndStop(30, true);
      });
    };

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          visible = e.isIntersecting;
          if (e.isIntersecting && !anim) {
            start();
          } else if (!e.isIntersecting && anim) {
            anim.destroy();
            anim = null;
          }
        });
      },
      { rootMargin: '160px' },
    );
    io.observe(el);
    return () => {
      cancelled = true;
      io.disconnect();
      if (anim) anim.destroy();
      anim = null;
    };
  }, [data, loop, holdFrame]);

  return (
    <span
      ref={ref}
      className={className}
      style={{ width: size, height: size, display: 'inline-block', flexShrink: 0, ...style }}
      aria-hidden
    />
  );
}

/** tailor-mark — the hanger draws itself on. Splash + route transitions. */
export function Mark({ size = 96, style }: { size?: number; style?: React.CSSProperties }) {
  return <LottieMark data={markData} size={size} holdFrame={0} style={style} />;
}

/** tailor-thinking — threads weave a breathing core. Every "AI working" moment. */
export function Thinking({ size = 40, style }: { size?: number; style?: React.CSSProperties }) {
  return <LottieMark data={thinkingData} size={size} style={style} />;
}
