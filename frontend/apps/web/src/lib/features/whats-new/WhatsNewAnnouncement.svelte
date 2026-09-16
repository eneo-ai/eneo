<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { toast } from "$lib/components/toast";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import { announcementSummary } from "./announcement";
  import { getWhatsNewStore } from "./whatsNewStore";

  const { user } = getAppContext();
  const { pendingAnnouncement, markLatestAnnounced } = getWhatsNewStore();

  // Shown once per user and release, on the first app load after the
  // release reaches them. Persistent rather than timed (WCAG 2.2.1): the
  // close button or the action dismisses it. Dismissing is not "seen" —
  // the menu dot stays until they open the page.
  onMount(() => {
    const release = pendingAnnouncement();
    if (!release) return;

    const { headlines, more } = announcementSummary(
      release,
      user.hasPermission("admin"),
      getLocale()
    );
    if (headlines.length === 0) return;

    const description =
      more > 0
        ? m.whats_new_announcement_more({ titles: headlines.join(", "), count: more })
        : headlines.join(", ");

    toast(m.whats_new_announcement_title({ version: release.version }), {
      description,
      duration: Number.POSITIVE_INFINITY,
      action: {
        label: m.whats_new_announcement_action(),
        onClick: () => {
          // eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing
          void goto(localizeHref("/whats-new"));
        }
      }
    });
    void markLatestAnnounced();
  });
</script>
