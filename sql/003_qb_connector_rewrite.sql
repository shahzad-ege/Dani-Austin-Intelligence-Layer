-- ============================================================
-- Migration 003: QuickBooks connector rewrite — schema changes
-- ============================================================
--
-- Context: the original qb_connector.py used QuickBooks' Reports API,
-- keying each row on `doc_num` (a user-facing, optional "document number"
-- field). A real production run showed this caused 82.7% of real
-- transactions to be silently excluded, since most transaction types
-- (deposits, transfers, many expense categorizations) don't have one.
--
-- The connector was rewritten to use the Accounting API's entity-query
-- approach instead, keyed on QuickBooks' real internal `Id` field (always
-- present). This requires two schema changes:

-- 1. qb_da_transaction_lines needs to support multiple line items per
--    transaction (a single Bill split across several expense accounts,
--    for example) -- the old unique(qb_txn_id) assumed one row per
--    transaction, which would have silently overwritten multi-line
--    transactions down to a single row.
alter table qb_da_transaction_lines drop constraint if exists qb_da_transaction_lines_qb_txn_id_key;

alter table qb_da_transaction_lines add column if not exists qb_line_id text;
alter table qb_da_transaction_lines add column if not exists qb_txn_type text;

alter table qb_da_transaction_lines add constraint qb_da_transaction_lines_txn_line_key unique (qb_txn_id, qb_line_id);

-- 2. QuickBooks rotates the refresh token on every use. Without persisting
--    the newly rotated token somewhere, the .env value goes stale after
--    the first successful run and every scheduled run after that fails.
create table if not exists qb_oauth_credentials (
  id bigint generated always as identity primary key,
  realm_id text not null unique,
  refresh_token text not null,
  updated_at timestamptz not null default now()
);

alter table qb_oauth_credentials enable row level security;

-- Note: the 60 rows previously written by the old Reports-API connector
-- (keyed by doc_num under the old scheme) were deleted from the live
-- project before this migration, since they used an incompatible
-- identifier scheme and would have sat alongside the new correctly-keyed
-- rows as undetected duplicates of the same real transactions.
