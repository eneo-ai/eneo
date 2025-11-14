<script lang="ts">
	import { Button, Dialog, Input } from "@intric/ui";
	import { writable, type Writable } from "svelte/store";
	import { page } from "$app/stores";
	import { invalidate } from "$app/navigation";

	export let provider: string;
	export let existingCredential:
		| {
				masked_key: string;
				config: Record<string, any>;
		  }
		| undefined = undefined;
	export let openController: Writable<boolean>;

	// Provider-specific field configurations
	const PROVIDER_FIELDS = {
		openai: [{ name: "api_key", label: "API Key", type: "password", required: true }],
		anthropic: [{ name: "api_key", label: "API Key", type: "password", required: true }],
		berget: [{ name: "api_key", label: "API Key", type: "password", required: true }],
		gdm: [{ name: "api_key", label: "API Key", type: "password", required: true }],
		mistral: [{ name: "api_key", label: "API Key", type: "password", required: true }],
		ovhcloud: [{ name: "api_key", label: "API Key", type: "password", required: true }],
		azure: [
			{ name: "api_key", label: "API Key", type: "password", required: true },
			{ name: "endpoint", label: "Endpoint URL", type: "text", required: true },
			{ name: "api_version", label: "API Version", type: "text", required: true },
			{ name: "deployment_name", label: "Deployment Name", type: "text", required: true }
		],
		vllm: [
			{ name: "api_key", label: "API Key", type: "password", required: true },
			{ name: "endpoint", label: "Endpoint URL", type: "text", required: true }
		]
	};

	const fields =
		PROVIDER_FIELDS[provider.toLowerCase() as keyof typeof PROVIDER_FIELDS] ||
		PROVIDER_FIELDS.openai;

	// Form state
	let formData: Record<string, string> = {
		api_key: "",
		...(existingCredential?.config || {})
	};
	let isSubmitting = false;
	let errors: Record<string, string> = {};

	// Validate form
	function validateForm(): boolean {
		errors = {};
		let isValid = true;

		for (const field of fields) {
			if (field.required && !formData[field.name]?.trim()) {
				errors[field.name] = `${field.label} is required`;
				isValid = false;
			} else if (field.name === "api_key" && formData.api_key.length < 8) {
				errors.api_key = "API key must be at least 8 characters long";
				isValid = false;
			}
		}

		return isValid;
	}

	// Submit form
	async function handleSubmit() {
		if (!validateForm()) {
			return;
		}

		isSubmitting = true;
		const { intric } = $page.data;

		try {
			const response = await intric.credentials.set(provider.toLowerCase(), formData);
			alert(`Credentials for ${provider} configured successfully. Key ending in ${response.masked_key}`);
			openController.set(false);
			// Reload the page data to reflect new credentials
			await invalidate("admin:models:load");
		} catch (error: any) {
			console.error("Failed to set credentials:", error);

			// Parse validation errors if available
			if (error.status === 422 && error.response?.detail?.errors) {
				const validationErrors = error.response.detail.errors;
				if (Array.isArray(validationErrors)) {
					alert(`Validation Error: ${validationErrors.join(", ")}`);
				} else {
					alert("Validation Error");
				}
			} else {
				alert(`Failed to configure credentials: ${error.message || "An unexpected error occurred"}`);
			}
		} finally {
			isSubmitting = false;
		}
	}

	// Format provider name for display
	const displayProviderName = provider.charAt(0).toUpperCase() + provider.slice(1);
</script>

<Dialog.Root {openController}>
	<Dialog.Content width="dynamic">
		<Dialog.Title>Configure {displayProviderName} Credentials</Dialog.Title>

		<Dialog.Section class="space-y-4 p-4">
			{#if existingCredential}
				<div class="rounded-md bg-blue-50 p-4 text-sm text-blue-900">
					<p class="font-medium">Current credential configured</p>
					<p class="mt-1">API Key: {existingCredential.masked_key}</p>
					{#if existingCredential.config.endpoint}
						<p class="mt-1">Endpoint: {existingCredential.config.endpoint}</p>
					{/if}
					<p class="mt-2 text-xs text-blue-700">
						Enter new values below to update the existing credentials.
					</p>
				</div>
			{/if}

			<form on:submit|preventDefault={handleSubmit} class="space-y-4">
				{#each fields as field}
					<div>
						<label for={field.name} class="mb-2 block text-sm font-medium text-gray-700">
							{field.label}
							{#if field.required}
								<span class="text-red-500">*</span>
							{/if}
						</label>
						<Input.Text
							id={field.name}
							type={field.type}
							bind:value={formData[field.name]}
							placeholder={field.type === "password"
								? existingCredential
									? "Enter new key to update"
									: "Enter API key"
								: `Enter ${field.label.toLowerCase()}`}
							disabled={isSubmitting}
							class={errors[field.name] ? "border-red-500" : ""}
						/>
						{#if errors[field.name]}
							<p class="mt-1 text-xs text-red-600">{errors[field.name]}</p>
						{/if}
					</div>
				{/each}

				<div class="rounded-md bg-gray-50 p-3 text-xs text-gray-600">
					<p>
						<strong>Note:</strong> All credentials are encrypted before storage and never exposed
						in full after being set.
					</p>
				</div>
			</form>
		</Dialog.Section>

		<Dialog.Controls let:close>
			<Button is={close} variant="secondary" disabled={isSubmitting}>Cancel</Button>
			<Button on:click={handleSubmit} variant="primary" disabled={isSubmitting}>
				{isSubmitting ? "Saving..." : "Save Credentials"}
			</Button>
		</Dialog.Controls>
	</Dialog.Content>
</Dialog.Root>
