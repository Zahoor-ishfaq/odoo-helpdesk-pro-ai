# Helpdesk AI Copilot — User Guide

This guide explains what Helpdesk AI Copilot does and how to set it
up, in plain language. You don't need any AI experience to use it.

## Installation

**Step 1: Install Helpdesk Pro first.**
Helpdesk AI Copilot is an add-on for [Helpdesk Pro](https://apps.odoo.com/apps/modules/19.0/helpdesk_community_pro)
(`helpdesk_community_pro`) — install that module first from the Apps
list.

**Step 2: Install Helpdesk AI Copilot.**
Once Helpdesk Pro is installed, find **Helpdesk AI Copilot**
(`helpdesk_community_pro_ai`) in the Apps list and install it too.

**Step 3: Add your API key.**
Go to **Settings ▸ General Settings**, scroll to **Helpdesk AI**,
paste your Anthropic API key into the **Anthropic API Key** field, and
click **Save**. (Don't have a key yet? See
[Getting an Anthropic API Key](#getting-an-anthropic-api-key) below.)

**Step 4: Turn AI on for a team.**
Go to **Helpdesk ▸ Teams**, open the team you want to use AI on,
check **AI Enabled** under the **AI Copilot** section, set the
**Ai Auto Apply Threshold** (see [what the threshold
means](#what-the-threshold-means) below), and click **Save**.

That's it — the team's tickets now get Smart Triage and Sentiment
Detection automatically, and agents can use the Draft Reply button.

## Features

### Smart Triage

**What it does:** The moment a new ticket comes in, Claude reads the
subject and description and suggests which team it belongs to, how
urgent it is, and what tags fit — the same judgment call an
experienced agent would make, just instant.

**What the agent sees:**

- If Claude is confident in its suggestion, it's applied automatically
  — the ticket's team, priority, and tags are already set when you
  open it. Nothing to do.
- If Claude is less sure, nothing changes yet. Instead you'll see a
  blue banner on the ticket: *"AI suggested: Team X | Priority Y |
  Confidence Z%"* with two buttons.

**How to accept or dismiss:** Click **Accept** to apply the suggestion
as-is, or **Dismiss** to ignore it and leave the ticket untouched.
Either way, the banner disappears and the ticket is never re-analyzed.

#### What the threshold means

The **Ai Auto Apply Threshold** is a number between 0 and 1 (shown as
a percentage) that controls how sure Claude has to be before it
applies a suggestion without asking. For example, a threshold of 0.70
means: any suggestion Claude is at least 70% confident about gets
applied automatically; anything less confident shows as a banner for
you to review instead. Lower it if you trust the suggestions and want
less manual review; raise it if you'd rather double-check more often.

### Sentiment Detection

**What it does:** Every time a customer emails in or replies (or
comments from the customer portal), Claude reads the message and
gauges how the customer is feeling. This runs automatically — nothing
for the agent to trigger.

**What the badges mean:**

- 🟢 **Calm** — a normal, even-toned message.
- ⚪ **Neutral** — no strong emotion either way.
- 🟠 **Frustrated** — the customer is annoyed or losing patience.
- 🔴 **Angry** — the customer is upset. This is the one that needs
  attention.

**What happens when angry is detected:** The ticket's priority is
automatically raised to **Urgent** (if it wasn't already), and every
manager on that team gets a to-do notifying them: *"Customer
sentiment: Angry — review recommended."* This way an upset customer
never sits quietly in a busy queue.

### AI Reply Assistant

**What it does:** Instead of staring at a blank reply box, click
**Draft Reply** on any ticket. Claude reads the ticket's recent
messages plus a few similar tickets your team has already resolved,
and writes a professional, empathetic first draft — usually in a few
seconds.

**How to use the Draft Reply button:** Open a ticket, click **Draft
Reply** in the header. A window opens showing the draft in an editable
box.

**How to edit and send:** Change anything you like in the draft box,
then click **Use This Reply** — this adds it to the ticket's internal
notes so you can copy it into your actual reply. **The AI never emails
the customer itself.** You always review the text, paste it into a
real reply, and click Send yourself. If you don't like the draft at
all, just click **Cancel** and write your own reply as normal.

### Usage Dashboard

**Where to find it:** Go to **Helpdesk ▸ Reporting ▸ AI Usage Log**.

**What the metrics mean:**

- **Total Tokens** — a rough measure of how much text was sent to and
  received from Claude for that call. More tokens = a bit more cost.
- **Cost Estimate** — the estimated price of that call in US dollars.
  Individual calls are tiny fractions of a cent, so this is shown with
  extra decimal places so it doesn't just look like "$0.00".
- **Call Type** — whether the call was a Triage suggestion, a
  Sentiment check, or a Reply Draft.

Switch between **List**, **Pivot**, and **Graph** using the icons in
the top-right to see the same data as a table, a breakdown by team and
call type, or a bar chart.

**How to read the accuracy %:** Each team's form has an **AI
Accuracy** button near the top. This is simply: *how many triage
suggestions were accepted, out of all triage suggestions made* — for
example, 75% means 3 out of every 4 suggestions were kept (whether
automatically or by an agent clicking Accept). Click the button to see
the underlying log entries for that team.

## Getting an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com) and
   create an account (or sign in).
2. Click **API Keys ▸ Create Key**, give it a name like
   `odoo-helpdesk`, and copy the key — it starts with `sk-ant-` and is
   shown only once.
3. Paste that key into Odoo under **Settings ▸ General Settings ▸
   Helpdesk AI ▸ Anthropic API Key** and click **Save**.

**Expected costs:** Every call is small — a triage or sentiment check
is a few hundred words at most. For a helpdesk handling **100
tickets a day** using the default (Haiku) model, expect roughly
**$3–10 per month**. You can check your own real numbers any time
under **Helpdesk ▸ Reporting ▸ AI Usage Log**.

**Setting a spending limit:** Before you start, it's a good idea to
cap what you could possibly spend. In the Anthropic Console, go to
**Settings ▸ Billing ▸ Usage limits** and set a **Monthly spend
limit** — for the example above, $10–15/month leaves comfortable
headroom. See [api-setup.md](api-setup.md) for more detail, including
how to rotate a key safely.

## FAQ

**Does the AI send emails automatically?**
No. The AI only ever drafts suggestions and replies. A human agent
always reviews and clicks Send — the AI never contacts a customer
directly.

**Is customer data sent to Anthropic?**
Only what's needed for the task at hand — the ticket subject and body
(cut off at 500 characters), and for replies, the last few chatter
messages. Customer email addresses and phone numbers are never
included. Nothing is sent unless a team has AI turned on.

**What if the API key runs out of credits?**
Nothing breaks. AI features fail gracefully — triage, sentiment, and
reply drafting simply stop working (a warning is written to the
server log) while everything else in the helpdesk keeps working
normally. Add credits or fix the key and AI resumes on the next
ticket.

**Which Anthropic models are supported?**
Three: **Claude Haiku** (the default — fastest and cheapest), **Claude
Sonnet** (a step up in quality, higher cost), and **Claude Opus** (the
most capable, highest cost). Pick one under **Settings ▸ General
Settings ▸ Helpdesk AI ▸ AI Model** — it applies to every AI-enabled
team.
