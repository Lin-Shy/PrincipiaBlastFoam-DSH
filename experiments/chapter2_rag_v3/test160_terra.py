"""Owner-amended GPT transport. Old scores keep their actual model identity.

The legacy gpt_sol identifier is a storage/JSON-contract slot, never a model claim.
Only body.model changes; no prompt, anonymous item, grade or frozen file is changed.
"""
import argparse
from copy import deepcopy
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import single_pass_dev40 as s
import test160_evaluation as ev
import dev40_finalize as rec
import scoring
from central_execution import Registry, exclusive_lock
from judge_api_adapter import digest
from test160_resume_scores import slot

BASE = s.RUN / 'test160_runs'
CONFIG = Path(__file__).resolve().parents[2] / 'config/llm/test160_gpt_runtime.json'
LEGACY_REQUEST = rec.request


def amendment():
    cfg = s.load(CONFIG)
    a = s.load(s.RUN / cfg['amendment'])
    assert cfg['api_model_id'] == a['new_model'] == 'gpt-6.1-terra'
    assert a['runtime_config_sha256'] == s.sha(CONFIG)
    assert a['manifest_sha256'] == s.sha(ev.runner.MANIFEST)
    assert a['historical_model_identity_preserved'] and a['new_requests_only']
    return cfg, a


def request(judge, item):
    profile, req, count = LEGACY_REQUEST(judge, item)
    if judge != 'gpt_sol':
        return profile, req, count
    cfg, _ = amendment()
    profile = deepcopy(profile)
    req = deepcopy(req)
    profile.update(model_id=cfg['api_model_id'], allowed_response_model_ids=cfg['allowed_response_model_ids'])
    req['body']['model'] = cfg['api_model_id']
    req['profile_sha256'] = digest(profile)
    req['request_sha256'] = digest(req['body'])
    return profile, req, count


def check_request(saved, item):
    """Allow exactly the authorized model-only delta from the frozen wire body."""
    profile, old, _ = LEGACY_REQUEST('gpt_sol', item)
    actual = deepcopy(saved['request'])
    model = actual['body']['model']
    assert model in ('gpt-6-sol', 'gpt-6.1-terra')
    actual['body']['model'] = old['body']['model']
    assert actual['body'] == old['body'] and actual['url'] == old['url']
    expected_profile = deepcopy(profile)
    expected_profile.update(model_id=model, allowed_response_model_ids=[model])
    assert saved['profile'] == expected_profile
    assert saved['request_sha256'] == digest(saved['request']['body'])
    assert saved['packet_item_sha256'] == digest(item)


def verify_canonical(root, item):
    """Read-only validation used by amended reporting, including old score reuse."""
    parsed = s.load(root/'parsed.json')
    resolution = s.load(root/'resolution.json')
    source = Path(resolution['source'])
    saved = s.load(source/'request.json')
    check_request(saved, item)
    actual = scoring.parse_current(saved['profile'], s.load(source/'response.txt'), item)
    assert actual['record'] == parsed['record']
    assert actual['response_model'] == parsed['response_model']
    assert actual['raw_response_sha256'] == parsed['raw_response_sha256']
    assert s.sha(source/'response.txt') == resolution['response_sha256']
    return 'valid'


def inspect(root, item):
    if item['generation_failed']:
        return False, 'formal_generation_failure'
    if (root/'parsed.json').exists():
        return False, 'reuse_valid'
    if (root/'input_hold.json').exists():
        return False, 'input_hold'
    attempts = rec.folders(root)
    valid = []; holds = []
    for folder in attempts:
        saved = s.load(folder/'request.json')
        check_request(saved, item)
        if not (folder/'response.txt').exists():
            holds.append('transport_unknown_no_resend')
            continue
        try:
            raw = s.load(folder/'response.txt')
        except ValueError:
            holds.append('identity_or_invalid_hold')
            continue
        state = s.load(folder/'status.json') if (folder/'status.json').exists() else {}
        try:
            parsed = scoring.parse_current(saved['profile'], raw, item)
        except (ValueError, KeyError, TypeError):
            error = raw.get('error') if isinstance(raw, dict) else None
            explicit = isinstance(error, dict) and not raw.get('choices') and not raw.get('output')
            if state.get('http_status') in rec.RETRY_HTTP:
                continue
            if explicit and (state.get('http_status') == 403 or error.get('code') == 'model_not_found' or error.get('type') == 'upstream_error'):
                continue
            if state.get('reason') in ('Duplicate/mismatched criteria', 'Truncated/multiple response', 'Unexpected or missing contract fields', 'Provider exceeds 32K combined context'):
                continue
            holds.append('identity_or_invalid_hold')
        else:
            valid.append((folder, parsed))
    if valid:
        # Earliest valid response, never highest grade.
        folder, parsed = valid[0]
        if not (folder/'parsed.json').exists():
            s.save(folder/'parsed.json', parsed)
        s.save(root/'parsed.json', parsed)
        s.save(root/'resolution.json', dict(status='valid', source=str(folder), response_sha256=s.sha(folder/'response.txt'), parsed_sha256=s.sha(folder/'parsed.json'), model_amendment='test160_gpt_terra_amendment_v1'))
        return False, 'recovered_saved_response'
    if holds:
        return False, 'transport_unknown_no_resend' if 'transport_unknown_no_resend' in holds else holds[0]
    if len(list((root/'recovery').glob('attempt_*'))) >= 3:
        return False, 'attempt_limit'
    return True, 'pending'


