# Comment and readability standard

## Comment standard: why, not what

Developers can read code. Comments that restate code are defects because they create noise and become stale.

Allowed comments:

- explain a non-obvious business rule
- explain a non-obvious ordering constraint
- explain why the obvious/simple approach is wrong
- explain a production incident or historical constraint
- explain transactional or idempotency requirements
- explain security or privacy constraints
- link to an ADR, ticket, migration, or incident when relevant

Forbidden comments:

- comments that restate the function name
- comments that narrate obvious control flow
- comments that compensate for bad names
- comments that say "temporary" without an owner and concrete removal
  condition; include a deadline only when it drives an enforceable removal
  decision
- comments that preserve uncertainty such as "maybe", "probably", or "should work"
- comments that describe old behavior after a refactor
- commented-out code

Before adding a comment that explains what code does, first try:

1. rename the variable/function/class
2. extract a function with a better name
3. introduce a value object/type
4. split the branch into named cases
5. move the code to a better module

Extraction is useful only when it improves ownership, locality, or the
abstraction level of the caller. Do not create a pass-through helper merely to
remove a comment or shorten a function.

A comment is suspicious if deleting it would not make the code harder to
understand. A comment is required if deleting it would hide a non-obvious
decision, invariant, or trade-off.

## Naming standard

Prefer domain language over technical placeholder names. Flag `data`, `result`,
`item`, `obj`, `manager`, `processor`, `handler`, and `helper` when the name
hides ownership, lifecycle phase, or domain meaning.

Names should reveal:

- the domain concept
- the lifecycle phase
- the canonical owner
- whether the value is persisted, derived, external, or transient

## Readability findings

Every readability finding must include file:line evidence, the hidden concept,
the proposed name or structure, why the change improves human comprehension,
and any test or migration impact.
