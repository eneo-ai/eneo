<script lang="ts">
	import { onMount } from 'svelte';
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
	import { Wrench, AlertTriangle } from 'lucide-svelte';
	import { getErrorMessage } from '$lib/core/errors/getErrorMessage';

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
		setQuestionText,
		focusMentionInput
	} = initMentionInput({
		triggerCharacter: '@',
		tools: () => chat.partner.tools,
		onEnterPressed: ask
	});

	type Props = { scrollToBottom: () => void };

	const { scrollToBottom }: Props = $props();

	let abortController: AbortController | undefined;
	const AUTO_ACCEPT_TOOLS_STORAGE_KEY = 'autoAcceptToolsEnabled';
	let autoAcceptTools = $state(true);
	let hasHydratedToolApprovalPreference = $state(false);

	onMount(() => {
		if (!browser) {
			hasHydratedToolApprovalPreference = true;
			return;
		}

		// Load auto-accept tools preference (default to true = auto-accept)
		try {
			const storedAutoAccept = window.localStorage.getItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY);
			if (storedAutoAccept === 'false') {
				autoAcceptTools = false;
			} else {
				autoAcceptTools = true;
				window.localStorage.setItem(AUTO_ACCEPT_TOOLS_STORAGE_KEY, 'true');
			}
		} catch (error) {
			console.warn('Unable to read auto-accept tools preference', error);
		} finally {
			hasHydratedToolApprovalPreference = true;
		}
	});

	$effect(() => {
		if (!browser || !hasHydratedToolApprovalPreference) return;

		try {
			window.localStorage.setItem(
				AUTO_ACCEPT_TOOLS_STORAGE_KEY,
				autoAcceptTools ? 'true' : 'false'
			);
		} catch (error) {
			console.warn('Unable to persist auto-accept tools preference', error);
		}
	});

	function queueUploadsFromClipboard(event: ClipboardEvent) {
		if (!event.clipboardData?.files || event.clipboardData.files.length === 0) return;
		queueValidUploads([...event.clipboardData.files]);
	}

	let inputError = $state<{ message: string; details?: string } | null>(null);
	let errorInputSnapshot = { question: '', attachmentIds: '' };

	function parseTokenError(errorMessage: string): { used: number; limit: number } | null {
		const match = errorMessage.match(/(\d[\d,]*)\s*tokens?\s*used.*?limit\s*(?:is\s*)?(\d[\d,]*)/i);
		if (match) {
			return {
				used: parseInt(match[1].replace(/,/g, '')),
				limit: parseInt(match[2].replace(/,/g, ''))
			};
		}
		return null;
	}

	async function ask() {
		if (isAskingDisabled) return;
		inputError = null;
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
		const toolApprovalEnabled = !autoAcceptTools && hasMcpTools;
		scrollToBottom();

		try {
			await chat.askQuestion($question, files, tools, webSearchEnabled, toolApprovalEnabled, abortController);
			resetMentionInput();
			clearUploads();
		} catch (error: unknown) {
			const errorMessage = error instanceof Error ? error.message : String(error);
			const lower = errorMessage.toLowerCase();
			const isContextError = lower.includes('context window') || lower.includes('context length') || lower.includes('tokens used') || lower.includes('too long');

			if (isContextError) {
				const tokenInfo = parseTokenError(errorMessage);
				if (tokenInfo) {
					const excess = tokenInfo.used - tokenInfo.limit;
					inputError = {
						message: m.context_window_exceeded(),
						details: `${tokenInfo.used.toLocaleString()} / ${tokenInfo.limit.toLocaleString()} tokens (${excess.toLocaleString()} ${m.over()})`
					};
				} else {
					inputError = { message: m.context_window_exceeded() };
				}
			} else {
				inputError = { message: getErrorMessage(error) };
			}
			errorInputSnapshot = { question: $question, attachmentIds: $attachments.map(a => a.fileRef?.id ?? '').sort().join(',') };
		}
	}

	// Clear error when user changes input (text or attachments)
	$effect(() => {
		const q = $question;
		const currentIds = $attachments.map(a => a.fileRef?.id ?? '').sort().join(',');
		const snap = errorInputSnapshot;
		if (snap.question && (q !== snap.question || currentIds !== snap.attachmentIds)) {
			inputError = null;
			errorInputSnapshot = { question: '', attachmentIds: '' };
		}
	});

	$effect(() => {
		track(chat.partner, chat.currentConversation);
		focusMentionInput();
	});

	let useWebSearch = $state(false);

	const shouldShowMentionButton = $derived.by(() => {
		const hasTools = chat.partner.tools.assistants.length > 0;
		const isEnabled =
			chat.partner.type === 'default-assistant' ||
			('allow_mentions' in chat.partner && chat.partner.allow_mentions);
		return hasTools && isEnabled;
	});

	// Check if the assistant has MCP servers/tools
	const hasMcpTools = $derived.by(() => {
		if (!chat.partner) return false;
		// Check for mcp_servers array on the partner
		if ('mcp_servers' in chat.partner && Array.isArray(chat.partner.mcp_servers)) {
			return chat.partner.mcp_servers.length > 0;
		}
		return false;
	});

	const isAskingDisabled = $derived(
		chat.askQuestion.isLoading ||
			$isUploading ||
			($question === '' && $attachments.length === 0) ||
			!chat.hasCompletionModel
	);
