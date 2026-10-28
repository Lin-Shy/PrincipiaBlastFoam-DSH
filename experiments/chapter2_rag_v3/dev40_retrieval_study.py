"""Fixed natural-query Dev40 mechanism study; graph bytes are never edited.

Gold is read only after deliveries have been generated, in a separate evaluator.
Ranking-edge filters preserve static graph-derived bonuses and context access.
"""
from collections import Counter, defaultdict
import argparse
import json
import os
from pathlib import Path
import sys
import time

import single_pass_dev40 as s

STUDY=s.RUN/'experiments/ablations/dev40'
CONFIGS={
    'baseline':{},
    'no_heading_lookup':{'ranking_exclude':['LITERAL_HEADING_REFERENCE']},
    'no_selector_expansion':{'ranking_exclude':['FILE_SELECTOR_CONTEXT']},
    'no_parameter_context_expansion':{'ranking_exclude':['PARAMETER_CONTEXT']},
    'no_identity_expansion':{'ranking_exclude':['SAME_PUBLIC_IDENTITY']},
    'no_section_parent_expansion':{'ranking_exclude':['SOURCE_SECTION_PARENT']},
    'no_adjacent_context':{'context_exclude':['SOURCE_NEXT_FRAGMENT']},
    'adjacent_context_only':{'context_policy':'adjacent'},
    'top5':{'top_slots':5},
    'top15':{'top_slots':15},
    'depth1':{'depth':1},
}


class FilteredGraph:
    def __init__(self,config):
        self.config=config
        common=s.paths_and_runtime()
        from retrieval import GraphEngine
        self.base=GraphEngine('graph')
        self.engine=self.base.engine
        self.full_adjacency=self.engine.adjacency
        self.rank_adjacency=self.filtered(config.get('ranking_exclude',[]))
        self.context_adjacency=self.filtered(config.get('context_exclude',[]))
        if 'depth' in config:self.engine.options['depth']=config['depth']
        if 'context_policy' in config:self.engine.context_policy=config['context_policy']

    def filtered(self,excluded):
        return defaultdict(list,{k:[x for x in v if x[1]['relation'] not in excluded]
                for k,v in self.full_adjacency.items()})

    def query(self,query):
        e=self.engine
        try:
            e.adjacency=self.rank_adjacency
            ranking=e.rank(query)
            e.adjacency=self.context_adjacency
            packet=e.read_native(ranking)
            slots=[dict(path=r['path'],start=z['start'],end=z['end'],node_id=r['native_unit'],
                        native_rank=r['native_rank'],delivery_role='anchor_and_context')
                   for r in packet['items'] for z in r['ranges']][:self.config.get('top_slots',10)]
        finally:e.adjacency=self.full_adjacency
        return slots,dict(ranking=ranking,packet=packet,selected_slots=slots,
                          graph_loaded=True,filter_config=self.config)


def prepare():
    STUDY.mkdir(parents=True,exist_ok=True)
    graph=s.RUN.parent/'current/revision_200_20261019_002/graphs/selected.json'
    g=s.load(graph)
    from chapter2_knowledge_graph_v2 import RELATION_DECAY
    counts=Counter(e['relation'] for e in g['edges'])
    roles={}
    for relation,n in sorted(counts.items()):
        roles[relation]=dict(edges=n,ranking_decay=RELATION_DECAY.get(relation),
            heading_lookup=relation=='LITERAL_HEADING_REFERENCE',
            source_context=relation in ('SOURCE_PARENT_CONTEXT','SOURCE_NEXT_FRAGMENT'),
            ownership_or_construction=relation in ('HAS_LITERAL','HAS_ENTRY','GROUNDED_IN','SAME_SOURCE_SCOPE'),
            note='Persistent structural/ownership edges remain intact; ranking whitelist controls adjacency only')
    definition=dict(schema='dev40_fixed_query_mechanisms',created_utc=s.now(),
        graph_sha256=s.sha(graph),questions_sha256=s.sha(s.QUESTIONS),configs=CONFIGS,
        primary='Per-answer two-judge mean EAS_arith; EAS_geo/K/F/A/evidence and cost diagnostic',
        selection='Few mechanistic finalists; no global-optimum claim; fixed Dev40 only',
        controls='Static declaration/alias/identity bonuses preserved. Ranking exclusions do not disable context edges. Adjacent-only explicitly removes physical-parent context access; not a semantic-edge ablation.',
        original_graph_modified=False,test160=False,
        design_sha256=s.sha(s.WORKSPACE/'graduation-thesis-materials/graduation-research/chapters/chapter02.md'),
        relation_inventory=roles,baseline_options=None)
    p=STUDY/'protocol.json'
    if p.exists():
        old=s.load(p)
        for k in ('graph_sha256','questions_sha256','configs','primary','design_sha256'):
            if old[k]!=definition[k]:raise ValueError('Study binding drift: '+k)
    else:s.save(p,definition)
    return definition


