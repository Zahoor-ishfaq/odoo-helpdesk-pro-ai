"""Single point of contact for all Anthropic API calls (§6).

Mandatory rules — do not weaken any of these:
- Called from models/wizards only — never from views or controllers.
- Never logs full prompts or responses — only token counts and summaries.
- Always returns a typed result dict; never raises to the caller.
- Always enforces a hard 30 second timeout.
- Always validates the API key format before sending.
- Always sends the Odoo instance URL as a header for abuse detection.
"""

import json
import logging
import ssl
import urllib.error
import urllib.request

_logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
API_KEY_PREFIX = "sk-ant-"
API_KEY_LENGTH = 108
REQUEST_TIMEOUT = 30
CONFIG_PARAM_KEY = "helpdesk_ai.anthropic_key"
CONFIG_PARAM_MODEL = "helpdesk_ai.model"
DEFAULT_MODEL = "claude-haiku-4-5"
MODEL_SELECTION = [
    ("claude-haiku-4-5", "Claude Haiku 4.5 (default, cheapest)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (balanced)"),
    ("claude-opus-4-6", "Claude Opus 4.6 (most capable)"),
]


def validate_api_key_format(key):
    """True if `key` matches Anthropic's current key format (§7.4)."""
    return bool(key) and key.startswith(API_KEY_PREFIX) and len(key) == API_KEY_LENGTH


class AnthropicClient:  # pylint: disable=too-few-public-methods
    """Thin wrapper around the Anthropic Messages API.

    Callers instantiate with the Odoo environment (`AnthropicClient(self.env)`)
    so the client can read the stored API key and instance URL itself.
    """

    def __init__(self, env):
        self.env = env

    def _get_api_key(self):
        """Read the stored key. Returns None if unset or malformed.

        Uses sudo() because this runs as system infrastructure (triage and
        sentiment crons, the reply-draft wizard) on behalf of any agent —
        access to the *setting itself* is already admin-gated (§7.4, §8).
        """
        key = self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM_KEY)
        return key if validate_api_key_format(key) else None

    def _get_configured_model(self):
        """The admin-selected model (§1), falling back to the default."""
        return (
            self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM_MODEL)
            or DEFAULT_MODEL
        )

    def _build_headers(self, api_key):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        return {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "User-Agent": f"OdooHelpdeskAI/1.0 (+{base_url})",
        }

    def _call_api(self, payload):
        """POST `payload` to the Messages API.

        Never raises — always returns a dict, either the parsed API
        response or {'error': ...}. This is the method tests patch (§9).
        """
        api_key = self._get_api_key()
        if not api_key:
            return {"error": "missing_or_invalid_api_key"}

        ctx = ssl.create_default_context()  # validates certs — never CERT_NONE
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(API_URL, data=data, method="POST")
            for header, value in self._build_headers(api_key).items():
                req.add_header(header, value)
            with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT, context=ctx
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            _logger.warning("Anthropic API HTTP error %s", err.code)
            return {"error": err.code, "body": err.read().decode("utf-8")}
        except Exception as err:  # pylint: disable=broad-except
            _logger.warning("Anthropic API call failed: %s", err.__class__.__name__)
            return {"error": "timeout_or_network", "detail": str(err)}

    def call(
        self, system, user, max_tokens, temperature=0, model=None
    ):  # pylint: disable=too-many-arguments
        """Send one message, returning a typed result — never raises:
        {'ok': True, 'text': ..., 'model': ..., 'usage': {...}}
        {'ok': False, 'error': ...}
        Never logs `system`/`user` content (§6, §8).
        """
        payload = {
            "model": model or self._get_configured_model(),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        response = self._call_api(payload)

        if "error" in response:
            return {"ok": False, "error": response["error"]}

        try:
            text = response["content"][0]["text"]
            usage = response.get("usage", {})
        except (KeyError, IndexError, TypeError):
            _logger.warning("Anthropic API response missing expected fields")
            return {"ok": False, "error": "unexpected_response_shape"}

        return {
            "ok": True,
            "text": text,
            "model": payload["model"],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
            },
        }
