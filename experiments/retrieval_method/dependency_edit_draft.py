"""Instantiate explicitly reviewed example bindings, never arbitrary search hits."""


def draft_dependency_edits(search, packet, active_rules, bindings):
    import evidence_bundle as b
    from condition_graph import validate
    if b.sha({k:v for k,v in bindings.items() if k!='snapshot'})!=bindings['snapshot']:
        raise ValueError('edit binding digest mismatch')
    if bindings['condition_snapshot']!=search.index['snapshot']:
        raise ValueError('edit binding condition snapshot changed')
    rules={r['id']:r for r in validate(search.index,search.engine)}
    exposed={c['id'] for c in packet.get('conditions',[])}
    edits=[];support=[];target_states=[]
    for binding in bindings['bindings']:
        rule_id=binding['rule']
        if rule_id not in active_rules or rule_id not in exposed:continue
        if binding['review']!='accept':continue
        rule=rules[rule_id];ev=rule['examples'][binding['example_index']]
        owner=next(c for c in search.engine.graph['cases'] if ev['path'].startswith(c+'/'))
        target=ev['path'][len(owner)+1:]
        source=(search.engine.skill/'corpus'/ev['path']).read_text()
        entries,diagnostics=b.k.parse_dictionary(source)
        if diagnostics:raise ValueError('example dictionary has unresolved syntax')
        prefix=binding['source_parent']
        targets=binding['target_parents']
        if 'lookup_requirement' in binding:
            lookups=rule['requirements'][binding['lookup_requirement']]['lookup_entries']
            targets=list(dict.fromkeys(x.rsplit('/',1)[0] for x in lookups))
        chosen=[];lines=source.splitlines(keepends=True)
        for entry in entries:
            key=entry['dictionary_path']
            if key.startswith('FoamFile/') or key.rpartition('/')[0]!=prefix:continue
            if not ev['start']<=entry['line_start']<=entry['line_end']<=ev['end']:continue
            raw=''.join(lines[entry['line_start']-1:entry['line_end']]).strip()
            if raw not in ev['quote'] or not entry['resolved']:continue
            chosen.append(entry)
        if not chosen:raise ValueError('reviewed example binding has no complete entries')
        edit_count=len(edits)
        for parent in targets:
            policy=binding.get('target_state_policy')
            if policy:
                condition=next(c for c in packet['conditions'] if c['id']==rule_id)
                reqs=condition.get('requirements',[])
                pos=binding['lookup_requirement']
                observation=reqs[pos].get('lookup_state',{}) if pos<len(reqs) else {}
                key=parent+'/'+policy['selector']
                value=observation.get('values',{}).get(key)
                if observation.get('status')=='file_absent':state='missing'
                elif observation.get('status')!='observed_not_validated' or not isinstance(value,str) or not value.strip():state='unresolved'
                elif value in policy['replace_values']:state='replacement_required'
                else:state='present_preserved'
                target_states.append({'path':target,'entry':key,'state':state,
                                      'value':value,'sha256':observation.get('sha256'),
                                      'via':observation.get('via')})
                # Existing selectors are preserved, not certified compatible.
                # Failed lookups are not evidence of absence or permission to overwrite.
                if state in ('present_preserved','unresolved'):continue
            for entry in chosen:
                mapped=parent+'/'+entry['dictionary_path'].rsplit('/',1)[-1] if parent else entry['dictionary_path'].rsplit('/',1)[-1]
                operation={'path':target,'entry':mapped,'value':entry['value']}
                prior=next((x for x in edits if (x['path'],x['entry'])==(target,mapped)),None)
                if prior and prior!=operation:raise ValueError('conflicting example bindings')
                if not prior:edits.append(operation)
        if len(edits)==edit_count:continue
        support.append({'rule':rule_id,'binding':binding['id'],'source':ev['path'],
                        'start':ev['start'],'end':ev['end'],'sha256':ev['sha256']})
    return {'status':'conditional_reference_draft','edits':edits,'support':support,'target_states':target_states,
            'activation':'caller supplied future active rules; not inferred from current inputs',
            'choice':'reviewed reference settings, not unique or universally appropriate numerical parameters'}
