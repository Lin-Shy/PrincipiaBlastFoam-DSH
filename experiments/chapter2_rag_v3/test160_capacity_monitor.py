"""Bounded read-only observation of the16-slot pilot; can only lower to8."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
import time
import test160_resume_scores as main
from central_execution import exclusive_lock

BASE = main.BASE
CONTROL = BASE/'gpt_concurrency_control_20261102.json'


def recent_events(start):
    result = []
    for base in (BASE, BASE/'supplement/single_pass'):
        path = base/'scoring/gpt_sol/recovery_events.jsonl'
        for line in path.read_text(encoding='utf-8-sig').splitlines(keepends=True):
            if not line.endswith('\n'):
                continue  # An append may still be in progress.
            row = json.loads(line)
            if datetime.fromisoformat(row['completed_utc']) >= start:
                result.append(row)
    return result


def run():
    started = datetime.now(timezone.utc)
    control = main.read(CONTROL)
    since = datetime.fromisoformat(control['pilot_started_utc'])
    with exclusive_lock(BASE/'gpt_capacity_monitor_20261102.lock'):
        while True:
            now = datetime.now(timezone.utc)
            events = recent_events(since)
            window = [r for r in events if datetime.fromisoformat(r['completed_utc']) >= now-timedelta(minutes=2)]
            rate_limits = sum(r.get('http_status') == 429 for r in window)
            transport_errors = sum(r.get('error_type') in ('RemoteDisconnected', 'SSLEOFError', 'TimeoutError') for r in window)
            rollback = rate_limits >= 2 or (transport_errors >= 6 and transport_errors/max(1, len(window)) >= .25)
            control = main.read(CONTROL)
            if rollback and control['gpt_total_slot_cap'] == 16:
                control.update(gpt_total_slot_cap=8, activation_state='capacity_monitor_lowered_to8',
                               capacity_rollback_utc=now.isoformat())
                main.s.save(CONTROL, control)
            finished = rollback or (now-started).total_seconds() >= 900 or control['gpt_total_slot_cap'] != 16
            main.s.save(BASE/'gpt_capacity_monitor_20261102_status.json', dict(
                utc=now.isoformat(), pid=os.getpid(), state='finished' if finished else 'observing',
                since=since.isoformat(), total_completed=len(events),
                states=dict(Counter(r['status'] for r in events)),
                recent_two_minutes=len(window), recent_rate_limits=rate_limits,
                recent_transport_errors=transport_errors, lowered_to8=rollback,
                total_slot_cap=control['gpt_total_slot_cap'], requests_sent=0))
            if finished:
                return
            time.sleep(15)


if __name__ == '__main__':
    run()
