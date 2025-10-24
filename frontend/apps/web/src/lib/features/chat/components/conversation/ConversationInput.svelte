<script lang="ts">
	import { onMount } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import { browser } from '$app/environment';
	import AttachmentUploadIconButton from '$lib/features/attachments/components/AttachmentUploadIconButton.svelte';
	import { IconEnter } from '@intric/icons/enter';
	import { IconStopCircle } from '@intric/icons/stop-circle';
	import { Button, Input, Tooltip } from '@intric/ui';
	import { getAttachmentManager } from '$lib/features/attachments/AttachmentManager';
	import MentionInput from '../mentions/MentionInput.svelte';
	import { initMentionInput } from '../mentions/MentionInput';
	import MentionButton from '../mentions/MentionButton.svelte';
	import { getChatService } from '../../ChatService.svelte';
	import { IconWeb } from '@intric/icons/web';
	import { track } from '$lib/core/helpers/track';
	import { getAppContext } from '$lib/core/AppContext';
	import { m } from '$lib/paraglide/messages';
	import TokenUsageBar from '$lib/features/tokens/TokenUsageBar.svelte';
	import { ChartPie } from 'lucide-svelte';

	const chat = getChatService();
	const { featureFlags } = getAppContext();

	const {
		state: { attachments, isUploading },
		queueValidUploads,
		clearUploads
	} = getAttachmentManager();

	const {
		states: { mentions, question },
		resetMentionInput,
		focusMentionInput
	} = initMentionInput({
		triggerCharacter: '@',
		tools: () => chat.partner.tools,
		onEnterPressed: ask
	});

	type Props = { scrollToBottom: () => void };

	const { scrollToBottom }: Props = $props();

	let abortController: AbortController | undefined;
	const TOKEN_USAGE_STORAGE_KEY = 'tokenUsageEnabled';
	let tokenUsageEnabled = $state(false);
	let hasHydratedTokenPreference = $state(false);

	onMount(() => {
		if (!browser) {
			hasHydratedTokenPreference = true;
			return;
		}

		try {
			const storedPreference = window.localStorage.getItem(TOKEN_USAGE_STORAGE_KEY);
			// Always default to false (OFF) - user must explicitly enable it
			// Only restore if it was explicitly set to true by user
			if (storedPreference === 'true') {
				tokenUsageEnabled = true;
			} else {
				// Ensure it's false and clear any stale values
				tokenUsageEnabled = false;
				window.localStorage.setItem(TOKEN_USAGE_STORAGE_KEY, 'false');
			}
		} catch (error) {
			console.warn('Unable to read token usage preference', error);
		} finally {
			hasHydratedTokenPreference = true;
		}
	});

	$effect(() => {
		if (!browser || !hasHydratedTokenPreference) return;

		try {
			window.localStorage.setItem(
				TOKEN_USAGE_STORAGE_KEY,
				tokenUsageEnabled ? 'true' : 'false'
			);
		} catch (error) {
			console.warn('Unable to persist token usage preference', error);
		}
	});

	function queueUploadsFromClipboard(event: ClipboardEvent) {
		if (!event.clipboardData?.files || event.clipboardData.files.length === 0) return;
		queueValidUploads([...event.clipboardData.files]);
	}

	function ask() {
		if (isAskingDisabled) return;
		const webSearchEnabled = featureFlags.showWebSearch && useWebSearch;
		const files = $attachments.map((file) => file?.fileRef).filter((file) => file !== undefined);
		abortController = new AbortController();
		const tools =
			$mentions.length > 0
				? {
						assistants: $mentions.map((mention) => {
							return { id: mention.id, handle: mention.handle };
						})
					}
				: undefined;
		chat.askQuestion($question, files, tools, webSearchEnabled, abortController);
		scrollToBottom();
		resetMentionInput();
		clearUploads();
		// Reset all token tracking when message is sent
		chat.resetNewPromptTokens();
	}

	$effect(() => {
		track(chat.partner, chat.currentConversation);
		focusMentionInput();
	});

	const isAskingDisabled = $derived(
		chat.askQuestion.isLoading || $isUploading || ($question === '' && $attachments.length === 0)
	);

	let useWebSearch = $state(false);

	// Disable web search when there are attachments
	$effect(() => {
		if ($attachments.length > 0 && useWebSearch) {
			useWebSearch = false;
		}
	});

	const shouldShowMentionButton = $derived.by(() => {
		const hasTools = chat.partner.tools.assistants.length > 0;
		const isEnabled =
			chat.partner.type === 'default-assistant' ||
			('allow_mentions' in chat.partner && chat.partner.allow_mentions);
		return hasTools && isEnabled;
	});

	// --- Token Calculation and Coloring Logic ---
	const historyTokens = $derived(chat.historyTokens);
	const promptTokens = $derived(chat.promptTokens);
	const newTokens = $derived(chat.newPromptTokens);
	const modelInfo = $derived(chat.partner?.model_info || null);
	const tokenLimit = $derived(modelInfo?.token_limit || 0);
	const isApproximate = $derived($question.length > 0);

	$effect(() => {
		const currentAttachments = $attachments
			.filter((att) => att.fileRef)
			.map((att) => ({
				id: att.fileRef!.id,
				size: att.fileRef!.size
			}));

		chat.calculateNewPromptTokens($question, currentAttachments);
	});

	const tokenUsagePercentage = $derived(() => {
		if (!tokenLimit) return 0;
		return ((newTokens + historyTokens + promptTokens) / tokenLimit) * 100;
	});

	const tokenUsageColorClass = $derived(() => {
		if (!tokenLimit) return 'text-tertiary';
		const percentage = tokenUsagePercentage();
		const totalTokens = newTokens + historyTokens + promptTokens;

		// If no tokens at all, keep it grey
		if (totalTokens === 0) return 'text-tertiary';

		// Match the semantic colors from TokenUsageBar
		if (percentage >= 95) return 'text-negative-stronger';
		if (percentage >= 85) return 'text-warning-stronger';
		if (percentage >= 70) return 'text-warning-stronger';
		return 'text-positive-stronger';
	});
