# Public detector evaluation

Public evidence uses original random/geometric fixtures, not derivatives of
private footage. Generate fixture videos and matching labels together, then use
the benchmark reproduction instructions. Results are retained in the synthetic
result artifact, including misses and false positives.

The constructed cases include hard cuts, equal-histogram edits, local edits,
interstitials, motion, exposure, flashes, duplicated/dropped updates, noise and
blur. They test mechanisms, not the diversity of natural recordings.

Use one-to-one exact-frame matching. Duplicate predictions are false positives;
review workload is not automatic recall. Candidate-assisted labels require an
explicit coverage limitation and are not exhaustive independently adjudicated truth.
Learned-model and target-platform comparisons cannot be inferred from these cases.

Private annotations, fingerprints, error ordinals and numeric measurements stay
local. They are intentionally unavailable in the public repository and its
rewritten branch/tag history. Cached copies of the old history may still exist.
