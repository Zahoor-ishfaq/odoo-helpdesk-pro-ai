"""Tests for the AI Reply Draft wizard: RAG context building, prompt
content, PII exclusion, API failure handling, access control, and
logging (§7.3, §9 item 8). Never calls the real Anthropic API (§9) --
every test that creates a ticket patches _call_api, since ticket
creation can also trigger M2's Smart Triage hook."""

from unittest.mock import patch

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from .common import CALL_API_TARGET as _CALL_API_TARGET
from .common import api_response as _api_response


@tagged("post_install", "-at_install")
class TestHelpdeskAiReplyWizard(TransactionCase):
    """Draft Reply wizard: prompt building, PII exclusion, similar
    tickets, API failure handling, access control, logging."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        """A team with one agent member, and a customer whose email must
        never reach the prompt."""
        super().setUpClass()
        cls.team = cls.env["helpdesk.team"].create({"name": "Reply Team"})
        cls.agent = cls.env["res.users"].create(
            {
                "name": "Reply Agent",
                "login": "reply_agent_test@example.com",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("helpdesk_community_pro.group_helpdesk_user").id),
                ],
            }
        )
        cls.team.member_ids = [(4, cls.agent.id)]
        cls.closed_stage = cls.env["helpdesk.stage"].search(
            [("is_closed", "=", True)], limit=1
        )
        cls.customer = cls.env["res.partner"].create(
            {"name": "Test Customer", "email": "customer_pii@example.com"}
        )

    def _create_ticket(self, mock_call_api, **extra):
        """Every ticket create() can trigger M2's triage hook -- pin the
        mock to a harmless failure for the create() call itself; tests
        that care about the wizard's own call reconfigure it afterwards."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        vals = {
            "name": "Cannot login to my account",
            "team_id": self.team.id,
            "partner_id": self.customer.id,
            "partner_email": self.customer.email,
        }
        vals.update(extra)
        return self.env["helpdesk.ticket"].create(vals)

    def _open_wizard(self, ticket, user=None):
        wizard_model = self.env["helpdesk.ai.reply.wizard"].with_user(
            user or self.agent
        )
        fields_list = [
            "ticket_id",
            "draft_reply",
            "context_summary",
            "generation_failed",
            "error_message",
        ]
        return wizard_model.with_context(active_id=ticket.id).default_get(fields_list)

    @patch(_CALL_API_TARGET)
    def test_prompt_includes_ticket_context_and_conversation(self, mock_call_api):
        """The prompt includes the ticket subject and recent messages."""
        ticket = self._create_ticket(mock_call_api)
        ticket.message_post(
            body="I can't log in, please help!",
            message_type="comment",
            author_id=self.customer.id,
        )

        mock_call_api.return_value = _api_response("Thanks for reaching out.")
        self._open_wizard(ticket)

        user_content = mock_call_api.call_args[0][0]["messages"][0]["content"]
        self.assertIn("Cannot login to my account", user_content)
        self.assertIn("I can't log in, please help!", user_content)

    @patch(_CALL_API_TARGET)
    def test_prompt_excludes_customer_pii(self, mock_call_api):
        """Customer email is never sent to the API (§8)."""
        ticket = self._create_ticket(mock_call_api)

        mock_call_api.return_value = _api_response("A reply.")
        self._open_wizard(ticket)

        payload = mock_call_api.call_args[0][0]
        self.assertNotIn(self.customer.email, payload["system"])
        self.assertNotIn(self.customer.email, payload["messages"][0]["content"])

    @patch(_CALL_API_TARGET)
    def test_similar_resolved_tickets_are_found_and_included(self, mock_call_api):
        """Resolved tickets with a similar subject in the same team are
        included as reference (ilike on the first 3 words, §7.3)."""
        resolved = self._create_ticket(
            mock_call_api, name="Cannot login to portal", stage_id=self.closed_stage.id
        )
        resolved.message_post(
            body="Try resetting your password from the login page.",
            message_type="comment",
            author_id=self.agent.partner_id.id,
        )
        ticket = self._create_ticket(mock_call_api, name="Cannot login to my dashboard")

        mock_call_api.return_value = _api_response("A reply.")
        self._open_wizard(ticket)

        user_content = mock_call_api.call_args[0][0]["messages"][0]["content"]
        self.assertIn("Cannot login to portal", user_content)
        self.assertIn("Try resetting your password", user_content)

    @patch(_CALL_API_TARGET)
    def test_similar_tickets_scoped_to_same_team(self, mock_call_api):
        """A subject-matching resolved ticket on a *different* team is
        never pulled in as reference."""
        other_team = self.env["helpdesk.team"].create({"name": "Other Team"})
        self._create_ticket(
            mock_call_api,
            name="Cannot login to remote server",
            team_id=other_team.id,
            stage_id=self.closed_stage.id,
        )
        ticket = self._create_ticket(mock_call_api, name="Cannot login to my account")

        mock_call_api.return_value = _api_response("A reply.")
        self._open_wizard(ticket)

        user_content = mock_call_api.call_args[0][0]["messages"][0]["content"]
        self.assertIn("(none found)", user_content)

    @patch(_CALL_API_TARGET)
    def test_api_failure_shows_error_not_draft(self, mock_call_api):
        """A failed API call leaves the wizard usable with an error
        message instead of raising or leaving a stale draft."""
        ticket = self._create_ticket(mock_call_api)

        mock_call_api.return_value = {"error": "timeout_or_network"}
        result = self._open_wizard(ticket)

        self.assertTrue(result["generation_failed"])
        self.assertFalse(result["draft_reply"])
        self.assertTrue(result["error_message"])

    @patch(_CALL_API_TARGET)
    def test_successful_call_logs_reply_draft(self, mock_call_api):
        """Every successful call creates exactly one helpdesk.ai.log
        record with token counts (§9 item 14)."""
        ticket = self._create_ticket(mock_call_api)

        mock_call_api.return_value = _api_response(
            "A reply.", prompt_tokens=80, completion_tokens=15
        )
        self._open_wizard(ticket)

        log = (
            self.env["helpdesk.ai.log"]
            .sudo()
            .search([("ticket_id", "=", ticket.id), ("call_type", "=", "reply_draft")])
        )
        self.assertEqual(len(log), 1)
        self.assertEqual(log.prompt_tokens, 80)
        self.assertEqual(log.completion_tokens, 15)

    @patch(_CALL_API_TARGET)
    def test_failed_call_does_not_log(self, mock_call_api):
        """A failed API call is never logged -- there's no usage to
        report, matching triage/sentiment's own convention."""
        ticket = self._create_ticket(mock_call_api)

        mock_call_api.return_value = {"error": "timeout_or_network"}
        self._open_wizard(ticket)

        log = (
            self.env["helpdesk.ai.log"]
            .sudo()
            .search([("ticket_id", "=", ticket.id), ("call_type", "=", "reply_draft")])
        )
        self.assertFalse(log)

    @patch(_CALL_API_TARGET)
    def test_agent_outside_team_cannot_open_wizard(self, mock_call_api):
        """§8 access control: only an agent on the ticket's own team may
        draft a reply for it."""
        ticket = self._create_ticket(mock_call_api)
        outsider = self.env["res.users"].create(
            {
                "name": "Outsider",
                "login": "outsider_test@example.com",
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (
                        4,
                        self.env.ref("helpdesk_community_pro.group_helpdesk_user").id,
                    ),
                ],
            }
        )

        with self.assertRaises(AccessError):
            self._open_wizard(ticket, user=outsider)

    @patch(_CALL_API_TARGET)
    def test_use_reply_posts_internal_note_only(self, mock_call_api):
        """Using the draft stages it as an internal note -- never emailed
        to the customer, since the AI never sends (§7.3)."""
        ticket = self._create_ticket(mock_call_api)
        ticket.message_subscribe(partner_ids=[self.customer.id])

        mock_call_api.return_value = _api_response("Thanks for reaching out!")
        vals = self._open_wizard(ticket)
        wizard = (
            self.env["helpdesk.ai.reply.wizard"]
            .with_user(self.agent)
            .with_context(active_id=ticket.id)
            .create(vals)
        )

        wizard.action_use_reply()

        note = self.env["mail.message"].search(
            [("model", "=", "helpdesk.ticket"), ("res_id", "=", ticket.id)],
            order="id desc",
            limit=1,
        )
        self.assertIn("Thanks for reaching out!", note.body)
        notifs = self.env["mail.notification"].search(
            [("mail_message_id", "=", note.id)]
        )
        self.assertFalse(notifs, "an internal note must never notify the customer")
