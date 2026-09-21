# Reference Platform

The **Reference Platform** is Edge Evidence's application/product layer around the
deterministic evidence components. Its canonical source remains private; this document is
a public-safe architectural summary, not a source mirror and not a new authority surface.

It consists of three independently packaged services:

- **Web UI** — browser interaction for the bounded reviewer journey.
- **Evidence API** — artifact retrieval and application-facing evidence access.
- **Edge Agent** — bounded inspection at the application edge without acquiring evidence,
  worker, deployment, or persistent-host authority.

Together they provide browser interaction, artifact retrieval, bounded inspection, and
same-origin integration around release-pinned deterministic component contracts and
outputs. Reviewer paths include local/containerized review plus separately accepted bounded
cloud reviewer evidence. The accepted cloud evidence demonstrates the reviewed
three-service application path and browser/client integration without making the hosted
surface a persistent evidence authority.

Processor and Replication retain authority for their evidence-processing and replication
state/contracts; the Reference Platform consumes those boundaries rather than absorbing
them.

This summary does **not** claim production SLOs, production traffic, persistent hosted
evidence authority, a public canonical source repository, or private provider coordinates.
It publishes no credentials, private topology, retained evidence payloads, or live
environment identities.
