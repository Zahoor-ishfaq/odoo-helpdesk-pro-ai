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

    def test_cost_estimate_prices_prompt_and_completion_separately(self):
        """1000 prompt + 1000 completion tokens -> $0.00025 + $0.00125 at
        claude-haiku-4-5's published per-1000-token rate (§1 item 6)."""
        log = self.env["helpdesk.ai.log"].create(
            {
                "ticket_id": self.ticket.id,
                "call_type": "triage",
                "prompt_tokens": 1000,
                "completion_tokens": 1000,
            }
        )
        self.assertAlmostEqual(log.cost_estimate, 0.0015, places=6)

    def test_cost_estimate_visible_for_small_token_counts(self):
        """A small, realistic call still shows a nonzero cost -- the field's
        6-decimal precision keeps near-zero costs from rounding to 0.00
        (rounded to that same precision on storage, hence places=6)."""
        log = self.env["helpdesk.ai.log"].create(
            {
                "ticket_id": self.ticket.id,
                "call_type": "sentiment",
                "prompt_tokens": 50,
                "completion_tokens": 5,
            }
        )
        self.assertGreater(log.cost_estimate, 0.0)
        self.assertAlmostEqual(log.cost_estimate, 0.00001875, places=6)

    def test_team_id_denormalized_from_ticket(self):
        """team_id is related/stored from ticket_id.team_id, for pivot/graph
        grouping by team (§1 item 6)."""
        log = self.env["helpdesk.ai.log"].create(
            {"ticket_id": self.ticket.id, "call_type": "triage"}
        )
        self.assertEqual(log.team_id, self.team)

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
