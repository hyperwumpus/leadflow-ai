# LeadWolf

**Hunt every lead.** Lead capture, transparent qualification, and follow-up
for local service businesses — white-labeled for any shop.

A customer submits the quote-request form → LeadWolf scores the lead 0–100
with a **visible breakdown** (base + urgency + high-intent keywords),
drafts a personalized response using your business name, and queues the
follow-up. The dashboard tracks every lead through the pipeline.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

- `/` — CRM dashboard (search, filter, stats, follow-up queue, CSV export)
- `/intake` — customer-facing quote form
- `/settings` — set your business name (white-label)
- `/api/leads` — JSON API

## Scoring (transparent)

| Component | Points |
|---|---|
| Base | 40 |
| Urgency ASAP / This week / This month / Just researching | +35 / +25 / +10 / +0 |
| High-intent keywords (quote, estimate, book, schedule, repair, replace, install, emergency, today, broken, leaking) | +5 each, max +25 |

Hot ≥ 80 · Warm ≥ 60 · Normal < 60. Every score stores its breakdown as JSON
so the UI can show exactly why a lead scored the way it did.

## The offer

**"Lead Response Automation"** — every website lead captured, qualified,
responded to fast, and followed up until they book or decline.

- Pilot: $300–$500 setup · Standard: $750–$1,500 · Care plan: $100–$300/mo
