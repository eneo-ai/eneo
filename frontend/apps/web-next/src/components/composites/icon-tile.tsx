import { cn } from "@/lib/utils";

/**
 * The categorical hues of the Eneo theme (Astryx `--color-text-*` and
 * `--color-background-*-muted`), plus a neutral one. Colour decorates; the
 * icon and the text beside it carry the meaning.
 */
export type IconTileHue = "neutral" | "blue" | "teal" | "purple" | "orange" | "pink";

// Full static strings so Tailwind's JIT keeps them — never `bg-ax-${hue}`.
const HUE_CLASSES: Record<IconTileHue, string> = {
  neutral: "bg-ax-muted text-ax-text-secondary",
  blue: "bg-ax-blue-muted text-ax-blue",
  teal: "bg-ax-teal-muted text-ax-teal",
  purple: "bg-ax-purple-muted text-ax-purple",
  orange: "bg-ax-orange-muted text-ax-orange",
  pink: "bg-ax-pink-muted text-ax-pink"
};

const SIZE_CLASSES = {
  sm: "rounded-ax-inner size-8 [&_svg]:size-4",
  md: "rounded-ax-container size-10 [&_svg]:size-5",
  lg: "rounded-ax-container size-12 [&_svg]:size-6"
} as const;

/**
 * One hue per area, so an area looks the same wherever it is empty or
 * introduced: the chat's start page uses the same tiles for its starters.
 */
export const AREA_HUES = {
  assistants: "purple",
  apps: "teal",
  knowledge: "blue",
  spaces: "orange",
  services: "pink"
} as const satisfies Record<string, IconTileHue>;

export type IconTileProps = {
  /** A lucide-react icon; sized by the tile. */
  icon: React.ReactNode;
  hue?: IconTileHue;
  size?: keyof typeof SIZE_CLASSES;
  className?: string;
};

/**
 * A coloured, rounded tile around an icon: the start page's starter cards,
 * empty states and feature cards share it. Decorative (`aria-hidden`): put the
 * meaning in the text next to it.
 */
export function IconTile({ icon, hue = "neutral", size = "md", className }: IconTileProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center",
        SIZE_CLASSES[size],
        HUE_CLASSES[hue],
        className
      )}
    >
      {icon}
    </span>
  );
}
