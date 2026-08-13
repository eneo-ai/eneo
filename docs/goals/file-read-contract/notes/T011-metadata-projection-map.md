# T011 metadata-projection map

## Public view evidence

- Direct File GET/list deliberately use `FileService._project_public_files` and
  read persisted transcription bytes into `FilePublic.transcription`.
- Assistant and App public assemblers convert hydrated `File` attachments to
  `FilePublic`, so they also expose transcription even though text/blob are
  discarded.
- Full Space responses discard non-default Assistant/App attachments, but the
  default Assistant can still expose transcription. Sparse Space application
  responses contain `AssistantSparse`/`AppSparse` and discard attachments
  completely.
- Execution, prompt/context-fit, history/replay, transcription, and download
  paths genuinely require verified content and must retain explicit hydration.

Key evidence:

- `backend/src/eneo/files/file_models.py:97`
- `backend/src/eneo/files/file_models.py:121`
- `backend/src/eneo/files/file_service.py:494`
- `backend/src/eneo/assistants/api/assistant_assembler.py:73`
- `backend/src/eneo/assistants/api/assistant_models.py:318`
- `backend/src/eneo/apps/apps/api/app_assembler.py:129`
- `backend/src/eneo/apps/apps/api/app_models.py:54`
- `backend/src/eneo/spaces/space_factory.py:150`
- `backend/src/eneo/spaces/api/space_assembler.py:384`
- `backend/src/eneo/spaces/api/space_router.py:151`

## Canonical ownership

Keep `FileRepository` plus `project_file_info` as the byte-free File projection
owner. Keep `FileContentLoader` as the one authorized grouped byte-hydration
interface. Reuse `FileInfo`; never construct a `File` without its required
text/blob.

The smallest candidate interface is an explicitly named grouped metadata
projection returning ordered `FileInfo`, alongside the existing grouped content
loader returning ordered hydrated `File`. Share tenant validation, reference
selection, deduplication, and ordering internally. Do not add a boolean mode,
provider branch, generic projection framework, cache, or fallback.

## Compatibility decision

`FilePublic.transcription` is optional in the schema but is populated today in
direct File, Assistant, App, and default-Assistant Space responses. A Judge must
decide whether nested aggregate transcription may become `null` while direct
File GET/list remains unchanged, or whether byte-free aggregate behavior needs
a separately named additive response/route. Existing sources do not authorize
silently changing that runtime value.

## Candidate T010 proof

- Corrupt or remove inline and real compatible-store attachment bytes, then
  prove chosen metadata-only views return unchanged metadata and execute zero
  payload queries/remote reads.
- Preserve direct File transcription byte-for-byte.
- Preserve Assistant/App execution, prompt preflight, history/replay, and both
  download contracts through existing focused suites.
- Stop if compatibility requires changing or removing public fields, execution
  receives `FileInfo`, a metadata path reads bytes, or the slice requires a flag,
  partial `File`, provider branch, #569/#571, or Flow work.
