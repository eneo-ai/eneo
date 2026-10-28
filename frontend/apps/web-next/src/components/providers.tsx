"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { getQueryClient } from "@/lib/api/query";
import { AstryxProvider } from "@/components/providers/astryx-provider";
import { NonceProvider } from "@/components/providers/nonce";
import { TooltipProvider } from "@/components/ui/tooltip";

// Keep the shell's hydration in the provider bundle. A direct server import
// can make Next assign this shared boundary to a page's client chunk instead.
export { HydrationBoundary } from "@tanstack/react-query";

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
