"""Attach explicitly reviewed conditional requirements to dictionary edit locations.

Bindings are author-reviewed retrieval hints. Conditions are never presumed true.
"""
import argparse
import fnmatch
import re
import subprocess
from pathlib import Path
import evidence_bundle as b
from edit_graph import EditSearch


def validate(index,engine):
    if b.sha({k:v for k,v in index.items() if k!='snapshot'})!=index['snapshot']:
        raise ValueError('condition index digest mismatch')
    accepted=[]
    for rule in index['rules']:
        if rule['review']['status']!='accept':continue
        if not rule.get('evidence'):raise ValueError('condition needs source evidence')
        guard=rule.get('runtime_guard')
        preparation=rule.get('preparation')
        if preparation and (not guard or preparation.get('relation')!='PREPARES_FOR'
                or preparation.get('review')!='accept' or not preparation.get('when')
                or not preparation.get('evidence')):
            raise ValueError('preparation needs reviewed branch and source evidence')
        if guard:
            compact=lambda s:re.sub(r'\s+','',s)
            if (guard.get('review')!='accept' or not guard.get('expression') or not guard.get('evidence')
                    or not any('if('+compact(guard['expression'])+')' in compact(ev['quote']) for ev in guard['evidence'])):
                raise ValueError('runtime guard is not a reviewed source if condition')
        for ev in rule['evidence']+rule.get('review_sources',[])+rule.get('examples',[])+rule.get('state_binding',{}).get('evidence',[])+[x for r in rule.get('requirements',[]) for x in r['evidence']]+(guard['evidence'] if guard else [])+(preparation['evidence'] if preparation else []):
            if engine.graph['inventory'].get(ev['path'])!=ev['sha256']:raise ValueError('condition source changed')
            lines=engine.texts.get(ev['path'])
            if lines is None:lines=(engine.skill/'corpus'/ev['path']).read_text().splitlines(keepends=True)
            if not 1<=ev['start']<=ev['end']<=len(lines):raise ValueError('invalid condition range')
            raw=''.join(lines[ev['start']-1:ev['end']])
            if not ev['quote'] or ev['quote'] not in raw:raise ValueError('invalid condition quote')
        accepted.append(rule)
    return accepted


def example_differences(rule,engine,case):
    """Compare exact keys in reviewed snippets; do not resolve patterns or physics."""
    result=[]
    for ev in rule.get('examples',[]):
        owner=next((c for c in engine.graph['cases'] if ev['path'].startswith(c+'/')),None)
        if owner is None:continue
        relative=ev['path'][len(owner)+1:];target=case+'/'+relative
        source=(engine.skill/'corpus'/ev['path']).read_text()
        target_file=engine.skill/'corpus'/target
        current={n['dictionary_path']:n['value'] for n in b.k.parse_dictionary(target_file.read_text())[0]} if target_file.is_file() else {}
        entries=[]
        source_lines=source.splitlines(keepends=True)
        for n in b.k.parse_dictionary(source)[0]:
            if n['dictionary_path'].startswith('FoamFile/') or not ev['start']<=n['line_start']<=n['line_end']<=ev['end']:continue
            raw=''.join(source_lines[n['line_start']-1:n['line_end']]).strip()
            if raw not in ev['quote']:continue
            value=current.get(n['dictionary_path'])
            if value==n['value']:continue
            entries.append({'entry':n['dictionary_path'],'example_value':n['value'],'target_value':value})
            if len(entries)>=6:break
        if entries:
            result.append({'target':relative,'example':ev['path'],'entries':entries,
                'status':'exact_key_difference_not_required_change; patterns/includes not resolved'})
        if len(result)>=3:break
    return result


