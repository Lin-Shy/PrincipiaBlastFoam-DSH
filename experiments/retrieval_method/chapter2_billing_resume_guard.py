"""仅允许凭新接入证据越过已封存的余额失败；不重新请求失败任务。"""
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('immutable billing recovery receipt drift')
        return
    with path.open('xb') as stream:
        stream.write(data)


def validate_package(folder, role):
    folder = Path(folder).resolve()
    manifest = read(folder / 'manifest.json')
    if manifest.get('schema') != 'knowledge_qa_billing_execution_extension_v1':
        raise ValueError('unregistered billing execution package')
    if role not in {'generation', 'grading', 'controller'}:
        raise ValueError('unknown recovery program role')
    for relative, expected in manifest['files_sha256'].items():
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or sha(path) != expected:
            raise ValueError('billing package program drift')
    for role_name, base in manifest['bases'].items():
        root = Path(base['runtime']).resolve()
        if sha(base['registration_file']) != base['registration_sha256']:
            raise ValueError('frozen registration drift')
        for relative, expected in base['runtime_source_sha256'].items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or sha(path) != expected:
                raise ValueError('original frozen runtime drift: ' + role_name)
    if manifest['grading_mode'] != 'non_preselected_only':
        raise ValueError('this package must keep preselected grading disabled')
    return manifest


def billing_failure(folder, model, endpoint):
    """只接受最后一个已记录请求的精确403 billing_error。"""
    paths = sorted((Path(folder) / 'requests').glob('*.json'))
    if not paths:
        return None
    path = paths[-1]
    record = read(path)
    if (record.get('status') != 'http_rejected' or record.get('endpoint') != endpoint
            or record.get('request', {}).get('model') != model):
        return None
    raw = json.dumps(record['request'], ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    if hashlib.sha256(raw).hexdigest() != record.get('request_sha256'):
        raise ValueError('failed billing request body/hash drift')
    events = record.get('events', [])
    if not events or events[-1].get('status') != 'http_error' or events[-1].get('code') != 403:
        return None
    event = events[-1]
    try:
        error = json.loads(event.get('provider_error_excerpt', ''))['error']
    except (ValueError, KeyError, TypeError):
        return None
    if error != {'message': 'insufficient balance', 'type': 'billing_error'}:
        return None
    started, seconds = event.get('started_unix'), event.get('seconds')
    if (type(started) not in (int, float) or type(seconds) not in (int, float)
            or not math.isfinite(started) or not math.isfinite(seconds) or seconds < 0):
        raise ValueError('billing failure terminal time absent')
    return {'request_file': path.name, 'request_file_sha256': sha(path),
            'request_sha256': record['request_sha256'], 'finished_unix': started + seconds}


def resume_billing_failure(folder, availability, model, endpoint, verifier, output, role):
    """原循环已核验旧结果绑定；新许可仅改变继续到下一任务的控制流。"""
    if availability is None:
        return False
    if role not in {'generation', 'grading'}:
        raise ValueError('unknown billing recovery role')
    failure = billing_failure(folder, model, endpoint)
    if failure is None:
        return False
    permit = verifier(Path(availability), model, endpoint)
    # 原冻结验证器仍执行10分钟、新响应、精确模型、端点、usage与请求哈希检查。
    paths = list((Path(availability) / 'requests').glob('*.json'))
    if len(paths) != 1:
        raise ValueError('single availability ledger required')
    success = [e for e in read(paths[0]).get('events', []) if e.get('status') == 'response']
    if len(success) != 1 or success[0]['started_unix'] <= failure['finished_unix']:
        raise ValueError('availability must follow this billing failure')
    name = 'result.json' if role == 'generation' else 'score.json'
    protected = Path(folder) / name
    if not protected.exists():
        raise ValueError('billing recovery only accepts a recorded terminal task')
    package = Path(__file__).resolve().parent
    manifest = package / 'manifest.json'
    receipt = {**permit, 'schema': 'bound_billing_failure_skip_receipt_v1', 'role': role,
        'prior_failure': failure, 'prior_terminal_file_sha256': sha(protected),
        'execution_extension_manifest_sha256': sha(manifest),
        'helper_sha256': sha(Path(__file__)), 'terminal_status_unchanged': True,
        'failed_task_reissued': False, 'content_retries': 0}
    target = Path(output) / 'availability-amendments' / ('billing-' + permit['summary_sha256']) / (Path(folder).name + '.json')
    save_new(target, receipt)
    return True
