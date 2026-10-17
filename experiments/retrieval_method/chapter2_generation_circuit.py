"""Disclosed bounded transient-failure admission; never retry a logical session."""
from collections import defaultdict, deque
from datetime import datetime, timezone
import json
from pathlib import Path

POLICY = 'per_model_two_consecutive_or_three_of_32_transient_sessions_v1'
ORIGINAL_SIGNAL = 'Stop new admissions and drain; preserve all terminal records without replay'


def transient(result):
    if result.get('status') == 'transport_error':return True
    if result.get('status') != 'http_rejected':return False
    turns=result.get('turns',[])
    return bool(turns and turns[-1].get('response',{}).get('http_status') in {500,502,503,504})


def wrap_scheduler(original, log_path, amendment_sha256):
    """Change only the frozen observer's exact transient-network stop signal."""
    def run(items, worker, on_result, *, model_of, workers_per_model=16):
        windows=defaultdict(lambda:deque(maxlen=32));streaks=defaultdict(int)
        path=Path(log_path);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as stream:
            def log(value):
                stream.write(json.dumps(value,ensure_ascii=False)+'\n');stream.flush()
            log(dict(event='start',created_utc=datetime.now(timezone.utc).isoformat(),policy=POLICY,
                     amendment_sha256=amendment_sha256,workers_per_model=workers_per_model,
                     model_requests_reissued=False))
            def observe(item,result):
                model=model_of(item);failure=transient(result)
                windows[model].append(failure)
                streaks[model]=streaks[model]+1 if failure else 0
                circuit=failure and (streaks[model]>=2 or sum(windows[model])>=3)
                row=dict(event='terminal_session',model=model,status=result.get('status'),
                         transient_failure=failure,consecutive_failures=streaks[model],
                         recent_sessions=len(windows[model]),recent_failures=sum(windows[model]),
                         threshold_reached=circuit,question_id=item.get('question',{}).get('id'),
                         cell_id=item.get('cell',{}).get('id'))
                try:on_result(item,result)
                except RuntimeError as exc:
                    # No identity, authentication, other HTTP, worker or arbitrary
                    # observer error is converted into admission permission.
                    if str(exc)!=ORIGINAL_SIGNAL or not failure or circuit:
                        log({**row,'outcome':'propagate_original_stop'});raise
                    log({**row,'outcome':'retain_isolated_failure_and_admit_unattempted'})
                else:log({**row,'outcome':'original_observer_completed'})
            try:
                return original(items,worker,observe,model_of=model_of,workers_per_model=workers_per_model)
            finally:log(dict(event='scheduler_closed',model_requests_reissued=False))
    return run
