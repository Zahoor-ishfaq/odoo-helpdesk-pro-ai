"""Tests for helpdesk.ticket Sentiment Detection: queue trigger, cron
processing, angry escalation (§7.2, §9 items 5-7). Never calls the real
Anthropic API (§9) -- every test that creates or processes a ticket
patches _call_api, since ticket creation can also trigger M2's Smart
Triage hook, which would otherwise attempt a real network call too."""

from unittest.mock import patch

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.addons.mail.tests.common import MailCommon
from odoo.tests import tagged

_CALL_API_TARGET = (
    "odoo.addons.helpdesk_community_pro_ai.services.anthropic_client"
    ".AnthropicClient._call_api"
)

EMAIL_TPL = """Return-Path: <whatever-2a840@postmaster.twitter.com>
X-Original-To: {to}
Delivered-To: {to}
To: {to}
cc: {cc}
Received: by mail1.odoo.com (Postfix, from userid 10002)
    id 5DF9ABFB2A; Fri, 10 Aug 2012 16:16:39 +0200 (CEST)
Message-ID: {msg_id}
References: {references}
Date: Tue, 29 Nov 2011 12:43:21 +0530
From: {email_from}
MIME-Version: 1.0
Subject: {subject}
Content-Type: text/plain; charset=ISO-8859-1; format=flowed

Hello,

This should create a helpdesk ticket.

Thanks,
A Customer"""


def _api_response(text, prompt_tokens=50, completion_tokens=5):
    return {
        "content": [{"text": text}],
        "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
    }


