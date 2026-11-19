"""Refresh the score download for the static report served from docs/."""

import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    results = json.loads((ROOT / 'data/results.json').read_text())
    config = json.loads((ROOT / 'compass/config.json').read_text())
    dimensions = list(config['dimension_weights'])
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(['system', 'cases', 'trials', 'composite', *dimensions,
                     'interval_low', 'interval_high'])
    for result in results:
        writer.writerow([result['system'], result['cases'], result['trials'],
                         result['composite'], *(result['dimensions'][d] for d in dimensions),
                         *result['interval']])
    scores = ROOT / 'docs/scores.csv'
    published = buffer.getvalue().encode('utf-8')
    if not scores.exists() or scores.read_bytes() != published:
        scores.write_bytes(published)
    print('The report is maintained in docs/index.html. Its score download is up to date.')


if __name__ == '__main__':
    main()
