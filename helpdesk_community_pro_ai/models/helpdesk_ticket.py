"""Helpdesk Ticket: Smart Triage on create (§5.2, §7.1)."""

import json
import logging
import re

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import _, api, fields, models
from odoo.tools.mail import html2plaintext

from ..services.anthropic_client import AnthropicClient
from .helpdesk_ai_log import SENTIMENT_SELECTION

_logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

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
    "You are a helpdesk triage assistant. Return ONLY valid JSON, no explanation. "
    "You must return ONLY a raw JSON object. No markdown, no code blocks, no "
    "explanation. Start your response with { and end with }."
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

MAX_SENTIMENT_CHARS = 300
SENTIMENT_MAX_TOKENS = 10
MAX_SENTIMENT_BATCH = 20
ANGRY_ACTIVITY_SUMMARY = "Customer sentiment: Angry — review recommended"

SENTIMENT_SYSTEM_PROMPT = (
    "Classify the sentiment of this customer support message. Return "
    "ONLY one word: calm, neutral, frustrated, or angry."
)


def _extract_json_block(text):
    """Best-effort {...} extraction for a response that wraps its JSON in
    markdown fences or explanatory prose despite being told not to (a real
    Claude behavior seen in production, not just a hypothetical)."""
    match = _JSON_BLOCK_RE.search(text or "")
    return match.group(0) if match else None


