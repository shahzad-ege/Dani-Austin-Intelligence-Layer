"""
models.py — Universal record schemas for the Dani Austin spoke.

Each dataclass mirrors a table already created in the Dani Austin Supabase
project. Keeping these in one place means every connector produces records
in a shape writer.py can upsert without special-casing.
"""

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Optional


@dataclass
class QBTransactionLine:
    qb_txn_id: str  # QuickBooks' real internal Id -- always present, unlike doc_num
    qb_line_id: Optional[str]  # line-item ID within the transaction; multi-line txns need this
    qb_txn_type: str  # Purchase | Bill | Invoice | SalesReceipt | Deposit
    txn_date: date
    category: str  # 'income' | 'expense' -- derived from qb_txn_type, not guessed
    account: str
    source: Optional[str]  # business_unit tag (from ClassRef, if present)
    amount: float
    memo: Optional[str] = None

    def to_row(self) -> dict:
        row = asdict(self)
        row["txn_date"] = self.txn_date.isoformat()
        return row


@dataclass
class AirtablePartnership:
    deal_id: str
    invoice_no: Optional[str]
    status: str
    deliverable_platform: Optional[str]
    client: Optional[str]
    is_repeat: Optional[bool]  # ALWAYS None -- no real field for this exists in the actual base, confirmed against the real schema. Kept for schema stability, not removed.
    gross_amt: Optional[float]
    net_amt: Optional[float]
    month_committed: Optional[date]
    month_completed: Optional[date]
    in_qbo: Optional[bool] = None  # real field, discovered in the actual base: explicit signal for QuickBooks reconciliation
    invoice_status: Optional[str] = None
    agreement_status: Optional[str] = None

    def to_row(self) -> dict:
        row = asdict(self)
        if self.month_committed:
            row["month_committed"] = self.month_committed.isoformat()
        if self.month_completed:
            row["month_completed"] = self.month_completed.isoformat()
        return row


@dataclass
class SocialPost:
    account_id: str
    post_id: str
    platform: str
    media_type: Optional[str] = None
    caption: Optional[str] = None
    permalink: Optional[str] = None
    posted_at: Optional[datetime] = None
    is_branded_content: bool = False
    branded_partner_name: Optional[str] = None
    is_ephemeral: bool = False  # Stories: insights vanish permanently at 24h

    def to_row(self) -> dict:
        row = asdict(self)
        row["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return row


@dataclass
class SocialPostMetric:
    post_id: str
    metric: str
    value: float
    fetched_at: datetime

    def to_row(self) -> dict:
        row = asdict(self)
        row["fetched_at"] = self.fetched_at.isoformat()
        return row


@dataclass
class SocialDemographic:
    account_id: str
    dimension: str        # 'age' | 'gender' | 'city' | 'country'
    dimension_value: str  # '25-34' | 'F' | 'Dallas, Texas' | 'US'
    value: float
    period_date: date

    def to_row(self) -> dict:
        row = asdict(self)
        row["period_date"] = self.period_date.isoformat()
        return row


@dataclass
class CashBalance:
    account_name: str
    current_balance: float
    as_of: datetime

    def to_row(self) -> dict:
        row = asdict(self)
        row["as_of"] = self.as_of.isoformat()
        return row


@dataclass
class SocialAccount:
    platform: str  # 'instagram','facebook','tiktok'
    handle: str
    account_id: str  # platform's native account id
    is_core: bool = True

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class SocialMetric:
    account_id: str
    metric: str
    period_date: date
    value: float
    source: str = "api"

    def to_row(self) -> dict:
        row = asdict(self)
        row["period_date"] = self.period_date.isoformat()
        return row
