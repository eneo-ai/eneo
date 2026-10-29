"use client";

import { Card } from "@astryxdesign/core/Card";
import { useTranslations } from "use-intl";
import type { ReactNode, Ref } from "react";
import { EneoWordMark } from "@/components/shell/eneo-logo";
import { cn } from "@/lib/utils";

/** Shared signed-out frame: one main, one heading and the installation's statement link. */
export function PublicPage({
  title,
  description,
  width = "sm",
  accessibilityStatementUrl,
  headingRef,
  footer,
  children
}: {
  title: string;
  description?: string;
  width?: "sm" | "md";
  accessibilityStatementUrl: string | null;
  headingRef?: Ref<HTMLHeadingElement>;
  footer?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations();
  return (
    <main className="bg-secondary flex min-h-svh flex-col items-center justify-center gap-6 p-4">
      <EneoWordMark className="h-8 w-auto" />
      <Card
        padding={6}
        className={cn("flex w-full flex-col gap-6", width === "md" ? "max-w-md" : "max-w-sm")}
      >
        <header className="flex flex-col gap-2 text-center">
          <h1
            ref={headingRef}
            tabIndex={headingRef ? -1 : undefined}
            className="text-ax-text text-xl leading-tight font-semibold"
          >
            {title}
          </h1>
          {description ? <p className="text-ax-text-secondary text-sm">{description}</p> : null}
        </header>
        <div className="flex flex-col gap-4">{children}</div>
        {footer ? <footer className="flex justify-end gap-2">{footer}</footer> : null}
      </Card>
      {accessibilityStatementUrl ? (
        <a
          href={accessibilityStatementUrl}
          className="text-muted-foreground hover:text-foreground focus-visible:outline-ring inline-flex min-h-6 items-center rounded-sm text-sm underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
        >
          {t("a11y_statement_link")}
        </a>
      ) : null}
    </main>
  );
}
