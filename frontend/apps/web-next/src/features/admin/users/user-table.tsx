"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { UserActions } from "./user-actions";
import type { AdminUser, UserState } from "./users";

const STATE_STYLES: Partial<Record<UserState, string>> = {
  active: "border-success/30 bg-success/10 text-success",
  invited: "border-primary/30 bg-primary/10 text-primary",
  inactive: "border-border bg-muted text-muted-foreground"
};

function StateBadge({ state }: { state: UserState }) {
  const t = useTranslations();
  const label =
    state === "active"
      ? t("active")
      : state === "inactive"
        ? t("inactive")
        : state === "invited"
          ? t("invited")
          : state;
  return (
    <span
      className={cn(
        "inline-block rounded-md border px-2 py-0.5 text-xs font-medium",
        STATE_STYLES[state] ?? "border-border bg-muted text-muted-foreground"
      )}
    >
      {label}
    </span>
  );
}

export function UserTable({ users }: { users: AdminUser[] }) {
  const t = useTranslations();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("email")}</TableHead>
          <TableHead>{t("roles")}</TableHead>
          <TableHead>{t("status")}</TableHead>
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map((user) => (
          <TableRow key={user.id}>
            <TableCell className="font-medium">{user.email}</TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                {user.roles.map((role) => (
                  <Badge key={role.id} variant="secondary">
                    {role.name}
                  </Badge>
                ))}
              </div>
            </TableCell>
            <TableCell>
              <StateBadge state={user.state} />
            </TableCell>
            <TableCell>
              <UserActions user={user} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
