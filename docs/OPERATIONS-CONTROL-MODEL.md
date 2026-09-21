# Operations Control Model

**Operations** is Edge Evidence's control-plane and evidence-governance layer. Its
canonical implementation remains private. This document exposes the reviewed control model
at a public-safe level; it is not an execution surface and grants no operational authority.

```text
intent
→ canonical command identity
→ history / duplicate check
→ policy decision
→ exact runbook binding
→ one authorized attempt
→ execution receipt
→ verification
→ retained evidence
```

The engineering signals in that flow are deterministic command identity, duplicate/replay
refusal, exact runbook binding, fail-closed validation, one-attempt semantics, structured
execution receipts, create-once evidence bundles, and post-execution classification after
verification. These controls make the authorization and evidence trail explicit rather
than allowing desired state or an adapter to become its own execution authority.

The boundary with Infrastructure is deliberate: **Infrastructure describes what reviewed
platform state should exist; Operations controls how an authorized attempt may inspect or
change that state and how the result is verified and evidenced.** Desired state therefore
does not authorize itself to execute.

This public summary omits live adapters, credentials or token material, provider
coordinates, private operational history, real environment identities, and retained
sensitive evidence. It adds no deployment, provider, scheduler, cleanup, or other
operational capability.
