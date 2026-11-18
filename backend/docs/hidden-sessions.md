# Hidden sessions

Some conversations live in the regular `sessions` / `questions` tables so
streaming, history replay, model selection and tool calling all work, but must
never appear in session, conversation, insights, analytics or export reads:

| Kind | Link table | Owner surface |
| --- | --- | --- |
| Helper runs (e.g. the Prompt Guide) | `help_assistant_runs` | `HelperRunService` |
| Insights conversations (the analysis chat in an assistant's or group chat's insights) | `insight_conversations` | `InsightConversationService` |

The rule lives in one place, `eneo.sessions.hidden_sessions`:
`hidden_session_clause(session_id_col)` is a `NOT EXISTS` per link table, and
`exclude_hidden_sessions(query, col)` applies it. The reads that apply it:

- `SessionRepository._exclude_helper_run_sessions` (every session read in
  `sessions_repo`: single sessions, ownership, chat partners, recent
  conversations, message feedback, the per-assistant and per-group-chat lists,
  tenant export);
- `analysis_repo._exclude_helper_run_sessions` (every session or question
  read and count behind the insights and analytics endpoints);
- `QuestionRepository.get_by_service` and `get_by_tenant` (exports);
- the per-user token usage analyzer;
- the insights tools' own reads and the insights figures (summary, activity,
  ratings inbox, target list, knowledge use, common questions, tool use and
  the findings with their cases) in `InsightsRepository`, so one analysis
  never reads or counts another.

Adding a new kind of hidden session means adding one `NOT EXISTS` to
`hidden_session_clause` and nothing else. The owner service loads its own
hidden sessions through a documented exception accessor on `SessionRepository`
(`get_for_helper_run`, `get_for_insight_conversation`), which is tenant-scoped
and restricted to rows that carry the link.

## Hidden assistants are another rule

`Assistants.hidden` marks an assistant that answers only where it was made
for, such as a helper chat's (a flow authoring chat is one). It decides which assistants are shown:
the chat partner list and the assistant counts leave hidden assistants out.
Their conversations are not hidden sessions: they stay in the session and
question figures, which measure model use, and a helper chat is reached
through its own `helper_chats` row.

## Sources are another rule

A conversation's principal is its source (`eneo.sessions.session_source`): a
user, a service API key or a widget visitor. API-key and widget conversations
are not hidden: the insights and analytics figures and the insights explore
list count and list them, each tagged with its source. They have no `users`
row, so these reads scope their tenant through `questions.tenant_id` or the
conversation's assistant or group chat, never through `users`. Per-user views
(a user's own conversation list, the active user count, per-user token usage)
filter on `sessions.user_id` and so never show them.

## Consequences

- The operator's own conversation list (`GET /conversations/?assistant_id=`)
  never lists insights conversations even though the session row carries the
  operator as `user_id`.
- Per-user token usage does not include helper runs or insights
  conversations. The tenant-wide usage per model does, as model use.
- Retention and cascade behave like any other session: deleting the analysed
  assistant or group chat removes its insights conversations. Retention never
  applies the hidden-session rule; an emptied session goes with its link row.
- An insights conversation is a copy of what its tools read: each tool
  registers the questions whose text it returns as sources
  (`eneo.data_retention.derivations`). Once one of them is removed, every read
  of the analysis answers 410 `derived_source_removed`, its history list
  leaves it out, and the derived copies task removes it.
- Conversation history removes an analysis of an assistant on that
  assistant's period, since its questions carry the assistant. An analysis of
  a group chat has no answering assistant on its questions, so no period
  selects them: it goes with a source it read, with the group chat, or when
  the operator deletes it. Its name follows the group chat's shortest member
  period like any group chat conversation.
