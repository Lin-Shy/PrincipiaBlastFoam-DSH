"""Experimental projection of exposed graph bindings into explicit model edits.

The native locator supplies explicit inputs and requested removal keys. This
module neither extracts values from prose nor chooses a model or obsolete keys.
"""
from decimal import Decimal, InvalidOperation
import re


def draft_model_edits(search, packet, inputs, removals=()):
    exposed={n['id'] for n in packet['locations']}
    traversed={(e['source'],e['target'],e.get('selector_entry')) for e in packet.get('relations',[])
               if e['relation']=='MODEL_INPUT_SCHEMA' and e.get('traversal')!='reverse'}
    links=[e for e in search.graph['edges'] if e['relation']=='MODEL_INPUT_SCHEMA'
           and e['source'] in exposed and e['target'] in exposed
           and (e['source'],e['target'],e['selector_entry']) in traversed]
    if len(links)!=1:
        return {'status':'ambiguous_or_missing_model_binding','edits':[]}
    link=links[0];selector=search.nodes[link['source']];schema=search.nodes[link['target']]
    if schema.get('complete_local_reads') is False:
        return {'status':'incomplete_source_schema','edits':[],'unresolved':schema.get('unresolved',[])}
    pairs=[e for e in search.graph['edges'] if e['relation']=='SELECTOR_COEFFICIENTS'
           and e['source']==link['source'] and e['selector_entry']==link['selector_entry']
           and e['target'] in exposed]
    if len(pairs)!=1:
        return {'status':'ambiguous_or_missing_coefficient_binding','edits':[]}
    coefficients=search.nodes[pairs[0]['target']]
    if selector['case']!=packet['case'] or coefficients['case']!=packet['case']:
        return {'status':'case_mismatch','edits':[]}
    relative=lambda n:n['path'].removeprefix(packet['case']+'/')
    prefix=schema['scope'].split('/',1)[1]+'/'
    mapped=[];missing=[]
    for item in schema['entries']:
        entry=item['entry']
        if not entry.startswith(prefix):return {'status':'unsupported_schema','edits':[]}
        key=entry[len(prefix):]
        if item.get('requirement')=='conditional':
            return {'status':'unresolved_input_condition','edits':[],'input':key,'conditions':item.get('conditions',[])}
        if key not in inputs:
            if item.get('requirement')!='optional':missing.append(key)
            continue
        if 'value_type' in item and item['value_type']!='scalar':
            return {'status':'unsupported_input_type','input':key,'edits':[]}
        value=inputs[key]
        try:
            if (not isinstance(value,str) or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',value)
                    or not Decimal(value).is_finite()):raise ValueError()
        except (InvalidOperation,ValueError):
            return {'status':'invalid_scalar_input','input':key,'edits':[]}
        mapped.append({'path':relative(coefficients),'entry':coefficients['scope']+'/'+key,'value':value})
    if missing:return {'status':'missing_inputs','missing_inputs':missing,'edits':[]}
    existing={e['entry'] for e in coefficients.get('entries',[])}
    deletions=[]
    for key in sorted(set(removals)):
        entry=coefficients['scope']+'/'+key
        if not re.fullmatch(r'[A-Za-z_]\w*',key) or entry not in existing:
            return {'status':'unbound_removal','edits':[]}
        if any(e['entry']==entry for e in mapped):
            return {'status':'conflicting_model_edits','edits':[]}
        deletions.append({'path':relative(coefficients),'entry':entry,'value':None})
    return {'status':'draft_requires_review',
            'edits':[{'path':relative(selector),'entry':link['selector_entry'],'value':schema['model']},*mapped,*deletions],
            'support':{'selector_node':selector['id'],'coefficient_node':coefficients['id'],
                       'input_schema_node':schema['id']},
            'remaining':'inherited inputs, unrequested old-key policy, numerical dependencies and runtime validation are not covered'}
