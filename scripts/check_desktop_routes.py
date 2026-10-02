"""Check (or explicitly regenerate) native bridge routes from the shared OpenAPI."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    schema = json.loads((ROOT / 'backend/openapi.json').read_text())
    routes = [{'path': path, 'methods': [method.upper() for method in entry
                                      if method in {'get', 'post', 'put', 'delete'}]}
              for path, entry in schema['paths'].items() if path.startswith('/api/')]
    target = ROOT / 'desktop/api-routes.json'
    if args.write:
        target.write_text(json.dumps(routes, indent=2) + '\n')
    if json.loads(target.read_text()) != routes:
        raise SystemExit('Native API routes differ from OpenAPI; run check_desktop_routes.py --write')
    print(f'{len(routes)} native API routes match OpenAPI')


if __name__ == '__main__':
    main()
