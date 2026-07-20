"""Helpdesk Ticket: Smart Triage on create (§5.2, §7.1)."""

import json
import logging

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import _, api, fields, models
from odoo.tools.mail import html2plaintext

from ..services.anthropic_client import AnthropicClient
from .helpdesk_ai_log import SENTIMENT_SELECTION

_logger = logging.getLogger(__name__)

MIN_TRIAGE_CONTENT_LENGTH = 20
MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 500
MAX_TRIAGE_TAGS = 20
TRIAGE_MAX_TOKENS = 100

# The prompt (§7.1) offers these four words regardless of the model's own
# Selection labels (Low/Medium/High/Urgent) -- "normal" is accepted as a
# synonym for "medium" since a response using either word is equally valid.
PRIORITY_WORD_TO_KEY = {
    "low": "0",
    "normal": "1",
    "medium": "1",
    "high": "2",
    "urgent": "3",
}

TRIAGE_SYSTEM_PROMPT = (
    "You are a helpdesk triage assistant. Return ONLY valid JSON, no explanation."
)

TRIAGE_USER_TEMPLATE = (
    "Ticket subject: {subject}\n"
    "Ticket body: {body}\n"
    "Available teams: {teams}\n"
    "Available priorities: urgent, high, normal, low\n"
    "Available tags: {tags}\n"
    'Return: {{"team": "...", "priority": "...", "tags": [...], '
    '"confidence": 0.0-1.0}}'
)


