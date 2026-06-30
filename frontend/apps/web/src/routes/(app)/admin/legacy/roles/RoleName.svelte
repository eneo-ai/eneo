<!--
    Displays a role name with optional Default badge and Template icon.
-->
<script lang="ts">
  import { Label } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";

  export let name: string;
  export let isDefault = false;
  export let templateSource: string | null = null;
</script>

<div class="flex items-center gap-2">
  <span class="font-medium">{name}</span>
  {#if isDefault}
    <Label.Single item={{ label: m.default_label(), color: "blue" }} capitalize={false} />
  {/if}
  {#if templateSource}
    <span
      title={m.template_role_tooltip({ name: templateSource })}
      aria-label={m.template_role_tooltip({ name: templateSource })}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke-width="1.5"
        stroke="currentColor"
        class="text-secondary h-4 w-4"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
        />
      </svg>
    </span>
  {/if}
</div>
