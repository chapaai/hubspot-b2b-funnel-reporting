"""
Synthetic HubSpot-style B2B dataset (as if synced to BigQuery via Fivetran/API).
Deliberately contains real-world data problems:
  1. contact-to-deal fan-out (deals with multiple contacts)
  2. lifecycle stage skipping (missing MQL dates)
  3. duplicate contacts & companies
  4. recycled leads
  5. inconsistent UTM / campaign naming vs. ad spend
  6. deals without any associated contact
"""
import numpy as np, pandas as pd, random, string, os
from datetime import datetime, timedelta

rng = np.random.default_rng(42); random.seed(42)
OUT = "data"; os.makedirs(OUT, exist_ok=True)
START, END = datetime(2025, 1, 1), datetime(2026, 9, 30)
DAYS = (END - START).days

def rdate(lo=START, hi=END):
    return lo + timedelta(seconds=int(rng.integers(0, max(1, int((hi - lo).total_seconds())))))

# ---------------- campaigns (spend side names = "truth") ----------------
CAMPAIGNS = {
    "google_ads":   ["DE_Search_Brand", "DE_Search_Generic_CRM", "DACH_Search_Competitor"],
    "linkedin_ads": ["LI_DACH_ABM_Enterprise", "LI_DACH_LeadGen_Ebook", "LI_DACH_Retargeting"],
    "meta_ads":     ["FB_DE_Webinar_Q"],
}
# how the same campaign shows up in UTMs (messy)
UTM_VARIANTS = {
    "DE_Search_Brand": ["de_search_brand", "DE_Search_Brand", "de-search-brand"],
    "DE_Search_Generic_CRM": ["de_search_generic_crm", "DE-Search-Generic-CRM"],
    "DACH_Search_Competitor": ["dach_search_competitor", "DACH_Search_Competitor "],
    "LI_DACH_ABM_Enterprise": ["li_dach_abm_enterprise", "LI_DACH_ABM_Enterprise", "li-dach-abm-enterprise "],
    "LI_DACH_LeadGen_Ebook": ["li_dach_leadgen_ebook", "LI DACH LeadGen Ebook"],
    "LI_DACH_Retargeting": ["li_dach_retargeting"],
    "FB_DE_Webinar_Q": ["fb_de_webinar_q", "FB_DE_Webinar_Q"],
}
UTM_SOURCE = {"google_ads": ["google", "Google", "adwords"], "linkedin_ads": ["linkedin", "LinkedIn", "lnkd"], "meta_ads": ["facebook", "fb", "meta"]}
ORPHAN_UTMS = ["spring_promo_2025", "test_campaign", "newsletter_oct"]  # in CRM, no spend

# ---------------- companies ----------------
PREFIX = ["Nord", "Rhein", "Alpen", "Spree", "Isar", "Elb", "Main", "Saar", "Ost", "West", "Hansa", "Berg", "Tal", "Stern", "Blau",
          "Sued", "Wald", "Feld", "Brueck", "Hafen", "Licht", "Kraft", "Fels", "Weser", "Neckar", "Mosel", "Donau", "Inn", "Ruhr", "Harz"]
SUFFIX = ["Logistik", "Software", "Systems", "Industrie", "Data", "Solutions", "Technik", "Media", "Finance", "Energie", "Health", "Retail", "Robotics", "Cloud"]
FORM = ["GmbH", "AG", "GmbH & Co. KG", "SE"]
INDUSTRY = ["COMPUTER_SOFTWARE", "LOGISTICS_AND_SUPPLY_CHAIN", "MACHINERY", "FINANCIAL_SERVICES", "HOSPITAL_HEALTH_CARE", "RETAIL", "RENEWABLES_ENVIRONMENT"]
COUNTRY = ["Germany"] * 7 + ["Austria"] * 2 + ["Switzerland"]

companies, seen = [], set()
cid = 100000
while len(companies) < 320:
    base = f"{random.choice(PREFIX)}{random.choice(SUFFIX)}"
    if base in seen: continue
    seen.add(base)
    dom = base.lower() + random.choice([".de", ".de", ".com", ".at", ".ch"])
    companies.append(dict(hs_object_id=cid, name=f"{base} {random.choice(FORM)}", domain=dom,
                          industry=random.choice(INDUSTRY), country=random.choice(COUNTRY),
                          numberofemployees=int(rng.choice([25, 60, 150, 400, 900, 2500, 8000])),
                          createdate=rdate(START, END - timedelta(days=30)), _dup_of=None))
    cid += 1

