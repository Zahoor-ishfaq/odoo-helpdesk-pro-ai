"""Helpdesk Team: per-team AI opt-in, auto-apply threshold, and usage
reporting (§5.3, §1 items 5-6)."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import fields, models


class HelpdeskTeam(models.Model):  # pylint: disable=too-few-public-methods
    """Adds AI opt-in, triage confidence threshold, and accuracy stat to
    each team."""

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
    ai_triage_accuracy = fields.Float(
        string="AI Accuracy",
        compute="_compute_ai_triage_accuracy",
        help="Percentage of this team's triage calls that were accepted "
        "(manually, or via auto-apply) out of all triage calls made "
        "(§1 item 5).",
    )

    def _compute_ai_triage_accuracy(self):
        """No @api.depends -- same convention as this model's own
        csat_avg/sla_compliance/avg_resolution_hours, which also derive a
        stat from a foreign model with no field-level dependency Odoo can
        track. Not stored: cheap to recompute (two counts per team)."""
        ai_log = self.env["helpdesk.ai.log"].sudo()
        for team in self:
            total = ai_log.search_count(
                [("team_id", "=", team.id), ("call_type", "=", "triage")]
            )
            if not total:
                team.ai_triage_accuracy = 0.0
                continue
            accepted = ai_log.search_count(
                [
                    ("team_id", "=", team.id),
                    ("call_type", "=", "triage"),
                    ("was_accepted", "=", True),
                ]
            )
            team.ai_triage_accuracy = accepted / total * 100

    def action_view_ai_log(self):
        """Open this team's AI usage log, pre-filtered (§1 item 5)."""
        self.ensure_one()
        # pylint: disable=protected-access
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "helpdesk_community_pro_ai.helpdesk_ai_log_action"
        )
        action["domain"] = [("team_id", "=", self.id)]
        return action
