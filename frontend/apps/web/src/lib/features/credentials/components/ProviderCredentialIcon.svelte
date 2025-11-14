<script lang="ts">
	import { Button, Tooltip } from "@intric/ui";
	import { KeyRound, ShieldCheck, ShieldAlert } from "lucide-svelte";
	import { writable } from "svelte/store";
	import ProviderCredentialDialog from "./ProviderCredentialDialog.svelte";

	export let provider: string;
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
		? `API Key configured: ${credential?.masked_key}\nClick to update`
		: `No credentials configured\nClick to add`;
	$: iconClass = isConfigured
		? "text-green-600 hover:text-green-700 bg-green-50 rounded"
		: "text-amber-500 hover:text-amber-600";

	// Debug logging
	$: if (credential) {
		console.log(`[ProviderCredentialIcon] ${provider}:`, credential);
	}
</script>

<div class="inline-flex items-center">
	<Tooltip text={tooltipText}>
		<Button
			variant="ghost"
			padding="icon"
			size="sm"
			on:click={openDialog}
			class="ml-2 h-6 w-6 {iconClass}"
		>
			{#if isConfigured}
				<ShieldCheck size={16} class="fill-green-100" />
			{:else}
				<ShieldAlert size={16} />
			{/if}
		</Button>
	</Tooltip>
</div>

<ProviderCredentialDialog {provider} existingCredential={credential} {openController} />
