<script lang="ts">
	interface Props {
		name: string;
		description?: string;
	}

	let { name, description }: Props = $props();
</script>

<div class="flex flex-col gap-1 py-1">
	<span class="font-medium text-default">{name}</span>
	{#if description}
		<span class="line-clamp-2 text-sm text-dimmer">
			{description}
		</span>
	{/if}
</div>
