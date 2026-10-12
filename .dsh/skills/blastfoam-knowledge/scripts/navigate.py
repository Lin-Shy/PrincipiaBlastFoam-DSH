"""Discover actual graph vocabulary, inspect source cards, and navigate co-mentioned entities."""
import argparse
from collections import Counter
import json
import re
from global_graph import GlobalGraph, ROOT, digest, KINDS
from context_packets import wire


def tokens(text):
    text=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',text)
    return set(re.findall(r'[^\W_]+',text.casefold()))


def bounded(base,items,budget=3000,offset=0,limit=30):
    if type(budget) is not int or budget<256:raise ValueError('budget must be >=256 characters')
    if offset<0 or not 1<=limit<=100:raise ValueError('invalid pagination')
    result={**base,'items':[],'total_items':len(items),'next_offset':offset if offset<len(items) else None}
    if len(wire(result))>budget:raise ValueError('budget too small for response metadata')
    for item in items[offset:offset+limit]:
        nxt=offset+len(result['items'])+1
        proposed={**result,'items':result['items']+[item],'next_offset':nxt if nxt<len(items) else None}
        if len(wire(proposed))>budget:break
        result=proposed
    if not result['items'] and offset<len(items):result['status']='budget_too_small_for_first_item'
    if len(wire(result))>budget:raise ValueError('budget too small for response status metadata')
    return result


