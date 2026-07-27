# T010 lease revision

Source revision: `a8418c40f28650238fa7a421bdb8d0ff9bb300ef`

The first Claude plan review returned `changes_required` at MIN_SCORE 5. It
confirmed that the original lease could not both reuse `SpaceActor` and prohibit
partial `Space` objects. It also identified the existing `SpaceFactory`
attachment hydration fence as a deliberate invariant that must not be weakened.

The Goal Maker Judge selected a typed authorization seam, then explicitly
approved scope amendment B′ after source review found a duplicate mapper:

- `SpaceActor` authorizes immutable `SpaceAccessFacts` instead of depending on a
  complete `Space` aggregate.
- Complete Space reads and the new sparse applications projection adapt into the
  same actor policy.
- `SpaceRepository` owns only the sparse queries, active-row filtering, ordering,
  and one factory call.
- `SpaceFactory` owns the additive DB-row-to-projection mapping and reuses the
  existing `_build_or_skip` validation belt. It may not change
  `create_space_from_db`, the hydration fence, or aggregate construction.
- Completion-model parity uses
  `completion_model_repo.all(with_deprecated=True)` plus a local O(1) id map;
  current AssistantSparse behavior does not use Space model mappings here.
- `SpaceAssembler` keeps one implementation for response mapping, ordering,
  filtering, item/list permissions, and API-key caps.
- `SpaceService` remains the endpoint authorization boundary.
- Every public schema, sibling route, aggregate factory behavior, and real byte
  consumer remains unchanged.

The unloaded-attachment alternative was rejected: representing persisted
attachments as an empty list would create false domain state.

The paused source-thread draft was accepted only as untrusted input. It had
already fixed deleted user/group query filtering and moved mapping into the
factory, but it must still restore `create_space_from_db`, remove the incorrect
Space completion-model filter from the sparse mapper, seal role mappings for
immutable O(1) lookup, and add focused factory/human-membership parity tests.

The current integration RED draft is untrusted until it also proves persisted
transcription, installs an independent byte-read tripwire, uses a full-Space
positive control for the SQL listener, resets observations, and compares the
complete `Applications` JSON. Its initial unchanged run did fail on source in
13.07 seconds and captured six forbidden queries beginning with
`assistants_files`, so the underlying performance defect is verified.
