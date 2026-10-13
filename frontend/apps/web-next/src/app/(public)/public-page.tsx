import { useTranslations } from "next-intl";
import { EneoWordMark } from "@/components/shell/eneo-logo";
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from "@/components/ui/card";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

/**
 * The frame of the signed-out pages (login, login failed, activation,
 * deactivated organisation): the word mark above a card on the muted
 * background, like the existing app's signed-out pages, with the page's one
 * <main> and <h1> (the card title), and the organisation's accessibility
 * statement below the card, in the same place on every one of them
 * (DOS-lagen; WCAG 3.2.6).
 */
export function PublicPage({
  title,
  description,
  width = "sm",
  footer,
  children
}: {
  title: string;
  /** One line under the title, e.g. why the visitor is asked to sign in. */
  description?: string;
  width?: "sm" | "md";
  /** Actions at the card's end (Log out, Try again, …). */
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const t = useTranslations();
  const statementUrl = env.ACCESSIBILITY_STATEMENT_URL;

  return (
    <main className="bg-secondary flex min-h-svh flex-col items-center justify-center gap-6 p-4">
      {/* Decorative: the page's name is its <h1>; the mark only says which service this is. */}
      <EneoWordMark className="h-8 w-auto" />
      <Card className={cn("w-full", width === "md" ? "max-w-md" : "max-w-sm")}>
        <CardHeader className="items-center text-center">
          <h1 data-slot="card-title" className="text-xl leading-none font-semibold">
            {title}
          </h1>
          {description ? <CardDescription>{description}</CardDescription> : null}
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
