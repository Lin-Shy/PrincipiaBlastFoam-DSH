"""Bounded traversal over the independently constructed Chapter 2 graph."""
from __future__ import annotations

from collections import defaultdict

from candidate_graph_utils import wire


STRUCTURAL = {'HAS_ENTRY','HAS_BLOCK','HAS_SECTION','HAS_UNIT','HAS_FILE','HAS_DIRECTORY','HAS_DIRECTIVE'}
SEMANTIC = {'DOCUMENTED_BY','PARAMETER_OF','CONSUMES_FIELD','PRODUCES_FIELD','DEFAULT_WHEN',
            'REQUIRES_WHEN','CONFLICTS_WITH','HAS_ROLE','HAS_UNIT','SELECTS_MODEL',
            'ASSERTION_SUBJECT','LEXICALLY_ALIGNED_WITH','INPUT_SIGNATURE_MATCH'}


class Paths:
    def __init__(self,graph):
        self.graph=graph;self.nodes=graph['nodes'];self.adjacency=defaultdict(list)
        for edge in graph['edges']:
            self.adjacency[edge['source']].append((edge['target'],edge,'forward'))
            if edge['relation'] in STRUCTURAL|{'DECLARES','DOCUMENTED_BY','STATIC_REFERS_TO','ASSERTION_OBJECT','PARAMETER_OF','CONFLICTS_WITH',
                                               'ASSERTION_SUBJECT','LEXICALLY_ALIGNED_WITH','INPUT_SIGNATURE_MATCH'}:
                self.adjacency[edge['target']].append((edge['source'],edge,'reverse_navigation'))

    def search(self,seeds,case_scopes=(),max_depth=5,beam=64,with_paths=True,with_cross=True,with_scope=True,condition_mode='declarations'):
        if condition_mode not in {'declarations','satisfied_only'}:raise ValueError('invalid condition search mode')
        active=[{'node':nid,'nodes':[nid],'edges':[],'score':score} for nid,score in seeds if nid in self.nodes]
        active=sorted(active,key=lambda path:(-path['score'],path['node']))[:beam]
        found=list(active);visits=0
        if not with_paths:return found,{'expanded_edges':0}
        for _ in range(max_depth):
            following=[]
            for path in active:
                for target,edge,direction in self.adjacency[path['node']]:
                    visits+=1
                    if target in path['nodes']:continue
                    relation=edge['relation']
                    if not with_cross and edge.get('instance_evidence') and edge.get('definition_evidence'):continue
                    if condition_mode=='satisfied_only' and edge.get('conditions') and edge.get('condition_satisfied') is not True:continue
                    scope=self.nodes[target].get('scope',{}).get('case_directory')
                    if with_scope and case_scopes and scope and scope not in case_scopes:continue
                    origin=self.nodes[path['nodes'][0]].get('scope',{}).get('case_directory')
                    if with_scope and origin and scope and origin!=scope:continue
                    if direction=='reverse_navigation' and relation in {'CONSUMES_FIELD','PRODUCES_FIELD','REQUIRES_WHEN','DEFAULT_WHEN'}:continue
                    score=path['score']*.8+(0.08 if relation=='DOCUMENTED_BY' else .02 if relation in SEMANTIC else 0)
                    following.append({'node':target,'nodes':path['nodes']+[target],
                        'edges':path['edges']+[{'id':edge['id'],'direction':direction}],'score':score})
            following.sort(key=lambda path:(-path['score'],path['node'],wire(path['edges'])))
            unique={}
            for path in following:
                unique.setdefault((path['node'],tuple(edge['id'] for edge in path['edges'])),path)
            active=list(unique.values())[:beam];found.extend(active)
            if not active:break
        return found,{'expanded_edges':visits,'max_depth':max_depth,'beam':beam}
