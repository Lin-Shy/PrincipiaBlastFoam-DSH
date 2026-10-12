"""冻结并执行完整候选的七项单因素消融和两项预注册交互消融。"""
from __future__ import annotations
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import time

import candidate_qa as candidate
import graphify_qa as base
import leaderboard_audit as audit
import navigation_qa as qa


ARM_FACTORS = {
    'minus_role_scope': ('role_scope',),
    'minus_conditional_bilateral': ('conditional_bilateral',),
    'minus_semantic_recall': ('semantic_recall',),
    'minus_paths': ('paths',),
    'minus_evidence_groups': ('evidence_groups',),
    'minus_gap_strategy': ('gap_strategy',),
    'minus_claim_verification': ('claim_verification',),
    'minus_role_scope_x_conditional_bilateral': ('role_scope', 'conditional_bilateral'),
    'minus_paths_x_evidence_groups': ('paths', 'evidence_groups'),
}
GROUPS = {name: ['retrieval_first'] for name in ARM_FACTORS}
ROLE_FIELDS = {'role', 'subject_role', 'selector_keys', 'parent_keys', 'input_signature',
               'output_signature', 'scope', 'dictionary', 'components', 'physical_components'}


def anchor_identity(anchor):
    return anchor['path'], anchor['start'], anchor['end']


def transform_graph(source, factors):
    """Create an information-removing graph artifact, rather than a query-only switch."""
    graph = copy.deepcopy(source)
    factors = set(factors)
    nodes = graph['nodes']
    edges = graph['edges']
    if 'role_scope' in factors:
        for node in nodes.values():
            for key in ROLE_FIELDS:
                node.pop(key, None)
            if node['kind'] == 'domain_definition':
                node['label'] = node.get('name', node['label'])
        # Remove every relation whose owner/target was chosen by role-aware construction.
        kept = []
        for edge in edges:
            source_node, target_node = nodes[edge['source']], nodes[edge['target']]
            role_owned_assertion = (source_node['kind'] == 'domain_definition'
                                    and target_node['kind'] == 'conditional_assertion')
            if edge['relation'] == 'DOCUMENTED_BY' or role_owned_assertion:
                continue
            row = {k: v for k, v in edge.items() if k not in ROLE_FIELDS}
            kept.append(row)
        edges = kept
        definitions = {}
        for node in nodes.values():
            if node['kind'] == 'domain_definition':
                definitions.setdefault(node.get('name'), []).append(node)
        # Bare-name links deliberately retain ambiguity; no selector, parent or scope can disambiguate.
        if 'conditional_bilateral' not in factors:
            for node in nodes.values():
                if node['kind'] != 'configuration' or not isinstance(node.get('value'), str):
                    continue
                for definition in definitions.get(node['value'], []):
                    edges.append({'source': node['id'], 'target': definition['id'],
                        'relation': 'DOCUMENTED_BY', 'status': 'ablation_bare_name_alignment',
                        'conditions': [], 'condition_satisfied': None,
                        'instance_evidence': node['evidence'],
                        'definition_evidence': definition['evidence'],
                        'evidence': node['evidence'] + definition['evidence']})
        for assertion in [n for n in nodes.values() if n['kind'] == 'conditional_assertion']:
            for definition in definitions.get(assertion.get('subject'), []):
                if definition['path'] != assertion['path']:
                    continue
                edges.append({'source': definition['id'], 'target': assertion['id'],
                    'relation': assertion['predicate'], 'status': 'ablation_bare_name_owner',
                    'conditions': [assertion['condition']] if assertion.get('condition') else [],
                    'condition_satisfied': None, 'evidence': assertion['evidence']})
        graph['candidates'] = []
        graph['issues'] = []
    if 'conditional_bilateral' in factors:
        edges = [e for e in edges if e['relation'] not in {'DOCUMENTED_BY', 'CONFLICTS_WITH'}
                 and not (e.get('instance_evidence') and e.get('definition_evidence'))]
        graph['candidates'] = [c for c in graph.get('candidates', [])
                               if c.get('relation') not in {'DOCUMENTED_BY', 'CONFLICTS_WITH'}
                               and not (c.get('instance_evidence') and c.get('definition_evidence'))]
    if 'paths' in factors:
        for node in nodes.values():
            node.pop('parent', None)
        edges = []
        graph['candidates'] = []
    if 'evidence_groups' in factors:
        for edge in edges:
            if edge.get('instance_evidence') or edge.get('definition_evidence'):
                edge.pop('instance_evidence', None)
                edge.pop('definition_evidence', None)
                edge['evidence'] = []
        graph['candidates'] = []
    graph['edges'] = edges
    for index, edge in enumerate(graph['edges']):
        edge['id'] = 'ablation.edge:' + qa.digest(qa.wire([sorted(factors), index, edge]))[:24]
    graph['ablation'] = {'removed_factors': sorted(factors),
        'source_graph_sha256': qa.digest(qa.wire(source)),
        'transformation': 'physical information removal before any model call'}
    return graph


