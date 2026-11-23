"""Central source of truth for public JSON-Schema versions.

Every writer that emits `releases.json`, `latest.json`, or
`specifications.json` must import these constants rather than hardcoding
a version string. This prevents a monthly-pipeline path from silently
regressing the schema version and getting rejected (or worse, silently
accepted) by consumers.

`schemas/specifications.schema.json` enforces its exact value with
`const`. `schemas/releases.schema.json` is version-aware: it accepts
exactly the versions in RELEASES_SCHEMA_VERSIONS_ACCEPTED (an `enum`,
never a pattern) and validates each document against the rules of the
version it declares. Committed 3.0.0 manifests therefore stay valid,
while every manifest written from now on declares
RELEASES_SCHEMA_VERSION.
"""

from __future__ import annotations

#: Written into every new releases.json / latest.json. 3.1.0 adds
#: nonconsecutive comparisons (a release whose preceding calendar month
#: has no published DMI).
RELEASES_SCHEMA_VERSION = "3.1.0"
#: Versions releases.schema.json validates. 3.0.0 is kept so published
#: manifests need not be rewritten to change a version number.
RELEASES_SCHEMA_VERSIONS_ACCEPTED = ("3.0.0", "3.1.0")
SPECIFICATIONS_SCHEMA_VERSION = "0.3.0"
