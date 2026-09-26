import { useTranslations } from "next-intl";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

/**
 * The frame of the signed-out pages (login, login failed, activation,
 * deactivated organisation): the page's one <main> and <h1> (the card title),
 * and the organisation's accessibility statement below the card, in the same
 * place on every one of them (DOS-lagen; WCAG 3.2.6).
 */
export function PublicPage({
  title,
  width = "sm",
  footer,
  children
}: {
  title: string;
  width?: "sm" | "md";
  /** Actions at the card's end (Log out, Try again, …). */
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useTranslations();
  const statementUrl = env.ACCESSIBILITY_STATEMENT_URL;

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 p-4">
      <Card className={cn("w-full", width === "md" ? "max-w-md" : "max-w-sm")}>
        <CardHeader>
          <h1 data-slot="card-title" className="text-xl leading-none font-semibold">
            {title}
          </h1>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">{children}</CardContent>
        {footer ? <CardFooter className="justify-end gap-2">{footer}</CardFooter> : null}
      </Card>
      {statementUrl ? (
        <p className="text-sm">
          <a
            href={statementUrl}
            className="text-muted-foreground hover:text-foreground focus-visible:outline-ring inline-flex min-h-6 items-center rounded-sm underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
          >
            {t("a11y_statement_link")}
          </a>
        </p>
      ) : null}
    </main>
  );
}