def retrieve():
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    common=s.paths_and_runtime()
    definition=prepare()
    # Process cannot read scoring-side files or contact any provider.
    def guard(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
            raise PermissionError('Offline retrieval network forbidden')
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            p=os.fsdecode(args[0]).replace('\\','/').lower()
            if '/scoring/' in p or p.endswith('/annotations.json') or p.endswith('/evidence.json'):
                raise PermissionError('Retrieval must not read Gold or scoring: '+p)
    sys.addaudithook(guard)
    questions=s.load(s.QUESTIONS)
    for name,cfg in CONFIGS.items():
        engine=FilteredGraph(cfg)
        if name=='baseline':
            s.save(STUDY/'baseline_options.json',dict(options=engine.engine.options,
                context_characters=engine.engine.context_characters,parent_ratio=engine.engine.parent_ratio,
                context_seed_limit=engine.engine.context_seed_limit,context_policy=engine.engine.context_policy))
        for q in questions:
            folder=STUDY/'deliveries'/name/q['id']
            if (folder/'retrieval.json').exists():continue
            folder.mkdir(parents=True,exist_ok=True)
            s.retrieve('graph',q['question'],common,engine,folder)
        print(json.dumps(dict(configuration=name,questions=40,status='delivered')),flush=True)
        del engine
    graph=s.RUN.parent/'current/revision_200_20261019_002/graphs/selected.json'
    assert s.sha(graph)==definition['graph_sha256']


def evaluate():
    """Evaluation side only; never makes query/ranking decisions."""
    annotations={x['id']:x for x in s.load(s.SPLIT/'gold/dev40/annotations.json')}
    evidence=s.load(s.SPLIT/'gold/dev40/evidence.json')
    questions=s.load(s.QUESTIONS)
    rows=[];aggregates=[]
    for name in CONFIGS:
        group=[]
        for q in questions:
            p=STUDY/'deliveries'/name/q['id']/'retrieval.json'
            if not p.exists():continue
            d=s.load(p);got={(x['path'],x['line']) for x in d['delivered_lines']}
            needed=set();spans=[]
            for eid in annotations[q['id']]['required_evidence_ids']:
                e=evidence[eid];span={(e['path'],n) for n in range(e['line_start'],e['line_end']+1)}
                needed|=span;spans.append(span)
            baseline=s.load(STUDY/'deliveries/baseline'/q['id']/'retrieval.json')
            ranks=d['trace']['ranking']['items'];b_ranks=baseline['trace']['ranking']['items']
            row=dict(config=name,question_id=q['id'],line_recall=len(got&needed)/len(needed),
                complete=needed<=got,evidence_span_recall=sum(span<=got for span in spans)/len(spans),
                characters=d['delivered_characters'],unique_lines=len(got),
                changed_delivery=d['delivery']!=baseline['delivery'],
                changed_top10=[r['node_id'] for r in ranks[:10]]!=[r['node_id'] for r in b_ranks[:10]],
                expanded_edges=d['trace']['ranking']['diagnostic'].get('expanded_edges'),
                retrieval_sha256=s.sha(p),truncated=d['truncated'])
            rows.append(row);group.append(row)
        if group:
            aggregates.append(dict(config=name,n=len(group),
                mean_line_recall=sum(r['line_recall'] for r in group)/len(group),
                mean_evidence_span_recall=sum(r['evidence_span_recall'] for r in group)/len(group),
                complete=sum(r['complete'] for r in group),changed_delivery=sum(r['changed_delivery'] for r in group),
                changed_top10=sum(r['changed_top10'] for r in group),
                mean_characters=sum(r['characters'] for r in group)/len(group),
                truncated=sum(r['truncated'] for r in group)))
    s.save(STUDY/'offline_evaluation.json',dict(aggregates=aggregates,per_question=rows,
        evidence_is_nonexhaustive=True,interpretation='Required evidence exact original-line recall; not native-node/chunk recall',
        test160=False,protocol_sha256=s.sha(STUDY/'protocol.json')))
    print(json.dumps(aggregates,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['retrieve','evaluate']);a=p.parse_args()
    if a.command=='retrieve':retrieve()
    else:evaluate()
