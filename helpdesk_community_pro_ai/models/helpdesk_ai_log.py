"""Helpdesk AI Log: audit trail for every Anthropic API call (§5.1)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import api, fields, models

CALL_TYPE_SELECTION = [
    ("triage", "Triage"),
    ("sentiment", "Sentiment"),
    ("reply_draft", "Reply Draft"),
]

SENTIMENT_SELECTION = [
    ("calm", "Calm"),
    ("neutral", "Neutral"),
    ("frustrated", "Frustrated"),
    ("angry", "Angry"),
]

# USD per 1000 tokens. Only claude-haiku-4-5's published rate is known
# (§1 item 6) -- used as the fallback estimate for any other model_used
# too, since a directionally-useful estimate beats a silent $0.00.
INPUT_PRICE_PER_1K_TOKENS = 0.00025
OUTPUT_PRICE_PER_1K_TOKENS = 0.00125


class HelpdeskAiLog(models.Model):  # pylint: disable=too-few-public-methods
    """One record per Anthropic API call, for usage tracking and accuracy
    reporting. Never stores raw prompts or full API responses (§8)."""

    _name = "helpdesk.ai.log"
    _description = "Helpdesk AI Usage Log"
    _order = "created_at desc"

    ticket_id = fields.Many2one(
        "helpdesk.ticket", required=True, index=True, ondelete="cascade"
    )
    team_id = fields.Many2one(
        "helpdesk.team",
        related="ticket_id.team_id",
        store=True,
        index=True,
        help="Denormalized from the ticket for usage-dashboard reporting "
        "by team (§1 item 6).",
    )
    call_type = fields.Selection(CALL_TYPE_SELECTION, required=True, index=True)
    model_used = fields.Char(help="Anthropic model id, e.g. claude-haiku-4-5.")
    prompt_tokens = fields.Integer()
    completion_tokens = fields.Integer()
    total_tokens = fields.Integer(compute="_compute_total_tokens", store=True)
    cost_estimate = fields.Float(
        compute="_compute_cost_estimate",
        store=True,
        digits=(16, 6),
        help="Estimated cost in USD, informational only -- prompt/completion "
        "tokens priced separately at claude-haiku-4-5's published rate.",
    )
    response_summary = fields.Text(
        help="Non-sensitive summary only — never the raw prompt or response."
    )
    was_accepted = fields.Boolean(
        help="For triage calls: did the agent accept the AI suggestion?"
    )
    sentiment_score = fields.Selection(
        SENTIMENT_SELECTION, help="Result of a sentiment call."
    )
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    @api.depends("prompt_tokens", "completion_tokens")
    def _compute_total_tokens(self):
        for log in self:
            log.total_tokens = log.prompt_tokens + log.completion_tokens

    @api.depends("prompt_tokens", "completion_tokens")
    def _compute_cost_estimate(self):
        for log in self:
            log.cost_estimate = (
                log.prompt_tokens / 1000 * INPUT_PRICE_PER_1K_TOKENS
                + log.completion_tokens / 1000 * OUTPUT_PRICE_PER_1K_TOKENS
            )
