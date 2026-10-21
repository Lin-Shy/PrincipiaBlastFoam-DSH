"""全200题验证A1/A2隔离，保存真实差异而不修改已冻结轨迹。"""
from common import *

def rank_identity(trace):
    return [(r['node_id'],r['score'],r['route'],r['native_rank']) for r in trace['ranking']['items']]

def validate(run_id,output):
    root=ARCHIVE/'runs'/run_id
    rows=[]
    for q in public_questions():
        traces={m:read(root/m/'traces'/(q['id']+'.json')) for m in ['graph','no_traversal','anchor_only']}
        full,a1,a2=(traces[m] for m in ['graph','no_traversal','anchor_only'])
        assert rank_identity(full)==rank_identity(a2)
        assert full['full_slots']==a2['full_slots']
        assert full['initial_seeds_before_relation_lookup']==a1['initial_seeds_before_relation_lookup']
        assert a1['ranking']['diagnostic']['expanded_edges']==0
        assert all(not r['route'] for r in a1['ranking']['items'])
        assert len(a2['selected_slots'])<=sum(len(r['anchors']) for r in a2['ranking']['items'])
        for s in a2['selected_slots']:
            assert any(r['node_id']==s['node_id'] and r['path']==s['path'] and r['start']<=s['start']<=s['end']<=r['end'] for r in full['full_slots'])
            node=next(r for r in a2['ranking']['items'] if r['node_id']==s['node_id'])
            assert any(e['start']<=s['start']<=s['end']<=e['end'] for e in node['anchors'])
        def nodeids(t):return [r['node_id'] for r in t['ranking']['items']]
        rows.append(dict(id=q['id'],initial_seeds_equal=True,a2_ranking_and_slots_equal=True,
            a1_expanded_edges=0,full_expanded_edges=full['ranking']['diagnostic']['expanded_edges'],
            a1_order_equal=nodeids(full)==nodeids(a1),full_slot_count=len(full['selected_slots']),
            anchor_slot_count=len(a2['selected_slots']),full_ranges=full['selected_slots'],
            no_traversal_ranges=a1['selected_slots'],anchor_ranges=a2['selected_slots']))
    save(ARCHIVE/'audit'/output,dict(questions=200,all_invariants_passed=True,
        changed_a1_rankings=sum(not r['a1_order_equal'] for r in rows),
        zero_full_expansion=sum(r['full_expanded_edges']==0 for r in rows),rows=rows,
        inputs={m:sha(root/m/'completed.json') for m in ['graph','no_traversal','anchor_only']},script_sha256=sha(Path(__file__))))
    print('all 200 paired graph trace invariants passed; changed A1 rankings',sum(not r['a1_order_equal'] for r in rows))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();validate(a.run_id,a.output)
