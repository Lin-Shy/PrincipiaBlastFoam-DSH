"""Read-only end-to-end evidence and release verification after cleanup."""
from pathlib import Path
import json,hashlib
W=Path(__file__).resolve().parents[3];C=W/'graduation-experiment-results/chapter2_retrieval/current'
R=C/'revision_200_20261019_002';PROJECT=W/'PrincipiaBlastFoam-DSH';RES=C.parent/'resources'
M=W/'graduation-thesis-materials/graduation-manuscript'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
P=read(R/'protocol.json');A=read(R/'analysis_001/summary.json');rows=read(R/'analysis_001/session-metrics.json')
assert A['formal_protocol_sha256']==sha(R/'protocol.json') and A['registered_sessions']==1400
assert len(rows)==1400 and len({(r['arm'],r['id']) for r in rows})==1400
assert sum(r['reused'] for r in rows)==800
for rel,digest in P['implementation_sha256'].items():
    assert sha(PROJECT/rel)==sha(R/'runtime'/rel)==digest,rel
for name,digest in P['source_resources'].items():assert sha(RES/name)==digest,name
for name,digest in P['graphs'].items():assert sha(R/'graphs'/(name+'.json'))==digest,name
assert sha(R/'graphs/manifest.json')==P['graph_manifest_sha256']
assert sha(R/'provenance/adopted-chapter02.md')==P['design_sha256']
for name,digest in P['e5_resources'].items():assert sha(RES/'e5'/name)==digest,name
D=W/'graduation-datasets/chapter02_knowledge_qa/formal_v2_200'
assert sha(D/'binding.json')==P['dataset_binding_sha256']
for name,digest in read(D/'binding.json')['files'].items():assert sha(D/name)==digest,name
for row in rows:
    arm,qid=row['arm'],row['id'];fresh=arm in P['arms']
    base=R if fresh else R/'reused'
    result=base/'generation'/arm/qid/'result.json'
    if fresh:
        assert sha(result)==read(R/'completion'/(arm+'.json'))['results_sha256'][qid]
        score=R/'scoring_001/sessions'/arm/qid/'result.json'
        assert sha(score)==read(R/'scoring_001/completion.json')['results_sha256'][arm+'/'+qid]
    else:
        binding=P['reused_baselines']['bindings'][arm+'/'+qid]
        assert sha(result)==binding['generation_sha256']
        assert sha(R/'reused/scoring/sessions'/arm/qid/'result.json')==binding['scoring_sha256']
for key,digest in read(R/'analysis_001/judge-request-bindings.json').items():
    arm,qid,number=key.split('/');base=R/'scoring_001' if arm in P['arms'] else R/'reused/scoring'
    assert sha(base/'sessions'/arm/qid/'requests'/(number+'.json'))==digest,key
construction=read(R/'provenance/construction/replay-audit.json')
for rel,digest in construction['retained_input_bindings'].items():assert sha(R/rel)==digest,rel
for path in ['formal_200_20261019_001','optimization_200_20261019_001']:
    assert not (C/path).exists(),path
assert not (R/'metric_options').exists() and not (RES/'graphs').exists()
resource=read(RES/'manifest.json')
for rel,digest in resource['files'].items():assert sha(RES/rel)==digest,rel
official=read(M/'official_manifest.json');assert sha(M/'main.pdf')==sha(M/'build/main.pdf')==official['pdf_sha256']
assert official['review']['visual_review_status']=='passed'
for rel,digest in official['source_files_sha256'].items():assert sha(M/rel)==digest,rel
plan=read(C/'publication-plan.json')
assert plan['status']=='revision_complete' and plan['manuscript_pdf_sha256']==official['pdf_sha256']
out=dict(verifier_source_sha256=sha(Path(__file__)),schema='current_revision_delivery_verified_v2',passed=True,questions=200,types_each=50,
    fresh_graph_sessions=600,reused_baseline_sessions=800,total_current_sessions=1400,
    frozen_runtime_sources=len(P['implementation_sha256']),all_judge_receipts_revalidated=True,
    dataset_and_raw_resource_bindings_verified=True,source_construction_replay_verified=True,
    retired_activities_and_unused_graphs_removed=True,
    protocol_sha256=sha(R/'protocol.json'),summary_sha256=sha(R/'analysis_001/summary.json'),
    official_pdf_sha256=official['pdf_sha256'],official_manifest_sha256=sha(M/'official_manifest.json'),
    official_pdf_pages=official['review']['pages'],visual_review_passed=True)
(C/'cleanup-verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
