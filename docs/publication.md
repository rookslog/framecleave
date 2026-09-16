# Publication guidelines

Audience: maintainers preparing a public commit or release. Before publication,
keep private media **and all derived metadata** outside the repository. This
includes thumbnails, labels, source hashes, cut timings, predictions, per-job
diagnostics and aggregate measurements. Anonymized numeric data is not exempt.
Original synthetic fixtures, generated measurements and benchmark tools may stay.

## Publication checks

Scan all reachable branch/tag trees and blobs for private fingerprints, account
paths, forbidden media and derived-data artifacts, not merely the current diff.
Inspect PR text and attachments separately. Run tests, source/release audits and
whitespace checks before publication.
