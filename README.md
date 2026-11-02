# B2B funnel & paid media reporting on HubSpot data

A small end-to-end project: HubSpot CRM data + ad spend → deduplicated contacts → lifecycle funnel → deal attribution → cost per MQL/SQL, CAC and ROAS per channel. Everything is in BigQuery SQL.

**About the data:** it's synthetic. I generated a HubSpot-shaped dataset (contacts, companies, deals, association tables, lifecycle stage dates) plus daily Google / LinkedIn / Meta spend, and put in the kind of problems you get with real CRM exports on purpose: duplicates, multi-contact deals, skipped stages, recycled leads, messy UTMs. I also pushed a subset into a real HubSpot account through the API to work with the actual data model (see below).

I used Claude Code as a coding assistant along the way, mostly for boilerplate and syntax. The modelling decisions and checks are mine.

---

## Data

| Table | Rows | What it is |
|---|---|---|
| `hubspot_contacts` | 3,390 | contacts with lifecycle stage dates, original source, UTM fields |
| `hubspot_companies` | 336 | companies (incl. some duplicates) |
| `hubspot_deals` | 271 | deals in the default pipeline, stage entry dates |
| `hubspot_assoc_deal_contact` | 491 | deal ↔ contact associations (many-to-many) |
| `hubspot_assoc_deal_company` | 271 | deal ↔ company |
| `hubspot_assoc_contact_company` | 3,390 | contact ↔ company |
| `ad_spend_daily` | 4,043 | daily spend / clicks per campaign (Google Ads, LinkedIn Ads, Meta) |

Period: Jan 2025 – Sep 2026.

## Pipeline

```
sql/01_contacts_dedup.sql     -> contact_person_map, contacts_clean, dedup_review
sql/02_funnel.sql             -> funnel_by_channel
sql/03_deal_attribution.sql   -> deal_attribution
sql/04_spend_roi.sql          -> campaign_performance
```

Run them in order in BigQuery (dataset `hubspot_demo`).

---

## Problems I ran into and what I decided

### 1. Duplicate contacts
Same person, several records: `Anna.Fischer47@FELSCLOUD.AT`, `" anna.fischer47@felscloud.at "`, `anna.fischer47+webinar@felscloud.at`.

Grouping on the raw email found 18 duplicate groups. After `LOWER` + `TRIM` + removing the `+tag` it was 163 groups, 164 extra records. **3,390 records → 3,226 people.**

Which record to keep was the harder question. The records often came in through different channels, and both first and last touch matter. So instead of picking one row and losing the rest, I build one row per person:
- lifecycle dates: earliest date per stage across all records
- first touch: channel/campaign of the oldest record
- last touch: channel/campaign of the newest record

One thing I tried first and dropped: matching on the part before the `@` only. That merged 16 different "niklas.kaya"s at different companies. Common German names make this a real risk.

Second pass: same first name + last name + company where one side uses a personal domain (gmail, web.de, gmx…). This finds people who signed up once with their work email and once privately. These go to `dedup_review` and are **not merged automatically**. Of the 44 flagged pairs, 43 turned out to be real duplicates and 1 was two different people with the same name at the same company, which is exactly why I didn't auto-merge them.

### 2. Skipped and recycled lifecycle stages
Some contacts jump from lead straight to SQL (no MQL date), some go from opportunity to customer without an SQL date. If you count "has an MQL date", those people drop out of the funnel and conversion rates get weird.

So the funnel uses "reached stage X" = has a date for X **or any later stage**. Recycled leads (reset to `lead` with lead status RECYCLED) still count for the stages they actually reached, based on the dates, not on the current `lifecyclestage` value.

### 3. Contact-to-deal join (fan-out)
Deals and contacts are many-to-many. 154 of the deals have more than one contact. A plain join counts the deal amount once per contact:

| | Closed won revenue |
|---|---|
| deals table | €1,148,600 |
| plain deal → contact join | **€2,444,500** |
| after attribution | €1,148,600 |

The plain join also gives every contact's channel full credit, and it doesn't hit channels evenly: accounts with bigger buying committees get inflated more.