def lookup_observations(requirement,case_root):
    """Resolve reviewed concrete inputs in current bytes, not example patterns."""
    entries=requirement.get('lookup_entries',[])
    if not entries:return {}
    path=b.k.confined(Path(case_root).resolve(),requirement['target'])
    if not path.is_file():return {'lookup_state':{'status':'file_absent'}}
    raw=path.read_bytes()
    result={'sha256':b.sha(raw),'via':'foamDictionary','values':{}}
    if b'#' in raw or b'$' in raw:
        return {'lookup_state':{**result,'status':'unsupported_directives'}}
    for entry in entries[:8]:
        try:
            p=subprocess.run(['foamDictionary',str(path),'-entry',entry,'-value'],capture_output=True,text=True,timeout=5)
            result['values'][entry]=p.stdout.strip() if p.returncode==0 else {'status':'lookup_failed'}
        except (OSError,subprocess.TimeoutExpired):
            result['values'][entry]={'status':'resolver_unavailable'}
    result['status']='observed_not_validated'
    if path.read_bytes()!=raw:return {'lookup_state':{'status':'changed_during_lookup'}}
    return {'lookup_state':result}


def requirement_packet(rule,case_root=None):
    sources=[];lookup={};requirements=[]
    for req in rule.get('requirements',[]):
        ids=[]
        for ev in req['evidence']:
            ref={k:v for k,v in ev.items() if k not in ('quote','sha256')};key=b.wire(ref)
            if key not in lookup:
                lookup[key]='S'+str(len(sources)+1);sources.append({'id':lookup[key],**ref})
            ids.append(lookup[key])
        requirements.append({k:v for k,v in req.items() if k not in ('evidence','lookup_entries')} | {'support':ids}
                            | (lookup_observations(req,case_root) if case_root is not None else {}))
    return {'requirements':requirements,'code_sources':sources}


def compact_differences(rule,engine,case):
    refs={ev['path']:'E'+str(i+1) for i,ev in enumerate(rule.get('examples',[]))}
    result=[]
    for d in example_differences(rule,engine,case):
        parents={x['entry'].rsplit('/',1)[0] for x in d['entries'] if '/' in x['entry']}
        prefix=next(iter(parents))+'/' if len(parents)==1 and len(d['entries'])>1 and all('/' in x['entry'] for x in d['entries']) else ''
        item={'target':d['target'],'example_ref':refs[d['example']]}
        if prefix:item['entry_prefix']=prefix
        missing={x['entry'][len(prefix):]:x['example_value'] for x in d['entries'] if x['target_value'] is None}
        different={x['entry'][len(prefix):]:[x['target_value'],x['example_value']] for x in d['entries'] if x['target_value'] is not None}
        if missing:item['missing_exact']=missing
        if different:item['different_exact']=different
        result.append(item)
    return result