def run(auth, probe=False):
    cfg, a = amendment()
    rec.dc.guard_operational()
    reg = Registry()
    jobs = []; held = Counter(); completed = Counter(); stop = threading.Event()
    for mode, base in [('agentic', BASE), ('single_pass', BASE/'supplement/single_pass')]:
        ev.authorize(auth, mode)
        packet = s.load(base/'scoring/packet.json')
        assert packet['protocol_sha256'] == s.sha(base/'protocol.json')
        for row in packet['items']:
            assert s.sha(s.RUN/row['generation_file']) == row['generation_sha256']
            item = row['item']; root = base/'scoring/gpt_sol'/item['sample_id']
            ok, why = inspect(root, item)
            if ok:
                jobs.append((base, root, item))
            else:
                held[why] += 1
            if probe and jobs:
                break
        if probe and jobs:
            break
    statusfile = BASE/'resume_gpt_terra_status.json'
    def progress(state):
        s.save(statusfile, dict(utc=s.now(), pid=__import__('os').getpid(), state=state, model=cfg['api_model_id'], legacy_slot='gpt_sol', planned=len(jobs), completed=sum(completed.values()), states=dict(completed), held_preflight=dict(held), probe=probe, amendment_sha256=s.sha(s.RUN/cfg['amendment'])))
    progress('running')
    print(__import__('json').dumps(dict(planned=len(jobs), held=dict(held))), flush=True)
    rec.request = request
    def job(args):
        base, root, item = args
        for _ in range(3):
            if stop.is_set() or (BASE/'PAUSE_gpt_terra').exists():
                return 'paused_not_sent'
            ok, why = inspect(root, item)
            if not ok:
                return why
            ordinal = len(list((root/'recovery').glob('attempt_*'))) + 1
            with slot('gpt_sol'):
                result = rec.attempt(root, 'gpt_sol', item, ordinal, reg)
            if result['status'] == 'valid':
                inspect(root, item)
                return 'valid'
            if result.get('reason') in ('model_identity_mismatch', 'usage_unknown_stop_and_reconcile', 'http_403', 'http_404'):
                stop.set()
                return 'provider_or_identity_stop'
            if result.get('http_status') not in rec.RETRY_HTTP:
                return 'invalid_response_hold'
            time.sleep(5 if ordinal < 2 else 20)
        return 'attempt_limit'
    with exclusive_lock(BASE/'resume_gpt_sol.lock'):
        for base in [BASE, BASE/'supplement/single_pass']:
            s.OUT = base
            with ThreadPoolExecutor(max_workers=2) as pool:
                fs = {pool.submit(job, x): x for x in jobs if x[0] == base}
                for f in as_completed(fs):
                    if f.cancelled():
                        continue
                    try:
                        state = f.result()
                    except Exception as exc:
                        stop.set(); state = 'exception_'+type(exc).__name__+':'+str(exc)[:200]
                    completed[state] += 1
                    print(__import__('json').dumps(dict(sample_id=fs[f][2]['sample_id'], status=state, utc=s.now())), flush=True)
                    progress('running')
                    if stop.is_set():
                        for future in fs:
                            future.cancel()
            if stop.is_set():
                break
    progress('held' if stop.is_set() else 'finished')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--authorization', type=Path, required=True)
    p.add_argument('--probe', action='store_true')
    a = p.parse_args()
    run(a.authorization, a.probe)
