"""Read a public runtime contract with the digest supplied by the new dispatch."""
import argparse
import hashlib
import json
from pathlib import Path


def inspect(path, expected_sha256):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Public runtime identity mismatch')
    value = json.loads(raw)
    if value.get('schema') != 'c3-openfoam-public-runtime-v1':
        raise ValueError('Unsupported public runtime schema')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=Path(__file__).with_name('RUNTIME.json'))
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.file, args.expected_sha256), ensure_ascii=False, indent=2))
