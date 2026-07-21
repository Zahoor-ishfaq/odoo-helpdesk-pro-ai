"""AI Reply Draft wizard (§7.3, §11 M4): builds a RAG-lite prompt from
the ticket's own conversation and similar resolved tickets, drafts a
reply via Claude, and lets the agent stage it into the chatter -- the AI
never posts or sends anything to the customer itself."""

# pylint: disable=import-error
# odoo is not installed in the isolated pylint-odoo pre-commit environment.
from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.mail import html2plaintext, plaintext2html

from ..services.anthropic_client import AnthropicClient

MAX_SUBJECT_CHARS = 200
MAX_MESSAGE_CHARS = 300
MAX_CONTEXT_MESSAGES = 3
MAX_SIMILAR_TICKETS = 5
MAX_SIMILAR_FIELD_CHARS = 100
REPLY_MAX_TOKENS = 300
REPLY_TEMPERATURE = 0.3

REPLY_SYSTEM_PROMPT = (
    "You are a helpful customer support agent. Write a professional, "
    "empathetic reply. Keep it under 150 words. Do not make promises "
    "about timelines. Use the resolved ticket examples as style/content "
    "reference only."
)

REPLY_USER_TEMPLATE = (
    "Customer ticket: {subject}\n"
    "Conversation so far: {messages}\n"
    "Similar resolved tickets for reference:\n{similar_tickets}\n"
    "Draft a reply:"
)


