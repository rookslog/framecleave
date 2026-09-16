# Public-data boundary and history cleanup

Audience: maintainers preparing a public commit or release. Before publication,
keep private media **and all derived metadata** outside the repository. This
includes thumbnails, labels, source hashes, cut timings, predictions, per-job
diagnostics and aggregate measurements. Anonymized numeric data is not exempt.
Original synthetic fixtures, generated measurements and benchmark tools may stay.

## Owner decision — 2026-09-16

The owner authorized removing private-derived evaluation data and rewriting
published branches and the existing release-candidate tag. Sanitized documents
retain workflow rationale and synthetic evidence, not private measurements.
Personal commit email and a local account path were redacted as part of cleanup.
The alternative, a deletion-only commit, was rejected because ancestors would
still expose the data. A pre-cleanup Git bundle is retained privately for recovery.
Runtime behavior and original videos/reports are outside the cleanup write set.

## Limits

Branch/tag rewriting changes commit IDs. Existing clones must be reconciled or
recloned, never merged back with the old history. GitHub-managed PR refs, cached
diffs, old commit URLs and third-party clones can retain removed objects; a
force-push is not an Internet-wide erasure. Repository owners may need GitHub
Support for server-side cached-reference removal. No complete cache purge is claimed.

## Publication checks

Scan all reachable branch/tag trees and blobs for private fingerprints, account
paths, forbidden media and derived-data artifacts, not merely the current diff.
Inspect PR text and attachments separately. Run tests, source/release audits and
whitespace checks. Only explicitly named branches/tag may be force-pushed, using
expected old ref values; never mirror-push GitHub pull-request refs.
