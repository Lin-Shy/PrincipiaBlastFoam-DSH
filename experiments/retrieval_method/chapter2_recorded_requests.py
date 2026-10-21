"""Reuse recorded terminal requests without retrying unresolved calls."""
import json

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))


def recorded_or_new(client, body, turn):
    path = client.folder / f'{turn:02d}.json'
    if not path.exists():
        return client(body, turn)
    record = read(path)
    if record.get('request') != body or record.get('endpoint') != client.deployment.endpoint:
        raise ValueError('Existing request identity differs')
    if record['status'] in {'in_flight', 'prepared'}:
        raise ValueError('Unresolved request must be separately sealed, never reissued')
    if record.get('raw_response') is not None:
        record = dict(record, response=record['raw_response'])
    return record
