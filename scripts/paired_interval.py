"""Estimate the difference between two named systems on matched scenario families."""
import csv
import json
import random
from collections import defaultdict
from math import floor
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]


def interval(first, second):
    if first == second:
        raise ValueError('Choose two different systems')
    cases = json.loads((ROOT / 'data/scenarios.json').read_text())
    config = json.loads((ROOT / 'compass/config.json').read_text())
    weights = config['dimension_weights']
    scores = {first: {}, second: {}}
    with (ROOT / 'data/trial-scores.csv').open() as handle:
        for row in csv.DictReader(handle):
            if row['system'] in scores:
                slots = scores[row['system']]
                key = row['case_id'], int(row['trial'])
                if key in slots:
                    raise ValueError('Duplicate trial')
                slots[key] = float(row['points'])
    expected = {(case['id'], n) for case in cases for n in (1, 2, 3)}
    if any(set(slots) != expected for slots in scores.values()):
        raise ValueError('A complete pair of full-bank runs is required')
    by_family = {dim: defaultdict(list) for dim in weights}
    for c in cases:
        gap = fmean(scores[first][c['id'], n] - scores[second][c['id'], n] for n in (1, 2, 3))
        by_family[c['dimension']][c['family_id']].append(gap)
    gaps = {d: [fmean(families[f]) for f in sorted(families)] for d, families in by_family.items()}
    return bootstrap(gaps, config)


def bootstrap(gaps, config):
    """Return point estimate and percentile interval in the released dimension order."""
    weights = config['dimension_weights']
    rng = random.Random(config['bootstrap_seed'])
    draws = sorted(sum(w * fmean(rng.choices(gaps[d], k=len(gaps[d]))) for d, w in weights.items())
                   for _ in range(config['bootstrap_replicates']))

    def percentile(p):
        index = (len(draws) - 1) * p
        lo = floor(index)
        return draws[lo] + (index - lo) * (draws[lo + 1] - draws[lo])

    return sum(w * fmean(gaps[d]) for d, w in weights.items()), percentile(.025), percentile(.975)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first')
    parser.add_argument('second')
    args = parser.parse_args()
    delta, low, high = interval(args.first, args.second)
    print(f'{args.first} minus {args.second}: {delta:+.2f} points (95% paired interval {low:+.2f} to {high:+.2f})')
