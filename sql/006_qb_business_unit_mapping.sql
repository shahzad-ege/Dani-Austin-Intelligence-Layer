-- ============================================================
-- Migration 006: QuickBooks business-unit mapping (Class confirmed unused)
-- ============================================================
--
-- CONFIRMED via direct diagnostic on real transactions: Dani Austin's
-- QuickBooks company does not use Class tracking at all. ClassRef is
-- genuinely absent at the detail, line, AND transaction-header level --
-- checked all three directly, not a parsing gap. This means source/
-- business_unit needs a different mechanism: an account-name lookup table,
-- same pattern as the Domas reference connector's qb_account_subcategory_map.

create table if not exists qb_account_business_unit_map (
  account_name text primary key,
  business_unit text not null,  -- Partnerships | Podcast | Affiliate | Overhead | needs_review
  notes text,
  created_at timestamptz not null default now()
);

alter table qb_account_business_unit_map enable row level security;

-- Seeded from REAL account names observed in qb_da_transaction_lines
-- (queried directly). Income-side mappings are high-confidence; expense-
-- side is conservative -- most G&A costs don't belong to one business unit
-- and are tagged Overhead. Genuinely ambiguous accounts (Agency Fee,
-- Accounts Receivable, the Divi expense line) are 'needs_review' rather
-- than guessed -- especially Divi, which has meant two different things
-- elsewhere in this project (a Slingshot Ventures portfolio company on the
-- EGE hub side, vs. a direct-brand affiliate relationship on Katelyn's
-- revenue sheet) -- do not assume which one without confirming.
insert into qb_account_business_unit_map (account_name, business_unit, notes) values
  ('Brand Partnership', 'Partnerships', null),
  ('Podcast Ad Sponsorship', 'Podcast', null),
  ('Podcast Agency Fee', 'Podcast', null),
  ('Affiliate Commission', 'Affiliate', null),
  ('Amazon Platform Affiliate Revenue', 'Affiliate', 'platform/marketplace affiliate, not direct-brand'),
  ('Facebook Platform Affiliate Commission', 'Affiliate', 'platform/marketplace affiliate, not direct-brand'),
  ('Third Party Affiliate', 'Affiliate', null),
  ('Agency Fee', 'needs_review', 'possibly Podcast (cf. Podcast Agency Fee) but not confirmed -- generic name'),
  ('Accounts Receivable (A/R)', 'needs_review', 'balance-sheet account, not itself a revenue-source indicator'),
  ('Merchant Fee - Paypal', 'needs_review', 'fee/adjustment, not real business-unit revenue'),
  ('Podcast Expenses', 'Podcast', null),
  ('Advertising & Marketing:Brand Promotion - Partnerships', 'Partnerships', null),
  ('Advertising & Marketing:Brand Promotion - Affiliate Purchases', 'Affiliate', null),
  ('Advertising & Marketing:Brand Promotion - Divi Expenses', 'needs_review', 'ambiguous -- "Divi" has meant different things elsewhere in this project; confirm before mapping'),
  ('Advertising & Marketing:Brand Promotion - DA Brand:Clothing', 'Overhead', null),
  ('Advertising & Marketing:Brand Promotion - DA Brand', 'Overhead', null),
  ('Advertising & Marketing:Social Media Ads', 'Overhead', null),
  ('Advertising & Marketing:Giveaway', 'Overhead', null),
  ('Other General & Administrative Expenses:Business Travel - Team:Travel Lodging and Transportation (Team)', 'Overhead', null),
  ('Other General & Administrative Expenses:Business Travel - Dani and Jordan:Travel Lodging and Transportation', 'Overhead', null),
  ('Other General & Administrative Expenses:Business Travel - Team:Travel Meals (Team)', 'Overhead', null),
  ('Other General & Administrative Expenses:Business Travel - Dani and Jordan:Travel Meals', 'Overhead', null),
  ('Other General & Administrative Expenses:Software Expenses', 'Overhead', null),
  ('Other General & Administrative Expenses:Personal Expenses', 'Overhead', null),
  ('Other General & Administrative Expenses:Business Meals and Entertainment:Meals & Entertainment - Dani and Jordan', 'Overhead', null),
  ('Other General & Administrative Expenses:Business Meals and Entertainment:Meals & Entertainment - Team', 'Overhead', null),
  ('Other General & Administrative Expenses:Recruiting Expenses', 'Overhead', null),
  ('Other General & Administrative Expenses:Cosmetics/Glam', 'Overhead', null),
  ('Other General & Administrative Expenses:Merchant & Bank Fees:Merchant Fees - QBO', 'Overhead', null),
  ('Other General & Administrative Expenses:Auto Expense:Lease', 'Overhead', null),
  ('Other General & Administrative Expenses:Charitable Contributions', 'Overhead', null),
  ('Office Expenses:Office Supplies & Shipping', 'Overhead', null),
  ('Relocation Expenses', 'Overhead', null),
  ('Prepaid Expenses', 'Overhead', null),
  ('Owners Distribution', 'Overhead', 'capital-type, not an operating cost'),
  ('Contractors:Stylist Contractors', 'Overhead', null),
  ('Contractors:Stylist Contractors:StyledbyCohen', 'Overhead', null),
  ('Payroll:Health Benefits Expense', 'Overhead', null)
on conflict (account_name) do nothing;
