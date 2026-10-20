"""Finance assistant tools (read-only). Every call verifies the account owner's email."""
from collections import defaultdict
from datetime import date

from langchain_core.tools import tool

from config import get_db


def _account(account_number: str, email: str) -> dict | None:
    rows = (get_db().table("fin_accounts")
            .select("account_number,account_type,balance,customers!inner(name,email)")
            .eq("account_number", account_number.strip().upper())
            .eq("customers.email", email.strip().lower()).execute().data)
    return rows[0] if rows else None


NOT_VERIFIED = "Could not verify that account number with that email address."


@tool
def get_account_summary(account_number: str, email: str) -> str:
    """Balance and type of an account (e.g. ACC-5001). Needs the owner's email to verify."""
    a = _account(account_number, email)
    if not a:
        return NOT_VERIFIED
    label = "Outstanding (owed)" if a["account_type"] == "credit_card" else "Balance"
    return (f"{a['account_number']} ({a['account_type']}) owned by {a['customers']['name']}. "
            f"{label}: Rs {abs(float(a['balance'])):,.2f}")


@tool
def recent_transactions(account_number: str, email: str, limit: int = 10) -> str:
    """Most recent transactions on an account. Needs the owner's email to verify."""
    if not _account(account_number, email):
        return NOT_VERIFIED
    rows = (get_db().table("fin_transactions").select("txn_date,description,category,amount")
            .eq("account_number", account_number.strip().upper())
            .order("txn_date", desc=True).limit(min(limit, 50)).execute().data)
    if not rows:
        return "No transactions found."
    return "\n".join(f"{r['txn_date']}  {r['description']:<28} {r['category']:<11} Rs {float(r['amount']):>11,.2f}"
                     for r in rows)


@tool
def spending_by_category(account_number: str, email: str, month: str = "") -> str:
    """Total money spent per category for a month (YYYY-MM, default: current month).
    Needs the owner's email to verify."""
    if not _account(account_number, email):
        return NOT_VERIFIED
    month = month or date.today().strftime("%Y-%m")
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError:
        return "Month must be YYYY-MM."
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    rows = (get_db().table("fin_transactions").select("category,amount")
            .eq("account_number", account_number.strip().upper())
            .gte("txn_date", start.isoformat()).lt("txn_date", end.isoformat()).execute().data)
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        if float(r["amount"]) < 0:
            totals[r["category"]] += -float(r["amount"])
    if not totals:
        return f"No spending recorded in {month}."
    lines = [f"- {c}: Rs {v:,.2f}" for c, v in sorted(totals.items(), key=lambda x: -x[1])]
    return f"Spending in {month} (total Rs {sum(totals.values()):,.2f}):\n" + "\n".join(lines)


FINANCE_TOOLS = [get_account_summary, recent_transactions, spending_by_category]
