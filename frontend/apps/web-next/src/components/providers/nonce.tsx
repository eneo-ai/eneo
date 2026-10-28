"use client";

import { createContext, use } from "react";

/*
 * The document's CSP nonce for client code that renders <style> elements.
 * The browser entry reads it once; the root passes it through Providers.
 */
const NonceContext = createContext<string | undefined>(undefined);

/**
 * Provides the document nonce to React consumers. The browser entry initializes
 * get-nonce's global before importing UI code; provider cleanup must not clear it.
 */
export function NonceProvider({
  nonce,
  children
}: {
  nonce: string | undefined;
  children: React.ReactNode;
}) {
  return <NonceContext value={nonce}>{children}</NonceContext>;
}

/** The request's CSP nonce, for a `<style nonce>` rendered on the client. */
export function useNonce(): string | undefined {
  return use(NonceContext);
}
