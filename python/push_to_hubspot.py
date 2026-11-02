"""
Push a small subset of the demo data into a real HubSpot account via the CRM API.

Usage (Cloud Shell, inside the folder with the CSV files):
    export HUBSPOT_TOKEN="your-service-key"
    python3 push_to_hubspot.py --dry-run     # only shows what would be sent
    (run it inside the data/ folder)
    python3 push_to_hubspot.py               # really sends it

What it does:
  1. picks 40 companies and their contacts and deals from the CSVs
  2. creates them in HubSpot with batch endpoints (max 100 records per call)
  3. links them to each other with associations (contact-company, deal-contact, deal-company)
  4. saves the mapping "demo id -> HubSpot id" to hubspot_id_map.csv
"""
import os, sys, time, json
import pandas as pd
import requests

DRY = "--dry-run" in sys.argv
N_COMPANIES = 40
BASE = "https://api.hubapi.com"
TOKEN = os.environ.get("HUBSPOT_TOKEN")
if not TOKEN and not DRY:
    sys.exit("Set the token first:  export HUBSPOT_TOKEN='...'")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def call(method, path, body=None):
    """One API call with a simple retry when HubSpot says 'too many requests' (429)."""
    for attempt in range(5):
        r = requests.request(method, BASE + path, headers=HEADERS, data=json.dumps(body) if body else None)
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1)); continue
        if r.status_code >= 400:
            print(f"  ERROR {r.status_code} on {path}:\n  {r.text[:800]}")
            r.raise_for_status()
        time.sleep(0.15)  # stay well below the free-tier rate limit
        return r.json() if r.text else {}
    raise RuntimeError("Rate limited too many times")


def chunks(lst, n=100):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def iso(ts):
    return None if pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(props):
    return {k: v for k, v in props.items() if v is not None and not (isinstance(v, float) and pd.isna(v))}


# ---------- 1. pick the subset ----------
comp = pd.read_csv("hubspot_companies.csv")
cont = pd.read_csv("hubspot_contacts.csv", keep_default_na=False, na_values=[""])
deal = pd.read_csv("hubspot_deals.csv")
a_cc = pd.read_csv("hubspot_assoc_contact_company.csv")
a_dc = pd.read_csv("hubspot_assoc_deal_contact.csv")
a_dco = pd.read_csv("hubspot_assoc_deal_company.csv")

# companies that have deals, real ones only (with a domain), first 40
comp = comp[comp.domain.notna() & ~comp.domain.str.startswith(("www.", "app."))]
with_deals = comp[comp.hs_object_id.isin(a_dco.company_id)]
comp = with_deals.head(N_COMPANIES)

cont = cont[cont.hs_object_id.isin(a_cc[a_cc.company_id.isin(comp.hs_object_id)].contact_id)].copy()
# HubSpot treats email as a unique key (case-insensitive), so a batch with two
# "anna@x.de" / "ANNA@x.de" records would fail. Keep one record per normalized email.
cont["email_clean"] = cont.email.str.strip().str.lower()
cont = cont.drop_duplicates("email_clean")

deal = deal[deal.hs_object_id.isin(a_dco[a_dco.company_id.isin(comp.hs_object_id)].deal_id)].copy()

print(f"Subset: {len(comp)} companies, {len(cont)} contacts, {len(deal)} deals")

# ---------- 2. create records ----------
id_map = []  # (object, demo_id, hubspot_id)


def create(object_type, rows, key_prop, key_col):
    """Batch-create records. HubSpot does not guarantee result order, so we match
    the returned records back to our rows by a unique property (email/domain/dealname)."""
    lookup = {}
    for batch in chunks(rows):
        body = {"inputs": [{"properties": p} for _, p in batch]}
        if DRY:
            print(f"  [dry-run] would create {len(batch)} {object_type}, e.g. {batch[0][1]}")
            for demo_id, p in batch:
                lookup[demo_id] = f"dry-{demo_id}"
            continue
        res = call("POST", f"/crm/v3/objects/{object_type}/batch/create", body)
        by_key = {r["properties"][key_prop].lower(): r["id"] for r in res["results"]}
        for demo_id, p in batch:
            lookup[demo_id] = by_key[p[key_prop].lower()]
        print(f"  created {len(batch)} {object_type}")
    for demo_id, hs_id in lookup.items():
        id_map.append((object_type, demo_id, hs_id))
    return lookup


print("\nCompanies")
comp_ids = create("companies", [
    (r.hs_object_id, clean({"name": r["name"], "domain": r.domain, "country": r.country,
                             "numberofemployees": str(int(r.numberofemployees))}))
    for _, r in comp.iterrows()], "domain", "domain")

print("\nContacts")
cont_ids = create("contacts", [
    (r.hs_object_id, clean({"email": r.email_clean, "firstname": r.firstname, "lastname": r.lastname,
                             "jobtitle": r.jobtitle, "company": r.company, "lifecyclestage": r.lifecyclestage}))
    for _, r in cont.iterrows()], "email", "email_clean")

print("\nDeals")
deal_ids = create("deals", [
    (r.hs_object_id, clean({"dealname": f"{r.dealname} (#{r.hs_object_id})",  # unique name for matching
                             "amount": str(r.amount), "pipeline": "default", "dealstage": r.dealstage,
                             "closedate": iso(r.closedate)}))
    for _, r in deal.iterrows()], "dealname", "dealname")

# ---------- 3. associations ----------
def associate(from_type, to_type, pairs, from_ids, to_ids):
    pairs = [(from_ids[f], to_ids[t]) for f, t in pairs if f in from_ids and t in to_ids]
    for batch in chunks(pairs):
        body = {"inputs": [{"from": {"id": f}, "to": {"id": t}} for f, t in batch]}
        if DRY:
            print(f"  [dry-run] would link {len(batch)} {from_type} -> {to_type}")
            continue
        call("POST", f"/crm/v4/associations/{from_type}/{to_type}/batch/associate/default", body)
        print(f"  linked {len(batch)} {from_type} -> {to_type}")


print("\nAssociations")
associate("contacts", "companies", a_cc[["contact_id", "company_id"]].itertuples(index=False), cont_ids, comp_ids)
associate("deals", "contacts", a_dc[["deal_id", "contact_id"]].itertuples(index=False), deal_ids, cont_ids)
associate("deals", "companies", a_dco[["deal_id", "company_id"]].itertuples(index=False), deal_ids, comp_ids)

pd.DataFrame(id_map, columns=["object", "demo_id", "hubspot_id"]).to_csv("hubspot_id_map.csv", index=False)
print("\nDone. Mapping saved to hubspot_id_map.csv")
