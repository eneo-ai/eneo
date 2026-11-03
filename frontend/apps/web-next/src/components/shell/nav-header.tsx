import { Icon } from "@astryxdesign/core/Icon";
import { IconButton } from "@astryxdesign/core/IconButton";
import { useSideNavCollapse } from "@astryxdesign/core/SideNav";
import { PanelLeft } from "lucide-react";
import { useTranslations } from "use-intl";
import { cn } from "@/lib/utils";

/**
 * The SideNav's collapse toggle. The wordmark and the bells live in the top
 * bar (top-bar.tsx), as in the Svelte app.
 *
 * One element for both states, so the toggle keeps its DOM node, and with it
 * the keyboard focus, when it collapses or expands the nav (WCAG 2.4.3).
 */
export function NavHeader({ navId }: { navId: string }) {
  const t = useTranslations();
  const { isCollapsed, toggle } = useSideNavCollapse();
  const toggleLabel = isCollapsed ? t("shell_expand_nav") : t("shell_collapse_nav");

  return (
    <div className={cn("flex items-center", isCollapsed ? "justify-center" : "justify-end")}>
      {/* SideNav's own collapse state, through a plain IconButton rather than
          SideNavCollapseButton: that one has no tooltip, and an icon-only
          control needs its name visible on hover. aria-expanded/-controls
          make it a disclosure for the nav. */}
      <IconButton
        variant="ghost"
        icon={<Icon icon={PanelLeft} />}
        label={toggleLabel}
        tooltip={toggleLabel}
        aria-expanded={!isCollapsed}
        aria-controls={navId}
        onClick={toggle}
      />
    </div>
  );
}
