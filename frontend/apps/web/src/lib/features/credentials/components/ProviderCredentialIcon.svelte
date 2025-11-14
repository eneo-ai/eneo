<script lang="ts">
	import { Button, Tooltip } from "@intric/ui";
	import { ShieldCheck, TriangleAlert } from "lucide-svelte";
	import { writable } from "svelte/store";
	import ProviderCredentialDialog from "./ProviderCredentialDialog.svelte";
	import { m } from "$lib/paraglide/messages";

	export let provider: string; // Credential provider ID (e.g., "azure", "openai", "anthropic")
	export let credential:
		| {
				masked_key: string;
				config: Record<string, any>;
		  }
		| undefined = undefined;

	const openController = writable(false);

	function openDialog() {
		openController.set(true);
	}

	// Reactive computed values
	$: isConfigured = !!credential;
	$: tooltipText = isConfigured
		? m.credentials_configured_tooltip({ masked_key: credential?.masked_key || "" })
		: m.credentials_missing_tooltip();
</script>

<div class="inline-flex items-center">
	<Tooltip text={tooltipText}>
		{#if isConfigured}
			<Button variant="on-fill" padding="icon" size="sm" on:click={openDialog}>
				<ShieldCheck class="text-green-600" size={20} />
			</Button>
		{:else}
			<Button variant="on-fill" padding="icon-leading" size="sm" on:click={openDialog}>
				<TriangleAlert class="text-yellow-500" size={20} />
				<span class="text-yellow-500">{m.provider_credentials_missing()}</span>
			</Button>
		{/if}
	</Tooltip>
</div>

<ProviderCredentialDialog {provider} existingCredential={credential} {openController} />
