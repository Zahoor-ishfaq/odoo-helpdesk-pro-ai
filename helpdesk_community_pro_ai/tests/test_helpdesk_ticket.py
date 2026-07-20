"""Tests for helpdesk.ticket AI triage: create()-time trigger, apply vs
banner logic, and idempotency (§7.1, §9 items 1-4). Never calls the real
Anthropic API (§9) -- every test that creates a ticket patches _call_api,
even ones expected to skip triage entirely, so a bug in the skip guard
can never let a real network call slip through."""

from unittest.mock import patch

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_CALL_API_TARGET = (
    "odoo.addons.helpdesk_community_pro_ai.services.anthropic_client"
    ".AnthropicClient._call_api"
)


def _api_response(text, prompt_tokens=100, completion_tokens=20):
    return {
        "content": [{"text": text}],
        "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
    }


@tagged("post_install", "-at_install")
class TestHelpdeskTicketTriage(TransactionCase):
    """Smart Triage: create()-time trigger, apply vs banner, idempotency."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        """An AI-enabled team, a second team as an apply-target, and a tag
        the AI can legitimately suggest."""
        super().setUpClass()
        cls.tag_billing = cls.env["helpdesk.tag"].create({"name": "Billing"})
        cls.team = cls.env["helpdesk.team"].create(
            {
                "name": "AI Triage Team",
                "ai_enabled": True,
                "ai_auto_apply_threshold": 0.85,
            }
        )
        cls.other_team = cls.env["helpdesk.team"].create({"name": "Technical Support"})

    def _create_ticket(self, **extra):
        vals = {
            "name": "Cannot log in to my account",
            "description": "<p>I keep getting an error when I try to sign in.</p>",
            "team_id": self.team.id,
        }
        vals.update(extra)
        return self.env["helpdesk.ticket"].create(vals)

    @patch(_CALL_API_TARGET)
    def test_high_confidence_auto_applies(self, mock_call_api):
        """High confidence -> team/priority/tags applied, accepted, logged."""
        mock_call_api.return_value = _api_response(
            '{"team": "Technical Support", "priority": "urgent", '
            '"tags": ["Billing"], "confidence": 0.95}'
        )
        ticket = self._create_ticket()

        self.assertTrue(ticket.ai_triage_done)
        self.assertTrue(ticket.ai_triage_accepted)
        self.assertEqual(ticket.team_id, self.other_team)
        self.assertEqual(ticket.priority, "3")
        self.assertEqual(ticket.tag_ids.ids, [self.tag_billing.id])
        self.assertAlmostEqual(ticket.ai_triage_confidence, 0.95)

        log = self.env["helpdesk.ai.log"].sudo().search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.call_type, "triage")
        self.assertEqual(log.prompt_tokens, 100)
        self.assertEqual(log.completion_tokens, 20)

    @patch(_CALL_API_TARGET)
    def test_low_confidence_posts_banner_without_applying(self, mock_call_api):
        """Low confidence -> chatter note posted, nothing auto-applied."""
        mock_call_api.return_value = _api_response(
            '{"team": "Technical Support", "priority": "high", '
            '"tags": [], "confidence": 0.4}'
        )
        ticket = self._create_ticket()

        self.assertTrue(ticket.ai_triage_done)
        self.assertFalse(ticket.ai_triage_accepted)
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.priority, "1")
        self.assertEqual(ticket.ai_triage_team_suggestion, "Technical Support")
        self.assertEqual(ticket.ai_triage_priority_suggestion, "high")
        self.assertTrue(ticket.ai_triage_needs_review)

        notes = ticket.message_ids.filtered(lambda m: "AI suggested" in (m.body or ""))
        self.assertTrue(notes)

    @patch(_CALL_API_TARGET)
    def test_invalid_json_response_is_skipped_gracefully(self, mock_call_api):
        """Malformed JSON -> no crash, ai_triage_done=True, nothing applied."""
        mock_call_api.return_value = _api_response("not valid json at all")
        ticket = self._create_ticket()

        self.assertTrue(ticket.ai_triage_done)
        self.assertFalse(ticket.ai_triage_accepted)
        self.assertEqual(ticket.team_id, self.team)
        log = self.env["helpdesk.ai.log"].sudo().search([("ticket_id", "=", ticket.id)])
        self.assertEqual(len(log), 1, "the API call still succeeded and used tokens")

    @patch(_CALL_API_TARGET)
    def test_ai_triage_done_prevents_retriage(self, mock_call_api):
        """ai_triage_done=True blocks any further triage call (idempotency)."""
        mock_call_api.return_value = _api_response(
            '{"team": "Technical Support", "priority": "high", '
            '"tags": [], "confidence": 0.4}'
        )
        ticket = self._create_ticket()
        self.assertEqual(mock_call_api.call_count, 1)

        ticket._run_ai_triage()  # pylint: disable=protected-access

        self.assertEqual(mock_call_api.call_count, 1)

    @patch(_CALL_API_TARGET)
    def test_too_short_content_skips_triage(self, mock_call_api):
        """Subject+body under 20 chars -> triage never attempted."""
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Hi", "team_id": self.team.id}
        )

        self.assertFalse(ticket.ai_triage_done)
        mock_call_api.assert_not_called()

    @patch(_CALL_API_TARGET)
    def test_team_without_ai_enabled_skips_triage(self, mock_call_api):
        """A team with ai_enabled=False never triggers triage."""
        ticket = self._create_ticket(team_id=self.other_team.id)

        self.assertFalse(ticket.ai_triage_done)
        mock_call_api.assert_not_called()

    @patch(_CALL_API_TARGET)
    def test_api_failure_is_graceful(self, mock_call_api):
        """A failed API call (e.g. timeout) never blocks ticket creation."""
        mock_call_api.return_value = {"error": "timeout_or_network"}
        ticket = self._create_ticket()

        self.assertTrue(ticket.ai_triage_done)
        self.assertFalse(ticket.ai_triage_accepted)
        log = self.env["helpdesk.ai.log"].sudo().search([("ticket_id", "=", ticket.id)])
        self.assertFalse(log, "a failed call consumed no tokens, nothing to log")

    @patch(_CALL_API_TARGET)
    def test_action_accept_triage_applies_suggestion(self, mock_call_api):
        """Accept applies the suggested team/priority and marks resolved."""
        mock_call_api.return_value = _api_response(
            '{"team": "Technical Support", "priority": "urgent", '
            '"tags": [], "confidence": 0.4}'
        )
        ticket = self._create_ticket()
        self.assertFalse(ticket.ai_triage_accepted)

        ticket.action_accept_triage()

        self.assertTrue(ticket.ai_triage_accepted)
        self.assertEqual(ticket.team_id, self.other_team)
        self.assertEqual(ticket.priority, "3")
        log = self.env["helpdesk.ai.log"].sudo().search([("ticket_id", "=", ticket.id)])
        self.assertTrue(log.was_accepted)

    @patch(_CALL_API_TARGET)
    def test_action_dismiss_triage_leaves_ticket_unchanged(self, mock_call_api):
        """Dismiss marks resolved without touching team/priority."""
        mock_call_api.return_value = _api_response(
            '{"team": "Technical Support", "priority": "urgent", '
            '"tags": [], "confidence": 0.4}'
        )
        ticket = self._create_ticket()

        ticket.action_dismiss_triage()

        self.assertTrue(ticket.ai_triage_accepted)
        self.assertEqual(ticket.team_id, self.team)
        self.assertEqual(ticket.priority, "1")
        log = self.env["helpdesk.ai.log"].sudo().search([("ticket_id", "=", ticket.id)])
        self.assertFalse(log.was_accepted)
