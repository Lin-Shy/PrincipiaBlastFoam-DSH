"""客户端消失后的单次请求结案；未知用量、时长和服务端结果保持未知。"""
from copy import deepcopy
from datetime import datetime


def validate_interruption_observation(value, activation_sha256):
    if (value.get('schema') != 'local_judge_root_interruption_observation_v1'
            or value.get('native_returncode') is not None
            or type(value.get('root_tool_session')) is not int
            or value.get('tool_handle_status') != 'missing'
            or value.get('os_matching_processes') != []
            or value.get('exclusive_scoring_lock_acquired') is not True
            or value.get('activation_sha256') != activation_sha256
            or value.get('endpoint_response_or_native_exit_not_observed') is not True
            or value.get('failed_requests_reissued') != 0):
        raise ValueError('Observed absent process and lost handle required; native exit is unknown')
    rows=value.get('interrupted_attempts', [])
    if not rows or len({r['relative_path'] for r in rows}) != len(rows):
        raise ValueError('Exact interrupted attempt inventory required')
    return rows


def interrupted_record(original, *, original_sha256, observation_relative_path, observation_sha256, observed_utc):
    if (original.get('status') != 'in_flight' or original.get('transport_attempts') != 1
            or original.get('content_retries') != 0 or 'raw_response' in original
            or 'seconds' in original):
        raise ValueError('Only a single unresolved issued attempt may be closed')
    elapsed=(datetime.fromisoformat(observed_utc)-datetime.fromisoformat(original['started_utc'])).total_seconds()
    if elapsed < 0: raise ValueError('Interruption observation precedes request')
    value=deepcopy(original)
    value.update(status='transport_error', error_type='ClientProcessInterrupted',
        error='Client process and tool handle absent; server outcome and elapsed HTTP time unknown; no reissue',
        seconds=None, usage_unknown=True, duration_unknown=True,
        process_interruption=dict(observation_relative_path=observation_relative_path,
            observation_sha256=observation_sha256,original_request_record_sha256=original_sha256,
            observed_utc=observed_utc,native_returncode=None,server_outcome='unknown',
            elapsed_until_observation_seconds=elapsed,failed_request_reissued=False))
    return value


def has_unknown_interruption_duration(record):
    proof=record.get('process_interruption') or {}
    return (record.get('provider')=='qwen_local' and record.get('status')=='transport_error'
        and record.get('error_type')=='ClientProcessInterrupted' and record.get('seconds') is None
        and record.get('duration_unknown') is True and record.get('usage_unknown') is True
        and proof.get('native_returncode') is None and proof.get('server_outcome')=='unknown'
        and proof.get('failed_request_reissued') is False
        and all(isinstance(proof.get(k),str) and len(proof[k])==64
            for k in ('observation_sha256','original_request_record_sha256')))
