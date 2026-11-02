-- =====================================================================
-- 01  Contact deduplication
-- ---------------------------------------------------------------------
-- Problem: the same person exists several times in the contacts table
--   (upper/lower case, leading/trailing spaces from imports, "+tag" aliases).
--   Counting raw rows inflates lead counts and makes cost per lead look
--   better than it is.
--
-- Approach:
--   1. normalize email -> email_norm
--   2. map every contact record to one person_id
--      (the record that got furthest in the funnel, ties -> oldest record)
--   3. build one row per person ("golden record"):
--        - lifecycle dates: earliest date per stage across all records
--        - first touch: source of the oldest record
--        - last touch:  source of the newest record
--   4. second pass: same first name + last name + company where one record
--      uses a personal email domain -> written to a review table,
--      NOT merged automatically (risk of merging two different people)
--
-- Output tables: contact_person_map, contacts_clean, dedup_review
-- =====================================================================


-- 1 + 2: every contact record -> person_id
CREATE OR REPLACE TABLE hubspot_demo.contact_person_map AS
WITH base AS (
  SELECT
    hs_object_id AS contact_id,
    REGEXP_REPLACE(LOWER(TRIM(email)), r'\+[^@]*@', '@') AS email_norm,
    createdate,
    -- how far did this record get? based on dates, not on the current
    -- lifecyclestage value (recycled leads were reset to "lead")
    CASE
      WHEN hs_lifecyclestage_customer_date               IS NOT NULL THEN 5
      WHEN hs_lifecyclestage_opportunity_date            IS NOT NULL THEN 4
      WHEN hs_lifecyclestage_salesqualifiedlead_date     IS NOT NULL THEN 3
      WHEN hs_lifecyclestage_marketingqualifiedlead_date IS NOT NULL THEN 2
      ELSE 1
    END AS stage_rank
  FROM hubspot_demo.hubspot_contacts
)
SELECT
  contact_id,
  email_norm,
  FIRST_VALUE(contact_id) OVER (
    PARTITION BY email_norm
    ORDER BY stage_rank DESC, createdate
  ) AS person_id
FROM base;


-- 3: one row per person
CREATE OR REPLACE TABLE hubspot_demo.contacts_clean AS
WITH rec AS (
  SELECT
    m.person_id,
    c.*,
    -- clean channel info of each record
    CASE
      WHEN LOWER(TRIM(c.utm_source)) IN ('google', 'adwords')       THEN 'google_ads'
      WHEN LOWER(TRIM(c.utm_source)) IN ('linkedin', 'lnkd')        THEN 'linkedin_ads'
      WHEN LOWER(TRIM(c.utm_source)) IN ('facebook', 'fb', 'meta')  THEN 'meta_ads'
      ELSE LOWER(c.hs_analytics_source)
    END AS channel,
    -- "LI DACH LeadGen Ebook", "li-dach-leadgen-ebook " -> "li_dach_leadgen_ebook"
    REGEXP_REPLACE(LOWER(TRIM(c.utm_campaign)), r'[\s\-]+', '_') AS campaign_key,
    ROW_NUMBER() OVER (PARTITION BY m.person_id ORDER BY c.createdate)      AS rn_first,
    ROW_NUMBER() OVER (PARTITION BY m.person_id ORDER BY c.createdate DESC) AS rn_last
  FROM hubspot_demo.contact_person_map m
  JOIN hubspot_demo.hubspot_contacts c ON c.hs_object_id = m.contact_id
),
dates AS (
  SELECT
    person_id,
    COUNT(*)                                            AS n_records,
    MIN(createdate)                                     AS first_seen_at,
    MIN(hs_lifecyclestage_lead_date)                    AS lead_date,
    MIN(hs_lifecyclestage_marketingqualifiedlead_date)  AS mql_date,
    MIN(hs_lifecyclestage_salesqualifiedlead_date)      AS sql_date,
    MIN(hs_lifecyclestage_opportunity_date)             AS opportunity_date,
    MIN(hs_lifecyclestage_customer_date)                AS customer_date
  FROM rec
  GROUP BY person_id
)
SELECT
  d.person_id,
  p.email_norm,
  keep.firstname,
  keep.lastname,
  keep.jobtitle,
  keep.company,
  d.n_records,
  d.first_seen_at,
  -- "reached stage X" = has a date for X or for any later stage.
  -- Handles skipped stages (e.g. lead -> SQL without an MQL date).
  TRUE                                                                    AS reached_lead,
  COALESCE(d.mql_date, d.sql_date, d.opportunity_date, d.customer_date) IS NOT NULL AS reached_mql,
  COALESCE(d.sql_date, d.opportunity_date, d.customer_date)             IS NOT NULL AS reached_sql,
  COALESCE(d.opportunity_date, d.customer_date)                         IS NOT NULL AS reached_opportunity,
  d.customer_date                                                       IS NOT NULL AS reached_customer,
  d.lead_date, d.mql_date, d.sql_date, d.opportunity_date, d.customer_date,
  f.channel      AS first_touch_channel,
  f.campaign_key AS first_touch_campaign,
  l.channel      AS last_touch_channel,
  l.campaign_key AS last_touch_campaign
FROM dates d
JOIN (SELECT DISTINCT person_id, email_norm FROM hubspot_demo.contact_person_map) p ON p.person_id = d.person_id
JOIN rec keep ON keep.hs_object_id = d.person_id
JOIN rec f    ON f.person_id = d.person_id AND f.rn_first = 1
JOIN rec l    ON l.person_id = d.person_id AND l.rn_last  = 1;


-- 4: second pass -> candidates for manual review
CREATE OR REPLACE TABLE hubspot_demo.dedup_review AS
WITH p AS (
  SELECT
    person_id, email_norm, firstname, lastname, company, first_seen_at,
    REGEXP_EXTRACT(email_norm, r'@(.*)$') AS email_domain
  FROM hubspot_demo.contacts_clean
)
SELECT
  a.person_id   AS person_id_a,
  a.email_norm  AS email_a,
  b.person_id   AS person_id_b,
  b.email_norm  AS email_b,
  a.firstname, a.lastname, a.company
FROM p a
JOIN p b
  ON  LOWER(a.firstname) = LOWER(b.firstname)
  AND LOWER(a.lastname)  = LOWER(b.lastname)
  AND LOWER(a.company)   = LOWER(b.company)
  AND a.first_seen_at < b.first_seen_at
WHERE b.email_domain IN ('gmail.com', 'googlemail.com', 'web.de', 'gmx.de', 'gmx.net', 'outlook.com', 'yahoo.com')
   OR a.email_domain IN ('gmail.com', 'googlemail.com', 'web.de', 'gmx.de', 'gmx.net', 'outlook.com', 'yahoo.com');


-- quick check
SELECT
  (SELECT COUNT(*) FROM hubspot_demo.hubspot_contacts) AS raw_records,
  (SELECT COUNT(*) FROM hubspot_demo.contacts_clean)   AS people_after_dedup,
  (SELECT COUNT(*) FROM hubspot_demo.dedup_review)     AS pairs_for_review;
