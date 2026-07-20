"""Helpdesk AI settings: Anthropic API key storage and validation (§7.4, §8)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services.anthropic_client import (
    CONFIG_PARAM_KEY,
    CONFIG_PARAM_MODEL,
    DEFAULT_MODEL,
    MODEL_SELECTION,
    validate_api_key_format,
)


class ResConfigSettings(
    models.TransientModel
):  # pylint: disable=too-few-public-methods
    """Adds the Anthropic API key field to General Settings.

    The key is write-only: `get_values` never reads the stored value back
    into the field, so a saved key is never echoed to the client again
    (§8). Reading/writing the underlying `ir.config_parameter` is further
    restricted to `base.group_system`, both by Odoo core's own ACL on that
    model and by the explicit check in `set_values` below.
    """

    _inherit = "res.config.settings"

    anthropic_api_key = fields.Char(
        string="Anthropic API Key",
        help="Paste a new key to replace the stored one. Leave blank to "
        "keep the current key unchanged.",
    )
    anthropic_api_key_configured = fields.Boolean(
        string="API Key Configured",
        compute="_compute_anthropic_api_key_configured",
        help="Whether an Anthropic API key is currently stored.",
    )
    anthropic_model = fields.Selection(
        MODEL_SELECTION,
        string="AI Model",
        default=DEFAULT_MODEL,
        config_parameter=CONFIG_PARAM_MODEL,
        help="Model used for triage, sentiment detection and reply drafting.",
    )

    def _compute_anthropic_api_key_configured(self):
        has_key = bool(
            self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM_KEY)
        )
        for record in self:
            record.anthropic_api_key_configured = has_key

    def get_values(self):
        """Populate settings defaults, but never the stored API key (§8)."""
        res = super().get_values()
        res["anthropic_api_key"] = False
        return res

    def set_values(self):
        """Validate and store a new key; blank input leaves it unchanged."""
        super().set_values()
        if self.anthropic_api_key:
            if not self.env.user.has_group("base.group_system"):
                raise AccessError(
                    _("Only administrators can set the Anthropic API key.")
                )
            if not validate_api_key_format(self.anthropic_api_key):
                raise ValidationError(
                    _(
                        "Invalid Anthropic API key format: it must start "
                        "with 'sk-ant-' and be exactly 108 characters long."
                    )
                )
            self.env["ir.config_parameter"].sudo().set_param(
                CONFIG_PARAM_KEY, self.anthropic_api_key
            )
