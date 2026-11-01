import { ChevronLeft } from "lucide-react";
import Link from "@/lib/link";
import { cn } from "@/lib/utils";

/**
 * "‹ Parent" above a detail page's title, 44 px tall on touch. A page below a
 * space tab gets the page bar's back link under 768 px, so it passes
 * `hideOnPhone`: this one is then for tablets and up.
 */
export function BackLink({
  href,
  children,
  hideOnPhone = false
}: {
  href: string;
  children: React.ReactNode;
  hideOnPhone?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm pointer-coarse:min-h-11",
        hideOnPhone && "max-md:hidden"
      )}
    >
      <ChevronLeft className="size-4" />
      {children}
    </Link>
  );
}
