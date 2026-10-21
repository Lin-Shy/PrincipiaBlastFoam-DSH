from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Barrier, Lock
from types import SimpleNamespace
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_local_bounded_execution import run_bounded, LockedFrozenParser


def test_independent_tasks_are_bounded_and_each_observed_once():
    guard=Lock();barrier=Barrier(8);active=0;peak=0;seen={}
    def work(item):
        nonlocal active,peak
        with guard:active+=1;peak=max(peak,active)
        barrier.wait(timeout=5)
        with guard:active-=1
        return item*2
    run_bounded(range(8),work,lambda i,v:seen.__setitem__(i,v),8)
    assert peak==8 and active==0 and seen=={i:i*2 for i in range(8)}


def test_worker_failure_drains_admitted_tasks_without_dispatching_rest():
    barrier=Barrier(2);started=[];seen=[]
    def work(i):
        started.append(i);barrier.wait(timeout=5)
        if i==0:raise ValueError('terminal worker failure')
        time.sleep(.02)
        return i
    with pytest.raises(ValueError,match='terminal worker failure'):
        run_bounded(range(20),work,lambda i,v:seen.append(i),2)
    assert set(started)=={0,1} and seen==[1]


def test_circuit_callback_stops_dispatch_but_collects_other_admitted_output():
    barrier=Barrier(2);started=[];seen=[]
    def work(i):
        started.append(i);barrier.wait(timeout=5)
        if i==1:time.sleep(.02)
        return i
    def observe(i,v):
        seen.append(i)
        if i==0:raise RuntimeError('circuit')
    with pytest.raises(RuntimeError,match='circuit'):run_bounded(range(20),work,observe,2)
    assert set(started)=={0,1} and set(seen)=={0,1}


@pytest.mark.parametrize('bound',[0,9,True])
def test_invalid_worker_bound_rejected_before_any_task(bound):
    with pytest.raises(ValueError,match='worker bound'):
        run_bounded([1],lambda _:pytest.fail('unexpected worker'),lambda *_:None,bound)


def parser_fixture():
    old_requests=lambda _:['original']
    old_parse=lambda *_:'original'
    partial=SimpleNamespace(source_free_requests=old_requests,parse_source_free_judgments=old_parse)
    def parse(responses,payload):
        time.sleep(.001)
        return partial.source_free_requests(payload),partial.parse_source_free_judgments(responses,payload)
    partial.parse_partial_judgments=parse
    reasoning=SimpleNamespace(parse_reasoning_judgments=lambda rs,payload,requests:requests)
    return partial,reasoning,old_requests,old_parse


def test_frozen_module_adapters_never_cross_answer_boundaries():
    partial,reasoning,old_requests,old_parse=parser_fixture();parse=LockedFrozenParser(partial,reasoning)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda i:parse([],{},[i]),range(40)))
    assert results==[([i],[i]) for i in range(40)]
    assert partial.source_free_requests is old_requests and partial.parse_source_free_judgments is old_parse


def test_frozen_adapters_restored_after_parse_exception():
    partial,reasoning,old_requests,old_parse=parser_fixture();parse=LockedFrozenParser(partial,reasoning)
    def fail(*_):raise ValueError('frozen parser failure')
    partial.parse_partial_judgments=fail
    with pytest.raises(ValueError,match='frozen parser failure'):parse([],{},['candidate'])
    assert partial.source_free_requests is old_requests and partial.parse_source_free_judgments is old_parse
