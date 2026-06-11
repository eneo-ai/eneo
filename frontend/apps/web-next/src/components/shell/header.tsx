import { getTranslations } from "next-intl/server";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { ThemeSwitcher } from "@/components/shell/theme-switcher";

// Placeholder profile area; replaced by the real profile menu in Phase 2 (auth).
async function ProfilePlaceholder() {
  const t = await getTranslations();

  return (
    <Avatar aria-label={t("profile")}>
      <AvatarFallback>E</AvatarFallback>
    </Avatar>
  );
}

export function Header() {
  return (
    <header className="bg-background sticky top-0 z-10 flex h-14 items-center gap-3 border-b px-4">
      <span className="text-lg font-semibold">Eneo</span>
      <div className="flex-1" />
      <ThemeSwitcher />
      <ProfilePlaceholder />
    </header>
  );
}
