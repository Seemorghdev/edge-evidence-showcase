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

- The current accepted Reference Platform application/cloud path is an owner-authorized
  bounded public Cloud Run recruiter deployment of Web UI, Evidence API, and Edge Agent.
  Synthetic artifact, health/inspection, exact-origin CORS, automated Firefox browser,
  and final provider-readback checks passed. Private provider coordinates and retained
  evidence remain unpublished.
- The current accepted Showcase live path is an owner-authorized public-safe Heroku
  recruiter deployment using exactly one Basic `web` dyno, zero add-ons, and no unexpected
  process types. HTTPS smoke plus Firefox/browser, console, and network checks passed
  against the accepted release.
- The earlier zero-mutation GKE external-exposure observation remains valid deeper platform
  evidence for the state it recorded.
- A historical, bounded owner-authorized authenticated-only Showcase Cloud Run deployment
  in a disposable environment also passed immutable-image/provider readback and the
  complete synthetic smoke path.
- Retained Cloud Run/Heroku adapters are bounded compatibility/proof surfaces; their
  presence does not make this repository provider authority.
- These cloud facts are evidence of bounded reviewed events, not a claim that this
  showcase is deployment authority, production infrastructure, or a persistent evidence
  system.

## Deliberately not claimed

- Physical camera, NAS, private evidence, footage, or field integration.
- Production-grade deployment, continuous operation, general availability, performance,
  fleet scale, uptime, or SLOs.
- Persistent hosted evidence authority.
- Equivalence between provider smoke/observation evidence and durable private evidence.
- Authorization for independent provider operations, IAM changes, infrastructure
  expansion, scheduler activation, or retained-state deletion outside reviewed controls.
- Custom-domain/DNS ownership, custom certificate naming, persistent-address guarantees,
  or production availability.
- Publication of provider coordinates, private topology, credentials, Terraform state, or
  retained private evidence payloads.

The Reference Platform, Processor, Replication, and Operations repositories are currently
private. Until their public release is separately approved, this showcase names those
canonical surfaces without fabricating public links. Infrastructure and Showcase are
currently public, but that visibility does not add readiness, cloud-authority, production,
or evidence claims.