Decision: each deal is attributed to **one** person, the earliest-created contact on the deal (the first person marketing brought in from that account), and the revenue goes to that person's first-touch channel and campaign. A decision-maker or split-credit model would also work. The important part is that every deal is counted exactly once. Deals without any contact (created manually by sales) stay in as `no_contact` (5 won deals, €52k) instead of disappearing.

### 4. Joining CRM to ad spend
There's no shared key except the UTM campaign on the contact, and the UTMs are inconsistent: `LI DACH LeadGen Ebook`, `li-dach-abm-enterprise `, `DE-Search-Generic-CRM`, and `utm_source` values like `google` / `Google` / `adwords`. Both sides get normalized to a `campaign_key` (lowercase, trimmed, spaces and hyphens → `_`).

Leads with UTM campaigns that don't exist in the spend data (`newsletter_oct`, `spring_promo_2025`, `test_campaign`, 92 leads) are listed in a separate check query instead of being silently dropped.

---

## Results

**Funnel (all channels, deduplicated)**

| Lead | MQL | SQL | Opportunity | Customer |
|---|---|---|---|---|
| 3,226 | 1,168 | 444 | 244 | 64 |

Average time: lead → MQL 15 days, MQL → SQL 11, SQL → opp 16, opp → won 66.

**Paid channels (full period)**

| Platform | Spend | MQLs | SQLs | Won deals | Won revenue | Cost / MQL | Cost / SQL | CAC | ROAS |
|---|---|---|---|---|---|---|---|---|---|
| LinkedIn Ads | €327.6k | 267 | 110 | 8 | €44.9k | €1,227 | €2,978 | €40.9k | 0.14 |
| Google Ads | €266.4k | 279 | 121 | 13 | €230.6k | €955 | €2,202 | €20.5k | 0.87 |
| Meta Ads | €13.8k | 40 | 20 | 3 | €49.2k | €344 | €688 | €4.6k | 3.58 |

What I'd take from this:
- LinkedIn has one of the best lead → MQL rates (47%), so in a lead or MQL report it looks great. But on won revenue it's the weakest by far. The deals it brings are smaller (avg ~€11k vs ~€24k on Google). Reporting on MQLs alone would push budget the wrong way.
- Meta looks very efficient but the volume is tiny (3 won deals). I wouldn't move budget on that without more data.
- ROAS here is first-year deal amount over spend. For a B2B subscription you'd look at it with LTV or at least annual contract value, and with a cohort view (spend in month X vs. pipeline created from those leads later), not same-month numbers.

Full tables: [`results/funnel_by_channel.csv`](results/funnel_by_channel.csv), [`results/campaign_performance.csv`](results/campaign_performance.csv).

---

## HubSpot API

`python/push_to_hubspot.py` loads a subset (40 companies, 422 contacts, 64 deals) into a free HubSpot account and creates the associations, using the CRM v3 batch endpoints and the v4 associations API with a service key (on a new account HubSpot no longer offers private apps, service keys replaced them).

Things I noticed:
- HubSpot treats email as unique (case-insensitive), so a batch with `anna@x.de` and `ANNA@x.de` fails as a whole. The script dedups before sending.
- Batch results don't come back in input order, so records are matched back by a unique property (email / domain / deal name) to build the demo-id → HubSpot-id mapping.
- A new portal comes with 2 sample contacts. Small thing, but it's the kind of record that has to be filtered out or counts don't reconcile.
- 64 deals → 96 deal-contact associations. You can see the multi-contact deals directly on the deal record.

## If this were a real client setup

- Pull HubSpot incrementally (`hs_lastmodifieddate`) and handle merged/deleted records separately, since they don't show up as modified.
- Keep daily snapshots or property history. HubSpot only stores the current state, so "what did pipeline look like on Sep 1" isn't answerable otherwise.
- A campaign mapping table maintained with the channel managers, instead of regex rules only.
- Reconciliation checks: spend in the warehouse vs. platform UI per day, so reporting issues get caught before a client sees them.
- Reporting layer in Google Sheets via Connected Sheets, or Looker Studio.

## Files

```
data/      CSVs (generated by python/generate_hubspot_data.py)
python/    data generator, HubSpot push script
sql/       BigQuery SQL, run in order
results/   output tables
```
