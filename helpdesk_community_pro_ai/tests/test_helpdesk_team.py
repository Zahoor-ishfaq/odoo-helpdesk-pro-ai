"""Tests for helpdesk.team AI fields: defaults (§5.3)."""

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
