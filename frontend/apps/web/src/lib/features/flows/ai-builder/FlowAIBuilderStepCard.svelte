<script lang="ts">
	import { m } from "$lib/paraglide/messages";
	import { slide } from "svelte/transition";
	import type { StepSpec } from "./protocol";

	interface Props {
		step: StepSpec;
		stepNumber: number;
		isFirst?: boolean;
		isLast?: boolean;
		planStatus?: string;
		onsuggestchange?: (prefill: string) => void;
		resolveModelName?: (ref: string | null) => string | null;
	}

	let { step, stepNumber, isFirst = false, isLast = false, planStatus = "", onsuggestchange, resolveModelName }: Props = $props();

	let showDetails = $state(false);
	let instructionsExpanded = $state(false);

	const changeKind = $derived(step.existing_step_ref ? "modified" : "new");

	const inputSourceLabel = $derived(
		({
			flow_input: m.ai_builder_step_flow_input(),
			previous_step: m.ai_builder_step_previous_step(),
			all_previous_steps: m.ai_builder_step_all_previous()
		} as Record<string, string>)[step.input_source] ?? step.input_source
	);

	function toggleDetails() {
		showDetails = !showDetails;
	}
</script>

<div class="step-wrapper" style:--step-delay="{stepNumber * 80}ms">
	<button
		class="step-card"
		class:mt-2={!isFirst}
		class:expanded={showDetails}
		onclick={toggleDetails}
		aria-expanded={showDetails}
	>
		<!-- Step header — clickable row -->
		<div class="step-header">
			<div class="step-title-row">
				<span class="step-number">{stepNumber}</span>
				<span class="step-name">{step.name}</span>
			</div>

			<div class="step-header-right">
				{#if changeKind === "new"}
					<span class="badge badge-new">{m.ai_builder_badge_new()}</span>
				{:else if changeKind === "modified"}
					<span class="badge badge-modified">{m.ai_builder_badge_modified()}</span>
				{/if}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="chevron"
					class:rotated={showDetails}
				>
					<path
						fill-rule="evenodd"
						d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
						clip-rule="evenodd"
					/>
				</svg>
			</div>
		</div>

		<!-- Step summary -->
		<div class="step-summary">
			<span class="summary-item">
				<span class="summary-label">{m.ai_builder_step_input()}:</span>
				{inputSourceLabel}
				<span class="summary-arrow">&rarr;</span>
				{step.input_type}
			</span>
			<span class="summary-item">
				<span class="summary-label">{m.ai_builder_step_output()}:</span>
				{step.output_type}
				{#if step.output_mode !== "pass_through"}
					<span class="summary-label">({step.output_mode})</span>
				{/if}
			</span>
		</div>
	</button>

	<!-- Details panel — outside the button for proper semantics -->
	{#if showDetails}
		<div class="details-panel" transition:slide={{ duration: 200 }}>
			{#if step.assistant_spec.instructions}
				<div class="detail-section">
					<span class="detail-label">{m.ai_builder_step_instructions()}:</span>
					<div class="instructions-container" class:instructions-collapsed={!instructionsExpanded}>
						<p class="detail-content whitespace-pre-wrap">{step.assistant_spec.instructions}</p>
					</div>
					{#if step.assistant_spec.instructions.length > 300}
						<button class="instructions-toggle" onclick={(e) => { e.stopPropagation(); instructionsExpanded = !instructionsExpanded; }}>
							{instructionsExpanded ? m.ai_builder_show_less() : m.ai_builder_show_more()}
						</button>
					{/if}
				</div>
			{/if}
			{#if step.assistant_spec.model_ref}
				<div class="detail-row-inline">
					<span class="detail-label">{m.ai_builder_step_model()}:</span>
					<span class="detail-value">{resolveModelName?.(step.assistant_spec.model_ref) ?? step.assistant_spec.model_ref}</span>
				</div>
			{/if}
			{#if step.assistant_spec.knowledge_refs.length > 0}
				<div class="detail-row-inline">
					<span class="detail-label">{m.ai_builder_step_knowledge()}:</span>
					<span class="detail-value">{step.assistant_spec.knowledge_refs.join(", ")}</span>
				</div>
			{/if}
			{#if step.input_bindings}
				<div class="detail-section">
					<span class="detail-label">{m.ai_builder_step_bindings()}:</span>
					<pre class="detail-pre">{JSON.stringify(step.input_bindings, null, 2)}</pre>
				</div>
			{/if}
			{#if step.output_contract?.properties}
				<div class="detail-section">
					<span class="detail-label">{m.ai_builder_step_output_contract()}:</span>
					<div class="contract-fields">
						{#each Object.entries(step.output_contract.properties) as [name, schema]}
							<div class="contract-field">
								<span class="contract-name">{name}</span>
								<span class="contract-type">({schema.type ?? 'object'})</span>
								{#if schema.description}
									<span class="contract-desc"> — {schema.description}</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
			{#if step.input_contract?.properties}
				<div class="detail-section">
					<span class="detail-label">{m.ai_builder_step_input_contract()}:</span>
					<div class="contract-fields">
						{#each Object.entries(step.input_contract.properties) as [name, schema]}
							<div class="contract-field">
								<span class="contract-name">{name}</span>
								<span class="contract-type">({schema.type ?? 'object'})</span>
								{#if schema.description}
									<span class="contract-desc"> — {schema.description}</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
			{#if step.mcp_policy === "restricted"}
				<div class="mcp-warning">
					<span>{m.ai_builder_mcp_restricted()}</span>
				</div>
			{/if}
			{#if planStatus === "proposed"}
				<button
					class="suggest-change-link"
					onclick={(e) => {
						e.stopPropagation();
						onsuggestchange?.(`${m.ai_builder_suggest_change_prefix()} '${step.name}': `);
					}}
				>
					{m.ai_builder_suggest_change()}
				</button>
			{/if}
		</div>
	{/if}
</div>

<style lang="postcss">
	@reference "@intric/ui/styles";

	.step-wrapper {
		position: relative;
		animation: step-enter 0.35s cubic-bezier(0.16, 1, 0.3, 1) var(--step-delay, 0ms) both;
	}

	@keyframes step-enter {
		from {
			opacity: 0;
			transform: translateY(0.5rem);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* --- Card as button — entire header is clickable --- */

	.step-card {
		display: block;
		width: 100%;
		border: 1px solid var(--border-default);
		border-radius: 0.75rem;
		padding: 1rem 1.25rem;
		background: var(--bg-primary);
		cursor: pointer;
		text-align: left;
		transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
	}

	.step-card:hover {
		border-color: oklch(from var(--border-default) l c h / 1.5);
		box-shadow: 0 4px 12px -4px oklch(0 0 0 / 0.05);
		background-color: var(--bg-hover-dimmer);
	}

	.step-card.expanded {
		border-color: oklch(from var(--border-default) l c h / 1.5);
		border-bottom-left-radius: 0;
		border-bottom-right-radius: 0;
		border-bottom-color: transparent;
	}

	/* --- Header --- */

	.step-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.step-title-row {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		min-width: 0;
	}

	.step-number {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: 50%;
		background: oklch(from var(--accent-default) l c h / 0.08);
		color: var(--accent-stronger);
		font-size: 0.75rem;
		font-weight: 600;
		flex-shrink: 0;
	}

	.step-name {
		font-size: 0.9375rem;
		font-weight: 600;
		color: var(--text-primary);
		letter-spacing: -0.01em;
	}

	.step-header-right {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		flex-shrink: 0;
	}

	.chevron {
		width: 1rem;
		height: 1rem;
		color: var(--text-muted);
		transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
		flex-shrink: 0;
	}

	.chevron.rotated {
		transform: rotate(180deg);
	}

	/* --- Badge --- */

	.badge {
		border-radius: 9999px;
		padding: 0.125rem 0.625rem;
		font-size: 0.6875rem;
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: uppercase;
	}

	.badge-new {
		background: var(--bg-positive-dimmer);
		color: var(--text-positive-stronger);
	}

	.badge-modified {
		background: var(--bg-warning-dimmer);
		color: var(--text-warning-stronger);
	}

	/* --- Summary --- */

	.step-summary {
		display: flex;
		flex-wrap: wrap;
		gap: 0.375rem 1.25rem;
		margin-top: 0.5rem;
		padding-left: 2.125rem;
		font-size: 0.8125rem;
	}

	.summary-item {
		color: var(--text-secondary);
	}

	.summary-label {
		color: var(--text-muted);
		font-weight: 500;
	}

	.summary-arrow {
		color: var(--text-muted);
		margin: 0 0.125rem;
	}

	/* --- Details panel — visually connected to card --- */

	.details-panel {
		border: 1px solid oklch(from var(--border-default) l c h / 1.5);
		border-top: none;
		border-bottom-left-radius: 0.75rem;
		border-bottom-right-radius: 0.75rem;
		padding: 1rem 1.25rem 1.25rem 3.375rem;
		background: var(--bg-primary);
		font-size: 0.8125rem;
	}

	.detail-section {
		margin-bottom: 0.625rem;
	}

	.detail-section:last-child {
		margin-bottom: 0;
	}

	.detail-label {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--text-secondary);
	}

	.instructions-container {
		transition: max-height 0.3s ease;
	}

	.instructions-collapsed {
		max-height: 8rem;
		overflow: hidden;
		position: relative;
	}

	.instructions-collapsed::after {
		content: "";
		position: absolute;
		bottom: 0;
		left: 0;
		right: 0;
		height: 2rem;
		background: linear-gradient(to bottom, transparent, var(--bg-secondary));
		pointer-events: none;
	}

	.instructions-toggle {
		display: inline-block;
		margin-top: 0.25rem;
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--accent-default);
		cursor: pointer;
		background: none;
		border: none;
		padding: 0;
	}

	.instructions-toggle:hover {
		text-decoration: underline;
	}

	.detail-content {
		color: var(--text-primary);
		margin-top: 0.25rem;
		line-height: 1.55;
		font-size: 0.75rem;
		max-width: 65ch;
	}

	.detail-row-inline {
		display: flex;
		gap: 0.375rem;
		align-items: baseline;
		margin-bottom: 0.375rem;
	}

	.detail-value {
		color: var(--text-secondary);
		font-size: 0.75rem;
	}

	.detail-pre {
		color: var(--text-secondary);
		margin-top: 0.25rem;
		overflow-x: auto;
		font-size: 0.75rem;
		font-family: var(--font-mono, monospace);
		background: var(--bg-primary);
		padding: 0.5rem;
		border-radius: 0.375rem;
		border: 1px solid var(--border-default);
	}

	/* --- Contracts --- */

	.contract-fields {
		margin-top: 0.25rem;
	}

	.contract-field {
		padding: 0.1875rem 0;
		font-size: 0.75rem;
	}

	.contract-name {
		font-weight: 600;
		color: var(--accent-default);
	}

	.contract-type {
		color: var(--text-secondary);
		font-size: 0.75rem;
	}

	.contract-desc {
		color: var(--text-secondary);
	}

	.mcp-warning {
		margin-top: 0.5rem;
		padding: 0.375rem 0.5rem;
		border-radius: 0.375rem;
		border: 1px solid var(--border-warning-default);
		background: var(--bg-warning-dimmer);
		color: var(--text-warning-stronger);
		font-size: 0.75rem;
	}

	.suggest-change-link {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		margin-top: 0.625rem;
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--accent-default);
		cursor: pointer;
		background: oklch(from var(--accent-default) l c h / 0.04);
		border: 1px solid oklch(from var(--accent-default) l c h / 0.15);
		border-radius: 999px;
		padding: 0.25rem 0.75rem;
		transition: background 0.15s ease, border-color 0.15s ease;
	}

	.suggest-change-link:hover {
		background: oklch(from var(--accent-default) l c h / 0.08);
		border-color: oklch(from var(--accent-default) l c h / 0.25);
	}

	@media (prefers-reduced-motion: reduce) {
		.step-wrapper {
			animation: none;
		}
	}
</style>
