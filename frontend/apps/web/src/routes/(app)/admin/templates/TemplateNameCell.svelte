<script lang="ts">
	import { m } from "$lib/paraglide/messages";
	import * as LucideIcons from 'lucide-svelte';

	interface Props {
		name: string;
		description?: string;
		isDefault?: boolean;
		iconName?: string | null;
	}

	let { name, description, isDefault = false, iconName }: Props = $props();

	// Convert kebab-case to PascalCase for icon lookup
	function toPascalCase(str: string): string {
		return str.charAt(0).toUpperCase() + str.slice(1).replace(/-([a-z])/g, (g) => g[1].toUpperCase());
	}

	const IconComponent = $derived.by(() => {
		if (!iconName) return null;
		const pascalName = toPascalCase(iconName);
		return (LucideIcons as any)[pascalName] || null;
	});
</script>

<div class="flex flex-col gap-1 py-1">
	<div class="flex items-center gap-2">
		{#if IconComponent}
			<div class="border-strong bg-subtle flex h-6 w-6 items-center justify-center rounded border">
				{@render IconComponent({ class: "text-text h-4 w-4" })}
			</div>
		{/if}
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
