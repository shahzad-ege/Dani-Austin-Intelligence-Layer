-- ============================================================
-- Migration 019: Katelyn's confirmations on the 3 remaining open items
-- ============================================================
--
-- 1. "Sales" -- confirmed: outdated account, revenue now defined by
--    income streams. Moved (along with "Digital Product Revenue", same
--    reasoning, confirmed earlier) to a new 'Historical-Excluded'
--    business_unit -- deliberately excluded from current totals, not
--    forced into an existing business unit, and distinct from
--    needs_review (a confirmed permanent decision, not a pending one).
--
--    needs_review is now genuinely at ZERO rows for the first time in
--    this project, down from ~8,270 at the start.
insert into qb_account_business_unit_map (account_name, business_unit, notes) values
('Digital Product Revenue', 'Historical-Excluded', 'Katelyn-confirmed (Sep 2026): not used/reported since 2022, predates her tenure -- same treatment as Sales.')
on conflict (account_name) do update set business_unit = excluded.business_unit, notes = excluded.notes;

update qb_da_transaction_lines set source = 'Historical-Excluded'
where account = 'Digital Product Revenue' and source = 'needs_review';

update qb_account_business_unit_map
set notes = 'Katelyn-confirmed (Sep 2026): outdated account, revenue now defined by income streams. Deliberately excluded, not forced into a current business unit.'
where account_name = 'Sales';

-- 2. Prepaid Agency Fee -- classification (Non-Operating) confirmed
--    correct by Katelyn directly. The $13,665 balance itself flagged by
--    her as higher than expected (~$3,000 usual running balance) --
--    investigated: $9,465 corresponds to invoices where every
--    referenced podcast ad-spot date has already aired as of Sep 2026,
--    suggesting these prepaid balances aren't being cleared once spots
--    actually run. No schema/data change made -- pending her own
--    verification, documented as a likely explanation only.

-- 3. AR current position (~$1.1M via da_ar_current_position) --
--    explicitly Katelyn-confirmed as correct (Sep 2026), upgraded from
--    an earlier soft match against her verbal estimate.
