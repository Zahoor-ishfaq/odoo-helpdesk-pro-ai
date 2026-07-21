# pylint: disable=missing-module-docstring,pointless-statement
# Odoo loads this file via ast.literal_eval(), which requires the file to
# contain exactly one bare expression -- no docstring or other statement
# can precede the dict literal.
{
    "name": "Helpdesk AI Copilot — Smart Triage, Reply Assistant & Sentiment",
    "summary": "Anthropic Claude-powered triage, sentiment detection and "
    "AI-drafted replies for Helpdesk Pro — free, no Enterprise license.",
    "version": "19.0.1.0.0",
    "category": "Services/Helpdesk",
    "author": "Zahoor Ishfaq",
    "website": "https://github.com/Zahoor-ishfaq/odoo-helpdesk-pro-ai",
    "license": "LGPL-3",
    "depends": ["helpdesk_community_pro"],
    "data": [
        "security/helpdesk_ai_security.xml",
        "security/ir.model.access.csv",
        "data/helpdesk_ai_cron.xml",
        "views/helpdesk_ai_settings_views.xml",
        "views/helpdesk_ai_log_views.xml",
        "views/helpdesk_team_views.xml",
        "wizard/helpdesk_ai_reply_views.xml",
        "views/helpdesk_ticket_views.xml",
        "views/helpdesk_menus.xml",
    ],
    "demo": [
        "demo/helpdesk_ai_demo.xml",
    ],
    "installable": True,
    "application": False,
}
