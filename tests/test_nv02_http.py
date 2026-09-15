"""Transport boundary tests: exact host, byte/deadline bounds and no redirects."""
import unittest
from unittest.mock import Mock, patch
from runtime.providers.nvidia import HTTPTransport, ProviderError


class HTTPTests(unittest.TestCase):
    def test_fixed_verified_https_endpoint_and_bounded_response(self):
        response = Mock(status=200)
        response.read1.return_value = b"small"
        response.isclosed.return_value = True
        connection = Mock()
        connection.getresponse.return_value = response
        with patch("runtime.providers.nvidia.http.client.HTTPSConnection", return_value=connection) as constructor:
            status, raw = HTTPTransport()(b"payload", "synthetic-key", 5, 512)
        self.assertEqual((200, b"small"), (status, raw))
        self.assertEqual("integrate.api.nvidia.com", constructor.call_args.args[0])
        self.assertTrue(constructor.call_args.kwargs["context"].check_hostname)
        self.assertEqual(("POST", "/v1/chat/completions"), connection.request.call_args.args)
        self.assertEqual(513, response.read1.call_args.args[0])
        connection.close.assert_called_once()

    def test_redirect_status_returns_without_reading_body_or_second_request(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=302)
        with patch("runtime.providers.nvidia.http.client.HTTPSConnection", return_value=connection):
            self.assertEqual((302, b""), HTTPTransport()(b"p", "synthetic-key", 5, 512))
        connection.request.assert_called_once()
        connection.getresponse.return_value.read1.assert_not_called()

    def test_total_deadline_rejects_slow_response_and_closes_connection(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200)
        with patch("runtime.providers.nvidia.http.client.HTTPSConnection", return_value=connection), \
                patch("runtime.providers.nvidia.time.monotonic", side_effect=[0, 1, 2, 3, 6]):
            with self.assertRaisesRegex(ProviderError, "PROVIDER_TIMEOUT") as error:
                HTTPTransport()(b"p", "synthetic-key", 5, 512)
        self.assertTrue(error.exception.outcome_unknown)
        connection.close.assert_called_once()
