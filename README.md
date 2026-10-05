# LeadFlow AI

A sellable MVP for local service businesses: capture website leads, score/qualify them, generate a response draft, track pipeline status, and queue follow-ups.

## What it does now
- Public quote-request form
- Automatic lead scoring (0-100)
- Hot/warm/normal qualification
- Automatic lead summary
- Suggested customer response
- CRM-style lead dashboard
- Lead statuses: New → Contacted → Qualified → Appointment Set → Won/Lost
- Follow-up due queue
- Activity log
- JSON API at `/api/leads`
- SQLite database (no setup required)

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000

## The offer you can sell

**"Lead Response Automation"**

> I install a system that makes sure every website lead is captured, immediately qualified, receives a fast response, and gets followed up with until they book or decline.

Suggested first-client pricing:
- Pilot: $300-$500 setup
- Standard: $750-$1,500 setup
- Ongoing support/hosting: $100-$300/month

Do not lead with "AI." Lead with the business outcome: fewer missed leads and faster follow-up.

## Best first niches
Start with businesses where one missed lead can be worth hundreds or thousands of dollars:
- HVAC
- plumbing
- roofing
- landscaping
- remodelers / contractors
- auto repair
- cleaning companies
- photographers

## Production upgrade path
The MVP deliberately works without paid APIs. After getting a prospect interested, add only the integrations that client needs.

1. **Twilio**: immediate SMS + missed-call text-back
2. **Email**: Gmail, SendGrid, or Resend
3. **Calendar**: Google Calendar / Calendly
4. **CRM**: HubSpot / GoHighLevel / client CRM
5. **OpenAI API**: richer qualification, extraction, personalization
6. **Webhook endpoint**: ingest Facebook Lead Ads / Google Ads / website forms

## First real automation workflow

```text
Lead submits form
    ↓
Store lead
    ↓
AI/logic scores urgency + intent
    ↓
Owner gets notification
    ↓
Customer gets immediate response
    ↓
Booking link sent
    ↓
No response? Follow up after 24h
    ↓
Still no response? Follow up after 72h
    ↓
Appointment booked → update CRM
    ↓
Job completed → request Google review
```

## How to demo it to a prospect
1. Change the demo wording to their company/service.
2. Enter a fake high-intent lead in front of them.
3. Show the lead appear in the dashboard instantly.
4. Show the qualification score and drafted response.
5. Explain that the production version sends the text/email automatically.
6. Ask: **"How many leads do you think go cold because nobody follows up fast enough?"**

## Important
This is the validation MVP. Before turning it into a broad SaaS, sell it to 1-3 real businesses and learn which integrations they will actually pay for.
