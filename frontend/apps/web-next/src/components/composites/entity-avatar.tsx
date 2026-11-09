import { entityAccent, ENTITY_TONE_CLASSES, type EntityTone } from "@/lib/entity-accent";
import { cn } from "@/lib/utils";

const SIZE_CLASSES = {
  sm: "size-6 rounded-ax-inner text-[0.625rem] [&_svg]:size-3.5",
  md: "size-8 rounded-ax-inner text-xs [&_svg]:size-4",
  lg: "size-10 rounded-ax-element text-sm [&_svg]:size-5",
  xl: "size-16 rounded-ax-container text-xl [&_svg]:size-7"
} as const;

export type EntityAvatarSize = keyof typeof SIZE_CLASSES;

export type EntityAvatarProps = {
  /** Display name; its initials are the fallback content. */
  name: string;
  /** Stable key for the colour (entity id). Falls back to `name`. */
  id?: string;
  /** Force a tone instead of deriving it from `id`. */
  tone?: EntityTone;
  /** Image URL (e.g. an uploaded assistant icon); covers the tile. */
  src?: string | null;
  /** Fallback glyph instead of initials, e.g. `<Bot />`. */
  icon?: React.ReactNode;
  size?: EntityAvatarSize;
  /**
   * Accessible name. Omit when the name is visible next to the tile (the
   * usual case): the tile is then decorative and hidden from screen readers.
   */
  label?: string;
  className?: string;
};

/**
 * Up to two initials: first letters of the first two words that start with a
 * letter or digit, so "Mötesanteckningar (2)" gives "M", not "M(".
 */
export function entityInitials(name: string): string {
  const words = name.split(/\s+/).filter((word) => /^[\p{L}\p{N}]/u.test(word));
  return words
    .slice(0, 2)
    .map((word) => Array.from(word)[0] ?? "")
    .join("")
    .toUpperCase(); // locale-independent: identical on server and client
}

/**
 * Coloured tile for a space, assistant or other entity: an image, an icon or
 * initials on the entity's deterministic categorical tone.
 *
 * @example
 * <EntityAvatar id={space.id} name={space.name} icon={<Users />} size="lg" />
 */
export function EntityAvatar({
  name,
  id,
  tone,
  src,
  icon,
  size = "md",
  label,
  className
}: EntityAvatarProps) {
  const toneClasses = tone ? ENTITY_TONE_CLASSES[tone] : entityAccent(id ?? name);
  const content = src ? null : (icon ?? entityInitials(name));
  // Initials are drawn by CSS, not written as text: axe reads hidden text as part of the visible
  // label of a control around the tile, which its name then has to repeat (WCAG 2.5.3).
  const initials = typeof content === "string" ? content : undefined;

  return (
    <span
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
      data-initials={initials}
      className={cn(
        "inline-flex shrink-0 items-center justify-center overflow-hidden leading-none font-semibold select-none",
        initials && "before:content-[attr(data-initials)]",
        toneClasses,
        SIZE_CLASSES[size],
        className
      )}
    >
      {src ? (
        <img src={src} alt="" className="size-full object-cover" />
      ) : initials ? null : (
        content
      )}
    </span>
  );
}