class ConditionalEditSearch:
    def __init__(self,engine,index):
        self.engine=engine;self.search=EditSearch(engine);self.index=index
        self.rules=validate(index,engine)

    def assess_case(self,case_root,case,budget=5000):
        """Bind reviewed rules to current files, never to a presumed future edit."""
        from case_state import viscosity_state
        if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('budget must be 1000..24000')
        case='tutorials/'+case.removeprefix('tutorials/')
        case=self.engine.graph['aliases'].get(case,case)
        if case not in self.engine.graph['cases']:raise ValueError('unknown case')
        self.engine.validate()
        rules=validate(self.index,self.engine)
        result={'status':'ok','case':case,'condition_snapshot':self.index['snapshot'],
                'scope':'current files only; reassess after edits; no automatic removal or future-state claim',
                'conditions':[],'omitted_rules':[]}
        state=None
        for rule in rules:
            binding=rule.get('state_binding',{})
            if binding.get('review',{}).get('status')!='accept':continue
            if binding.get('predicate')!='explicit_const_zero_excludes_viscosity':continue
            # Runtime interpretation must have an explicit reviewed solver scope.
            if not rule.get('case_patterns') or not any(fnmatch.fnmatchcase(case,p) for p in rule['case_patterns']):continue
            if not binding.get('evidence'):raise ValueError('state binding needs evidence')
            if state is None:state=viscosity_state(case_root)
            control=b.k.confined(Path(case_root).resolve(),'system/controlDict')
            application=None;control_sha=None
            if control.is_file():
                data=control.read_bytes();control_sha=b.sha(data)
                entries,diagnostics=b.k.parse_dictionary(data.decode())
                apps=[n for n in entries if n['dictionary_path'].split('@')[0]=='application']
                if not diagnostics and len(apps)==1 and apps[0]['resolved']:application=apps[0]['value']
            application_matches=bool(binding.get('application')) and application==binding['application']
            inactive=state['state']=='all_const_zero' and application_matches
            item={'id':rule['id'],'when':rule['when'],
                  'condition_evaluation':'inactive_for_current_inputs' if inactive else 'not_evaluated',
                  'state':state,'binding_evidence':binding['evidence'],
                  'application_check':{'application':application,'matches_reviewed_application':application_matches,
                                       'controlDict_sha256':control_sha},
                  'required_files_semantics':rule['required_files_semantics'],
                  'required_files':[] if inactive else rule['required_files'],
                  'requirements_scope':rule.get('requirements_scope'),
                  **({'requirements':[],'code_sources':[]} if inactive else requirement_packet(rule,case_root))}
            candidate={**result,'conditions':result['conditions']+[item]}
            if len(b.wire(candidate))<=budget-200:result=candidate
            else:result['omitted_rules'].append(rule['id'])
        if result['omitted_rules']:result['status']='partial'
        if len(b.wire(result))>budget:return {'status':'insufficient_budget','conditions':[]}
        return result

    def locate(self,original,case,query='',translation='',budget=5000,graph=True):
        packet=self.search.locate(original,case,query,translation,budget,graph)
        if not graph:return packet
        rules=validate(self.index,self.engine)
        selected=[]
        for rule in rules:
            if rule.get('case_patterns') and not any(fnmatch.fnmatchcase(packet['case'],p) for p in rule['case_patterns']):continue
            # Bind only the primary edit locations. Low-ranked filler or graph
            # context must not activate unrelated physical dependency packets.
            matches=[x['dictionary'] for x in packet['locations'][:2] if x['path'].startswith(packet['case']+'/')
                     and any(fnmatch.fnmatchcase(x['dictionary'],p) for p in rule['dictionary_patterns'])]
            if not matches:continue
            selected.append({'id':rule['id'],'relation':rule.get('relation','REQUIRES_WHEN'),'when':rule['when'],
                **({'preparation':{k:rule['preparation'][k] for k in ('relation','when')}} if rule.get('preparation') else {}),
                'condition_evaluation':'not_evaluated','binding_status':'reviewed_hint',
                'required_files_semantics':rule['required_files_semantics'],
                'required_files':[{'path':p,'present_in_template':packet['case']+'/'+p in self.engine.graph['inventory']}
                                  for p in rule['required_files']],
                'evidence':[{k:v for k,v in ev.items() if k not in ('quote','sha256')} for ev in rule['evidence']] if rule.get('requirements') else rule['evidence'],'examples':[{'id':'E'+str(i+1),**{k:v for k,v in ev.items() if k not in ('quote','sha256')}} for i,ev in enumerate(rule.get('examples',[]))] if rule.get('requirements') else rule.get('examples',[]),
                'example_differences':compact_differences(rule,self.engine,packet['case']) if rule.get('requirements') else example_differences(rule,self.engine,packet['case']),
                'difference_semantics':'example exact keys, not required edits; entry_prefix + key',
                'requirements_scope':rule.get('requirements_scope'),
                **requirement_packet(rule,self.engine.skill/'corpus'/packet['case'])})
            if len(selected)>=2:break
        # Reserve complete conditional evidence, then repack the ordinary edit locations.
        while selected:
            additions={'conditions':selected,'condition_snapshot':self.index['snapshot']}
            extra=len(b.wire(additions))+2
            if budget-extra>=1000:
                scoped=self.search.locate(original,case,query,translation,budget-extra,graph)
                result={**scoped,**additions}
                if len(b.wire(result))<=budget:return result
            selected.pop()
        return packet


def main():
    p=argparse.ArgumentParser();p.add_argument('--condition-index',type=Path,required=True)
    p.add_argument('--original',required=True);p.add_argument('--case',required=True)
    p.add_argument('--query',default='');p.add_argument('--translation',default='');p.add_argument('--budget',type=int,default=5000)
    a=p.parse_args();engine=b.EvidenceSearch();search=ConditionalEditSearch(engine,b.k.read_json(a.condition_index))
    print(b.wire(search.locate(a.original,a.case,a.query,a.translation,a.budget)))

if __name__=='__main__':main()
