"""Tests for helpdesk.team AI fields: defaults (§5.3), and the AI
accuracy stat (§1 item 5)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHelpdeskTeamAiFields(TransactionCase):
    """A new team opts out of AI by default, at the documented threshold."""

    def test_ai_fields_default(self):
        """ai_enabled defaults False; ai_auto_apply_threshold defaults 0.85."""
        team = self.env["helpdesk.team"].create({"name": "AI Fields Team"})
        self.assertFalse(team.ai_enabled)
        self.assertEqual(team.ai_auto_apply_threshold, 0.85)

    def test_ai_fields_can_be_set(self):
        """ai_enabled and ai_auto_apply_threshold are writable per-team."""
        team = self.env["helpdesk.team"].create({"name": "AI Fields Team 2"})
        team.write({"ai_enabled": True, "ai_auto_apply_threshold": 0.5})
        self.assertTrue(team.ai_enabled)
        self.assertEqual(team.ai_auto_apply_threshold, 0.5)


@tagged("post_install", "-at_install")
class TestHelpdeskTeamAiAccuracy(TransactionCase):
    """AI Accuracy stat: accepted / total triage calls (§1 item 5)."""

    def _create_triage_log(self, team, accepted):
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Accuracy test ticket", "team_id": team.id}
        )
        return self.env["helpdesk.ai.log"].create(
            {
                "ticket_id": ticket.id,
                "call_type": "triage",
                "was_accepted": accepted,
            }
        )

    def test_accuracy_computed_correctly(self):
        """3 accepted out of 5 triage calls -> 60%."""
        team = self.env["helpdesk.team"].create({"name": "Accuracy Team"})
        for accepted in (True, True, True, False, False):
            self._create_triage_log(team, accepted)
        self.assertAlmostEqual(team.ai_triage_accuracy, 60.0)

    def test_accuracy_zero_when_no_triage_calls(self):
        """A team with no triage calls shows 0%, not a division error."""
        team = self.env["helpdesk.team"].create({"name": "No Calls Team"})
        self.assertEqual(team.ai_triage_accuracy, 0.0)

    def test_accuracy_ignores_non_triage_call_types(self):
        """Sentiment/reply_draft calls never count toward triage accuracy."""
        team = self.env["helpdesk.team"].create({"name": "Mixed Calls Team"})
        self._create_triage_log(team, True)
        ticket = self.env["helpdesk.ticket"].create(
            {"name": "Sentiment ticket", "team_id": team.id}
        )
        self.env["helpdesk.ai.log"].create(
            {"ticket_id": ticket.id, "call_type": "sentiment"}
        )
        self.assertEqual(team.ai_triage_accuracy, 100.0)

    def test_action_view_ai_log_filters_to_team(self):
        """Clicking the stat button opens the AI log filtered to this team."""
        team = self.env["helpdesk.team"].create({"name": "Action Team"})
        action = team.action_view_ai_log()
        self.assertEqual(action["res_model"], "helpdesk.ai.log")
        self.assertEqual(action["domain"], [("team_id", "=", team.id)])
