<script lang="ts">
	import { Mic, MicOff, Square, Loader2 } from 'lucide-svelte';
	import { Tooltip } from '@intric/ui';
	import { m } from '$lib/paraglide/messages';
	import { browser } from '$app/environment';
	import { onDestroy } from 'svelte';

	export let onTranscriptionComplete: (text: string) => void;
	export let onInterimUpdate: (text: string) => void;

	type State = 'idle' | 'starting' | 'recording';
	let state: State = 'idle';
	let error: string | null = null;

	// Audio level visualization (same approach as AudioRecorder.svelte)
	let volumeLevel = 0;
	let audioContext: AudioContext | null = null;
	let analyserNode: AnalyserNode | null = null;
	let levelBuffer = new Float32Array();
	let mediaStream: MediaStream | null = null;
	let animFrameId: number | null = null;

	function startAudioLevelMonitoring(stream: MediaStream) {
		mediaStream = stream;
		audioContext = new AudioContext();
		analyserNode = audioContext.createAnalyser();
		levelBuffer = new Float32Array(analyserNode.fftSize);
		const source = audioContext.createMediaStreamSource(stream);
		source.connect(analyserNode);

		const tick = () => {
			if (analyserNode && levelBuffer.length > 0) {
				analyserNode.getFloatTimeDomainData(levelBuffer);
				let sumSquares = 0;
				for (const amplitude of levelBuffer) {
					sumSquares += amplitude * amplitude;
				}
				const rms = Math.sqrt(sumSquares / levelBuffer.length);
				volumeLevel = Math.min(1, rms / 0.15);
			}
			animFrameId = requestAnimationFrame(tick);
		};
		animFrameId = requestAnimationFrame(tick);
	}

	function stopAudioLevelMonitoring() {
		if (animFrameId !== null) {
			cancelAnimationFrame(animFrameId);
			animFrameId = null;
		}
		volumeLevel = 0;
		if (audioContext) {
			audioContext.close();
			audioContext = null;
			analyserNode = null;
		}
		if (mediaStream) {
			mediaStream.getTracks().forEach((t) => t.stop());
			mediaStream = null;
		}
	}

	// SpeechRecognition support (Chromium + Safari 14.1+)
	function getSpeechRecognitionCtor(): (new () => any) | null {
		if (!browser) return null;
		return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
	}
	const isSupported = browser && !!getSpeechRecognitionCtor();

	/**
	 * Join SpeechRecognition segments into natural text.
	 * Each "final" segment starts with a capital letter, so we:
	 * - add ". " between final segments (pause = sentence break)
	 * - append any in-progress interim text at the end
	 */
	function buildTranscript(finals: string[], interim: string): string {
		let result = '';
		for (let i = 0; i < finals.length; i++) {
			const seg = finals[i];
			if (!seg) continue;

			if (i === 0) {
				result = seg;
			} else {
				const lastChar = result.slice(-1);
				if (lastChar && !'.!?'.includes(lastChar)) {
					result += '.';
				}
				result += ' ' + seg;
			}
		}
		if (interim) {
			if (result) {
				const lastChar = result.slice(-1);
				if (lastChar && !'.!?'.includes(lastChar)) {
					result += '.';
				}
				result += ' ' + interim;
			} else {
				result = interim;
			}
		}
		return result;
	}

	let recognition: any = null;

	function handleStart() {
		if (state !== 'idle') return;
		error = null;
		state = 'starting';

		const Ctor = getSpeechRecognitionCtor()!;
		recognition = new Ctor();
		recognition.continuous = true;
		recognition.interimResults = true;
		recognition.lang = document.documentElement.lang || 'en';

		let finalSegments: string[] = [];
		let currentInterim = '';

		recognition.onstart = () => {
			state = 'recording';
			navigator.mediaDevices.getUserMedia({ audio: true })
				.then((stream) => startAudioLevelMonitoring(stream))
				.catch(() => { /* volume viz is optional */ });
		};

		recognition.onresult = (event: any) => {
			finalSegments = [];
			currentInterim = '';

			for (let i = 0; i < event.results.length; i++) {
				const text = event.results[i][0].transcript;
				if (event.results[i].isFinal) {
					finalSegments.push(text.trim());
				} else {
					currentInterim += text;
				}
			}

			onInterimUpdate(buildTranscript(finalSegments, currentInterim.trim()));
		};

		recognition.onerror = (event: any) => {
			if (event.error === 'not-allowed') {
				error = m.voice_input_error_no_mic();
			} else if (event.error !== 'aborted') {
				error = m.voice_input_error_transcription();
			}
			onInterimUpdate('');
			stopAudioLevelMonitoring();
			state = 'idle';
			recognition = null;
		};

		recognition.onend = () => {
			const text = buildTranscript(finalSegments, currentInterim.trim());
			if (text) {
				onTranscriptionComplete(text);
			}
			onInterimUpdate('');
			stopAudioLevelMonitoring();
			state = 'idle';
			recognition = null;
		};

		try {
			recognition.start();
		} catch {
			error = m.voice_input_error_transcription();
			state = 'idle';
			recognition = null;
		}
	}

	function handleStop() {
		if (recognition) {
			recognition.stop();
		}
	}

	onDestroy(() => {
		stopAudioLevelMonitoring();
		if (recognition) {
			try { recognition.abort(); } catch {}
		}
	});