def options_for(factors):
    options = dict(candidate.DEFAULTS)
    mapping = {'role_scope': 'with_scope', 'conditional_bilateral': 'with_cross',
               'semantic_recall': 'semantic', 'paths': 'with_paths',
               'evidence_groups': 'with_groups', 'gap_strategy': 'with_gap',
               'claim_verification': 'with_claim_verification'}
    for factor in factors:
        options[mapping[factor]] = False
    return options


def verify_transform(graph, factors):
    factors = set(factors); nodes = graph['nodes']; edges = graph['edges']
    if 'role_scope' in factors:
        if any(ROLE_FIELDS & set(n) for n in nodes.values()) or any(ROLE_FIELDS & set(e) for e in edges):
            raise ValueError('role/scope metadata survived transformation')
        if any(n.get('label') != n.get('name') for n in nodes.values() if n['kind'] == 'domain_definition'):
            raise ValueError('role-bearing definition label survived transformation')
        if any(e.get('status') == 'literal_role_matched_alignment_not_runtime_activation' for e in edges):
            raise ValueError('role-specific alignment survived transformation')
    if 'conditional_bilateral' in factors and any(e['relation'] in {'DOCUMENTED_BY', 'CONFLICTS_WITH'}
            or e.get('instance_evidence') or e.get('definition_evidence') for e in edges):
        raise ValueError('bilateral relation survived transformation')
    if 'paths' in factors and (edges or any('parent' in n for n in nodes.values())):
        raise ValueError('path or ancestor metadata survived transformation')
    if 'evidence_groups' in factors and any(e.get('instance_evidence') or e.get('definition_evidence') for e in edges):
        raise ValueError('paired evidence cache survived transformation')


