"use client";

import { createContext, use, useLayoutEffect } from "react";

const NonceContext = createContext<string | undefined>(undefined);

declare global {
  // get-nonce reads this global before react-remove-scroll injects a style.
  var __webpack_nonce__: string | undefined;
}

/** Share the request nonce with client components and Radix's scroll lock. */
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

export function useNonce(): string | undefined {
  return use(NonceContext);
}
