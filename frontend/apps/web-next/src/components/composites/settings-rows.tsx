import { useId } from "react";

/**
 * A titled card grouping related settings rows. `id` is the scroll anchor used by
 * the editor's section navigation. `description` (optional) sits under the title
 * in the card header — use it for the section's one-line summary so individual
 * rows don't have to repeat the section name.
 */
export function SettingsGroup({
  id,
  title,
  description,
  headerEnd,
  children
}: {
  id?: string;
  title: string;
  description?: string;
  headerEnd?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="bg-card scroll-mt-32 rounded-xl border">
      <div className="border-b px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold">{title}</h2>
            {description ? (
              <p className="text-muted-foreground mt-0.5 text-sm">{description}</p>
            ) : null}
          </div>
          {headerEnd ? <div className="flex shrink-0 flex-wrap gap-1.5">{headerEnd}</div> : null}
        </div>
      </div>
      <div className="flex flex-col gap-6 px-5 py-5">{children}</div>
    </section>
  );
}

/**
 * One setting. By default the label/description stack ABOVE a full-width control
 * so nothing leaves a dead gutter — the control owns the whole column width.
 *
 * Pass `inline` for a lone compact control (a single switch/toggle) that reads
 * better beside its label on one line. Pass `htmlFor` when the row wraps a single
 * labelable control so the title is a real `<label>`; omit it for groups, lists,
 * or custom widgets and the title labels the control region via `role="group"`.
 * Omit `title` entirely for a row whose label would just repeat the card header.
 */
export function SettingsRow({
  title,
  description,
  htmlFor,
  inline,
  children
}: {
  title?: string;
  description?: string;
  htmlFor?: string;
  inline?: boolean;
  children: React.ReactNode;
}) {
  const reactId = useId();
  const titleId = `${reactId}-title`;
  const descriptionId = description ? `${reactId}-desc` : undefined;
  const hasLabel = Boolean(title || description);

  const label = hasLabel ? (
    <div className="flex flex-col gap-0.5">
      {title ? (
        htmlFor ? (
          <label htmlFor={htmlFor} className="text-sm font-medium">
            {title}
          </label>
        ) : (
          <span id={titleId} className="text-sm font-medium">
            {title}
          </span>
        )
      ) : null}
      {description ? (
        <p id={descriptionId} className="text-muted-foreground text-sm">
          {description}
        </p>
      ) : null}
    </div>
  ) : null;

  const groupAttrs =
    htmlFor || !title
      ? {}
      : ({ role: "group", "aria-labelledby": titleId, "aria-describedby": descriptionId } as const);

  if (inline && hasLabel) {
    return (
      <div className="flex items-center justify-between gap-4">
        {label}
        <div className="flex min-w-0 shrink-0 flex-col items-end gap-2" {...groupAttrs}>
          {children}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {label}
      <div className="flex w-full min-w-0 flex-col gap-2" {...groupAttrs}>
        {children}
      </div>
    </div>
  );
}