</script>

{#if isSupported}
	{#if state === 'idle'}
		<Tooltip text={error || m.voice_input_start()} placement="top">
			<button
				type="button"
				onclick={handleStart}
				class="hover:bg-accent-dimmer hover:text-accent-stronger border-default hover:border-accent-default flex h-8 w-8 items-center justify-center rounded-full border transition-colors"
				class:text-negative-stronger={!!error}
				aria-label={m.voice_input_start()}
			>
				<Mic class="h-4 w-4" />
			</button>
		</Tooltip>
	{:else if state === 'recording'}
		<div class="flex items-center gap-1.5">
			<Tooltip text={m.voice_input_stop()} placement="top">
				<button
					type="button"
					onclick={handleStop}
					class="voice-record-btn bg-negative-dimmer text-negative-stronger border-negative-default flex h-8 w-8 items-center justify-center rounded-full border"
					aria-label={m.voice_input_stop()}
				>
					<Square class="h-3.5 w-3.5" />
				</button>
			</Tooltip>
			<div class="volume-bar-track">
				<div class="volume-bar-fill" style="transform: scaleX({volumeLevel})"></div>
			</div>
		</div>
	{:else}
		<div class="border-default text-secondary flex h-8 w-8 items-center justify-center rounded-full border">
			<Loader2 class="h-4 w-4 animate-spin" />
		</div>
	{/if}
{:else if browser}
	<Tooltip text={m.voice_input_unsupported_browser()} placement="top">
		<div
			class="border-default text-tertiary flex h-8 w-8 cursor-not-allowed items-center justify-center rounded-full border opacity-50"
			role="img"
			aria-label={m.voice_input_unsupported_browser()}
		>
			<MicOff class="h-4 w-4" />
		</div>
	</Tooltip>
{/if}

<style lang="postcss">
	@reference "@intric/ui/styles";

	@keyframes breathe-ring {
		0%, 100% {
			transform: scale(1);
			opacity: 0.4;
		}
		50% {
			transform: scale(1.15);
			opacity: 0;
		}
	}

	.voice-record-btn {
		position: relative;
	}

	.voice-record-btn::before {
		content: "";
		position: absolute;
		inset: -3px;
		border-radius: 9999px;
		border: 2px solid currentColor;
		animation: breathe-ring 2s ease-in-out infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.voice-record-btn::before {
			animation: none;
			opacity: 0;
		}
	}

	.volume-bar-track {
		@apply h-2 w-14 overflow-hidden rounded-full;
		background: linear-gradient(90deg, #e5e7eb 0%, #d1d5db 100%);
	}

	:global(.dark) .volume-bar-track {
		background: linear-gradient(90deg, #374151 0%, #4b5563 100%);
	}

	.volume-bar-fill {
		@apply h-full origin-left rounded-full;
		background: linear-gradient(90deg, #4ade80 0%, #facc15 70%, #f87171 100%);
		transition: transform 50ms linear;
	}
</style>
