"""Helpdesk Team: per-team AI opt-in and auto-apply threshold (§5.3)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import fields, models


class HelpdeskTeam(models.Model):  # pylint: disable=too-few-public-methods
    """Adds AI opt-in and triage confidence threshold to each team."""

    _inherit = "helpdesk.team"

    ai_enabled = fields.Boolean(
        default=False,
        help="Enable AI triage, sentiment detection and reply drafting "
        "for this team.",
    )
    ai_auto_apply_threshold = fields.Float(
        default=0.85,
        help="Triage confidence (0.0-1.0) above which AI suggestions are "
        "applied automatically instead of shown for review.",
    )
