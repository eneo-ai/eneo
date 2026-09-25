import { redirect } from "@sveltejs/kit";
import { hasPermission } from "$lib/core/hasPermission.js";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo, user, currentSpace } = await event.parent();
  const { spaceId, assistantId } = event.params;

  // The widgets permission unlocks the feature; the backend enforces it too.
  if (!hasPermission(user)("widgets")) {
    redirect(302, `/spaces/${spaceId}/assistants/${assistantId}/edit`);
  }

  const isAdmin = hasPermission(user)("admin");
  // The policy is readable with the widgets permission, so every editor
  // checks limits against the same bounds the server enforces.
  const [assistant, widgets, policy, templates] = await Promise.all([
    eneo.assistants.get({ id: assistantId }),
    eneo.widgets.list({ spaceId: currentSpace.id }),
    eneo.widgets.policy.get().catch(() => null),
    eneo.widgets.templates.list().catch(() => [])
  ]);

  return {
    ...event.data,
    assistant,
    widget: widgets.find((w) => w.target_id === assistantId && w.status !== "archived") ?? null,
    isAdmin,
    policy,
    templates
  };
};