</script>

<form
	onsubmit={async (e) => { e.preventDefault(); await ask(); }}
	class="border-default bg-primary ring-dimmer relative flex w-[100%] max-w-[74ch] flex-col border-t p-1.5 shadow-md ring-offset-0 transition-all duration-300 md:w-full md:rounded-xl md:border {chat.hasCompletionModel ? 'focus-within:border-stronger hover:border-stronger focus-within:shadow-lg hover:ring-4' : ''}"
>
	{#if !chat.hasCompletionModel}
		<div class="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-primary/80 backdrop-blur-[1px]">
			<div class="flex items-center gap-2 px-4 text-sm text-secondary">
				<AlertTriangle class="h-4 w-4 flex-shrink-0" />
				<p>{m.no_completion_model_description()}</p>
			</div>
		</div>
	{/if}
	<div class="relative">
		<MentionInput onpaste={queueUploadsFromClipboard}></MentionInput>
		{#if chat.askQuestion.isLoading}
			<div class="absolute inset-0 flex items-center justify-center rounded-lg bg-primary/60 backdrop-blur-[1px]">
				<div class="flex items-center gap-2 text-sm text-secondary">
					<svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
					</svg>
					{m.generating_answer()}
				</div>
			</div>
		{/if}
	</div>

	{#if inputError}
		<div class="flex items-start gap-2 px-2 py-1.5 text-sm text-negative-stronger bg-negative-dimmer/30 rounded-md mt-1">
			<AlertTriangle class="h-4 w-4 flex-shrink-0 mt-0.5" />
			<div>
				<p class="font-medium">{inputError.message}</p>
				{#if inputError.details}
					<p class="text-negative-stronger mt-0.5">{inputError.details}</p>
				{/if}
			</div>
		</div>
	{/if}

	<div class="flex justify-between mt-2">
		<div class="flex items-center gap-2 {chat.askQuestion.isLoading ? 'opacity-40 pointer-events-none' : ''}">
			<AttachmentUploadIconButton label={m.upload_documents_to_conversation()} />
			{#if shouldShowMentionButton}
				<MentionButton></MentionButton>
			{/if}

			{#if chat.partner.type === 'default-assistant' && featureFlags.showWebSearch}
				<div
					class="hover:bg-accent-dimmer hover:text-accent-stronger border-default hover:border-accent-default flex items-center justify-center rounded-full border p-1.5"
				>
					<Input.Switch bind:value={useWebSearch} class="*:!cursor-pointer">
						<span class="-mr-2 flex gap-1"><IconWeb></IconWeb>{m.search()}</span></Input.Switch
					>
				</div>
			{/if}

			{#if hasMcpTools}
				<Tooltip text={autoAcceptTools ? m.auto_accept_tools_on() : m.auto_accept_tools_off()} placement="top">
					<div
						class="hover:bg-accent-dimmer hover:text-accent-stronger border-default hover:border-accent-default flex items-center justify-center rounded-full border p-1.5 {autoAcceptTools ? 'bg-accent-dimmer text-accent-stronger border-accent-default' : ''}"
					>
						<Input.Switch bind:value={autoAcceptTools} class="*:!cursor-pointer">
							<span class="-mr-2 flex items-center gap-1"><Wrench class="h-5 w-5" />{m.auto_accept_tools()}</span>
						</Input.Switch>
					</div>
				</Tooltip>
			{/if}
		</div>

		<div class="flex items-center gap-2">
			{#if chat.askQuestion.isLoading}
				<Tooltip text={m.cancel_your_request()} placement="top" let:trigger asFragment>
					<Button
						unstyled
						aria-label={m.cancel_your_request()}
						type="button"
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
