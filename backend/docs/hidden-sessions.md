# Hidden sessions

Some conversations live in the regular `sessions` / `questions` tables so
streaming, history replay, model selection and tool calling all work, but must
never appear in session, conversation, insights, analytics or export
endpoints:

| Kind | Link table | Owner surface |
| --- | --- | --- |
| Helper runs (e.g. the Prompt Guide) | `help_assistant_runs` | `HelperRunService` |
| Insight conversations (the Insights tab's analysis chat) | `insight_conversations` | `InsightConversationService` |

The rule lives in one place, `eneo.sessions.hidden_sessions`:
`hidden_session_clause(session_id_col)` is a `NOT EXISTS` per link table, and
`exclude_hidden_sessions(query, col)` applies it. Every repository query that
returns session or question rows, or aggregates derived from them, applies it
(`SessionRepository._exclude_helper_run_sessions`, the module-level helper in
`analysis_repo`, `questions_repo`, the token-usage analyzer).

Adding a new kind of hidden session means adding one `NOT EXISTS` to
`hidden_session_clause` and nothing else. The owner service loads its own
hidden sessions through a documented exception accessor on
`SessionRepository` (`get_for_helper_run`, `get_for_insight_conversation`),
which is tenant-scoped and restricted to rows that carry the link.

Consequences to keep in mind:

- The operator's own conversation sidebar (`GET /conversations/?assistant_id=`)
  never lists insight conversations even though the session row carries the
  operator as `user_id`.
- Token-usage analytics do not include helper runs or insight conversations.
- Retention and cascade behave like any other session: deleting the target
  assistant or group chat removes its insight conversations.
