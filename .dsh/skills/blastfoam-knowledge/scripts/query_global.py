"""Entity-first global graph lookup with a bounded, source-readable context packet."""
import argparse,json
from global_graph import GlobalGraph,ROOT
from context_packets import semantic_items,pack

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--terms',nargs='+',required=True);p.add_argument('--relation',action='append');p.add_argument('--case')
    p.add_argument('--budget',type=int,default=8000)
    a=p.parse_args();r=GlobalGraph().lookup(a.terms,a.relation,a.case)
    print(json.dumps(pack(semantic_items(r,ROOT/'corpus'),a.budget,r['status']),ensure_ascii=False,separators=(',',':')))
