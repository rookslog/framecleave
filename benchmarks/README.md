# Reproducing public measurements

For contributors: generate an original synthetic corpus, then run the benchmark
against its matching generated labels. Public evidence is synthetic only.

```sh
python scripts/synthetic_corpus.py --output /tmp/framecleave-fixtures
python scripts/benchmark.py /tmp/framecleave-fixtures/*.mkv \
  --annotations /tmp/framecleave-fixtures --output /tmp/synthetic-evaluation.json
```

Use a new output directory. Fixture hashes can vary with FFmpeg versions, so
generate matching labels in the same run. Keep the RNG seed and code fixed.
Synthetic labels test specific mechanisms, not natural-footage representativeness.

Local evaluation of permitted media may use the same tooling, but keep originals,
labels, source hashes, predictions, timings, aggregates, reports and diagnostics
outside the repository. Neutral IDs and numeric summaries do not make those
artifacts publishable. Do not attach them to issues, PRs, logs or packages.

Only original generated-fixture results may be checked in. The public privacy
policy covers content-derived metadata as well as pixels and filenames.
See the privacy cleanup record for history and cache limitations.
