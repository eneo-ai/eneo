<script lang="ts">
	import { m } from "$lib/paraglide/messages";

	interface Props {
		name: string;
		description?: string;
		isDefault?: boolean;
	}

	let { name, description, isDefault = false }: Props = $props();
</script>

<div class="flex flex-col gap-1 py-1">
	<div class="flex items-center gap-2">
		<span class="font-medium text-default">{name}</span>
		{#if isDefault}
			<span
				class="border-positive-stronger text-positive-stronger cursor-default rounded-full border px-2 py-0.5 text-xs font-medium"
			>
				{m.default_model()}
			</span>
		{/if}
	</div>
	{#if description}
		<span class="line-clamp-2 text-sm text-dimmer">
			{description}
		</span>
	{/if}
</div>