# duplicate companies (~5%): www-prefix, subdomain, missing domain, name variants
dup_companies = []
for c in random.sample(companies, 16):
    kind = random.choice(["www", "sub", "nodomain", "name"])
    d = dict(c); d["hs_object_id"] = cid; cid += 1
    d["createdate"] = c["createdate"] + timedelta(days=int(rng.integers(5, 200)))
    if kind == "www": d["domain"] = "www." + c["domain"]
    elif kind == "sub": d["domain"] = "app." + c["domain"]
    elif kind == "nodomain": d["domain"] = None
    else: d["name"] = c["name"].split(" ")[0].upper()
    d["_dup_of"] = c["hs_object_id"]; dup_companies.append(d)
companies_all = companies + dup_companies

# ---------------- contacts ----------------
FIRST = ["Lukas", "Anna", "Jonas", "Lea", "Felix", "Marie", "Paul", "Laura", "Max", "Sophie", "Tim", "Julia", "Jan", "Lena", "Moritz", "Hannah", "Ben", "Clara", "Niklas", "Sarah", "Elif", "Can", "Mehmet", "Ayse"]
LAST = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Neumann", "Yilmaz", "Kaya", "Braun", "Zimmermann", "Krüger"]
TITLES = ["Head of Marketing", "CMO", "Marketing Manager", "CFO", "Head of Sales", "IT Director", "Operations Manager", "CEO", "Procurement Lead"]

SOURCES = [  # (hs_analytics_source, platform, weight, p_mql)
    ("PAID_SEARCH", "google_ads", 0.24, 0.42),
    ("PAID_SOCIAL", "linkedin_ads", 0.20, 0.47),
    ("PAID_SOCIAL", "meta_ads", 0.06, 0.25),
    ("ORGANIC_SEARCH", None, 0.20, 0.33),
    ("DIRECT_TRAFFIC", None, 0.12, 0.28),
    ("REFERRALS", None, 0.08, 0.40),
    ("EMAIL_MARKETING", None, 0.05, 0.30),
    ("OFFLINE", None, 0.05, 0.50),
]
sw = np.array([s[2] for s in SOURCES]); sw /= sw.sum()

def ascii_(s): return s.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")

