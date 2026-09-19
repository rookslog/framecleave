# Publication guidelines

Audience: maintainers preparing a public commit or release. Before publication,
keep private media **and all derived metadata** outside the repository. This
includes thumbnails, labels, source hashes, cut timings, predictions, per-job
diagnostics and aggregate measurements. Anonymized numeric data is not exempt.
Original synthetic fixtures, generated measurements and benchmark tools may stay.

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
whitespace checks before publication.