class HelpdeskTicket(models.Model):  # pylint: disable=too-few-public-methods
    """Adds AI triage fields and the create()-time triage hook (§5.2, §7.1)."""

    _inherit = "helpdesk.ticket"

    ai_triage_done = fields.Boolean(
        help="True once triage has run for this ticket -- never re-triaged."
    )
    ai_triage_team_suggestion = fields.Char(
        help="Team name Claude suggested (display only)."
    )
    ai_triage_priority_suggestion = fields.Char(
        help="Priority word Claude suggested (display only)."
    )
    ai_triage_confidence = fields.Float(help="Claude's confidence, 0.0-1.0.")
    ai_triage_accepted = fields.Boolean(
        help="True once the suggestion has been resolved -- auto-applied, "
        "or the agent clicked Accept or Dismiss."
    )
    ai_sentiment = fields.Selection(
        SENTIMENT_SELECTION, help="Result of the most recent sentiment check (§7.2)."
    )
    ai_sentiment_updated = fields.Datetime(help="When ai_sentiment was last computed.")
    ai_enabled = fields.Boolean(
        related="team_id.ai_enabled",
        store=True,
        help="Whether this ticket's team has AI features enabled.",
    )
    ai_triage_needs_review = fields.Boolean(
        compute="_compute_ai_triage_needs_review",
        help="True when a low-confidence suggestion is awaiting Accept/Dismiss.",
    )

    @api.depends(
        "ai_triage_done",
        "ai_triage_accepted",
        "ai_triage_confidence",
        "team_id.ai_auto_apply_threshold",
    )
    def _compute_ai_triage_needs_review(self):
        for ticket in self:
            threshold = (
                ticket.team_id.ai_auto_apply_threshold if ticket.team_id else 1.0
            )
            ticket.ai_triage_needs_review = (
                ticket.ai_triage_done
                and not ticket.ai_triage_accepted
                and ticket.ai_triage_confidence < threshold
            )

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        for ticket in tickets:
            ticket._run_ai_triage()  # pylint: disable=protected-access
        return tickets

    def action_accept_triage(self):
        """Apply the low-confidence suggestion the agent chose to accept."""
        self.ensure_one()
        vals = {"ai_triage_accepted": True}
        if self.ai_triage_team_suggestion:
            team = self.env["helpdesk.team"].search(
                [("name", "=", self.ai_triage_team_suggestion)], limit=1
            )
            if team:
                vals["team_id"] = team.id
        priority_key = PRIORITY_WORD_TO_KEY.get(
            (self.ai_triage_priority_suggestion or "").strip().lower()
        )
        if priority_key:
            vals["priority"] = priority_key
        self.write(vals)
        self._mark_triage_log_accepted(True)

    def action_dismiss_triage(self):
        """Discard the low-confidence suggestion; the ticket stays as-is."""
        self.ensure_one()
        self.ai_triage_accepted = True
        self._mark_triage_log_accepted(False)

    def _mark_triage_log_accepted(self, accepted):
        self.ensure_one()
        log = (
            self.env["helpdesk.ai.log"]
            .sudo()
            .search(
                [("ticket_id", "=", self.id), ("call_type", "=", "triage")],
                order="created_at desc",
                limit=1,
            )
        )
        if log:
            log.was_accepted = accepted

    def _run_ai_triage(self):
        """Triage this ticket via Claude, once (§7.1).

        Any failure is caught and logged -- ticket creation must never fail
        because of AI (task requirement) -- and ai_triage_done is always
        set afterwards so a ticket is never re-triaged.
        """
        self.ensure_one()
        if self.ai_triage_done or not self.team_id.ai_enabled:
            return
        plain_description = html2plaintext(self.description or "")
        if len((self.name or "") + plain_description) < MIN_TRIAGE_CONTENT_LENGTH:
            return
        try:
            self._perform_ai_triage(plain_description)
        except Exception:  # pylint: disable=broad-except
            _logger.warning("AI triage failed for ticket %s", self.id, exc_info=True)
        finally:
            self.ai_triage_done = True

    def _perform_ai_triage(self, plain_description):
        self.ensure_one()
        teams = self.env["helpdesk.team"].search([])
        tags = self.env["helpdesk.tag"].search([], order="name", limit=MAX_TRIAGE_TAGS)
        user_content = TRIAGE_USER_TEMPLATE.format(
            subject=(self.name or "")[:MAX_SUBJECT_CHARS],
            body=plain_description[:MAX_BODY_CHARS],
            teams=", ".join(teams.mapped("name")),
            tags=", ".join(tags.mapped("name")),
        )
        result = AnthropicClient(self.env).call(
            system=TRIAGE_SYSTEM_PROMPT,
            user=user_content,
            max_tokens=TRIAGE_MAX_TOKENS,
            temperature=0,
        )
        if not result["ok"]:
            _logger.warning(
                "AI triage call failed for ticket %s: %s", self.id, result["error"]
            )
            return

        suggestion = self._parse_triage_response(result["text"])
        self._log_triage_call(result, suggestion)

        if suggestion is None:
            _logger.warning(
                "AI triage returned an unparseable response for ticket %s", self.id
            )
            return

        self._apply_triage_suggestion(suggestion, teams, tags)

    @staticmethod
    def _parse_triage_response(text):
        """Strictly parse and validate the triage JSON (§7.1, §8): only the
        expected keys/types are accepted, everything else -> None."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        team = data.get("team")
        priority = data.get("priority")
        tags = data.get("tags")
        confidence = data.get("confidence")
        if not isinstance(team, str) or not isinstance(priority, str):
            return None
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return None
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return None
        if not 0.0 <= confidence <= 1.0:
            return None
        return {
            "team": team,
            "priority": priority.strip().lower(),
            "tags": tags,
            "confidence": float(confidence),
        }

    def _apply_triage_suggestion(self, suggestion, teams, tags):
        self.ensure_one()
        team_match = teams.filtered(lambda t: t.name == suggestion["team"])
        priority_key = PRIORITY_WORD_TO_KEY.get(suggestion["priority"])
        tag_matches = tags.filtered(lambda t: t.name in suggestion["tags"])
        threshold = self.team_id.ai_auto_apply_threshold
        auto_apply = suggestion["confidence"] >= threshold

        vals = {
            "ai_triage_team_suggestion": suggestion["team"],
            "ai_triage_priority_suggestion": suggestion["priority"],
            "ai_triage_confidence": suggestion["confidence"],
        }
        if auto_apply:
            vals["ai_triage_accepted"] = True
            if team_match:
                vals["team_id"] = team_match[0].id
            if priority_key:
                vals["priority"] = priority_key
            if tag_matches:
                vals["tag_ids"] = [(6, 0, tag_matches.ids)]
        self.write(vals)

        if not auto_apply:
            tags_text = ", ".join(suggestion["tags"]) if suggestion["tags"] else "none"
            self.message_post(
                body=_(
                    "AI suggested: Team %(team)s | Priority %(priority)s | "
                    "Tags %(tags)s — Accept or Dismiss",
                    team=suggestion["team"],
                    priority=suggestion["priority"],
                    tags=tags_text,
                )
            )

    def _log_triage_call(self, result, suggestion):
        self.ensure_one()
        if suggestion is None:
            summary = "Response did not match the expected triage JSON schema."
        else:
            summary = (
                f"Suggested team={suggestion['team']!r}, "
                f"priority={suggestion['priority']!r}, "
                f"confidence={suggestion['confidence']:.2f}"
            )
        usage = result.get("usage", {})
        self.env["helpdesk.ai.log"].sudo().create(
            {
                "ticket_id": self.id,
                "call_type": "triage",
                "model_used": result.get("model"),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "response_summary": summary,
            }
        )