contacts, ctc_assoc = [], []
ctid = 500000
for i in range(3200):
    comp = random.choice(companies)
    # some contacts land on the duplicate company record
    dups_of_comp = [d for d in dup_companies if d["_dup_of"] == comp["hs_object_id"]]
    comp_rec = random.choice(dups_of_comp) if dups_of_comp and rng.random() < 0.4 else comp
    fn, ln = random.choice(FIRST), random.choice(LAST)
    s = SOURCES[rng.choice(len(SOURCES), p=sw)]
    lead_dt = rdate(max(START, comp["createdate"] - timedelta(days=60)), END)
    utm_src = utm_camp = None
    if s[1]:
        camp = random.choice(CAMPAIGNS[s[1]])
        utm_src = random.choice(UTM_SOURCE[s[1]])
        utm_camp = random.choice(UTM_VARIANTS[camp])
        if rng.random() < 0.06: utm_camp = random.choice(ORPHAN_UTMS)
        if rng.random() < 0.05: utm_camp = None  # lost UTM
    # funnel progression
    def nxt(d, lo, hi): return d + timedelta(days=int(rng.integers(lo, hi)), hours=int(rng.integers(0, 23)))
    mql = sql = opp = cust = None
    if rng.random() < s[3]:
        mql = nxt(lead_dt, 0, 30)
        if rng.random() < 0.40:
            sql = nxt(mql, 1, 21)
            if rng.random() < 0.55:
                opp = nxt(sql, 2, 30)
                if rng.random() < 0.32:
                    cust = nxt(opp, 20, 120)
    dates = dict(lead=lead_dt, mql=mql, sql=sql, opp=opp, cust=cust)
    for k in list(dates):
        if dates[k] and dates[k] > END: 
            # cut future stages
            for kk in ["lead", "mql", "sql", "opp", "cust"][["lead", "mql", "sql", "opp", "cust"].index(k):]:
                dates[kk] = None
            break
    # PROBLEM: stage skipping -> MQL date missing for sales-sourced / fast-tracked
    skipped = False
    if dates["sql"] and rng.random() < 0.10: dates["mql"] = None; skipped = True
    if dates["cust"] and rng.random() < 0.08: dates["sql"] = None; skipped = True
    stage = "customer" if dates["cust"] else "opportunity" if dates["opp"] else "salesqualifiedlead" if dates["sql"] else "marketingqualifiedlead" if dates["mql"] else "lead"
    lead_status = None
    # PROBLEM: recycled leads (were MQL/SQL, went cold, reset to lead)
    if stage in ("marketingqualifiedlead", "salesqualifiedlead") and rng.random() < 0.12:
        stage = "lead"; lead_status = "RECYCLED"
    dom = (comp["domain"] or "example.de")
    email = f"{ascii_(fn)}.{ascii_(ln)}{rng.integers(1, 99) if rng.random() < 0.2 else ''}@{dom}"
    rec = dict(hs_object_id=ctid, email=email, firstname=fn, lastname=ln, jobtitle=random.choice(TITLES),
               company=comp_rec["name"], lifecyclestage=stage, hs_lead_status=lead_status,
               hs_analytics_source=s[0], utm_source=utm_src, utm_campaign=utm_camp,
               createdate=dates["lead"],
               hs_lifecyclestage_lead_date=dates["lead"],
               hs_lifecyclestage_marketingqualifiedlead_date=dates["mql"],
               hs_lifecyclestage_salesqualifiedlead_date=dates["sql"],
               hs_lifecyclestage_opportunity_date=dates["opp"],
               hs_lifecyclestage_customer_date=dates["cust"],
               _company_true=comp["hs_object_id"], _company_rec=comp_rec["hs_object_id"], _dup_of=None, _skipped=skipped)
    contacts.append(rec)
    ctc_assoc.append(dict(contact_id=ctid, company_id=comp_rec["hs_object_id"]))
    ctid += 1

# PROBLEM: duplicate contacts (~6%)
dup_contacts = []
for c in random.sample(contacts, 190):
    d = dict(c); d["hs_object_id"] = ctid; ctid += 1
    kind = random.choice(["case", "personal", "typo", "plus"])
    local, dom = c["email"].split("@")
    if kind == "case": d["email"] = c["email"].title().replace("@", "@").replace(dom.title(), dom.upper())
    elif kind == "personal": d["email"] = f"{local}@{random.choice(['gmail.com', 'web.de', 'gmx.de', 'googlemail.com'])}"
    elif kind == "typo": d["email"] = f" {c['email']} "  # whitespace from import
    else: d["email"] = f"{local}+webinar@{dom}"
    later = c["createdate"] + timedelta(days=int(rng.integers(3, 300)))
    if later > END: later = END - timedelta(days=1)
    d.update(createdate=later, hs_lifecyclestage_lead_date=later, lifecyclestage="lead", hs_lead_status=None,
             hs_lifecyclestage_marketingqualifiedlead_date=None, hs_lifecyclestage_salesqualifiedlead_date=None,
             hs_lifecyclestage_opportunity_date=None, hs_lifecyclestage_customer_date=None, _dup_of=c["hs_object_id"])
    # dup often comes in through a different channel
    if rng.random() < 0.5:
        s = SOURCES[rng.choice(len(SOURCES), p=sw)]
        d["hs_analytics_source"] = s[0]
        if s[1]:
            camp = random.choice(CAMPAIGNS[s[1]])
            d["utm_source"], d["utm_campaign"] = random.choice(UTM_SOURCE[s[1]]), random.choice(UTM_VARIANTS[camp])
        else:
            d["utm_source"] = d["utm_campaign"] = None
    dup_contacts.append(d)
    ctc_assoc.append(dict(contact_id=d["hs_object_id"], company_id=c["_company_rec"]))
contacts_all = contacts + dup_contacts

