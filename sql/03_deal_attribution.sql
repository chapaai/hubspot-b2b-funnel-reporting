-- =====================================================================
-- 03  Contact-to-deal join and deal attribution
-- ---------------------------------------------------------------------
-- Problem: deals and contacts are many-to-many (hubspot_assoc_deal_contact).
--   A deal with 3 contacts appears 3 times after a plain join, so revenue
--   is counted 3 times and every contact's channel gets full credit.
--
-- Decision: attribute each deal to ONE person = the earliest-created
--   contact on the deal (the first person marketing brought in from that
--   account). Revenue goes to that person's first-touch channel/campaign.
--   Alternatives (decision-maker label, split credit) are possible; the
--   important part is that each deal is counted exactly once.
--
-- Deals without any associated contact (created manually by sales) are
-- kept and labelled "no_contact" instead of silently dropped.
--
-- Output table: deal_attribution (one row per deal)
-- =====================================================================

CREATE OR REPLACE TABLE hubspot_demo.deal_attribution AS
WITH deal_people AS (
  SELECT
    a.deal_id,
    m.person_id,
    ROW_NUMBER() OVER (PARTITION BY a.deal_id ORDER BY c.createdate, c.hs_object_id) AS rn
  FROM hubspot_demo.hubspot_assoc_deal_contact a
  JOIN hubspot_demo.contact_person_map m ON m.contact_id   = a.contact_id   -- duplicates -> one person
  JOIN hubspot_demo.hubspot_contacts   c ON c.hs_object_id = a.contact_id
)
SELECT
  d.hs_object_id                                   AS deal_id,
  d.dealname,
  d.dealstage,
  d.amount,
  d.createdate,
  d.closedate,
  d.dealstage = 'closedwon'                        AS is_won,
  dp.person_id                                     AS attributed_person_id,
  COALESCE(cc.first_touch_channel, 'no_contact')   AS channel,
  cc.first_touch_campaign                          AS campaign
FROM hubspot_demo.hubspot_deals d
LEFT JOIN deal_people dp ON dp.deal_id = d.hs_object_id AND dp.rn = 1
LEFT JOIN hubspot_demo.contacts_clean cc ON cc.person_id = dp.person_id;


-- sanity check: plain join vs. attributed revenue (closed won)
SELECT
  (SELECT SUM(amount) FROM hubspot_demo.hubspot_deals WHERE dealstage = 'closedwon')
    AS revenue_in_deals_table,
  (SELECT SUM(d.amount)
     FROM hubspot_demo.hubspot_deals d
     JOIN hubspot_demo.hubspot_assoc_deal_contact a ON a.deal_id = d.hs_object_id
    WHERE d.dealstage = 'closedwon')
    AS revenue_plain_contact_join,
  (SELECT SUM(amount) FROM hubspot_demo.deal_attribution WHERE is_won)
    AS revenue_attributed;


-- won revenue by channel
SELECT
  channel,
  COUNTIF(is_won)                    AS won_deals,
  SUM(IF(is_won, amount, 0))         AS won_revenue,
  ROUND(AVG(IF(is_won, amount, NULL)), 0) AS avg_won_deal
FROM hubspot_demo.deal_attribution
GROUP BY channel
ORDER BY won_revenue DESC;
