"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { getQueryClient } from "@/lib/api/query";
import { NonceProvider } from "@/components/providers/nonce";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({
  nonce,
  children
}: {
  nonce: string | undefined;
  children: React.ReactNode;
}) {
  // getQueryClient (not useState): a stable client that survives suspense
  // re-renders without being recreated, per the TanStack SSR guide.
  const queryClient = getQueryClient();

  return (
    <NonceProvider nonce={nonce}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>{children}</TooltipProvider>
        <ReactQueryDevtools initialIsOpen={false} />
      </QueryClientProvider>
    </NonceProvider>
  );
}
