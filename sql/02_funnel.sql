-- =====================================================================
-- 02  Lifecycle funnel: Lead -> MQL -> SQL -> Opportunity -> Customer
-- ---------------------------------------------------------------------
-- Uses contacts_clean (one row per person), so each person counts once.
-- "Reached" flags count a person in every stage up to the furthest one,
-- so stage skipping (e.g. lead -> SQL with no MQL date) does not create
-- holes in the funnel. Recycled leads (reset to "lead") still count for
-- the stages they really reached.
-- Channel = first touch of the person.
-- =====================================================================

CREATE OR REPLACE TABLE hubspot_demo.funnel_by_channel AS
SELECT
  first_touch_channel                                   AS channel,
  COUNT(*)                                              AS leads,
  COUNTIF(reached_mql)                                  AS mqls,
  COUNTIF(reached_sql)                                  AS sqls,
  COUNTIF(reached_opportunity)                          AS opportunities,
  COUNTIF(reached_customer)                             AS customers,
  ROUND(SAFE_DIVIDE(COUNTIF(reached_mql),         COUNT(*)), 3)               AS lead_to_mql,
  ROUND(SAFE_DIVIDE(COUNTIF(reached_sql),         COUNTIF(reached_mql)), 3)   AS mql_to_sql,
  ROUND(SAFE_DIVIDE(COUNTIF(reached_opportunity), COUNTIF(reached_sql)), 3)   AS sql_to_opp,
  ROUND(SAFE_DIVIDE(COUNTIF(reached_customer),    COUNTIF(reached_opportunity)), 3) AS opp_to_customer,
  ROUND(SAFE_DIVIDE(COUNTIF(reached_customer),    COUNT(*)), 3)               AS lead_to_customer
FROM hubspot_demo.contacts_clean
GROUP BY channel;


-- total funnel + average days between stages
SELECT
  COUNT(*)                         AS leads,
  COUNTIF(reached_mql)             AS mqls,
  COUNTIF(reached_sql)             AS sqls,
  COUNTIF(reached_opportunity)     AS opportunities,
  COUNTIF(reached_customer)        AS customers,
  ROUND(AVG(TIMESTAMP_DIFF(mql_date, lead_date, DAY)), 1)              AS avg_days_lead_to_mql,
  ROUND(AVG(TIMESTAMP_DIFF(sql_date, mql_date, DAY)), 1)               AS avg_days_mql_to_sql,
  ROUND(AVG(TIMESTAMP_DIFF(opportunity_date, sql_date, DAY)), 1)       AS avg_days_sql_to_opp,
  ROUND(AVG(TIMESTAMP_DIFF(customer_date, opportunity_date, DAY)), 1)  AS avg_days_opp_to_customer
FROM hubspot_demo.contacts_clean;


SELECT * FROM hubspot_demo.funnel_by_channel ORDER BY leads DESC;