def _safe_json_loads(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _describe_unparseable_response(text):
    """A structural, content-free description of why triage parsing
    failed, safe to persist in helpdesk.ai.log.response_summary.

    Deliberately never includes the response text itself, truncated or
    otherwise: §5.1/§8 forbid storing raw prompts or responses there even
    in part, since prose Claude generates around the JSON can echo back
    ticket content. Only the failure category and a length are safe.
    """
    text = text or ""
    length = len(text)
    block = _extract_json_block(text)
    if block is None:
        return f"No JSON object found in a {length}-char response."
    if _safe_json_loads(block) is None:
        return (
            f"Found a {{...}} block in a {length}-char response, but it "
            "was not valid JSON."
        )
    return (
        f"Found valid JSON in a {length}-char response, but it did not "
        "match the expected team/priority/tags/confidence schema."
    )


def _parse_sentiment_response(text):
    """One word expected -- calm/neutral/frustrated/angry (§7.2). Case and
    stray punctuation are normalized; anything else defaults to neutral,
    same as a missing/malformed response (a safe, conservative fallback,
    not a bug to work around like triage's JSON parsing was)."""
    word = (text or "").strip().strip(".").lower()
    if word in dict(SENTIMENT_SELECTION):
        return word
    return "neutral"


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
    needs_sentiment_check = fields.Boolean(
        default=False,
        index=True,
        help="Queued for a sentiment check by the periodic cron (§7.2).",
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
        """Create tickets, then run AI triage on each (§7.1)."""
        tickets = super().create(vals_list)
        for ticket in tickets:
            ticket._run_ai_triage()  # pylint: disable=protected-access
        return tickets

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Create a ticket from inbound email, then queue it for a
        sentiment check if the team has AI enabled (§7.2)."""
        ticket = super().message_new(msg_dict, custom_values=custom_values)
        if ticket.team_id.ai_enabled:
            ticket.needs_sentiment_check = True
        return ticket

    def message_update(self, msg_dict, update_vals=None):
        """Thread an inbound reply, then queue a sentiment check for it
        if the team has AI enabled (§7.2)."""
        result = super().message_update(msg_dict, update_vals=update_vals)
        for ticket in self:
            if ticket.team_id.ai_enabled:
                ticket.needs_sentiment_check = True
        return result

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
        """Strictly parse and validate the triage JSON (§7.1, §8): a
        direct parse first, falling back to extracting a {...} block for
        responses that wrap JSON in markdown fences or prose despite the
        system prompt saying not to. Only the expected keys/types are
        ever accepted -- everything else -> None."""
        data = _safe_json_loads(text)
        if not isinstance(data, dict):
            extracted = _extract_json_block(text)
            data = _safe_json_loads(extracted) if extracted else None
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
        confidence_is_number = not isinstance(confidence, bool) and isinstance(
            confidence, (int, float)
        )
        if not confidence_is_number or not 0.0 <= confidence <= 1.0:
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
            summary = _describe_unparseable_response(result.get("text", ""))
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

    @api.model
    def _cron_process_sentiment_queue(self):
        """Batch-process the sentiment queue (§7.2, §7.5): max 20 open
        tickets per run, regardless of backlog size -- a closed ticket
        doesn't need a sentiment check. The ai_enabled filter is defense
        in depth alongside message_new/message_update only ever setting
        the flag for AI-enabled teams in the first place."""
        tickets = self.search(
            [
                ("needs_sentiment_check", "=", True),
                ("stage_id.is_closed", "=", False),
                ("team_id.ai_enabled", "=", True),
            ],
            limit=MAX_SENTIMENT_BATCH,
        )
        for ticket in tickets:
            ticket._run_ai_sentiment_check()  # pylint: disable=protected-access

    def _run_ai_sentiment_check(self):
        """Score this ticket's latest inbound message, once (§7.2).

        Any failure is caught and logged; needs_sentiment_check is always
        cleared afterwards so a failing ticket can't wedge the queue --
        it just gets no sentiment this cycle, matching §7.5's graceful
        degradation ("helpdesk still works, just without AI").
        """
        self.ensure_one()
        try:
            self._perform_ai_sentiment_check()
        except Exception:  # pylint: disable=broad-except
            _logger.warning(
                "AI sentiment check failed for ticket %s", self.id, exc_info=True
            )
        finally:
            self.needs_sentiment_check = False

    def _perform_ai_sentiment_check(self):
        self.ensure_one()
        message = self.env["mail.message"].search(
            [
                ("model", "=", "helpdesk.ticket"),
                ("res_id", "=", self.id),
                ("message_type", "=", "email"),
            ],
            order="date desc",
            limit=1,
        )
        if not message:
            return
        plain_body = html2plaintext(message.body or "")[:MAX_SENTIMENT_CHARS]
        if not plain_body.strip():
            return

        result = AnthropicClient(self.env).call(
            system=SENTIMENT_SYSTEM_PROMPT,
            user=plain_body,
            max_tokens=SENTIMENT_MAX_TOKENS,
            temperature=0,
        )
        if not result["ok"]:
            _logger.warning(
                "AI sentiment call failed for ticket %s: %s", self.id, result["error"]
            )
            return

        sentiment = _parse_sentiment_response(result["text"])
        self._log_sentiment_call(result, sentiment)
        self._apply_sentiment(sentiment)

    def _apply_sentiment(self, sentiment):
        self.ensure_one()
        self.write(
            {"ai_sentiment": sentiment, "ai_sentiment_updated": fields.Datetime.now()}
        )
        if sentiment == "angry":
            self._handle_angry_sentiment()

    def _handle_angry_sentiment(self):
        """Bump priority to Urgent and notify the team's manager(s) (§7.2).

        member_ids is sudo()'d before the has_group() check: that method
        raises AccessError when called on any user other than self.env.user
        unless running as superuser -- looping over other users' groups
        under the cron's own (unpredictable) execution user would be a
        latent bug otherwise, not just an access-control nicety.
        """
        self.ensure_one()
        if int(self.priority) < 3:
            self.write({"priority": "3"})
        managers = self.team_id.member_ids.sudo().filtered(
            lambda u: u.has_group("helpdesk_community_pro.group_helpdesk_manager")
        )
        for manager in managers:
            self.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                summary=ANGRY_ACTIVITY_SUMMARY,
                user_id=manager.id,
            )

    def _log_sentiment_call(self, result, sentiment):
        self.ensure_one()
        usage = result.get("usage", {})
        self.env["helpdesk.ai.log"].sudo().create(
            {
                "ticket_id": self.id,
                "call_type": "sentiment",
                "model_used": result.get("model"),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "sentiment_score": sentiment,
                "response_summary": f"Detected sentiment: {sentiment}",
            }
        )
