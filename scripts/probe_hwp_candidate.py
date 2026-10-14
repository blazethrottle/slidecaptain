"""D1 synthetic feasibility experiment; not a production HWP extractor.

Install python-hwpx==6.7.0 separately. No user document or Hancom application
is opened. A new output directory outside the checkout is required.
"""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.out_dir.resolve()
    if output.exists() or output == root or root in output.parents:
        raise SystemExit('Use a new output directory outside the checkout')
    from hwpx import HwpxDocument
    from importlib.metadata import version
    if version('python-hwpx') != '6.7.0':
        raise SystemExit('This experiment requires python-hwpx==6.7.0')
    output.mkdir(parents=True)
    document = HwpxDocument.new()
    document.paragraphs[0].text = '합성 보고서'
    document.add_paragraph('검증된 자료만 사용합니다.')
    table = document.add_table(rows=2, cols=2)
    cells = [['항목', '건수'], ['완료', '8']]
    for row, values in enumerate(cells):
        for col, value in enumerate(values):
            table.cell(row, col).text = value
    results = []
    for extension in ['hwpx', 'hwp']:
        target = output / f'synthetic-table.{extension}'
        document.save_to_path(target)
        read = HwpxDocument.open(target)
        paragraphs = [paragraph.text for paragraph in read.paragraphs]
        tables = list(read.tables)
        assert paragraphs[:2] == ['합성 보고서', '검증된 자료만 사용합니다.']
        assert len(tables) == 1
        assert [[tables[0].cell(row, col).text for col in range(2)] for row in range(2)] == cells
        results.append({'format': extension, 'paragraphs': 'passed', 'table_cells': 'passed',
                        'bytes': target.stat().st_size})
    report = {'library': 'python-hwpx', 'version': '6.7.0', 'synthetic_only': True,
              'results': results, 'real_documents_tested': False, 'production_support': False}
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
