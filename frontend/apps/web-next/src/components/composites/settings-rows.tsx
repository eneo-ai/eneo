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
  children
}: {
  id?: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="bg-card scroll-mt-24 rounded-xl border">
      <div className="border-b px-5 py-4">
        <h2 className="text-base font-semibold">{title}</h2>
        {description ? <p className="text-muted-foreground mt-0.5 text-sm">{description}</p> : null}
      </div>
      <div className="flex flex-col gap-6 px-5 py-5">{children}</div>
    </section>
  );
}

/**
 * One setting: a compact label column (≤200px) on the left and the control(s)
 * filling the rest of the width, stacking on small screens.
 *
 * Pass `htmlFor` when the row wraps a single labelable control (input, textarea,
 * select) so the title is a real `<label>`; omit it for groups, lists, or custom
 * widgets and the title labels the control region via `role="group"`. Either way
 * the control gets an accessible name. Omit `title` entirely for a row whose
 * label would just repeat the section's card header — the control still needs its
 * own `aria-label`/`aria-labelledby`.
 */
export function SettingsRow({
  title,
  description,
  htmlFor,
  children
}: {
  title?: string;
  description?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  const reactId = useId();
  const titleId = `${reactId}-title`;
  const descriptionId = description ? `${reactId}-desc` : undefined;
  const hasLabel = Boolean(title || description);

  return (
    <div className="grid gap-x-6 gap-y-2 md:grid-cols-[minmax(0,200px)_minmax(0,1fr)]">
      {hasLabel ? (
        <div className="flex flex-col gap-1">
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
      ) : null}
      <div
        className={
          hasLabel ? "flex min-w-0 flex-col gap-2" : "col-span-full flex min-w-0 flex-col gap-2"
        }
        {...(htmlFor || !title
          ? {}
          : { role: "group", "aria-labelledby": titleId, "aria-describedby": descriptionId })}
      >
        {children}
      </div>
    </div>
  );
}