</script>

<div class="flex w-[100%] max-w-[74ch] flex-col md:w-full">
	{#if useWebSearch}
		<div class="bg-yellow-200 text-yellow-900 border-l border-r border-t border-yellow-400 text-sm px-3 py-2 rounded-t-xl text-center md:rounded-t-xl">
			{m.websearch_notice()}
		</div>
	{/if}

	<!-- This interaction is just a convenience function -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<form
		onclick={() => {
			focusMentionInput();
		}}
		class="{useWebSearch ? 'border-yellow-400 focus-within:border-yellow-500 hover:border-yellow-500' : 'border-default focus-within:border-stronger hover:border-stronger'} bg-primary ring-dimmer relative flex flex-col gap-2 border-t p-1.5 shadow-md ring-offset-0 transition-all duration-300 focus-within:shadow-lg hover:ring-4 {useWebSearch ? 'rounded-b-xl rounded-t-none border-l border-r border-b md:rounded-b-xl md:rounded-t-none' : 'rounded-xl border'} md:border"
	>
		<!-- Icon always absolutely positioned to prevent jumping -->
		{#if modelInfo && tokenLimit > 0}
			<div class="absolute top-2 right-2.5 z-10">
				<Tooltip text={tokenUsageEnabled ? m.hide_token_details() : m.show_token_details()} placement="top">
					<button
						type="button"
						onclick={(e) => {
							e.stopPropagation();
							tokenUsageEnabled = !tokenUsageEnabled;
						}}
						class="flex h-7 w-7 items-center justify-center rounded-full transition-colors duration-200 hover:bg-black/5 {tokenUsageColorClass()}"
						aria-label={tokenUsageEnabled ? m.hide_token_details() : m.show_token_details()}
						aria-pressed={tokenUsageEnabled ? "true" : "false"}
					>
						<ChartPie class="h-4.5 w-4.5 transition-colors duration-200" />
					</button>
				</Tooltip>
			</div>
		{/if}

		<!-- Usage bar slides in below, with smooth animation -->
		{#if modelInfo && tokenLimit > 0 && tokenUsageEnabled}
			<div
				transition:slide={{ duration: 350, easing: quintOut, axis: 'y' }}
			>
				<div class="px-2 pt-1 pr-11 pb-2">
					<TokenUsageBar tokens={newTokens} limit={tokenLimit} {historyTokens} {promptTokens} {isApproximate} />
				</div>
			</div>
		{/if}

		<MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>

		<div class="flex justify-between">
			<div class="flex items-center gap-2">
				<AttachmentUploadIconButton disabled={useWebSearch} label={m.upload_documents_to_conversation()} />
				{#if shouldShowMentionButton}
					<MentionButton></MentionButton>
				{/if}
				{#if chat.partner.type === 'default-assistant' && featureFlags.showWebSearch}
					<div
						class="border-default flex items-center justify-center rounded-full border p-1.5 {$attachments.length > 0 ? 'opacity-50 cursor-not-allowed' : 'hover:bg-accent-dimmer hover:text-accent-stronger hover:border-accent-default'}"
					>
						<Input.Switch bind:value={useWebSearch} disabled={$attachments.length > 0} class={$attachments.length > 0 ? '*:!cursor-not-allowed' : '*:!cursor-pointer'}>
							<span class="-mr-2 flex gap-1"><IconWeb></IconWeb>{m.search()}</span></Input.Switch
						>
					</div>
				{/if}
			</div>

			<div class="flex items-center gap-2">
				{#if chat.askQuestion.isLoading}
					<Tooltip text={m.cancel_your_request()} placement="top" let:trigger asFragment>
						<Button
							unstyled
							aria-label={m.cancel_your_request()}
							type="submit"
							is={trigger}
							onclick={() => abortController?.abort('User cancelled')}
							name="ask"
							class="bg-secondary hover:bg-hover-stronger disabled:bg-tertiary disabled:text-secondary flex h-9 items-center justify-center !gap-1 rounded-lg !pr-1 !pl-2"
						>
							{m.stop_answer()}
							<IconStopCircle />
						</Button>
					</Tooltip>
				{:else}
					<Button
						disabled={isAskingDisabled}
						aria-label={m.submit_your_question()}
						type="submit"
						onclick={() => ask()}
						name="ask"
						class="bg-secondary hover:bg-hover-stronger disabled:bg-tertiary disabled:text-secondary flex h-9 items-center justify-center !gap-1 rounded-lg !pr-1 !pl-2"
					>
						{m.send()}
						<IconEnter />
					</Button>
				{/if}
			</div>
		</div>
	</form>
</div>