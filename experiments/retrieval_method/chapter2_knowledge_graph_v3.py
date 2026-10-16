"""Source identity and graph-adjacent original context; no external index."""
from collections import defaultdict,deque
from pathlib import PurePosixPath
import re
import unicodedata

from chapter2_knowledge_graph_v2 import EvidenceGraphV2,PLATFORM_WORDS,ENGLISH_STOP
from chapter2_knowledge_graph_retriever import present,terms
from candidate_graph_utils import tokens


def identity_fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))


class SourceContextGraph(EvidenceGraphV2):
    def __init__(self,*args,context_characters=2400,identity_ranking=True,parent_retrieval=True,**kwargs):
        super().__init__(*args,**kwargs)
        if type(context_characters) is not int or context_characters<0:raise ValueError('Invalid source context budget')
        self.context_characters=context_characters
        self.identity_ranking=identity_ranking
        self.parent_retrieval=parent_retrieval
        self.raw_nodes={n['unit_id']:n['id'] for n in self.nodes.values() if n['kind']=='original_unit'}
        self.case_aliases=defaultdict(set)
        for unit in self.graph['units'].values():
            context=unit.get('source_context',{})
            if context.get('case_directory'):
                self.case_aliases[context['case_directory']].update(context['case_aliases'])
        for parent in self.graph.get('source_containers',{}).values():
            members=[self.graph['units'][uid] for uid in parent['members']]
            if (not members or len({u['id'] for u in members})!=len(members)
                or any(u['path']!=parent['path'] or u['sha256']!=parent['sha256'] for u in members)
                or members[0]['start']!=parent['start'] or members[-1]['end']!=parent['end']
                or any(l['end']+1!=r['start'] for l,r in zip(members,members[1:]))):
                raise ValueError('Invalid source parent membership')

    def _facet_flat(self,query):
        flat=super()._facet_flat(query)
        if not self.identity_ranking:return flat
        folded=identity_fold(query)
        if folded!=query.casefold():
            normalized=super()._facet_flat(folded)
            merged={r['node_id']:r for r in flat['items']}
            for row in normalized['items']:
                if row['node_id'] not in merged or row['score']>merged[row['node_id']]['score']:merged[row['node_id']]=row
            flat['items']=list(merged.values())
        distinctive=re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])',' ',query,flags=re.I)
        distinctive=re.sub(r'场景\s*[A-Z](?![A-Za-z0-9_])',' ',distinctive)
        identifiers={identity_fold(s) for s in re.findall(r'[A-Za-z_\u00c0-\u024f][A-Za-z0-9_\u00c0-\u024f]*',distinctive)}-ENGLISH_STOP-PLATFORM_WORDS-{'yes','no','true','false'}
        explicit_files={p for p in self.hashes if any(p.casefold().endswith('/'+s.casefold()) for s in re.findall(r'[A-Za-z0-9_./]+',query) if '/' in s)}
        cases={case for case,aliases in self.case_aliases.items() if any(present(query,alias) for alias in aliases)}
        rows=[];node_by_unit=defaultdict(list)
        for row in flat['items']:node_by_unit[self.nodes[row['node_id']]['unit_id']].append(row)
        for uid,unit in self.graph['units'].items():
            if ('手册' in query and '教程' not in query and not cases and unit['path'].startswith('tutorials/')):continue
            if ('只查教程' in query or '仅查教程' in query) and unit['path'].startswith('manual/'):continue
            if re.search(r'"key"\s*:\s*"FoamFile"',unit['owner_key']):continue
            stripped=re.sub(r'/\*[\s\S]*?\*/|//[^\n]*','',unit['text']).strip()
            if not stripped:continue
            nodecase=unit.get('source_context',{}).get('case_directory')
            if cases and nodecase and nodecase not in cases:continue
            # Literal identity matching operates on each source-owned fragment,
            # so an exact filename/field anchors the owning original, rather
            # than rewarding an unrelated node with a common parameter name.
            text=identity_fold(unit['text'])
            exact={t for t in identifiers if present(text,t)}
            basename=PurePosixPath(unit['path']).name.casefold()
            filename=(basename in identifiers and (len(basename)>2 or bool(cases))) or unit['path'] in explicit_files
            context_match=bool(cases and nodecase in cases)
            declared=set(self.graph.get('source_file_declarations',{}).get(unit['path'],{}).get('keys',[]))
            joint_keys=identifiers & {identity_fold(k) for k in declared}
            joint_coverage=len(joint_keys)/max(1,len(identifiers)) if len(joint_keys)>=2 and self.options['with_cross'] and self.options['with_paths'] else 0
            headings=unit.get('context',[])
            direct_heading={t for t in identifiers if headings and headings[-1]['level']>1 and present(identity_fold(headings[-1]['title']),t)}
            if uid not in node_by_unit and (filename or context_match or direct_heading):
                nid=self.raw_nodes[uid]
                node_by_unit[uid]=[dict(node_id=nid,score=0,origin=nid,visited=[nid],route=[],reasons={})]
            for row in node_by_unit[uid]:
                node=self.nodes[row['node_id']]
                score=row['score']*.45+24*len(exact)/max(1,len(identifiers))
                score+=24*filename+12*context_match+12*joint_coverage
                score+=8*len(direct_heading)
                if '默认' in query and unit['path'].startswith('manual/') and present(text,'default'):score+=6
                if node.get('dictionary','').startswith('FoamFile'):continue
                reasons=dict(row['reasons'],source_filename_match=filename,
                    source_case_alias_match=context_match,original_identifier_overlap=sorted(exact),direct_heading_identifiers=sorted(direct_heading),parent_declared_key_overlap=sorted(joint_keys),parent_declaration_bonus=12*joint_coverage)
                rows.append({**row,'score':score,'reasons':reasons})
        rows.sort(key=lambda r:(-r['score'],self.nodes[r['node_id']]['path'],self.graph['units'][self.nodes[r['node_id']]['unit_id']]['start'],r['node_id']))
        return dict(items=rows,diagnostic={**flat['diagnostic'],'seeds':rows[:self.options['seed_limit']],
            'seed_policy':'literal_case_file_and_owned_original_v3','source_derived_cases':sorted(cases)})

    def rank(self,query):
        result=super().rank(query)
        result['schema']='source_identity_context_graph_ranking_v3_development'
        result['diagnostic'].update(context_characters=self.context_characters,identity_ranking=self.identity_ranking,parent_retrieval=self.parent_retrieval)
        return result

    def _context(self,row):
        node=self.nodes[row['node_id']];uid=node['unit_id'];unit=self.graph['units'][uid]
        selected={uid:unit};routes={uid:[]}
        if not self.options['with_paths'] or not self.context_characters:return selected,routes
        if self.parent_retrieval:
            parents=[self.graph['source_containers'][cid] for cid in unit.get('parent_context_ids',[])]
            parents.sort(key=lambda p:(p['characters'],p['start']))
            def bridge(source,target,parent):
                if source==target:return []
                for dest,edge,direction in self.adjacency[source]:
                    if dest==target and edge['relation']=='SOURCE_PARENT_CONTEXT' and edge.get('support',{}).get('container_id')==parent['id']:
                        return [dict(edge_id=edge['id'],relation=edge['relation'],direction=direction,cross_owner=edge['cross_owner'],container_id=parent['id'])]
                raise ValueError('Source parent membership lacks an allowed graph edge')
            # Preserve ancestor introductions before spending the context
            # allowance on sibling detail. A long parent is not silently
            # described as fully returned: every selected fragment is listed.
            for parent in parents:
                intro=self.graph['units'][parent['members'][0]]
                if intro['id'] in selected:continue
                if not self.options['with_cross'] and intro['owner']!=unit['owner']:continue
                if sum(len(v['text']) for v in selected.values())+len(intro['text'])>self.context_characters:continue
                selected[intro['id']]=intro
                routes[intro['id']]=bridge(self.raw_nodes[uid],self.raw_nodes[intro['id']],parent)
            for parent in parents:
                members=[self.graph['units'][v] for v in parent['members']]
                combined={**selected,**{v['id']:v for v in members}}
                if sum(len(v['text']) for v in combined.values())>self.context_characters:continue
                if not self.options['with_cross'] and any(v['owner']!=unit['owner'] for v in members):continue
                representative=self.raw_nodes[parent['members'][0]]
                for v in members:
                    selected[v['id']]=v
                    routes[v['id']]=bridge(self.raw_nodes[uid],representative,parent)+bridge(representative,self.raw_nodes[v['id']],parent) if v['id']!=uid else []
        used=sum(len(v['text']) for v in selected.values());frontier=deque([(self.raw_nodes[k],routes[k]) for k in selected])
        while frontier:
            current,route=frontier.popleft()
            for target,edge,direction in sorted(self.adjacency[current],key=lambda e:self.graph['units'][self.nodes[e[0]]['unit_id']]['start']):
                if edge['relation']!='SOURCE_NEXT_FRAGMENT':continue
                other=self.nodes[target];v=self.graph['units'][other['unit_id']]
                if v['id'] in selected or v['path']!=unit['path']:continue
                if any(c['title'].strip().casefold() in {'contents','table of contents','目录'} for c in v.get('context',[])):continue
                # File boilerplate is a traversal barrier, never a relevance hit.
                if re.search(r'"key"\s*:\s*"FoamFile"',v['owner_key']):continue
                if used+len(v['text'])>self.context_characters:continue
                used+=len(v['text']);selected[v['id']]=v
                next_route=route+[dict(edge_id=edge['id'],direction=direction,relation=edge['relation'],cross_owner=edge['cross_owner'])]
                routes[v['id']]=next_route;frontier.append((target,next_route))
        return selected,routes

    def read_native(self,ranking):
        items=[];seen=set()
        for row in ranking['items']:
            selected,routes=self._context(row)
            fresh=[v for k,v in selected.items() if k not in seen]
            if not fresh:continue
            fresh.sort(key=lambda v:v['start']);ranges=[]
            for unit in fresh:
                if ranges and ranges[-1]['end']+1==unit['start']:ranges[-1]['end']=unit['end']
                else:ranges.append(dict(start=unit['start'],end=unit['end']))
                seen.add(unit['id'])
            items.append(dict(path=row['path'],ranges=ranges,native_unit=row['node_id'],
                native_rank=row['native_rank'],owner=row['owner'],original_sha256=self.hashes[row['path']],
                read_policy='original_fragments_linked_by_literal_adjacency',
                context_fragments=[dict(unit_id=v['id'],owner=v['owner'],start=v['start'],end=v['end'],route=routes[v['id']]) for v in fresh]))
        return dict(items=items,ranking_diagnostic=ranking['diagnostic'],native_ranking=ranking)
