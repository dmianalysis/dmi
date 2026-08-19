"""Central source of truth for public JSON-Schema versions.

Every writer that emits `releases.json`, `latest.json`, or
`specifications.json` must import these constants rather than hardcoding
a version string. This prevents a monthly-pipeline path from silently
regressing the schema version and getting rejected (or worse, silently
accepted) by consumers.

The corresponding schema files at `schemas/releases.schema.json` and
`schemas/specifications.schema.json` enforce these exact values with
`const`, so any drift here surfaces immediately in schema-validation
tests.
"""

from __future__ import annotations

RELEASES_SCHEMA_VERSION = "3.0.0"
SPECIFICATIONS_SCHEMA_VERSION = "0.3.0"
