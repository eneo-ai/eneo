"use client";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function ResourceTileCard({
  className,
  children
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Card
      className={cn(
        "group hover:border-primary/40 focus-within:border-ring focus-within:ring-ring/50 relative gap-0 p-4 transition-colors focus-within:ring-[3px]",
        className
      )}
    >
      {children}
    </Card>
  );
}

export function ResourceTileActions({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute top-2 right-2 z-10 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
      {children}
    </div>
  );
}
