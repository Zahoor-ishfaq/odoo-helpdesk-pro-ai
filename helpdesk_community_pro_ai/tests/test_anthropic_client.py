"""Tests for AnthropicClient: format validation and typed, non-raising
call results (§6). Never calls the real Anthropic API (§9)."""

from unittest.mock import patch

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.anthropic_client import (
    CONFIG_PARAM_KEY,
    AnthropicClient,
    validate_api_key_format,
)

VALID_KEY = "sk-ant-" + "a" * 101  # 108 chars total, matches §7.4 format
_CALL_API_TARGET = (
    "odoo.addons.helpdesk_community_pro_ai.services.anthropic_client"
    ".AnthropicClient._call_api"
)


@tagged("post_install", "-at_install")
class TestAnthropicClient(TransactionCase):
    """Key format validation and typed, non-raising call results."""

    def test_validate_api_key_format(self):
        """Only the 'sk-ant-' + 108-char format passes (§7.4)."""
        self.assertTrue(validate_api_key_format(VALID_KEY))
        self.assertFalse(validate_api_key_format("sk-ant-tooshort"))
        self.assertFalse(validate_api_key_format("wrong-prefix" + "a" * 96))
        self.assertFalse(validate_api_key_format(False))

    def test_call_without_stored_key_is_graceful(self):
        """No API key configured -> typed error, never raises. M1 wires no
        real callers yet, so this is the only reachable path unmocked."""
        result = AnthropicClient(self.env).call(
            system="You are a test.", user="hello", max_tokens=10
        )
        self.assertEqual(result, {"ok": False, "error": "missing_or_invalid_api_key"})

    @patch(_CALL_API_TARGET)
    def test_call_parses_successful_response(self, mock_call_api):
        """A well-formed API response is mapped to the typed result (§9)."""
        self.env["ir.config_parameter"].sudo().set_param(CONFIG_PARAM_KEY, VALID_KEY)
        mock_call_api.return_value = {
            "content": [{"text": '{"team": "Technical Support"}'}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
        result = AnthropicClient(self.env).call(system="sys", user="hi", max_tokens=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], '{"team": "Technical Support"}')
        self.assertEqual(result["usage"]["prompt_tokens"], 100)
        self.assertEqual(result["usage"]["completion_tokens"], 20)

    @patch(_CALL_API_TARGET)
    def test_call_maps_api_error_to_typed_result(self, mock_call_api):
        """An HTTPError-shaped result from _call_api never raises (§6)."""
        self.env["ir.config_parameter"].sudo().set_param(CONFIG_PARAM_KEY, VALID_KEY)
        mock_call_api.return_value = {"error": 529, "body": "overloaded"}
        result = AnthropicClient(self.env).call(system="sys", user="hi", max_tokens=10)
        self.assertEqual(result, {"ok": False, "error": 529})

    @patch(_CALL_API_TARGET)
    def test_call_handles_malformed_response_shape(self, mock_call_api):
        """A response missing the expected fields is handled gracefully."""
        self.env["ir.config_parameter"].sudo().set_param(CONFIG_PARAM_KEY, VALID_KEY)
        mock_call_api.return_value = {"unexpected": "shape"}
        result = AnthropicClient(self.env).call(system="sys", user="hi", max_tokens=10)
        self.assertEqual(result, {"ok": False, "error": "unexpected_response_shape"})
