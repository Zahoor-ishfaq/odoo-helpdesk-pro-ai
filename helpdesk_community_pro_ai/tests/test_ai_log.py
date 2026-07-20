"""Tests for helpdesk.ai.log: field computation and read access (§8)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHelpdeskAiLog(TransactionCase):
    """Token totals and read access restricted to helpdesk managers (§8)."""

    @classmethod
    def setUpClass(cls):  # pylint: disable=invalid-name
        """Share one team and ticket to attach AI log entries to."""
        super().setUpClass()
        cls.team = cls.env["helpdesk.team"].create({"name": "AI Log Team"})
        cls.ticket = cls.env["helpdesk.ticket"].create(
            {"name": "AI log test ticket", "team_id": cls.team.id}
        )

    def test_total_tokens_computed(self):
        """total_tokens is the sum of prompt and completion tokens."""
        log = self.env["helpdesk.ai.log"].create(
            {
                "ticket_id": self.ticket.id,
                "call_type": "triage",
                "prompt_tokens": 120,
                "completion_tokens": 30,
            }
        )
        self.assertEqual(log.total_tokens, 150)

    def test_manager_can_read_log(self):
        """A helpdesk manager can read AI log entries."""
        manager = self.env["res.users"].create(
            {
                "name": "AI Log Manager",
                "login": "ai_log_manager@example.com",
                "group_ids": [
                    (
                        4,
                        self.env.ref(
                            "helpdesk_community_pro.group_helpdesk_manager"
                        ).id,
                    )
                ],
            }
        )
        log = self.env["helpdesk.ai.log"].create(
            {"ticket_id": self.ticket.id, "call_type": "sentiment"}
        )
        log.with_user(manager).read(["call_type"])

    def test_agent_cannot_read_log(self):
        """A plain helpdesk agent (non-manager) cannot read AI log entries,
        per §8: 'AI log view → group_helpdesk_manager only'."""
        agent = self.env["res.users"].create(
            {
                "name": "AI Log Agent",
                "login": "ai_log_agent@example.com",
                "group_ids": [
                    (
                        4,
                        self.env.ref("helpdesk_community_pro.group_helpdesk_user").id,
                    )
                ],
            }
        )
        log = self.env["helpdesk.ai.log"].create(
            {"ticket_id": self.ticket.id, "call_type": "sentiment"}
        )
        with self.assertRaises(AccessError):
            log.with_user(agent).read(["call_type"])