class HelpdeskAiReplyWizard(models.TransientModel):
    """Draft Reply wizard: RAG-lite context, one Claude call, editable
    draft. The agent always sends -- this never posts to the customer."""

    _name = "helpdesk.ai.reply.wizard"
    _description = "AI Reply Draft Wizard"

    ticket_id = fields.Many2one("helpdesk.ticket", required=True)
    draft_reply = fields.Text(help="Claude's draft -- edit freely before using it.")
    context_summary = fields.Char(
        readonly=True, help="What context was used to build this draft."
    )
    generation_failed = fields.Boolean(readonly=True)
    error_message = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        """Populate ticket_id from the ticket this wizard opened from, and
        generate the draft immediately so it's ready the moment the
        wizard appears -- no separate "Generate" click needed."""
        defaults = super().default_get(fields_list)
        ticket_id = self.env.context.get("active_id")
        if "ticket_id" in fields_list and ticket_id and not defaults.get("ticket_id"):
            defaults["ticket_id"] = ticket_id
        wants_draft = ticket_id and (
            "draft_reply" in fields_list or "context_summary" in fields_list
        )
        if wants_draft:
            ticket = self.env["helpdesk.ticket"].browse(ticket_id)
            self._check_ticket_access(ticket)
            defaults.update(self._generate_draft(ticket))
        return defaults

    def _check_ticket_access(self, ticket):
        """Only an agent on the ticket's own team may draft a reply for it
        (§8 access control) -- checked explicitly here since the general
        helpdesk.ticket ACL doesn't itself scope internal users to their
        teams."""
        if self.env.user not in ticket.team_id.member_ids:
            raise AccessError(
                _("You can only draft replies for tickets on your own team.")
            )

    def _generate_draft(self, ticket):
        """Build the RAG-lite prompt and call Claude once; returns a vals
        dict ready to merge into default_get's result."""
        ticket.ensure_one()
        messages = self._recent_conversation(ticket)
        similar_tickets = self._find_similar_resolved_tickets(ticket)
        user_content = REPLY_USER_TEMPLATE.format(
            subject=(ticket.name or "")[:MAX_SUBJECT_CHARS],
            messages=self._format_messages(messages) or "(no prior messages)",
            similar_tickets=self._format_similar_tickets(similar_tickets)
            or "(none found)",
        )

        result = AnthropicClient(self.env).call(
            system=REPLY_SYSTEM_PROMPT,
            user=user_content,
            max_tokens=REPLY_MAX_TOKENS,
            temperature=REPLY_TEMPERATURE,
        )

        summary = _(
            "%(msg_count)d prior message(s), %(similar_count)d similar "
            "resolved ticket(s) used as reference.",
            msg_count=len(messages),
            similar_count=len(similar_tickets),
        )

        if not result["ok"]:
            return {
                "draft_reply": False,
                "context_summary": summary,
                "generation_failed": True,
                "error_message": _(
                    "AI reply generation is currently unavailable. Please "
                    "write your reply manually."
                ),
            }

        self._log_reply_draft_call(ticket, result, len(similar_tickets))
        return {
            "draft_reply": result["text"].strip(),
            "context_summary": summary,
            "generation_failed": False,
            "error_message": False,
        }

    def _recent_conversation(self, ticket):
        """Last 3 chatter messages (email or comment -- never the system's
        own notification noise), oldest first for a readable transcript."""
        return self.env["mail.message"].search(
            [
                ("model", "=", "helpdesk.ticket"),
                ("res_id", "=", ticket.id),
                ("message_type", "in", ("email", "comment")),
            ],
            order="date desc",
            limit=MAX_CONTEXT_MESSAGES,
        )[::-1]

    @staticmethod
    def _format_messages(messages):
        lines = [
            html2plaintext(message.body or "")[:MAX_MESSAGE_CHARS]
            for message in messages
        ]
        return "\n".join(line for line in lines if line.strip())

    def _find_similar_resolved_tickets(self, ticket):
        """Last 5 resolved tickets on the same team with a similar subject
        -- a plain ilike on the ticket's first 3 words, no vector DB
        (§7.3): simple SQL search is enough for V1."""
        search_phrase = " ".join((ticket.name or "").split()[:3])
        if not search_phrase:
            return self.env["helpdesk.ticket"]
        return self.env["helpdesk.ticket"].search(
            [
                ("team_id", "=", ticket.team_id.id),
                ("stage_id.is_closed", "=", True),
                ("id", "!=", ticket.id),
                ("name", "ilike", search_phrase),
            ],
            order="write_date desc",
            limit=MAX_SIMILAR_TICKETS,
        )

    def _last_agent_message(self, ticket):
        """The last message authored by one of the ticket's own team
        members -- a lightweight stand-in for "how this kind of ticket
        was resolved", without a dedicated resolution-notes field."""
        return self.env["mail.message"].search(
            [
                ("model", "=", "helpdesk.ticket"),
                ("res_id", "=", ticket.id),
                ("author_id", "in", ticket.team_id.member_ids.partner_id.ids),
            ],
            order="date desc",
            limit=1,
        )

    def _format_similar_tickets(self, tickets):
        """Subject + last agent message per ticket, each capped at 100
        chars (§7.3) -- never customer email/phone, which live on
        partner_id/partner_email and are never touched here."""
        lines = []
        for similar in tickets:
            subject = (similar.name or "")[:MAX_SIMILAR_FIELD_CHARS]
            message = self._last_agent_message(similar)
            resolution = (
                html2plaintext(message.body or "")[:MAX_SIMILAR_FIELD_CHARS]
                if message
                else ""
            )
            lines.append(f"- Subject: {subject} | Resolution: {resolution}")
        return "\n".join(lines)

    def _log_reply_draft_call(self, ticket, result, similar_count):
        usage = result.get("usage", {})
        self.env["helpdesk.ai.log"].sudo().create(
            {
                "ticket_id": ticket.id,
                "call_type": "reply_draft",
                "model_used": result.get("model"),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "response_summary": (
                    f"Drafted a reply using {similar_count} similar "
                    "ticket(s) as reference."
                ),
            }
        )

    def action_use_reply(self):
        """Stage the edited draft as an internal chatter note -- visible
        only to agents, never emailed to the customer (§7.3: the AI never
        sends; the agent still has to compose and click Send themselves)."""
        self.ensure_one()
        self.ticket_id.message_post(
            body=plaintext2html(self.draft_reply or ""),
            subject=_("AI drafted reply (copy into your response)"),
            subtype_xmlid="mail.mt_note",
        )
        return {"type": "ir.actions.act_window_close"}
