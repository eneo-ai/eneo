"use client";

import { createContext, use, useLayoutEffect } from "react";

/*
 * The request's CSP nonce (src/proxy.ts) for client code that renders or
 * injects <style> elements: production allows a <style> only with the nonce
 * (AGENTS.md → CSP). The root layout reads it once and hands it to Providers.
 */
const NonceContext = createContext<string | undefined>(undefined);

declare global {
  // Where get-nonce looks when nobody called its setNonce() (webpack's name).
  var __webpack_nonce__: string | undefined;
}

/**
 * Provides the nonce to useNonce(), and to get-nonce, the nonce source of
 * react-style-singleton: react-remove-scroll injects its scroll-lock <style>
 * through it (Radix Select locks the page's scroll while open). get-nonce
 * falls back to the `__webpack_nonce__` global, which Turbopack leaves to the
 * global scope. Set in a layout effect: before any passive effect in the same
 * commit injects a style (react-style-singleton injects in one).
 */
export function NonceProvider({
  nonce,
  children
}: {
  nonce: string | undefined;
  children: React.ReactNode;
}) {
  useLayoutEffect(() => {
    globalThis.__webpack_nonce__ = nonce;
    return () => {
      if (globalThis.__webpack_nonce__ === nonce) globalThis.__webpack_nonce__ = undefined;
    };
  }, [nonce]);
  return <NonceContext value={nonce}>{children}</NonceContext>;
}

/** The request's CSP nonce, for a `<style nonce>` rendered on the client. */
export function useNonce(): string | undefined {
  return use(NonceContext);
}