class Navigator:
    def __init__(self,graph=None,case=None,scope=None):
        self.g=graph or GlobalGraph();self.case=case;self.scope=scope
        if case and case not in self.g.manifest['case_paths']:raise ValueError('case_unavailable')
        if scope not in (None,'manual','tutorial'):raise ValueError('invalid scope')
        self.cards={cid:c for cid,c in self.g.cards.items() if (not scope or c['scope']==scope) and
                    (not case or not c['case'] or c['case']==case)}
        self.adj={eid:sorted({edge['target'] for edge in edges if edge['target'] in self.cards}) for eid,edges in self.g.adj.items()}
        self.adj={eid:cids for eid,cids in self.adj.items() if cids}
        self.ids={digest(eid)[:16]:eid for eid in self.adj}
        if len(self.ids)!=len(self.adj):raise ValueError('entity handle collision')

    def entity(self,eid):
        e=self.g.entities[eid]
        return {'id':digest(eid)[:16],'name':e['name'],'kind':e['kind'],'namespace':e.get('namespace','')}

    def resolve(self,handle):
        if handle in self.adj:return handle
        if handle in self.ids:return self.ids[handle]
        raise ValueError('unknown entity ID in current scope; use discover')

    def base(self,action):
        return {'status':'ok','action':action,'snapshot':self.g.graph['snapshot']}

    def discover(self,query='',kind=None,namespace=None,**paging):
        if kind is not None and kind not in KINDS:
            raise ValueError('invalid kind; choose '+', '.join(sorted(KINDS))+' or omit kind')
        wanted=tokens(query);ranked=[]
        for eid in self.adj:
            e=self.entity(eid)
            if kind and e['kind']!=kind:continue
            if namespace and e['namespace']!=namespace:continue
            overlap=len(wanted & tokens(e['name']+' '+e['namespace']))
            if wanted and not overlap:continue
            ranked.append((e['name'].casefold()==query.casefold(),overlap,e))
        ranked.sort(key=lambda x:(-x[0],-x[1],x[2]['name'].casefold(),x[2]['namespace'],x[2]['id']))
        return bounded({**self.base('discover'),'available_kinds':sorted({self.g.entities[e]['kind'] for e in self.adj})},[x[2] for x in ranked],**paging)

    def inspect(self,entity,**paging):
        eid=self.resolve(entity);cards=[self.cards[c] for c in self.adj[eid]]
        # No relation hard filter: display the actual categories so the caller can inspect them.
        cards.sort(key=lambda c:(c['evidence'][0]['path'],c['evidence'][0]['line_start'],c['id']))
        items=[{'card_id':c['id'],'title':c['title'],'relation':c['relation'],
                'sources':[{'path':ev['path'],'start':ev['line_start'],'end':ev['line_end']} for ev in c['evidence']]} for c in cards]
        return bounded({**self.base('inspect'),'entity':self.entity(eid),
                        'relations':dict(sorted(Counter(c['relation'] for c in cards).items())),
                        'interpretation':'candidate card index; read sources to verify claims'},items,**paging)

    def neighbors(self,entity,card=None,**paging):
        eid=self.resolve(entity);cids=self.adj[eid]
        if card:
            if card not in cids:raise ValueError('card is not adjacent to this entity in current scope')
            cids=[card]
        routes={}
        for cid in cids:
            c=self.cards[cid]
            for other in c['entities']:
                from global_graph import entity_id
                target=entity_id(other)
                if target==eid or target not in self.adj:continue
                routes.setdefault(target,set()).add(cid)
        items=[{**self.entity(target),'via_cards':sorted(cids)} for target,cids in sorted(routes.items())]
        return bounded({**self.base('neighbors'),'entity':self.entity(eid),
                        'interpretation':'co-mentioned in source cards, not a causal or modification dependency'},items,**paging)

    def source(self,path,start=1,end=None,budget=3000):
        if type(budget) is not int or budget<256:raise ValueError('budget must be >=256 characters')
        root=(self.g.skill/'corpus').resolve();p=(root/path).resolve()
        if not p.is_relative_to(root):raise ValueError('source outside corpus')
        relative=str(p.relative_to(root))
        if relative not in self.g.manifest['corpus_hashes']:raise ValueError('source absent from frozen corpus')
        if self.scope=='manual' and not relative.startswith('manual/'):raise ValueError('source outside manual scope')
        if self.scope=='tutorial' and not relative.startswith('tutorials/'):raise ValueError('source outside tutorial scope')
        if self.case and relative.startswith('tutorials/'):
            owner=max((c for c in self.g.manifest['case_paths'] if relative.startswith(c+'/')),key=len,default=None)
            if owner!=self.case:raise ValueError('source outside case scope')
        raw=p.read_bytes()
        if digest(raw)!=self.g.manifest['corpus_hashes'][relative]:raise ValueError('source changed; rebuild graph')
        lines=raw.decode().splitlines(keepends=True);requested_end=end;end=len(lines) if end is None else end
        if type(start) is not int or type(end) is not int or not (1<=start<=len(lines)) or end<start:
            raise ValueError(f'invalid source line range; file has {len(lines)} lines')
        end=min(end,len(lines))
        result={**self.base('source'),'path':relative,'sha256':digest(raw),'line_start':start,
                'line_end':None,'text':'','next_line':start,'requested_end':requested_end,'total_lines':len(lines)}
        for n in range(start,end+1):
            nxt={**result,'text':result['text']+lines[n-1],'line_end':n,'next_line':n+1 if n<end else None}
            if len(wire(nxt))>budget:break
            result=nxt
        if result['line_end'] is None:result['status']='budget_too_small_for_first_line'
        if len(wire(result))>budget:raise ValueError('budget too small for source metadata')
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['discover','inspect','neighbors','source'])
    p.add_argument('--query',default='');p.add_argument('--kind',choices=sorted(KINDS));p.add_argument('--namespace');p.add_argument('--entity');p.add_argument('--card')
    p.add_argument('--case');p.add_argument('--scope',choices=['manual','tutorial']);p.add_argument('--budget',type=int,default=3000)
    p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=30)
    p.add_argument('--path');p.add_argument('--start',type=int,default=1);p.add_argument('--end',type=int)
    a=p.parse_args();nav=Navigator(case=a.case,scope=a.scope);paging={'budget':a.budget,'offset':a.offset,'limit':a.limit}
    if a.action=='discover':r=nav.discover(a.query,a.kind,a.namespace,**paging)
    elif a.action=='inspect':r=nav.inspect(a.entity,**paging)
    elif a.action=='neighbors':r=nav.neighbors(a.entity,a.card,**paging)
    else:r=nav.source(a.path,a.start,a.end,a.budget)
    print(wire(r))

if __name__=='__main__':main()
