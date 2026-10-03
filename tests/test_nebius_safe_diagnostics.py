"""Offline negative tests for metadata on rejected exact completions."""
import json
import unittest
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

from providers.exact import (CancellationToken, ExactCallError, ExactRequest,
                            decode_response, generate_http_exact, sanitize_diagnostics)
from providers.messages import ChatMessage


class SafeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.request = ExactRequest('nebius', 'nvidia/Nemotron-3_5-Lightning',
                                    (ChatMessage('user', 'OK'),), 512)

    def rejected(self, **changes):
        payload = {'model': self.request.requested_model, 'id': 'chatcmpl-safe-42',
                   'usage': {'prompt_tokens': 8, 'completion_tokens': 512, 'total_tokens': 520},
                   'choices': [{'finish_reason': 'length', 'message': {'content': 'private-response',
                               'reasoning_content': 'private-reasoning'}}]}
        payload.update(changes)
        with self.assertRaises(ExactCallError) as caught:
            decode_response(json.dumps(payload).encode(), self.request)
        return caught.exception

    def test_length_retains_usage_identity_and_request_id(self):
        error = self.rejected()
        self.assertEqual(error.code, 'INCOMPLETE_COMPLETION')
        self.assertEqual(error.safe_metadata['finish_reason'], 'length')
        self.assertEqual(error.safe_metadata['request_id'], 'chatcmpl-safe-42')
        self.assertEqual(error.safe_metadata['reported_model'], self.request.requested_model)
        self.assertEqual(error.safe_metadata['usage']['completion_tokens'], 512)

    def test_all_non_stop_reasons_fail_including_empty_content(self):
        for reason in ('length', 'content_filter', 'tool_calls', 'function_call', None, 'unknown'):
            with self.subTest(reason=reason):
                error = self.rejected(choices=[{'finish_reason': reason, 'message': {'content': ''}}])
                self.assertEqual(error.code, 'INCOMPLETE_COMPLETION')

    def test_identity_mismatch_retains_safe_metadata(self):
        error = self.rejected(model='nvidia/another-model')
        self.assertEqual(error.code, 'MODEL_IDENTITY_MISMATCH')
        self.assertEqual(error.safe_metadata['reported_model'], 'nvidia/another-model')

    def test_content_reasoning_and_arbitrary_fields_never_persist(self):
        error = self.rejected(headers={'Authorization': 'private-authorization'},
                              prompt='private-prompt', api_key='private-key')
        encoded = json.dumps(error.safe_metadata)
        for secret in ('private-response', 'private-reasoning', 'private-authorization',
                       'private-prompt', 'private-key'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(set(error.safe_metadata),
                         {'provider', 'requested_model', 'reported_model', 'finish_reason', 'request_id', 'usage'})

    def test_malformed_nested_usage_is_sanitized_independently(self):
        error = self.rejected(usage={'prompt_tokens': {'secret': 'private'},
                                    'completion_tokens': True, 'total_tokens': 520,
                                    'nested': {'content': 'private'}})
        self.assertEqual(error.safe_metadata['usage'], {'total_tokens': 520})
        self.assertNotIn('private', json.dumps(error.safe_metadata))

    def test_diagnostic_strings_reject_credentials_and_arbitrary_text(self):
        for value in ('Bearer private', 'sk-' + 'A' * 48, 'AKIA' + 'A' * 16,
                      'nebius_api_key_' + 'B' * 48, 'private HAT text\n', 'x' * 200):
            with self.subTest(value=value[:10]):
                clean = sanitize_diagnostics({'request_id': value, 'finish_reason': value,
                                              'reported_model': value, 'provider': value})
                self.assertEqual(clean, {})

    def test_constructor_resanitizes_untrusted_metadata(self):
        error = ExactCallError('INCOMPLETE_COMPLETION', safe_metadata={
            'finish_reason': 'length', 'request_id': 'req-safe', 'usage': {'total_tokens': 9,
            'content': 'private'}, 'raw_provider_payload': 'private', 'latency_ms': 23,
            'http_status': 200, 'headers': 'private'})
        self.assertEqual(error.safe_metadata, {'finish_reason': 'length', 'request_id': 'req-safe',
                         'usage': {'total_tokens': 9}, 'latency_ms': 23, 'http_status': 200})

    def test_malformed_metadata_does_not_raise(self):
        for value in (None, [], {'usage': []}, {'latency_ms': float('nan')}, {'request_id': {'x': 1}}):
            self.assertEqual(sanitize_diagnostics(value), {})

    def test_stop_remains_required_even_with_complete_looking_content(self):
        self.assertEqual(self.rejected().code, 'INCOMPLETE_COMPLETION')

    def test_http_error_and_incomplete_keep_only_safe_transport_metadata(self):
        for status in (200, 429):
            captured = []
            payload = {'model': self.request.requested_model, 'id': 'req-wire-safe',
                       'usage': {'completion_tokens': 512},
                       'choices': [{'finish_reason': 'length', 'message': {'content': 'private-wire'}}]}
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass
                def do_POST(self):
                    captured.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                    body = json.dumps(payload).encode()
                    self.send_response(status)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            server = HTTPServer(('127.0.0.1', 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                request = replace(self.request, transport_scope='TEST', bound_reasoning_tokens=True)
                adapter = SimpleNamespace(provider='nebius', model=request.requested_model,
                                          base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key='fixture')
                with self.assertRaises(ExactCallError) as caught:
                    generate_http_exact(adapter, request, CancellationToken(), time.monotonic()+3, fixture=True)
                error = caught.exception
                self.assertEqual(error.safe_metadata['http_status'], status)
                self.assertGreaterEqual(error.safe_metadata['latency_ms'], 0)
                self.assertNotIn('private-wire', json.dumps(error.safe_metadata))
                self.assertEqual(len(captured), 1)
                self.assertEqual(captured[0]['max_completion_tokens'], 512)
                self.assertNotIn('max_tokens', captured[0])
                if status == 200:
                    self.assertEqual(error.code, 'INCOMPLETE_COMPLETION')
                    self.assertEqual(error.safe_metadata['request_id'], 'req-wire-safe')
                else:
                    self.assertEqual(error.code, 'PROVIDER_HTTP_429')
                    self.assertNotIn('request_id', error.safe_metadata)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(2)


if __name__ == '__main__':
    unittest.main()
