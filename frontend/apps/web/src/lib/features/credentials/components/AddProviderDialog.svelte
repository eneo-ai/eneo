<script lang="ts">
	import { Button, Dialog, Select } from "@intric/ui";
	import { writable, type Writable } from "svelte/store";
	import ProviderCredentialDialog from "./ProviderCredentialDialog.svelte";

	export let openController: Writable<boolean>;
	export let existingProviders: string[] = [];

	// All supported providers from backend
	const ALL_PROVIDERS = [
		{ id: "openai", name: "OpenAI" },
		{ id: "anthropic", name: "Anthropic" },
		{ id: "azure", name: "Azure OpenAI" },
		{ id: "berget", name: "Berget" },
		{ id: "gdm", name: "GDM" },
		{ id: "mistral", name: "Mistral AI" },
		{ id: "ovhcloud", name: "OVHcloud" },
		{ id: "vllm", name: "vLLM" }
	];

	// Filter out providers that already have credentials
	$: availableProviders = ALL_PROVIDERS.filter(
		(p) => !existingProviders.map((ep) => ep.toLowerCase()).includes(p.id)
	);

	let selectedProvider: { id: string; name: string } | undefined = undefined;
	const credentialDialogOpen = writable(false);

	function handleAdd() {
		if (!selectedProvider) return;
		openController.set(false);
		// Small delay to ensure smooth transition between dialogs
		setTimeout(() => {
			credentialDialogOpen.set(true);
		}, 100);
	}
</script>

<Dialog.Root {openController}>
	<Dialog.Content width="medium">
		<Dialog.Title>Add Provider Credentials</Dialog.Title>

		<Dialog.Section scrollable={false}>
			{#if availableProviders.length === 0}
				<p class="text-sm text-gray-600 p-4">
					All supported providers already have credentials configured.
				</p>
			{:else}
				<Select.Simple
					class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
					options={availableProviders.map((provider) => ({
						label: provider.name,
						value: provider
					}))}
					bind:value={selectedProvider}
				>
					Select a provider
				</Select.Simple>
			{/if}
		</Dialog.Section>

		<Dialog.Controls let:close>
			<Button is={close} variant="secondary">Cancel</Button>
			<Button variant="primary" disabled={!selectedProvider} on:click={handleAdd}>
				Add Credentials
			</Button>
		</Dialog.Controls>
	</Dialog.Content>
</Dialog.Root>

{#if selectedProvider}
	<ProviderCredentialDialog
		provider={selectedProvider.id}
		existingCredential={undefined}
		openController={credentialDialogOpen}
	/>
{/if}
