"""仅在原文、节点与非引用边完全不变时，将已审核语义层绑定到引用规则新快照。"""
import argparse
import copy
import json
from pathlib import Path

import manual_graph as g


def rebase(old, new, semantic, review):
    for artifact in (old, new, semantic):
        if artifact['snapshot'] != g.sha(g.encoded({k:v for k,v in artifact.items() if k != 'snapshot'})):
            raise ValueError('snapshot integrity mismatch')
    if semantic['foundation_snapshot'] != old['snapshot'] or review['semantic_snapshot'] != semantic['snapshot']:
        raise ValueError('semantic lineage mismatch')
    for key in ('inventory', 'nodes'):
        if old[key] != new[key]:
            raise ValueError('sources or nodes changed; re-extraction/review required')
    structural = lambda graph: [e for e in graph['edges'] if e['relation'] not in {'REFERS_TO_SECTION','REFERS_TO_FORMULA'}]
    if structural(old) != structural(new):
        raise ValueError('non-reference structure changed')
    result = copy.deepcopy(semantic)
    result['foundation_snapshot'] = new['snapshot']
    result['rebase'] = {'semantic_snapshot': semantic['snapshot'], 'foundation_snapshot': old['snapshot'],
                        'reason': 'only explicit reference edges and builder metadata changed',
                        'new_extraction_calls': 0}
    result['snapshot'] = g.sha(g.encoded({k:v for k,v in result.items() if k != 'snapshot'}))
    reviewed = copy.deepcopy(review); reviewed['semantic_snapshot'] = result['snapshot']
    reviewed['rebase_from_review_sha256'] = g.sha(g.encoded(review))
    return result, reviewed


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('old-foundation','foundation','semantic','review','output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--source', type=Path, default=g.ROOT/'corpus/manual/markdown')
    a = p.parse_args(); read = lambda path: json.loads(path.read_text())
    old = read(a.old_foundation); new = read(a.foundation)
    g.validate(old, a.source); g.validate(new, a.source)
    semantic, review = rebase(old, new, read(a.semantic), read(a.review))
    if (a.output/'semantic.json').exists():
        raise ValueError('use a new output directory')
    g.write(a.output/'semantic.json', semantic); g.write(a.output/'review.json', review)
    print(g.encoded({'facts': len(semantic['facts']), 'review': review['counts'], 'new_extraction_calls': 0}))
