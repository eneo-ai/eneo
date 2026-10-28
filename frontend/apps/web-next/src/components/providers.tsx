"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useEffect } from "react";
import { getQueryClient } from "@/lib/api/query";
import { reloadOnIdentityChange } from "@/lib/session/identity-broadcast";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import { NonceProvider } from "@/components/providers/nonce";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({
  nonce,
  children
}: {
  /** The request's CSP nonce, for client code that injects <style> elements. */
  nonce: string | undefined;
  children: React.ReactNode;
}) {
  // getQueryClient (not useState): a stable client that survives suspense
  // re-renders without being recreated, per the TanStack SSR guide.
  const queryClient = getQueryClient();
  // A sign-in or sign-out in another tab reloads this one (identity-broadcast).
  useEffect(() => reloadOnIdentityChange(), []);

  return (
    <NonceProvider nonce={nonce}>
      <AstryxProvider>
        <QueryClientProvider client={queryClient}>
          <TooltipProvider>{children}</TooltipProvider>
          <ReactQueryDevtools initialIsOpen={false} />
        </QueryClientProvider>
      </AstryxProvider>
    </NonceProvider>
  );
}
