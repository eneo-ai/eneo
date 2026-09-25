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

/** Up to two initials: first letters of the first two words. */
export function entityInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
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

  return (
    <span
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
      className={cn(
        "inline-flex shrink-0 items-center justify-center overflow-hidden leading-none font-semibold select-none",
        toneClasses,
        SIZE_CLASSES[size],
        className
      )}
    >
      {src ? (
        // Backend-served upload behind the auth proxy; next/image cannot optimize it.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt="" className="size-full object-cover" />
      ) : (
        (icon ?? entityInitials(name))
      )}
    </span>
  );
}
