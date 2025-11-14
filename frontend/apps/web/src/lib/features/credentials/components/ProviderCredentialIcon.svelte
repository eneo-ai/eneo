<script lang="ts">
	import { Button, Tooltip } from "@intric/ui";
	import { IconKey } from "@intric/icons/key";
	import { IconLockClosed } from "@intric/icons/lock-closed";
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
</script>

<div class="inline-flex items-center">
	<Tooltip text={tooltipText}>
		<Button
			variant="on-fill"
			padding="icon"
			on:click={openDialog}
			class={isConfigured ? "" : "opacity-60"}
		>
			{#if isConfigured}
				<IconKey />
			{:else}
				<IconLockClosed />
			{/if}
		</Button>
	</Tooltip>
</div>

<ProviderCredentialDialog {provider} existingCredential={credential} {openController} />
