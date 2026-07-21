"""Tests for the AI Usage Log menu/action: the menu was reported missing
from the UI entirely -- these lock in that a manager can actually reach
helpdesk.ai.log, so the regression can't silently reappear."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHelpdeskAiLogMenu(TransactionCase):
    """AI Usage Log action/menu: correct target, correct place, manager-only."""

    def test_action_targets_ai_log_model(self):
        """The action opens helpdesk.ai.log, not some other model."""
        action = self.env.ref("helpdesk_community_pro_ai.helpdesk_ai_log_action")
        self.assertEqual(action.res_model, "helpdesk.ai.log")

    def test_action_offers_pivot_and_graph_views(self):
        """The action's view_mode includes pivot/graph alongside list, so
        users can switch between them (§1 item 6)."""
        action = self.env.ref("helpdesk_community_pro_ai.helpdesk_ai_log_action")
        self.assertEqual(action.view_mode, "list,pivot,graph")

    def test_pivot_view_opens_without_error(self):
        """The pivot view's arch is valid against the model."""
        pivot_view = self.env.ref(
            "helpdesk_community_pro_ai.helpdesk_ai_log_view_pivot"
        )
        self.env["helpdesk.ai.log"].get_view(view_id=pivot_view.id, view_type="pivot")

    def test_graph_view_opens_without_error(self):
        """The graph view's arch is valid against the model."""
        graph_view = self.env.ref(
            "helpdesk_community_pro_ai.helpdesk_ai_log_view_graph"
        )
        self.env["helpdesk.ai.log"].get_view(view_id=graph_view.id, view_type="graph")

    def test_menu_is_under_reporting_under_helpdesk_root(self):
        """Helpdesk > Reporting > AI Usage Log, wired to the right action."""
        menu = self.env.ref("helpdesk_community_pro_ai.helpdesk_menu_ai_log")
        action = self.env.ref("helpdesk_community_pro_ai.helpdesk_ai_log_action")
        reporting = self.env.ref("helpdesk_community_pro_ai.helpdesk_menu_ai_reporting")
        helpdesk_root = self.env.ref("helpdesk_community_pro.helpdesk_menu_root")

        self.assertEqual(menu.action, action)
        self.assertEqual(menu.parent_id, reporting)
        self.assertEqual(reporting.parent_id, helpdesk_root)

    def test_reporting_menu_is_manager_only(self):
        """Only group_helpdesk_manager is granted the Reporting menu (§8)."""
        reporting = self.env.ref("helpdesk_community_pro_ai.helpdesk_menu_ai_reporting")
        manager_group = self.env.ref("helpdesk_community_pro.group_helpdesk_manager")
        self.assertIn(manager_group, reporting.group_ids)

    def test_manager_can_see_the_menu(self):
        """A real helpdesk manager can actually reach the menu (the bug)."""
        # base.group_user (Internal User) is required for any ir.ui.menu
        # access at all -- the Settings > Users UI always grants it
        # alongside a feature role like Helpdesk Manager, so a real manager
        # always has both; this mirrors that real provisioning.
        manager = self.env["res.users"].create(
            {
                "name": "Menu Test Manager",
                "login": "menu_test_manager@example.com",
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (
                        4,
                        self.env.ref(
                            "helpdesk_community_pro.group_helpdesk_manager"
                        ).id,
                    ),
                ],
            }
        )
        menu = self.env.ref("helpdesk_community_pro_ai.helpdesk_menu_ai_log")
        # pylint: disable=protected-access
        visible = self.env["ir.ui.menu"].with_user(manager)._visible_menu_ids()
        self.assertIn(menu.id, visible)

    def test_agent_cannot_see_the_menu(self):
        """A non-manager agent must not see the manager-only menu (§8)."""
        agent = self.env["res.users"].create(
            {
                "name": "Menu Test Agent",
                "login": "menu_test_agent@example.com",
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (
                        4,
                        self.env.ref("helpdesk_community_pro.group_helpdesk_user").id,
                    ),
                ],
            }
        )
        menu = self.env.ref("helpdesk_community_pro_ai.helpdesk_menu_ai_log")
        # pylint: disable=protected-access
        visible = self.env["ir.ui.menu"].with_user(agent)._visible_menu_ids()
        self.assertNotIn(menu.id, visible)
