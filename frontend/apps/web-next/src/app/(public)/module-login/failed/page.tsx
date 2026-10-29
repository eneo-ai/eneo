import { env } from "@/lib/env";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { moduleLoginFailureReason } from "@/lib/auth/module-login";
import { ModuleLoginFailed } from "@/features/auth/module-login-failed";

/** Like the hand-off's own responses: not indexed, no referrer sent on. */
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations();
  return {
    title: t("module_login_failed"),
    robots: { index: false, follow: false, noarchive: true },
    referrer: "no-referrer"
  };
}

export default async function ModuleLoginFailedPage({
  searchParams
}: {
  searchParams: Promise<{ reason?: string | string[] }>;
}) {
  const { reason } = await searchParams;
  return (
    <ModuleLoginFailed
      accessibilityStatementUrl={env.ACCESSIBILITY_STATEMENT_URL ?? null}
      reason={moduleLoginFailureReason(reason)}
    />
  );
}