def prepare(parent, candidate_report, preregistration, output):
    if output.exists():
        raise FileExistsError('preserve ablation evaluation')
    parent_protocol = audit.verify(parent)
    report = qa.read(candidate_report)
    if report.get('protocol_sha256') != audit.sha(parent/'protocol.json') or not report.get('all_arms_rankable'):
        raise ValueError('full candidate development evaluation is not admitted')
    registration = qa.read(preregistration)
    if registration['planned_additional_arms'] != len(ARM_FACTORS) or registration['planned_additional_sessions'] != 972:
        raise ValueError('registered ablation grid changed')
    if registration.get('model') != 'deepseek-flash' or registration.get('source_candidate_protocol_sha256') != audit.sha(parent/'protocol.json'):
        raise ValueError('preregistration does not bind the exact Flash candidate')
    if registration.get('candidate_quality_sha256') != audit.sha(candidate_report):
        raise ValueError('preregistration does not bind the admitted candidate result')
    if registration.get('arm_factors') != {key: list(value) for key, value in ARM_FACTORS.items()}:
        raise ValueError('registered ablation factors changed')
    output.mkdir(parents=True)
    shutil.copytree(parent/'hybrid', output/'hybrid')
    shutil.copytree(parent/'control', output/'control')
    for path in Path(__file__).parent.glob('*.py'):
        shutil.copy2(path, output/path.name)
    source_graph = qa.read(parent/'candidate-graph.json')
    source_arm = parent/'full_candidate'
    source_arm_protocol = qa.read(source_arm/'protocol.json')
    (output/'graphs').mkdir()
    graph_files = {}
    for arm, factors in ARM_FACTORS.items():
        transformed = transform_graph(source_graph, factors)
        verify_transform(transformed, factors)
        path = output/'graphs'/(arm+'.json')
        qa.write(path, transformed)
        graph_files[arm] = str(path.relative_to(output))
        arm_dir = output/arm
        arm_dir.mkdir()
        for name, expected in source_arm_protocol['files'].items():
            source = source_arm/name
            if audit.sha(source) != expected:
                raise ValueError('candidate arm source drift')
            destination = arm_dir/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        arm_protocol = {**source_arm_protocol, 'arm': arm, 'methods': ['retrieval_first'],
            'removed_factors': list(factors), 'options': options_for(factors),
            'graph': graph_files[arm], 'graph_sha256': audit.sha(path),
            'same_budget': parent_protocol['limits'], 'source_candidate_protocol_sha256': audit.sha(parent/'protocol.json')}
        arm_protocol['files'] = {name: audit.sha(arm_dir/name) for name in source_arm_protocol['files']}
        qa.write(arm_dir/'protocol.json', arm_protocol)
    frozen = {p.relative_to(output).as_posix(): audit.sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    protocol = {'schema': 'candidate-preregistered-ablation-v1', 'files': frozen, 'groups': GROUPS,
        'replicates': 3, 'model': parent_protocol['model'], 'corpus_id': parent_protocol['corpus_id'],
        'runtime_identity': parent_protocol['runtime_identity'], 'planned_sessions': 972,
        'shuffle_seed': 20260910, 'limits': parent_protocol['limits'], 'max_generated_tokens': 8000,
        'max_model_calls': 9, 'source_candidate_protocol_sha256': audit.sha(parent/'protocol.json'),
        'candidate_quality_sha256': audit.sha(candidate_report),
        'preregistration_sha256': audit.sha(preregistration),
        'arm_factors': {k: list(v) for k, v in ARM_FACTORS.items()}, 'graph_files': graph_files,
        'holdout_unlocked': False,
        'failure_policy': 'same frozen at-most-nine identical-request transport attempts; four consecutive no-HTTP network errors stop the batch; isolated exhausted requests score strict failure'}
    qa.write(output/'protocol.json', protocol)
    audit.verify(output)
    print(qa.wire({'prepared': str(output), 'arms': len(GROUPS), 'sessions': 972}))


def run_logged(engine, question, method, key, replicate, replay):
    folder = engine.run/'sessions'/f"{question['id']}--{method}--r{replicate}"
    journal = folder/'invocations'/f'{time.time_ns()}.json'; begin = time.monotonic()
    record = {'status': 'running', 'replay': replay, 'started_unix_ns': time.time_ns(), 'elapsed_seconds': None}
    qa.write(journal, record)
    try:
        result = candidate.run_one(engine, question, method, key, replicate, replay)
        record['status'] = result['status']
        return result
    except BaseException:
        record['status'] = 'error'
        raise
    finally:
        record['elapsed_seconds'] = time.monotonic()-begin
        qa.write(journal, record)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('command', choices=['prepare', 'verify', 'smoke', 'run', 'replay'])
    cli.add_argument('--run', type=Path, required=True); cli.add_argument('--parent', type=Path)
    cli.add_argument('--candidate-report', type=Path); cli.add_argument('--preregistration', type=Path)
    cli.add_argument('--key-file', type=Path)
    cli.add_argument('--workers', type=int, default=4)
    a = cli.parse_args(); root = a.run.resolve()
    if a.command == 'prepare':
        prepare(a.parent.resolve(), a.candidate_report.resolve(), a.preregistration.resolve(), root)
        return
    protocol = audit.verify(root); base.verify_runtime(protocol)
    if Path(__file__).resolve() != root/'candidate_ablation.py':
        raise ValueError('execute frozen ablation implementation')
    for arm, factors in protocol['arm_factors'].items():
        graph = qa.read(root/protocol['graph_files'][arm])
        verify_transform(graph, factors)
        if audit.sha(root/protocol['graph_files'][arm]) != qa.read(root/arm/'protocol.json')['graph_sha256']:
            raise ValueError('ablation graph drift')
    if a.command == 'verify':
        print('PASS: all preregistered ablation identities and removals')
        return
    base.SECRET = a.key_file.read_text().strip() if a.key_file else ''
    base.reset_transport_circuit()
    qa.write = base.save; qa.instrument_file_reads()
    with (root/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        engines = {arm: candidate.Engine(root/arm, arm, root/'hybrid', root/protocol['graph_files'][arm],
                                         qa.read(root/arm/'protocol.json')['options']) for arm in GROUPS}
        if a.command == 'smoke':
            checks = []
            for arm, engine in engines.items():
                session = candidate.Session(engine, 'retrieval_first', 'movingCone dynamicMeshDict mesh motion')
                result, accounting = session.dispatch({'action': 'locate', 'needs': ['mesh configuration']}, 6000)
                checks.append({'arm': arm, 'status': result.get('status'), 'groups': len(result.get('groups', [])),
                               'options': engine.options, 'accounting': accounting})
                if result.get('status') != 'ok' or not session.seen:
                    raise ValueError('ablation evidence smoke failed')
                if not engine.options['with_gap'] and 'gaps' in result:
                    raise ValueError('gap state leaked into ablation result')
                if not engine.options['with_groups'] and any(g.get('metadata') for g in result.get('groups', [])):
                    raise ValueError('group metadata leaked into ablation result')
            qa.write(root/'verification/adapter-smoke.json', checks)
            print('PASS: nine ablation tools, zero model calls')
            return
        questions = qa.read(root/'control/questions.json')
        jobs = [(arm, q, 'retrieval_first', rep) for q in questions for rep in range(1, 4) for arm in GROUPS]
        random.Random(protocol['shuffle_seed']).shuffle(jobs)
        journal = root/'invocations'/f'{time.time_ns()}.json'; begin = time.monotonic()
        state = {'pid': os.getpid(), 'state': 'running', 'jobs': len(jobs), 'completed': 0,
                 'errors': [], 'command': a.command}
        qa.write(journal, state)
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures = {}
            for arm, question, method, replicate in jobs:
                name = f"{question['id']}--{method}--r{replicate}"
                if a.command == 'run' and (root/arm/'sessions'/name/'result.json').exists():
                    state['completed'] += 1
                    continue
                futures[pool.submit(run_logged, engines[arm], question, method, base.SECRET or None,
                                    replicate, a.command == 'replay')] = arm+'/'+name
            for future in as_completed(futures):
                try:
                    result = future.result(); state['completed'] += 1
                    print('DONE', futures[future], result['status'], flush=True)
                except Exception as error:
                    state['errors'].append({'session': futures[future], 'type': type(error).__name__})
                    print('ERROR', futures[future], type(error).__name__, flush=True)
                qa.write(journal, {**state, 'elapsed_seconds': time.monotonic()-begin})
        outage = any(error['type'] == 'GlobalTransportOutage' for error in state['errors'])
        qa.write(journal, {**state, 'state': 'network_circuit_open' if outage else 'finished',
                           'elapsed_seconds': time.monotonic()-begin})
        audit.verify(root)
        if outage:
            raise SystemExit(75)


if __name__ == '__main__':
    main()
