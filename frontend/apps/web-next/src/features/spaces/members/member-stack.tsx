"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { AvatarGroup, AvatarGroupOverflow } from "@astryxdesign/core/AvatarGroup";
import { useTranslations } from "next-intl";
import { memberDisplayName, personToneClass } from "./member-avatar";

const VISIBLE_MEMBERS = 3;

/** A space's first members as avatars, then "+n"; named by the member count. */
export function MemberStack({ members }: { members: { id: string; email: string }[] }) {
  const t = useTranslations();
  const hidden = members.length - VISIBLE_MEMBERS;

  if (members.length === 0) return null;

  return (
    <AvatarGroup size={32} aria-label={t("space_members_count", { count: members.length })}>
      {members.slice(0, VISIBLE_MEMBERS).map((member) => (
        <Avatar
          key={member.id}
          name={memberDisplayName(member)}
          className={personToneClass(member.id)}
        />
      ))}
      {hidden > 0 ? <AvatarGroupOverflow count={hidden} /> : null}
    </AvatarGroup>
  );
}
