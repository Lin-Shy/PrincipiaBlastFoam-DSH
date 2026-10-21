from pathlib import Path
import sys,threading
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_proxy_bounded_execution import run_bounded


def test_sixteen_answers_really_overlap_without_exceeding_bound():
    lock=threading.Lock();barrier=threading.Barrier(16,timeout=5)
    active=0;peak=0;observed=[]
    def worker(item):
        nonlocal active,peak
        with lock:active+=1;peak=max(active,peak)
        barrier.wait()
        with lock:active-=1
        return item
    run_bounded(range(32),worker,lambda item,value:observed.append(value),16)
    assert peak==16 and sorted(observed)==list(range(32)) and active==0


def test_failure_stops_new_admission_and_drains_every_admitted_answer():
    started=[];finished=[];lock=threading.Lock()
    def worker(item):
        with lock:started.append(item)
        if item==0:raise RuntimeError('registered circuit')
        with lock:finished.append(item)
        return item
    observed=[]
    with pytest.raises(RuntimeError,match='registered circuit'):
        run_bounded(range(100),worker,lambda item,value:observed.append(value),16)
    assert sorted(started)==list(range(16))
    assert sorted(finished)==sorted(observed)==list(range(1,16))


@pytest.mark.parametrize('bound',[0,17,True,1.0])
def test_unregistered_worker_bounds_are_rejected(bound):
    with pytest.raises(ValueError):run_bounded([],None,None,bound)
