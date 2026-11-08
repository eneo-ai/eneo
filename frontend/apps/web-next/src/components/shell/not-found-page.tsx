import { useTranslations } from "use-intl";
import { Button } from "@/components/ui/button";
import Link from "@/lib/link";

/**
 * The page for an address the app does not have, with a way back to the start
 * page. On its own it fills the screen; in the shell's page panel it fills
 * the panel instead, so it never makes the panel scroll.
 */
export function NotFoundPage() {
  const t = useTranslations();
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-8 text-center [#main-content>&]:min-h-0 [#main-content>&]:flex-1">
      <p className="text-muted-foreground font-mono text-sm">404</p>
      <h1 className="text-2xl font-semibold">{t("page_not_found")}</h1>
      <Button asChild>
        <Link href="/">{t("back_to_home")}</Link>
      </Button>
    </div>
  );
}
