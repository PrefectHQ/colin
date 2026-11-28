# Stop invalidation at unchanged compiled results

Recompilation does not necessarily change an upstream result. Propagating every
recompilation through the graph repeats downstream template and provider work.

Compare a dependency fingerprint before adding a freshly compiled source URI to
the set that invalidates dependents. Keep updating the manifest and compiled
output even when the fingerprint is unchanged.

The body hash alone is insufficient: references expose names, descriptions,
publication paths, output formats and named sections. The fingerprint therefore
includes output hashes, names, descriptions, formats, publication status, sections
and file-output metadata. Other frontmatter values are not exposed by project
references and do not affect the fingerprint.

Store the fingerprint as an optional DocumentMeta field. Old manifests load
without migration and conservatively propagate the first recompilation of an
entry without a fingerprint. Compare later results normally. Resolve referenced
output paths back to source URIs when checking propagation.

Dependency ordering, cache policies, expiration and external version checks stay
in place. No-cache runs still start with an empty manifest and compile everything.
