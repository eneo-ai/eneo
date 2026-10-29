import type { ComponentProps } from "react";
import { PublicPage as PublicPageFrame } from "@/features/auth/public-page";
import { env } from "@/lib/env";

export function PublicPage(
  props: Omit<ComponentProps<typeof PublicPageFrame>, "accessibilityStatementUrl">
) {
  return (
    <PublicPageFrame
      {...props}
      accessibilityStatementUrl={env.ACCESSIBILITY_STATEMENT_URL ?? null}
    />
  );
}
