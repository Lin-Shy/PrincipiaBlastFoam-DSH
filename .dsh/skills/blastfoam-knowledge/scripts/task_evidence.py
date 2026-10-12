"""把任务结构投影为现有定位器可遍历的原文单元；排序/提示/预算保持不变。"""
from collections import defaultdict
from pathlib import Path

import evidence_bundle as b
import domain_graph as d


def build(skill):
    skill=Path(skill); graph=b.build(skill)
    source=b.k.read_json(b.k.release_path(skill/'index')/'graph.json')
    structure=source.get('task_structure')
    if not structure:raise ValueError('task structure graph required')
    nodes={n['id']:n for n in source['nodes']}; units={u['id']:u for u in graph['units']}
    byfile=defaultdict(list)
    for unit in units.values():byfile[unit['path']].append(unit)
    parameters={n['id']:n for n in source['nodes'] if n['kind']=='manual_parameter'}
    parameter_units={}
    for uid,param in parameters.items():
        ev=param['evidence']
        found=[u['id'] for u in byfile[ev['path']] if u['start']==ev['line_start'] and u['end']==ev['line_end']]
        if len(found)!=1:raise ValueError('parameter row does not have a unique original evidence unit')
        parameter_units[uid]=found[0]
        unit=units[found[0]]
        unit.update(parameter=param,source_category='manual',evidence_status='manual_explicit')
    def targets(node):
        if node['id'] in parameter_units:return [parameter_units[node['id']]]
        if node['kind']=='manual_section':
            documented=[nodes[e['target']] for e in source['edges'] if e['source']==node['id'] and e['relation']=='DOCUMENTED_ON']
            return sorted({uid for n in documented for uid in targets(n)})
        ev=node.get('evidence')
        if not ev:return []
        exact=[u['id'] for u in byfile[ev['path']] if u['start']==ev['line_start'] and u['end']==ev['line_end']]
        if exact:return exact
        return [u['id'] for u in byfile[ev['path']] if u['start']<=ev['line_end'] and u['end']>=ev['line_start']]
    for edge in source['edges']:
        if edge['relation'] not in {'PARAMETER_CONTEXT','PARAMETER_INSTANCE','PARAMETER_INSTANCE_CANDIDATE','SELECTS_DOCUMENTED_MODEL'}:continue
        relation='SECTION_CONTEXT' if edge['relation']=='PARAMETER_CONTEXT' else edge['relation']
        proof=edge.get('supporting_evidence',[edge['evidence']])
        for src in targets(nodes[edge['source']]):
            for dst in targets(nodes[edge['target']]):
                if src==dst:continue
                graph['edges'].append({'source':src,'target':dst,'relation':relation,'evidence':proof,'status':edge['status'],
                    'structural_relation':edge['relation'],'structural_source':edge['source'],'structural_target':edge['target']})
    # Preserve the exact dictionary paths behind each physical evidence block.
    for node in source['nodes']:
        if node['kind']!='configuration' or node['dictionary_path'].startswith('FoamFile/'):continue
        for uid in targets(node):
            units[uid].setdefault('configuration_paths',[]).append(node['dictionary_path'])
    for unit in units.values():
        if 'configuration_paths' in unit:unit['configuration_paths']=sorted(set(unit['configuration_paths']))
    graph['edges']=list({b.wire(e):e for e in graph['edges']}.values())
    graph['task_structure']={**structure,'projection_sha256':b.sha(Path(__file__).read_bytes())}
    graph['snapshot']=b.sha({key:value for key,value in graph.items() if key!='snapshot'})
    return graph


class EvidenceSearch(b.EvidenceSearch):
    def __init__(self,skill):
        super().__init__(graph=build(skill),skill=skill)

    def validate(self):
        data=self.graph['task_structure']
        if data['projection_sha256']!=b.sha(Path(__file__).read_bytes()):raise ValueError('task projection changed')
        for name,expected in data['dependencies'].items():
            if b.sha((self.skill/'scripts'/name).read_bytes())!=expected:raise ValueError('task structure dependency changed: '+name)
        super().validate()


def domain(engine):
    result=d.build(engine)
    for uid,unit in engine.units.items():
        param=unit.get('parameter')
        if not param:continue
        parent=next((meta for key,meta in result['metadata'].items() if meta['section']==param['section']),None)
        if parent is None:raise ValueError('manual parameter parent metadata missing')
        result['metadata'][uid]={**parent,'parameter_id':param['id'],'parameter_label':param['label']}
    result['coverage']['parameter_rows']=sum('parameter' in u for u in engine.units.values())
    result['snapshot']=b.sha({key:value for key,value in result.items() if key!='snapshot'})
    return result
