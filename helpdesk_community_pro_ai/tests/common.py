"""Shared test fixtures for helpdesk_community_pro_ai: every AI test
patches _call_api at the same target and needs the same typed mock
response shape, so this is the one place both live."""

CALL_API_TARGET = (
    "odoo.addons.helpdesk_community_pro_ai.services.anthropic_client"
    ".AnthropicClient._call_api"
)


def api_response(text, prompt_tokens=100, completion_tokens=20):
    """The typed dict shape AnthropicClient._call_api returns on success."""
    return {
        "content": [{"text": text}],
        "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
    }
