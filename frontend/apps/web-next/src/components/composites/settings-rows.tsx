import { useId } from "react";
import { cn } from "@/lib/utils";

/**
 * Where a page bar names the section, the card does not repeat the title (it
 * stays the section's heading for assistive technology, and where focus
 * lands), and the card's frame and inset give way to the page's gutter: an
 * editor's section on a phone (SectionedSettings' phone index, below 768 px),
 * and a page pushed from Konto (`data-pushed-section`, below 1024 px, as long
 * as its PageBar shows). A description or header actions stay, above the rows.
 */
const IN_PHONE_SECTION = {
  card: "max-md:in-[[data-editor-section]]:rounded-none max-md:in-[[data-editor-section]]:border-0 max-md:in-[[data-editor-section]]:bg-transparent max-lg:in-[[data-pushed-section]]:rounded-none max-lg:in-[[data-pushed-section]]:border-0 max-lg:in-[[data-pushed-section]]:bg-transparent",
  header:
    "max-md:in-[[data-editor-section]]:border-b-0 max-md:in-[[data-editor-section]]:p-0 max-md:in-[[data-editor-section]]:has-[p,[data-settings-group-end]]:pb-4 max-lg:in-[[data-pushed-section]]:border-b-0 max-lg:in-[[data-pushed-section]]:p-0 max-lg:in-[[data-pushed-section]]:has-[p,[data-settings-group-end]]:pb-4",
  title: "max-md:in-[[data-editor-section]]:sr-only max-lg:in-[[data-pushed-section]]:sr-only",
  body: "max-md:in-[[data-editor-section]]:p-0 max-lg:in-[[data-pushed-section]]:p-0"
};

/**
 * A titled card grouping related settings rows. `id` is the scroll anchor used by
 * the editor's section navigation. `description` (optional) sits under the title
 * in the card header — use it for the section's one-line summary so individual
 * rows don't have to repeat the section name.
 */
export function SettingsGroup({
  id,
  tour,
  title,
  description,
  headerEnd,
  children
}: {
  id?: string;
  tour?: string;
  title: string;
  description?: string;
  headerEnd?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      data-tour={tour}
      className={cn("bg-card scroll-mt-32 rounded-xl border", IN_PHONE_SECTION.card)}
    >
      <div className={cn("border-b px-5 py-4", IN_PHONE_SECTION.header)}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={cn("text-base font-semibold", IN_PHONE_SECTION.title)}>{title}</h2>
            {description ? (
              <p className="text-muted-foreground mt-0.5 text-sm">{description}</p>
            ) : null}
          </div>
          {headerEnd ? (
            <div data-settings-group-end="" className="flex shrink-0 flex-wrap gap-1.5">
              {headerEnd}
            </div>
          ) : null}
        </div>
      </div>
      <div className={cn("flex flex-col gap-6 px-5 py-5", IN_PHONE_SECTION.body)}>{children}</div>
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
 * `id` gives a save error a direct link to this row.
 * Omit `title` entirely for a row whose label would just repeat the card header.
 */
export function SettingsRow({
  id,
  title,
  tour,
  description,
  htmlFor,
  inline,
  children
}: {
  id?: string;
  title?: string;
  tour?: string;
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
      <div
        id={id}
        data-tour={tour}
        className="flex scroll-mt-32 items-center justify-between gap-4"
      >
        {label}
        <div className="flex min-w-0 shrink-0 flex-col items-end gap-2" {...groupAttrs}>
          {children}
        </div>
      </div>
    );
  }

  return (
    <div id={id} data-tour={tour} className="flex scroll-mt-32 flex-col gap-2">
      {label}
      <div className="flex w-full min-w-0 flex-col gap-2" {...groupAttrs}>
        {children}
      </div>
    </div>
  );
}
