"""One-to-one cut evaluation; exact matching is the default, not a tolerance window."""
from __future__ import annotations


def match_cuts(
    predicted: list[int], reference: list[int], *, tolerance: int = 0,
    duration_seconds: float,
) -> dict:
    """Maximum-cardinality, then minimum-offset monotone matching.

    A nearby prediction cannot satisfy two reference cuts. Empty denominators are
    represented as null rather than manufacturing perfect precision or recall.
    """
    if tolerance < 0 or duration_seconds <= 0:
        raise ValueError("tolerance must be nonnegative and duration positive")
    p, r = sorted(predicted), sorted(reference)
    if tolerance == 0:
        from collections import Counter
        pc, rc = Counter(p), Counter(r)
        shared = pc & rc
        pairs = [(i, i) for i, n in sorted(shared.items()) for _ in range(n)]
        fp = sorted((pc - shared).elements())
        fn = sorted((rc - shared).elements())
    else:
        # Each cell records a direction; rows of (match count, negative cost)
        # retain an optimal score without quadratic Python object storage.
        choices = [bytearray(len(r) + 1) for _ in range(len(p) + 1)]
        previous = [(0, 0)] * (len(r) + 1)
        for i, a in enumerate(p, 1):
            current = [(0, 0)] * (len(r) + 1)
            for j, b in enumerate(r, 1):
                score, direction = previous[j], 1
                if current[j - 1] > score:
                    score, direction = current[j - 1], 2
                if abs(a - b) <= tolerance:
                    q = previous[j - 1]
                    candidate = (q[0] + 1, q[1] - abs(a - b))
                    if candidate >= score:
                        score, direction = candidate, 3
                current[j] = score
                choices[i][j] = direction
            previous = current
        pairs, fp, fn = [], [], []
        i, j = len(p), len(r)
        while i or j:
            direction = choices[i][j] if i and j else (1 if i else 2)
            if direction == 3:
                pairs.append((p[i - 1], r[j - 1]))
                i -= 1
                j -= 1
            elif direction == 1:
                fp.append(p[i - 1])
                i -= 1
            else:
                fn.append(r[j - 1])
                j -= 1
        pairs.reverse()
        fp.sort()
        fn.sort()
    tp = len(pairs)
    precision = tp / len(p) if p else None
    recall = tp / len(r) if r else None
    f1 = 2 * tp / (len(p) + len(r)) if p or r else None
    return {
        "tp": tp, "fp": len(fp), "fn": len(fn), "precision": precision,
        "recall": recall, "f1": f1, "tolerance_frames": tolerance,
        "false_positive_frames": fp, "false_negative_frames": fn,
        "offsets_frames": [a - b for a, b in pairs],
        "false_positives_per_hour": len(fp) * 3600 / duration_seconds,
        "false_negatives_per_hour": len(fn) * 3600 / duration_seconds,
        "duration_seconds": duration_seconds,
    }
