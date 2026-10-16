"""Local endpoint routing and immutable attempt recording."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'experiments/retrieval_method/chapter2_qwen_local.py'
spec = importlib.util.spec_from_file_location('chapter2_qwen_local', MODULE)
local = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = local
spec.loader.exec_module(local)


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = self.root / '.env'
        self.settings.write_text('QWEN_LOCAL_API_KEY=test-secret\n'
            'QWEN_LOCAL_8B_BASE_URL=http://127.0.0.1:8000/v1\n'
            'QWEN_LOCAL_14B_BASE_URL=http://127.0.0.1:8001/v1\n'
            'QWEN_LOCAL_8B_MODEL=Qwen3-8B\nQWEN_LOCAL_14B_MODEL=Qwen3-14B\n')

    def test_routes_and_secret_repr(self):
        for size, port in [('8b', 8000), ('14b', 8001)]:
            model = local.load_model('qwen3-' + size, self.settings)
            self.assertEqual(model.endpoint, f'http://127.0.0.1:{port}/v1/chat/completions')
            self.assertNotIn('test-secret', repr(model))

    def test_actual_body_preserves_original_and_limits(self):
        body = {'messages': [{'role': 'user', 'content': 'question'}],
                'enable_thinking': False, 'temperature': 0, 'max_tokens': 4096}
        deployment = local.load_model('qwen3-14b', self.settings)
        actual = local.prepare_body(body, deployment)
        self.assertEqual(body['messages'][0]['content'], 'question')
        self.assertEqual(actual['messages'][0]['content'], 'question\n/no_think')
        self.assertEqual(actual['max_tokens'], 4096)
        self.assertEqual(actual, local.prepare_body(actual, deployment))
        self.assertNotIn('enable_thinking', actual)
        with self.assertRaises(ValueError):
            local.prepare_body(dict(body, enable_thinking=True), deployment)

    def test_no_overwrite_or_retry_and_model_mismatch(self):
        client = local.LocalQwenClient('qwen3-8b', self.root / 'calls', self.settings)
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'model': 'wrong-model', 'choices': [
                    {'message': {'content': 'ok'}}]}).encode()
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                return Response()
        opener = client.opener = Opener()
        body = {'messages': [{'role': 'user', 'content': 'question'}]}
        self.assertEqual(client(body, 0)['status'], 'model_mismatch')
        with self.assertRaises(FileExistsError): client(body, 0)
        self.assertEqual(opener.calls, 1)
        self.assertNotIn('test-secret', (self.root / 'calls/00.json').read_text())

    def test_invalid_config_and_model_fail_closed(self):
        with self.assertRaises(ValueError): local.load_model('other', self.settings)
        with self.settings.open('a') as out: out.write('QWEN_LOCAL_API_KEY=duplicate\n')
        with self.assertRaises(ValueError): local.load_model('qwen3-8b', self.settings)


if __name__ == '__main__': unittest.main()
