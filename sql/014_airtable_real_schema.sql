-- ============================================================
-- Migration 014: Airtable connector -- confirmed real schema
-- ============================================================
--
-- Every original field-name guess (from the reporting spec, before the
-- real base could be seen) has now been checked against the actual base
-- schema, fetched via check_airtable_schema.py:
--
--   AIRTABLE_TABLE_NAME: "Master Tracking" (wrong) -> "Partnerships" (confirmed real)
--   invoice_no:          "Invoice #" (wrong)        -> "Invoice Number"
--   deliverable_platform: "Platform" (didn't exist)  -> "Deliverables"
--   client:               "Agency Source" (wrong)    -> "Client" (direct real match)
--   gross_amt / net_amt:  "Gross/Net Amount" (wrong)  -> "Gross Amt" / "Net Amt"
--   month_committed/completed: name was right, but the REAL field type is
--     singleLineText, not a proper date field -- parsing is now defensive
--     (returns null on unparseable text rather than crashing the sync)
--   is_repeat: no real field exists in the base at all. Always null now,
--     not a bug -- genuinely unavailable data, kept in the schema for
--     stability rather than removed.
--
-- New columns added for a real field found that was never in original
-- scope: "In QBO" (checkbox) -- explicit signal for whether a deal has
-- been recorded in QuickBooks, a better reconciliation signal than the
-- previously-unconfirmed doc_num/invoice_no guess-join.
alter table airtable_partnerships add column if not exists in_qbo boolean;
alter table airtable_partnerships add column if not exists invoice_status text;
alter table airtable_partnerships add column if not exists agreement_status text;
