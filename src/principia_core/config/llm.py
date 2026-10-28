"""Central Chapter 2 model registry, credentials and fail-closed spending gates.

The .yaml files use the JSON subset of YAML 1.2, parsed with the standard library.
Registry loading and snapshots never read or contain secret credential values.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


PROJECT = Path(__file__).resolve().parents[3]
CONFIG = PROJECT / 'config/llm'
FILES = ('providers.yaml', 'models.yaml', 'generation.yaml', 'judging.yaml', 'execution.yaml')


class ConfigurationBlocked(PermissionError):
    pass


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def financial_gate(stage):
    if stage.get('scope_authorized') is not True:
        raise ConfigurationBlocked('scope_not_authorized')
    if stage.get('control_mode') == 'owner_authorized_request_quota_v1':
        # Owner explicitly superseded monetary prerequisites for this finite run.
        allowed = {'connectivity': (1, 1), 'dev120': (1080, 120), 'calibration_first': (36, 18),
                   'ai_cross_calibration': (154, 18), 'dual_judge_sol_flash': (276, 30)}
        bounds = allowed.get(stage.get('quota_scope'))
        actual=(stage.get('max_physical_requests'), stage.get('max_sessions'))
        revised_cross=stage.get('quota_scope')=='ai_cross_calibration' and actual==(162,18) and stage.get('technical_recovery_amendment')=='bounded_runtime_and_instruction_delivery_v2'
        if not bounds or actual != bounds and not revised_cross:
            raise ConfigurationBlocked('invalid_owner_authorized_request_quota')
        return dict(control_mode=stage['control_mode'], currency=None, hard_limit=None,
                    input_price_per_million=None, output_price_per_million=None,
                    actual_cost='Unknown')
    b = stage.get('financial', {})
    missing = [k for k in ('currency', 'hard_limit', 'input_price_per_million', 'output_price_per_million')
               if b.get(k) is None or b.get(k) == '']
    if b.get('approved') is not True:
        missing.insert(0, 'approved')
    if missing:
        raise ConfigurationBlocked('financial_configuration_required:' + ','.join(missing))
    if not isinstance(b['currency'], str) or not b['currency'].isascii() or not b['currency'].isalpha():
        raise ConfigurationBlocked('invalid_currency')
    try:
        amounts = [Decimal(str(b[k])) for k in ('hard_limit', 'input_price_per_million', 'output_price_per_million')]
    except (InvalidOperation, ValueError):
        raise ConfigurationBlocked('invalid_financial_value') from None
    if any(not x.is_finite() or x <= 0 for x in amounts):
        raise ConfigurationBlocked('positive_finite_approved_amount_and_tariffs_required')
    return deepcopy(b)


class Registry:
    def __init__(self, directory=CONFIG, project=PROJECT):
        self.directory = Path(directory).resolve()
        self.project = Path(project).resolve()
        self.workspace = self.project.parent
        self.data = {name.removesuffix('.yaml'): load_json(self.directory / name) for name in FILES}
        self.hashes = {name: sha(self.directory / name) for name in FILES}
        self.providers = self.data['providers']['providers']
        self.models = self.data['models']['models']
        self.generation = self.data['generation']
        self.judging = self.data['judging']
        self.execution = self.data['execution']
        for model in self.models.values():
            if model['provider'] not in self.providers:
                raise ValueError('Unknown provider')
            if model['protocol'] not in self.providers[model['provider']]['protocols']:
                raise ValueError('Protocol not declared by provider')
            if model['api_model_id'] not in model['allowed_response_model_ids']:
                raise ValueError('Response identity does not bind the configured model')
        if self.generation['max_sessions'] != 120 or self.generation['question_count'] != 40:
            raise ValueError('Wrong initial Dev120 scope')

    def _private_paths(self, provider):
        for reference in provider['credential_files']:
            kind, relative = reference.split(':', 1)
            root = self.workspace if kind == 'workspace' else self.project if kind == 'project' else None
            if root is None:
                raise ValueError('Invalid private credential location')
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Credential path outside designated root')
            yield path

    def _value(self, provider, variable):
        """Resolve only the explicitly configured variable. Never return whole files."""
        values = []
        if os.environ.get(variable):
            values.append(os.environ[variable])
        for path in self._private_paths(provider):
            if not path.is_file():
                continue
            found = []
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                name, sep, value = line.strip().removeprefix('export ').partition('=')
                if sep and name.strip() == variable and value.strip():
                    found.append(value.strip().strip('\"\''))
            if len(found) > 1:
                raise ConfigurationBlocked('duplicate_private_variable:' + variable)
            values.extend(found)
        if len(set(values)) > 1:
            raise ConfigurationBlocked('conflicting_private_variable:' + variable)
        return values[0] if values else None

    def credential_status(self, model_key):
        p = self.providers[self.models[model_key]['provider']]
        return {'variable': p['key_env'], 'present': bool(self._value(p, p['key_env'])), 'value_saved': False}

    def private_key(self, model_key):
        """Call only AFTER financial_gate; caller must never serialize this value."""
        p = self.providers[self.models[model_key]['provider']]
        value = self._value(p, p['key_env'])
        if not value or any(c.isspace() for c in value):
            raise ConfigurationBlocked('credential_missing_or_invalid:' + p['key_env'])
        return value

    def resolve(self, model_key):
        m = deepcopy(self.models[model_key]);p = self.providers[m['provider']]
        override = self._value(p, p['base_url_env'])
        base = override or p['base_url']
        if not base:
            raise ConfigurationBlocked('base_url_missing:' + p['base_url_env'])
        base = base.rstrip('/')
        if p['base_url'] and base != p['base_url'].rstrip('/'):
            raise ConfigurationBlocked('base_url_drift_requires_review')
        parsed = urlsplit(base)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != '/v1':
            raise ConfigurationBlocked('invalid_base_url')
        if parsed.scheme != 'https':
            if parsed.scheme != 'http' or p.get('allow_private_http') is not True:
                raise ConfigurationBlocked('https_required')
            try:
                private = ipaddress.ip_address(parsed.hostname).is_private
            except ValueError:
                private = parsed.hostname == 'localhost'
            if not private:
                raise ConfigurationBlocked('http_only_for_explicit_private_local_endpoint')
        m.update(base_url=base, key_env=p['key_env'], max_concurrency=p['max_concurrency'],
                 endpoint=base + ('/responses' if m['protocol'] == 'responses' else '/chat/completions'))
        return m

    def judge_profile(self, judge_id):
        key = self.judging['judges'].get(judge_id)
        if key is None:
            raise ValueError('Human has no API profile')
        m = self.resolve(key)
        dual = self.judging.get('dual_judge', {})
        budget = dual.get('model_token_budgets', {}).get(judge_id, {})
        input_cap = budget.get('input_token_cap', self.judging['input_token_cap'])
        output_cap = budget.get('output_token_cap', self.judging['output_token_cap'])
        if input_cap + output_cap > 32768 or input_cap <= 0 or output_cap <= 0:
            raise ConfigurationBlocked('invalid_judge_combined_token_budget')
        return dict(judge_id=judge_id, model_id=m['api_model_id'],
                    allowed_response_model_ids=m['allowed_response_model_ids'],
                    protocol=m['protocol'], base_url=m['base_url'], key_env=m['key_env'],
                    wire_parameters=m['wire_parameters'],
                    input_token_cap=input_cap, output_token_cap=output_cap,
                    prompt_version=dual.get('selected_prompt_versions',{}).get(judge_id,self.judging['prompt_version']), registry_sha256=self.hashes,
                    output_token_field=m.get('selected_repair_variant',{}).get('output_token_field','max_tokens'),
                    stream=m.get('selected_repair_variant',{}).get('stream',False),
                    api_authorized=False, capabilities_verified_live=False)

    def snapshot(self):
        # Public configuration only. Credential file contents and their hashes excluded.
        return dict(schema='principia_llm_sanitized_snapshot_v1', files=deepcopy(self.data),
                    source_sha256=self.hashes, credentials_included=False)

    def stage(self, name):
        if name not in self.execution['stages']:
            raise ConfigurationBlocked('stage_not_authorized:' + name)
        return self.execution['stages'][name]
