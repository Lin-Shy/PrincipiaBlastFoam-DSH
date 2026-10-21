"""原代理事件与新版单次请求的统一费用核算；中断请求须有精确封存。"""
from pathlib import Path
from chapter2_knowledge_stage_costs import event_rows,empty_totals,add_event,canonical,sha


def physical_proxy_cost(paths, root, sealed_unresolved=None):
    root=Path(root).absolute();sealed=sealed_unresolved or {}
    seen_paths=set();seen_events={};files=[];duplicates=0;interrupted=0;total=empty_totals()
    for item in paths:
        path=Path(item).absolute();identity_path=path.resolve()
        if identity_path in seen_paths:continue
        seen_paths.add(identity_path)
        row=event_rows(path,root)
        if row is None:raise ValueError('Not a model request ledger')
        if row['endpoint'].startswith('http:'):raise ValueError('Proxy cost cannot include local deployment')
        relative=path.relative_to(root).as_posix()
        for identity,event in row['events']:
            if identity in seen_events:
                if canonical(seen_events[identity])!=canonical(event):raise ValueError('Conflicting physical event copies')
                duplicates+=1;continue
            seen_events[identity]=event
            if event.get('status')=='in_flight':
                if sealed.get(relative)!=row['sha256']:
                    raise ValueError('Unsealed unresolved attempt cannot enter completed costs')
                interrupted+=1
            add_event(total,row['model'],event)
        files.append(dict(path=str(path),sha256=row['sha256']))
    return dict(total,provider='qwen_proxy',request_files=files,
        sum_physical_request_seconds=total['sum_known_physical_request_seconds'],
        duplicate_physical_events_not_recharged=duplicates,
        sealed_interrupted_unknown_attempts=interrupted,money_cost=None,
        money_cost_reason='No frozen monetary tariff or invoice; failed and interrupted charges are unknown.',
        unknown_usage_not_zero=True,
        interruption_scope='Exactly hash-bound historic upstream outcomes remain unknown; native batch termination is verified separately.')
