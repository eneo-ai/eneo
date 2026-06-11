import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { ThemeSwitcher } from "@/components/shell/theme-switcher";

// Placeholder profile area; replaced by the real profile menu in Phase 4.
function ProfilePlaceholder({ email }: { email: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground hidden text-sm sm:block">{email}</span>
      <Avatar>
        <AvatarFallback>{email.slice(0, 1).toUpperCase()}</AvatarFallback>
      </Avatar>
    </div>
  );
}

export function Header({ userEmail }: { userEmail: string }) {
  return (
    <header className="bg-background sticky top-0 z-10 flex h-14 items-center gap-3 border-b px-4">
      <span className="text-lg font-semibold">Eneo</span>
      <div className="flex-1" />
      <ThemeSwitcher />
      <ProfilePlaceholder email={userEmail} />
    </header>
  );
}
