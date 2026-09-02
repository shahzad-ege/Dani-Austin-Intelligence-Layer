-- ============================================================
-- Migration 016: Scenario reference data (SCENARIO 1/2/3 + CASH variants)
-- ============================================================
--
-- Imported at explicit user request, for comparison against real-time
-- data sources -- NOT a live data source in its own right.
--
-- CORRECTION to an earlier assessment in this project: these 6 tabs were
-- first assumed to be stale, identical duplicate tabs based on a narrow
-- sample (first ~5 rows matched across all 3). A fuller check (50 rows x
-- 20 columns) found they genuinely differ from each other in forward-
-- looking budget assumptions -- e.g. annual Total Income budget ranges
-- $5.92M (Scenario 2/3) to $7.84M (Scenario 1).
--
-- Real data-quality issue confirmed, not guessed around: the tabs' own
-- date headers say 2024, but values for already-elapsed months match
-- 2026 actuals in da_budget_actual_pnl exactly. The date labels are very
-- likely a leftover template error. period_label is stored AS SHOWN IN
-- THE SOURCE rather than "corrected" to what might be the true intended
-- calendar date, since a wrong guess would be worse than transparency
-- about the ambiguity.

create table if not exists da_scenario_pnl_reference (
  id bigint generated always as identity primary key,
  scenario_name text not null,
  line_item text not null,
  period_label text not null,
  budget numeric(14,2),
  actual numeric(14,2),
  variance numeric(14,2),
  created_at timestamptz not null default now(),
  unique (scenario_name, line_item, period_label)
);
alter table da_scenario_pnl_reference enable row level security;

create table if not exists da_scenario_cash_reference (
  id bigint generated always as identity primary key,
  scenario_name text not null,
  line_item text not null,
  period_label text not null,
  value numeric(14,2),
  created_at timestamptz not null default now(),
  unique (scenario_name, line_item, period_label)
);
alter table da_scenario_cash_reference enable row level security;

-- Final counts: 582 PNL reference rows (SCENARIO 1: 202, SCENARIO 2: 190,
-- SCENARIO 3: 190), 330 CASH reference rows (110 each).