# ---------------- deals ----------------
STAGES = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled", "decisionmakerboughtin", "contractsent", "closedwon", "closedlost"]
deals, dc_assoc, dco_assoc = [], [], []
did = 900000
opp_contacts = [c for c in contacts if c["hs_lifecyclestage_opportunity_date"]]
used = set()
for c in opp_contacts:
    if c["hs_object_id"] in used: continue
    created = c["hs_lifecyclestage_opportunity_date"]
    won = c["hs_lifecyclestage_customer_date"] is not None
    # buying committee: other contacts from same company
    peers = [p for p in contacts if p["_company_true"] == c["_company_true"] and p["hs_object_id"] != c["hs_object_id"]
             and p["createdate"] <= created + timedelta(days=30)]
    n_extra = int(rng.choice([0, 0, 1, 1, 2, 3]))
    committee = [c] + random.sample(peers, min(n_extra, len(peers)))
    for p in committee: used.add(p["hs_object_id"])
    size = next(x for x in companies if x["hs_object_id"] == c["_company_true"])["numberofemployees"]
    amount = round(float(rng.lognormal(np.log(4000 + size * 6), 0.5)), -2)
    path = [created]
    for _ in range(4): path.append(path[-1] + timedelta(days=int(rng.integers(2, 25))))
    if won:
        close = c["hs_lifecyclestage_customer_date"]; stage = "closedwon"
    else:
        age = (END - created).days
        if age > 90 or rng.random() < 0.5:
            close = created + timedelta(days=int(rng.integers(15, 100))); stage = "closedlost"
            if close > END: close, stage = None, random.choice(STAGES[:5])
        else:
            close, stage = None, random.choice(STAGES[:5])
    n_reached = 5 if stage in ("closedwon", "closedlost") else STAGES.index(stage) + 1
    if stage == "closedlost": n_reached = int(rng.integers(1, 6))
    d = dict(hs_object_id=did, dealname=f"{next(x for x in companies if x['hs_object_id']==c['_company_true'])['name'].split(' ')[0]} - New Business",
             pipeline="default", dealstage=stage, amount=amount, deal_currency_code="EUR",
             createdate=created, closedate=close, hs_is_closed_won=stage == "closedwon")
    for j, st in enumerate(STAGES[:5]):
        d[f"hs_date_entered_{st}"] = path[j] if j < n_reached and path[j] <= END else None
    d["hs_date_entered_closedwon"] = close if stage == "closedwon" else None
    d["hs_date_entered_closedlost"] = close if stage == "closedlost" else None
    deals.append(d)
    for k, p in enumerate(committee):
        dc_assoc.append(dict(deal_id=did, contact_id=p["hs_object_id"],
                             association_label="Decision Maker" if k == 0 and rng.random() < 0.6 else None))
    dco_assoc.append(dict(deal_id=did, company_id=c["_company_rec"]))
    did += 1

# PROBLEM: deals created manually by sales, no contact association
no_contact_deals = 0
for _ in range(35):
    comp = random.choice(companies)
    created = rdate()
    stage = random.choice(STAGES)
    close = created + timedelta(days=int(rng.integers(20, 90))) if stage in ("closedwon", "closedlost") else None
    if close and close > END: close, stage = None, "contractsent"
    d = dict(hs_object_id=did, dealname=f"{comp['name'].split(' ')[0]} - Upsell" if rng.random() < 0.5 else f"{comp['name'].split(' ')[0]} - Inbound call",
             pipeline="default", dealstage=stage, amount=round(float(rng.lognormal(np.log(8000), 0.6)), -2),
             deal_currency_code="EUR", createdate=created, closedate=close, hs_is_closed_won=stage == "closedwon")
    for st in STAGES[:5]: d[f"hs_date_entered_{st}"] = None
    d["hs_date_entered_closedwon"] = close if stage == "closedwon" else None
    d["hs_date_entered_closedlost"] = close if stage == "closedlost" else None
    deals.append(d); dco_assoc.append(dict(deal_id=did, company_id=comp["hs_object_id"]))
    did += 1; no_contact_deals += 1

