# Claims and limitations

This page separates portfolio navigation from evidence claims, then separates three proof
classes that should not be conflated: generated worker reliability, the local integrated
synthetic demo, and accepted cloud observations.

## Portfolio navigation is not an evidence claim

The canonical repository surfaces are:

- Processor — `edge-evidence-processor`, currently private;
- Replication — `edge-evidence-replication`, currently private;
- Reference Platform — `edge-evidence-reference-platform`, currently private;
- Infrastructure — `edge-evidence-infrastructure`, currently public;
- Operations — `edge-evidence-operations`, currently private;
- Showcase — `edge-evidence-showcase`, currently public.

Visibility records publication state only. Private does not mean unready, public does not
mean complete, and neither visibility state grants implementation, infrastructure,
operations, deployment, or cloud authority.

The still-public `edge-evidence-processor-worker` and
`edge-evidence-replication-worker` repositories are legacy generated/export surfaces.
They remain relevant to the bundled synthetic demo and its provenance, but they are not
the canonical current Processor or Replication component-product repositories.

## Supported by the generated worker exports/showcase bundle

- Separately generated and separately installed processor and replication workers.
- Processor normal processing, committed resume, lock defer/retry, and replay proofs.
- Replication target creation/adoption, immutable create, independent readback, transient
  cleanup, replay, and collision refusal proofs.
- Byte-for-byte handoff of the verified processor report into one deterministic local
  replication target.
- A read-only HTTP adapter with health/readiness endpoints and one fixed synthetic
  demonstration endpoint that accepts no body, query input, evidence, or camera source.
- No credentials, model call, ADK execution, Ollama, or external service call from the
  synthetic workload itself.

## Accepted cloud evidence

- One owner-authorized, authenticated-only Cloud Run deployment in a disposable
  environment passed immutable-image/provider readback and the complete synthetic smoke
  path. Its coordinates and retained evidence remain private.
- A separate reference-platform evidence track has an accepted zero-mutation GKE
  external-exposure observation. It verified the reviewed synthetic three-service
  workload and bounded same-origin HTTP journey under a stable provider state.
- Those cloud facts are evidence of bounded reviewed events, not a claim that this
  showcase is deployment authority or that the resulting environment is a persistent
  evidence system.

## Deliberately not claimed

- Physical camera, NAS, private evidence, footage, or field integration.
- Production-grade deployment, continuous operation, general availability, performance,
  fleet scale, uptime, or SLOs.
- Persistent hosted evidence authority.
- Equivalence between provider smoke/observation evidence and durable private evidence.
- Authorization for independent provider operations, IAM changes, infrastructure
  expansion, scheduler activation, or retained-state deletion outside reviewed controls.
- Final stable-address ownership/binding, public DNS naming, ManagedCertificate/TLS/HTTPS,
  or a permanent public endpoint.
- Publication of provider coordinates, private topology, credentials, Terraform state, or
  retained private evidence payloads.

The Reference Platform, Processor, Replication, and Operations repositories are currently
private. Until their public release is separately approved, this showcase names those
canonical surfaces without fabricating public links. Infrastructure and Showcase are
currently public, but that visibility does not add readiness, cloud-authority, production,
or evidence claims.
