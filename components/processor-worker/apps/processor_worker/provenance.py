"""Generated public-safe provenance constants for the processor distribution."""

SOURCE_IDENTITY = "private-redacted"
PUBLIC_SOURCE_LABEL = "private canonical source (identity withheld)"
PUBLIC_COMMIT_SENTINEL = "0000000000000000000000000000000000000000"

# Legacy template compatibility is rendered only to the public zero sentinel:
# CANONICAL_COMMIT = "0000000000000000000000000000000000000000"
# Compatibility names remain public-safe and never expose the private source.
CANONICAL_REPOSITORY = SOURCE_IDENTITY
CANONICAL_COMMIT = PUBLIC_COMMIT_SENTINEL
