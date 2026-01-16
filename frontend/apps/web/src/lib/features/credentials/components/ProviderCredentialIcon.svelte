<script lang="ts">
	import type { ModelProviderPublic } from "@intric/intric-js";
	import { Button, Tooltip } from "@intric/ui";
	import { ShieldCheck, TriangleAlert } from "lucide-svelte";
	import { m } from "$lib/paraglide/messages";

	export let provider: ModelProviderPublic;
	export let onEdit: () => void;

	// Reactive computed values
	$: isConfigured = !!provider.masked_api_key;
	$: tooltipText = isConfigured
		? m.credentials_configured_tooltip({ masked_key: provider.masked_api_key || "" })
		: m.credentials_missing_tooltip();
</script>

<div class="inline-flex items-center">
	<Tooltip text={tooltipText}>
		{#if isConfigured}
			<Button variant="on-fill" padding="icon" size="sm" on:click={onEdit}>
				<ShieldCheck class="text-green-600" size={20} />
			</Button>
		{:else}
			<Button variant="on-fill" padding="icon-leading" size="sm" on:click={onEdit}>
				<TriangleAlert class="text-yellow-500" size={20} />
				<span class="text-yellow-500">{m.provider_credentials_missing()}</span>
			</Button>
		{/if}
	</Tooltip>
</div>
