"""Tests for the Helpdesk AI settings: key validation, admin-only access,
and the write-only (never-echoed) API key field (§7.4, §8)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..services.anthropic_client import CONFIG_PARAM_KEY

VALID_KEY = "sk-ant-" + "a" * 101  # 108 chars total, matches §7.4 format
INVALID_KEY = "wrong-prefix-key"


@tagged("post_install", "-at_install")
class TestHelpdeskAiSettings(TransactionCase):
    """API key format validation, admin-only access, write-only field."""

    def test_valid_key_is_stored(self):
        """A correctly-formatted key is written to ir.config_parameter."""
        settings = self.env["res.config.settings"].create(
            {"anthropic_api_key": VALID_KEY}
        )
        settings.set_values()
        stored = self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM_KEY)
        self.assertEqual(stored, VALID_KEY)

    def test_invalid_key_is_rejected(self):
        """A malformed key raises and is never written to storage (§7.4)."""
        settings = self.env["res.config.settings"].create(
            {"anthropic_api_key": INVALID_KEY}
        )
        with self.assertRaises(ValidationError):
            settings.set_values()
        stored = self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM_KEY)
        self.assertFalse(stored)

    def test_blank_key_keeps_existing_value(self):
        """Saving settings with the field left blank must not wipe an
        already-stored key: blank means 'leave unchanged', since the
        field never shows the current value (it's write-only)."""
        self.env["ir.config_parameter"].sudo().set_param(CONFIG_PARAM_KEY, VALID_KEY)
        settings = self.env["res.config.settings"].create({})
        settings.set_values()
        stored = self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM_KEY)
        self.assertEqual(stored, VALID_KEY)

    def test_get_values_never_echoes_stored_key(self):
        """A stored key is never returned to populate the form field (§8)."""
        self.env["ir.config_parameter"].sudo().set_param(CONFIG_PARAM_KEY, VALID_KEY)
        settings = self.env["res.config.settings"].create({})
        self.assertFalse(settings.get_values().get("anthropic_api_key"))

    def test_non_admin_cannot_set_key(self):
        """Non-admins can't even open Settings in this Odoo build (core ACL
        on res.config.settings itself), which is the outer layer of the
        admin-only guarantee; set_values()'s own has_group check is the
        inner layer, exercised directly here since it can't be reached
        through create() as a non-admin."""
        agent = self.env["res.users"].create(
            {
                "name": "Non Admin Settings",
                "login": "non_admin_ai_settings@example.com",
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )
        with self.assertRaises(AccessError):
            self.env["res.config.settings"].with_user(agent).create(
                {"anthropic_api_key": VALID_KEY}
            )

        settings_as_agent = self.env["res.config.settings"].create(
            {"anthropic_api_key": VALID_KEY}
        )
        with self.assertRaises(AccessError):
            settings_as_agent.with_user(agent).set_values()

    def test_non_admin_cannot_access_config_parameter_directly(self):
        """Only base.group_system may access ir.config_parameter without
        sudo(); the Anthropic key's at-rest protection relies on this
        core Odoo ACL (§7.4, §8)."""
        agent = self.env["res.users"].create(
            {
                "name": "Non Admin Config",
                "login": "non_admin_config_param@example.com",
                "group_ids": [(4, self.env.ref("base.group_user").id)],
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(CONFIG_PARAM_KEY, VALID_KEY)
        with self.assertRaises(AccessError):
            self.env["ir.config_parameter"].with_user(agent).search(
                [("key", "=", CONFIG_PARAM_KEY)]
            )
