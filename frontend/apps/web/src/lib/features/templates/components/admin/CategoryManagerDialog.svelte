<script lang="ts">
	import { Dialog, Button, Input } from '@intric/ui';
	import { m } from '$lib/paraglide/messages';
	import { IconTrash } from '@intric/icons/trash';
	import { IconPlus } from '@intric/icons/plus';
	import type { Writable } from 'svelte/store';

	interface Props {
		openController: Writable<boolean>;
		categories?: string[];
		onCategoryAdded?: (category: string) => void;
		onCategoryDeleted?: (category: string) => void;
	}

	let { openController, categories = [], onCategoryAdded, onCategoryDeleted }: Props = $props();

	let newCategoryName = $state('');
	let deleteConfirmCategory = $state<string | null>(null);
	let isSaving = $state(false);

	// Simulated category usage counts (in real app, this would come from API)
	function getCategoryUsageCount(category: string): number {
		// TODO: Replace with actual API call to get template count per category
		return 0;
	}

	async function handleAddCategory() {
		if (!newCategoryName.trim()) return;

		// Validate category name format (lowercase with hyphens)
		const formattedName = newCategoryName.trim().toLowerCase().replace(/\s+/g, '-');

		if (categories.includes(formattedName)) {
			// Already exists, just clear input
			newCategoryName = '';
			return;
		}

		isSaving = true;
		try {
			// In real implementation, this would call the API
			onCategoryAdded?.(formattedName);
			newCategoryName = '';
		} catch (error) {
			console.error('Failed to add category:', error);
			alert(m.failed_to_create_category());
		} finally {
			isSaving = false;
		}
	}

	async function handleDeleteCategory(category: string) {
		isSaving = true;
		try {
			// In real implementation, this would call the API
			onCategoryDeleted?.(category);
			deleteConfirmCategory = null;
		} catch (error) {
			console.error('Failed to delete category:', error);
			alert(m.failed_to_delete_category());
		} finally {
			isSaving = false;
		}
	}

	function handleKeyPress(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleAddCategory();
		}
	}
</script>

<Dialog.Root controller={openController}>
	<Dialog.Content width="medium">
		<Dialog.Header>
			<Dialog.Title>{m.manage_categories()}</Dialog.Title>
			<Dialog.Description>{m.manage_categories_description()}</Dialog.Description>
		</Dialog.Header>

		<div class="flex flex-col gap-6 p-6">
			<!-- Add New Category Section -->
			<div class="flex flex-col gap-3">
				<h4 class="text-sm font-semibold text-default">{m.add_new_category()}</h4>

				<div class="flex gap-2">
					<div class="flex-1">
						<Input.Text
							bind:value={newCategoryName}
							placeholder={m.category_name_placeholder()}
							onkeypress={handleKeyPress}
							disabled={isSaving}
						/>
					</div>
					<Button
						variant="primary"
						size="medium"
						onclick={handleAddCategory}
						disabled={!newCategoryName.trim() || isSaving}
						iconLeading={IconPlus}
					>
						{m.add()}
					</Button>
				</div>
			</div>

			<!-- Divider -->
			<div class="border-t border-default"></div>

			<!-- Existing Categories Section -->
			<div class="flex flex-col gap-3">
				<h4 class="text-sm font-semibold text-default">{m.existing_categories()}</h4>

				{#if categories.length === 0}
					<p class="text-sm text-dimmer">{m.no_categories_yet()}</p>
				{:else}
					<div class="flex flex-col gap-2">
						{#each categories as category (category)}
							{@const usageCount = getCategoryUsageCount(category)}
							<div
								class="flex items-center justify-between rounded-lg border border-default p-3 hover:bg-hover-default"
							>
								<div class="flex flex-col gap-1">
									<span class="font-medium text-default">{category}</span>
									<span class="text-xs text-dimmer">
										{usageCount}
										{usageCount === 1 ? m.instance() : m.instances()}
									</span>
								</div>

								<Button
									variant="ghost"
									size="small"
									iconLeading={IconTrash}
									onclick={() => (deleteConfirmCategory = category)}
									disabled={isSaving}
									aria-label={m.delete_category()}
								/>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<Dialog.Footer>
			<Button variant="outlined" onclick={() => openController.set(false)}>{m.close()}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<!-- Delete Confirmation Dialog -->
{#if deleteConfirmCategory}
	{@const usageCount = getCategoryUsageCount(deleteConfirmCategory)}
	<Dialog.Root controller={{ subscribe: () => {}, set: () => {} }}>
		<Dialog.Content width="small">
			<Dialog.Header>
				<Dialog.Title>{m.confirm_delete()}</Dialog.Title>
			</Dialog.Header>

			<div class="flex flex-col gap-4 p-6">

				{#if usageCount > 0}
					<div
						class="flex items-start gap-3 rounded-lg border border-warning-default bg-warning-default/10 p-3"
					>
						<span class="text-sm font-medium text-warning-default">{m.warning()}</span>
					</div>
					<p class="text-sm text-default">
						{m.delete_category_with_templates_warning().replace('{count}', usageCount.toString())}
					</p>
				{/if}

				<p class="text-sm text-dimmer">{m.delete_category_consequence()}</p>
			</div>

			<Dialog.Footer>
				<Button variant="ghost" onclick={() => (deleteConfirmCategory = null)}>{m.cancel()}</Button
				>
				<Button
					variant="danger"
					onclick={() => {
						if (deleteConfirmCategory) {
							handleDeleteCategory(deleteConfirmCategory);
						}
					}}
					disabled={isSaving}
				>
					{isSaving ? m.deleting() : m.delete()}
				</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
{/if}
