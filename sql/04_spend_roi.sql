-- =====================================================================
-- 04  Joining CRM data to ad spend: cost per MQL / SQL, CAC, ROAS
-- ---------------------------------------------------------------------
-- There is no shared key between the ad platforms and HubSpot except the
-- UTM campaign captured on the contact. UTM values are messy
-- ("LI DACH LeadGen Ebook", "li-dach-abm-enterprise ", "DE_Search_Brand"),
-- so both sides are normalized to the same campaign_key.
--
-- Contacts with UTM campaigns that do not exist in the spend data
-- (newsletter_oct, test_campaign, ...) are listed separately instead of
-- being dropped silently.
--
-- Period: full history (Jan 2025 - Sep 2026). With long B2B sales cycles,
-- a monthly view should compare spend with the pipeline it created later
-- (cohort by lead month), not with deals closed in the same month.
-- =====================================================================

CREATE OR REPLACE TABLE hubspot_demo.campaign_performance AS
WITH spend AS (
  SELECT
    platform,
    REGEXP_REPLACE(LOWER(TRIM(campaign_name)), r'[\s\-]+', '_') AS campaign_key,
    SUM(cost)   AS spend,
    SUM(clicks) AS clicks
  FROM hubspot_demo.ad_spend_daily
  GROUP BY 1, 2
),
crm AS (
  SELECT
    first_touch_campaign            AS campaign_key,
    COUNT(*)                        AS leads,
    COUNTIF(reached_mql)            AS mqls,
    COUNTIF(reached_sql)            AS sqls,
    COUNTIF(reached_opportunity)    AS opportunities
  FROM hubspot_demo.contacts_clean
  WHERE first_touch_campaign IS NOT NULL
  GROUP BY 1
),
won AS (
  SELECT
    campaign                        AS campaign_key,
    COUNTIF(is_won)                 AS won_deals,
    SUM(IF(is_won, amount, 0))      AS won_revenue
  FROM hubspot_demo.deal_attribution
  WHERE campaign IS NOT NULL
  GROUP BY 1
)
SELECT
  s.platform,
  s.campaign_key,
  ROUND(s.spend, 0)                                     AS spend,
  COALESCE(c.leads, 0)                                  AS leads,
  COALESCE(c.mqls, 0)                                   AS mqls,
  COALESCE(c.sqls, 0)                                   AS sqls,
  COALESCE(w.won_deals, 0)                              AS won_deals,
  COALESCE(w.won_revenue, 0)                            AS won_revenue,
  ROUND(SAFE_DIVIDE(s.spend, c.leads), 0)               AS cost_per_lead,
  ROUND(SAFE_DIVIDE(s.spend, c.mqls), 0)                AS cost_per_mql,
  ROUND(SAFE_DIVIDE(s.spend, c.sqls), 0)                AS cost_per_sql,
  ROUND(SAFE_DIVIDE(s.spend, w.won_deals), 0)           AS cac,
  ROUND(SAFE_DIVIDE(w.won_revenue, s.spend), 2)         AS roas
FROM spend s
LEFT JOIN crm c ON c.campaign_key = s.campaign_key
LEFT JOIN won w ON w.campaign_key = s.campaign_key;


-- platform level
SELECT
  platform,
  SUM(spend)       AS spend,
  SUM(leads)       AS leads,
  SUM(mqls)        AS mqls,
  SUM(sqls)        AS sqls,
  SUM(won_deals)   AS won_deals,
  SUM(won_revenue) AS won_revenue,
  ROUND(SAFE_DIVIDE(SUM(spend), SUM(mqls)), 0)          AS cost_per_mql,
  ROUND(SAFE_DIVIDE(SUM(spend), SUM(sqls)), 0)          AS cost_per_sql,
  ROUND(SAFE_DIVIDE(SUM(spend), SUM(won_deals)), 0)     AS cac,
  ROUND(SAFE_DIVIDE(SUM(won_revenue), SUM(spend)), 2)   AS roas
FROM hubspot_demo.campaign_performance
GROUP BY platform
ORDER BY spend DESC;


-- UTM campaigns in the CRM without matching spend (data quality check)
SELECT
  cc.first_touch_campaign AS campaign_key,
  COUNT(*)                AS leads
FROM hubspot_demo.contacts_clean cc
LEFT JOIN (
  SELECT DISTINCT REGEXP_REPLACE(LOWER(TRIM(campaign_name)), r'[\s\-]+', '_') AS campaign_key
  FROM hubspot_demo.ad_spend_daily
) s ON s.campaign_key = cc.first_touch_campaign
WHERE cc.first_touch_campaign IS NOT NULL
  AND s.campaign_key IS NULL
GROUP BY 1
ORDER BY leads DESC;
