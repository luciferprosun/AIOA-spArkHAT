# MIT License; Copyright (c) 2026 Lukasz Zuchowski. See LICENSE.
# Pure redaction tests ported from AOIA-Core 5ec74f8; no Tk credential UI port.
from __future__ import annotations

import unittest

from critical_loop.redaction import (
    REDACTED,
    redact_exception,
    redact_secret_data,
    redact_secret_text,
)


class SecretRedactionTests(unittest.TestCase):
    def test_redacts_bearer_token(self) -> None:
        text = "Authorization: Bearer sk-abcdef1234567890abcdef"
        self.assertNotIn("sk-abcdef1234567890abcdef", redact_secret_text(text))

    def test_redacts_known_secret_verbatim(self) -> None:
        secret = "or-super-secret-value-123456"
        text = f"failed while using key {secret} against host"
        result = redact_secret_text(text, known_secrets=(secret,))
        self.assertNotIn(secret, result)
        self.assertIn(REDACTED, result)

    def test_redacts_key_equals_value_pattern(self) -> None:
        text = "config error: api_key=abc123XYZshouldnotappear"
        result = redact_secret_text(text)
        self.assertNotIn("abc123XYZshouldnotappear", result)

    def test_redact_secret_data_masks_sensitive_dict_keys(self) -> None:
        payload = {"Authorization": "Bearer sk-xyz", "model": "gpt-test", "nested": {"api_key": "abc"}}
        redacted = redact_secret_data(payload)
        self.assertEqual(redacted["Authorization"], REDACTED)
        self.assertEqual(redacted["nested"]["api_key"], REDACTED)
        self.assertEqual(redacted["model"], "gpt-test")

    def test_redact_exception_never_raises(self) -> None:
        try:
            raise ValueError("token=abc123 leaked")
        except ValueError as error:
            message = redact_exception(error)
        self.assertNotIn("abc123", message)


if __name__ == "__main__":
    unittest.main()