# ---------------- ad spend ----------------
spend_rows = []
BASE = {"DE_Search_Brand": 90, "DE_Search_Generic_CRM": 260, "DACH_Search_Competitor": 140,
        "LI_DACH_ABM_Enterprise": 320, "LI_DACH_LeadGen_Ebook": 210, "LI_DACH_Retargeting": 80, "FB_DE_Webinar_Q": 70}
for plat, camps in CAMPAIGNS.items():
    for camp in camps:
        for dd in range(DAYS + 1):
            day = START + timedelta(days=dd)
            if camp == "FB_DE_Webinar_Q" and day.month % 3 != 1: continue  # flighted
            season = 1 + 0.25 * np.sin(2 * np.pi * day.timetuple().tm_yday / 365) - (0.35 if day.month in (8, 12) else 0)
            wk = 0.55 if day.weekday() >= 5 else 1.0
            cost = max(0, BASE[camp] * season * wk * rng.normal(1, 0.15))
            cpc = {"google_ads": 3.2, "linkedin_ads": 7.5, "meta_ads": 1.1}[plat] * rng.normal(1, 0.1)
            clicks = int(cost / cpc); impr = int(clicks / max(0.004, rng.normal({"google_ads": 0.045, "linkedin_ads": 0.006, "meta_ads": 0.01}[plat], 0.002)))
            spend_rows.append(dict(date=day.date(), platform=plat, account_currency="EUR",
                                   campaign_name=camp, impressions=impr, clicks=clicks, cost=round(cost, 2)))

# ---------------- write ----------------
def clean(rows):
    df = pd.DataFrame(rows)
    return df[[c for c in df.columns if not c.startswith("_")]]

clean(companies_all).sort_values("hs_object_id").to_csv(f"{OUT}/hubspot_companies.csv", index=False)
clean(contacts_all).sample(frac=1, random_state=1).to_csv(f"{OUT}/hubspot_contacts.csv", index=False)
clean(deals).to_csv(f"{OUT}/hubspot_deals.csv", index=False)
pd.DataFrame(ctc_assoc).to_csv(f"{OUT}/hubspot_assoc_contact_company.csv", index=False)
pd.DataFrame(dc_assoc).to_csv(f"{OUT}/hubspot_assoc_deal_contact.csv", index=False)
pd.DataFrame(dco_assoc).to_csv(f"{OUT}/hubspot_assoc_deal_company.csv", index=False)
pd.DataFrame(spend_rows).to_csv(f"{OUT}/ad_spend_daily.csv", index=False)

# ---------------- answer key (hidden truth, for checking your SQL) ----------------
dc = pd.DataFrame(dc_assoc)
multi = (dc.groupby("deal_id").size() > 1).sum()
true = pd.DataFrame(contacts)
key = f"""# Answer key — injected problems (check your SQL against these)

- Companies: {len(companies)} real, {len(dup_companies)} duplicates (www./app. subdomains, missing domain, name variants) → total rows {len(companies_all)}
- Contacts: {len(contacts)} real people, {len(dup_contacts)} duplicate records (case, whitespace, +alias, personal email) → total rows {len(contacts_all)}
- Contacts with a skipped lifecycle stage (MQL or SQL date missing but later stage present): {int(true['_skipped'].sum())}
- Recycled leads (lifecyclestage=lead, hs_lead_status=RECYCLED, but MQL date present): {int((true['hs_lead_status']=='RECYCLED').sum())}
- Deals: {len(deals)} total, {multi} with >1 associated contact (fan-out risk), {no_contact_deals} with no contact at all
- Closed won deals: {sum(d['dealstage']=='closedwon' for d in deals)}, closed won revenue: {sum(d['amount'] for d in deals if d['dealstage']=='closedwon'):,.0f} EUR
- Naive contact-join revenue would be inflated to: {pd.DataFrame(deals).merge(dc, left_on='hs_object_id', right_on='deal_id').query("dealstage=='closedwon'")['amount'].sum():,.0f} EUR
- UTM campaigns: spend side has {sum(len(v) for v in CAMPAIGNS.values())} clean names; CRM side has case/space/hyphen variants + orphan UTMs {ORPHAN_UTMS} + some NULLs
- Total ad spend: {pd.DataFrame(spend_rows)['cost'].sum():,.0f} EUR
"""
open(f"{OUT}/ground_truth.md", "w").write(key)
print(key)