@tagged("post_install", "-at_install")
class TestHelpdeskTicketSentimentQueue(MailCommon):
    """message_new / message_update queue tickets for a sentiment check
    only when their team has AI enabled (§7.2)."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        """An AI-enabled team and a non-AI team, each with a mail alias."""
        super().setUpClass()
        cls.team = cls.env["helpdesk.team"].create(
            {"name": "Sentiment AI Team", "ai_enabled": True}
        )
        cls.team.alias_name = "sentiment-ai"
        cls.other_team = cls.env["helpdesk.team"].create(
            {"name": "Sentiment Non-AI Team", "ai_enabled": False}
        )
        cls.other_team.alias_name = "sentiment-no-ai"

    def _alias_email(self, team):
        return f"{team.alias_name}@{self.alias_domain}"

    @patch(_CALL_API_TARGET)
    def test_message_new_flags_ai_enabled_team(self, mock_call_api):
        """A ticket created from email on an AI-enabled team is queued."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.format_and_process(
            EMAIL_TPL,
            to=self._alias_email(self.team),
            email_from="customer@example.com",
            subject="Help please",
            target_model="helpdesk.ticket",
        )
        self.assertTrue(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_message_new_does_not_flag_non_ai_team(self, mock_call_api):
        """A ticket created on a non-AI team is never queued."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.format_and_process(
            EMAIL_TPL,
            to=self._alias_email(self.other_team),
            email_from="customer@example.com",
            subject="Help please",
            target_model="helpdesk.ticket",
        )
        self.assertFalse(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_message_update_flags_reply_on_ai_enabled_team(self, mock_call_api):
        """A reply threaded onto an existing ticket queues it again."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.format_and_process(
            EMAIL_TPL,
            to=self._alias_email(self.team),
            email_from="customer@example.com",
            subject="Original",
            msg_id="<sentiment-original@example.com>",
            target_model="helpdesk.ticket",
        )
        ticket.needs_sentiment_check = False  # simulate the cron already ran

        self.format_and_process(
            EMAIL_TPL,
            to=self._alias_email(self.team),
            email_from="customer@example.com",
            subject="Re: Original",
            references="<sentiment-original@example.com>",
            msg_id="<sentiment-reply@example.com>",
            target_model="helpdesk.ticket",
        )
        self.assertTrue(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_message_post_flags_inbound_comment_from_customer(self, mock_call_api):
        """A customer message typed directly into the chatter -- not
        routed through message_new/message_update -- still queues a
        sentiment check (§7.2 scope extension, approved 2026-07-21)."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Portal ticket", "team_id": self.team.id}
        )
        customer = self.env["res.partner"].create(
            {"name": "Angry Customer", "email": "angry@example.com"}
        )
        ticket.needs_sentiment_check = False

        ticket.message_post(
            body="This is unacceptable!",
            message_type="comment",
            author_id=customer.id,
        )
        self.assertTrue(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_message_post_does_not_flag_agents_own_message(self, mock_call_api):
        """An agent's own reply/note, authored as the acting user, is not
        mistaken for an inbound customer message."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Agent note ticket", "team_id": self.team.id}
        )
        ticket.needs_sentiment_check = False

        ticket.message_post(
            body="Internal note",
            message_type="comment",
            author_id=self.env.user.partner_id.id,
        )
        self.assertFalse(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_message_post_does_not_flag_non_ai_team(self, mock_call_api):
        """The team-level ai_enabled gate applies to message_post too."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Non-AI portal ticket", "team_id": self.other_team.id}
        )
        customer = self.env["res.partner"].create(
            {"name": "Angry Customer", "email": "angry2@example.com"}
        )

        ticket.message_post(
            body="This is unacceptable!",
            message_type="comment",
            author_id=customer.id,
        )
        self.assertFalse(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_message_post_does_not_flag_notification_messages(self, mock_call_api):
        """A system notification (e.g. ticket-created) is never mistaken
        for an inbound customer message."""
        mock_call_api.return_value = {"error": "missing_or_invalid_api_key"}
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Notification ticket", "team_id": self.team.id}
        )
        customer = self.env["res.partner"].create(
            {"name": "Angry Customer", "email": "angry3@example.com"}
        )
        ticket.needs_sentiment_check = False

        ticket.message_post(
            body="System generated",
            message_type="notification",
            author_id=customer.id,
        )
        self.assertFalse(ticket.needs_sentiment_check)


@tagged("post_install", "-at_install")
class TestHelpdeskTicketSentimentCron(MailCommon):
    """Cron processing: sentiment scoring, angry escalation, batching,
    graceful degradation (§7.2, §7.5, §9 items 5-7)."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        """A manager on an AI-enabled team, and a non-AI team as a
        negative control for the cron's own team filter."""
        super().setUpClass()
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Sentiment Test Manager",
                "login": "sentiment_test_manager@example.com",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (
                        4,
                        cls.env.ref("helpdesk_community_pro.group_helpdesk_manager").id,
                    ),
                ],
            }
        )
        cls.team = cls.env["helpdesk.team"].create(
            {
                "name": "Sentiment Cron Team",
                "ai_enabled": True,
                "member_ids": [(4, cls.manager.id)],
            }
        )
        cls.other_team = cls.env["helpdesk.team"].create(
            {"name": "Sentiment Cron Non-AI Team", "ai_enabled": False}
        )

    def _create_flagged_ticket(
        self, message_body="I am upset about this.", team=None, priority="1"
    ):
        ticket = self.env["helpdesk.ticket"].create(
            {
                # Deliberately under MIN_TRIAGE_CONTENT_LENGTH (20 chars,
                # no description) so M2's Smart Triage hook never fires
                # here -- these tests are about sentiment only, and a
                # stray triage call would pollute both the mock call
                # count and the helpdesk.ai.log records these tests read.
                "name": "Sentiment test",
                "team_id": (team or self.team).id,
                "priority": priority,
            }
        )
        self.env["mail.message"].create(
            {
                "model": "helpdesk.ticket",
                "res_id": ticket.id,
                "message_type": "email",
                "body": f"<p>{message_body}</p>",
            }
        )
        ticket.needs_sentiment_check = True
        return ticket

    def _run_sentiment_cron(self):
        # pylint: disable=protected-access
        self.env["helpdesk.ticket"]._cron_process_sentiment_queue()

    @patch(_CALL_API_TARGET)
    def test_angry_bumps_priority_and_notifies_manager(self, mock_call_api):
        """§9.5: angry -> priority bumped to Urgent, manager activity
        created, logged with sentiment_score."""
        mock_call_api.return_value = _api_response("angry")
        ticket = self._create_flagged_ticket(priority="1")

        self._run_sentiment_cron()

        self.assertEqual(ticket.ai_sentiment, "angry")
        self.assertTrue(ticket.ai_sentiment_updated)
        self.assertEqual(ticket.priority, "3")
        self.assertFalse(ticket.needs_sentiment_check)

        activities = ticket.activity_ids.filtered(lambda a: a.user_id == self.manager)
        self.assertTrue(activities)
        self.assertIn("Angry", activities[0].summary)

        log = (
            self.env["helpdesk.ai.log"]
            .sudo()
            .search([("ticket_id", "=", ticket.id), ("call_type", "=", "sentiment")])
        )
        self.assertEqual(log.call_type, "sentiment")
        self.assertEqual(log.sentiment_score, "angry")

    @patch(_CALL_API_TARGET)
    def test_angry_does_not_lower_already_higher_priority(self, mock_call_api):
        """Priority is only ever bumped up, never down."""
        mock_call_api.return_value = _api_response("angry")
        ticket = self._create_flagged_ticket(priority="3")

        self._run_sentiment_cron()

        self.assertEqual(ticket.priority, "3")

    @patch(_CALL_API_TARGET)
    def test_calm_leaves_priority_unchanged(self, mock_call_api):
        """§9.6: calm -> no priority change, no manager activity."""
        mock_call_api.return_value = _api_response("calm")
        ticket = self._create_flagged_ticket(priority="1")

        self._run_sentiment_cron()

        self.assertEqual(ticket.ai_sentiment, "calm")
        self.assertEqual(ticket.priority, "1")
        self.assertFalse(ticket.activity_ids)

    @patch(_CALL_API_TARGET)
    def test_malformed_response_defaults_to_neutral(self, mock_call_api):
        """§9.7: an unrecognized response -> defaults to neutral, no crash."""
        mock_call_api.return_value = _api_response("I'm not sure, maybe upset?")
        ticket = self._create_flagged_ticket()

        self._run_sentiment_cron()

        self.assertEqual(ticket.ai_sentiment, "neutral")
        self.assertEqual(ticket.priority, "1")
        self.assertFalse(ticket.needs_sentiment_check)

    @patch(_CALL_API_TARGET)
    def test_cron_only_processes_ai_enabled_teams(self, mock_call_api):
        """The cron's own query excludes non-AI teams -- defense in depth
        alongside the message_new/message_update flagging guarantee,
        independent of however needs_sentiment_check got set."""
        mock_call_api.return_value = _api_response("angry")
        ticket = self._create_flagged_ticket(team=self.other_team)

        self._run_sentiment_cron()

        mock_call_api.assert_not_called()
        self.assertTrue(ticket.needs_sentiment_check, "left queued, not processed")
        self.assertFalse(ticket.ai_sentiment)

    @patch(_CALL_API_TARGET)
    def test_cron_skips_closed_tickets(self, mock_call_api):
        """A closed ticket is never processed even if flagged."""
        mock_call_api.return_value = _api_response("angry")
        closed_stage = self.env["helpdesk.stage"].search(
            [("is_closed", "=", True)], limit=1
        )
        ticket = self._create_flagged_ticket()
        ticket.stage_id = closed_stage

        self._run_sentiment_cron()

        mock_call_api.assert_not_called()
        self.assertFalse(ticket.ai_sentiment)

    @patch(_CALL_API_TARGET)
    def test_cron_processes_at_most_20_per_run(self, mock_call_api):
        """§7.5: batch size is capped at 20 regardless of backlog size."""
        mock_call_api.return_value = _api_response("calm")
        for _ in range(25):
            self._create_flagged_ticket()

        self._run_sentiment_cron()

        self.assertEqual(mock_call_api.call_count, 20)

    @patch(_CALL_API_TARGET)
    def test_api_failure_is_graceful(self, mock_call_api):
        """A failed API call clears the flag without crashing or logging."""
        mock_call_api.return_value = {"error": "timeout_or_network"}
        ticket = self._create_flagged_ticket()

        self._run_sentiment_cron()

        self.assertFalse(ticket.needs_sentiment_check)
        self.assertFalse(ticket.ai_sentiment)
        log = (
            self.env["helpdesk.ai.log"]
            .sudo()
            .search([("ticket_id", "=", ticket.id), ("call_type", "=", "sentiment")])
        )
        self.assertFalse(log)

    @patch(_CALL_API_TARGET)
    def test_no_inbound_message_found_is_graceful(self, mock_call_api):
        """A flagged ticket with no email-type message is skipped
        gracefully -- no crash, flag cleared, no API call attempted."""
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "No message ticket", "team_id": self.team.id}
        )
        ticket.needs_sentiment_check = True

        self._run_sentiment_cron()

        mock_call_api.assert_not_called()
        self.assertFalse(ticket.needs_sentiment_check)
