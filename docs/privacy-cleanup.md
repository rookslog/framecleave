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

Post-push check: the private annotation directory is absent from current main,
but an old annotation remains readable by its original commit ID. The rewritten
branches/tag and sanitized PR description are published. The owner subsequently
accepted the residual metadata exposure and declined a Support request because
further removal effort was not worthwhile. This resolves the privacy readiness
gate; it does not mean the old object was purged. Exact reproduction details are
retained privately, not linked here. Revisit only if the owner's privacy requirement
changes or materially different exposed content is discovered.

Branch/tag rewriting changes commit IDs. Existing clones must be reconciled or
recloned, never merged back with the old history. GitHub-managed PR refs, cached
diffs, old commit URLs and third-party clones can retain removed objects; a
force-push is not an Internet-wide erasure. Repository owners may need GitHub
Support for server-side cached-reference removal. No complete cache purge is claimed.

## Publication checks

Prevention: keep real-job artifacts outside the checkout. Existing `.gitignore`
rules exclude media, annotations and non-synthetic benchmark results; the release
audit rejects forbidden tracked/package entries and private calibration corpora.
Eight regression cases exercise those guards, and Linux CI runs the audit before
packaging. Review prose and PR text separately: these guards do not detect every
private measurement pasted into an otherwise permitted document.

Scan all reachable branch/tag trees and blobs for private fingerprints, account
paths, forbidden media and derived-data artifacts, not merely the current diff.
Inspect PR text and attachments separately. Run tests, source/release audits and
whitespace checks. Only explicitly named branches/tag may be force-pushed, using
expected old ref values; never mirror-push GitHub pull-request refs.
