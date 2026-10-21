"""Bulk proxy bound of up to sixteen independent answer workers; drain on error."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED


def run_bounded(items,worker,on_result,max_workers):
    if type(max_workers) is not int or not 1<=max_workers<=16:
        raise ValueError('Proxy worker bound must be between one and sixteen')
    source=iter(items);pending={};errors=[];exhausted=False
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while pending or not exhausted:
            while not errors and not exhausted and len(pending)<max_workers:
                try:item=next(source)
                except StopIteration:exhausted=True;break
                pending[pool.submit(worker,item)]=item
            if not pending:break
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                item=pending.pop(future)
                try:on_result(item,future.result())
                except Exception as exc:errors.append(exc)
            if errors:exhausted=True
    if errors:raise errors[0]
