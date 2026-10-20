"""HR assistant tools: employee profile, policy search, leave requests."""
from datetime import date, timedelta

from langchain_core.tools import tool

from config import get_db


def working_days(start: date, end: date) -> int:
    return sum(1 for i in range((end - start).days + 1) if (start + timedelta(i)).weekday() < 5)


def _employee(emp_code: str) -> dict | None:
    rows = get_db().table("hr_employees").select("*").eq("emp_code", emp_code.strip().upper()).execute().data
    return rows[0] if rows else None


def _pending_days(emp_code: str) -> int:
    rows = (get_db().table("hr_leave_requests").select("days")
            .eq("emp_code", emp_code).eq("status", "pending").execute().data)
    return sum(r["days"] for r in rows)


@tool
def get_employee(emp_code: str) -> str:
    """Get an employee's profile and leave balance by employee code (e.g. E101)."""
    e = _employee(emp_code)
    if not e:
        return f"No employee with code {emp_code}."
    pending = _pending_days(e["emp_code"])
    return (f"{e['name']} ({e['emp_code']}), {e['role']} in {e['department']}, manager: "
            f"{e['manager'] or 'none'}, joined {e['join_date']}. Leave balance: "
            f"{e['leave_balance']} days ({pending} days pending approval).")


@tool
def search_hr_policy(question: str) -> str:
    """Search HR policies: annual leave, sick leave, work from home, expenses,
    parental leave, notice period."""
    rows = get_db().rpc("search_hr_policies", {"q": question, "k": 2}).execute().data
    if not rows:
        return "No matching HR policy found."
    return "\n\n".join(f"{r['title']}: {r['content']}" for r in rows)


@tool
def request_leave(emp_code: str, start_date: str, end_date: str, reason: str) -> str:
    """Submit an annual leave request. Dates must be YYYY-MM-DD. Checks balance and
    notice rules before creating a pending request for the manager."""
    e = _employee(emp_code)
    if not e:
        return f"No employee with code {emp_code}."
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        return "Dates must be in YYYY-MM-DD format."
    today = date.today()
    if start < today or end < start:
        return "The leave period must be in the future and end on or after the start date."
    days = working_days(start, end)
    if days == 0:
        return "That period has no working days, so no leave is needed."
    available = e["leave_balance"] - _pending_days(e["emp_code"])
    if days > available:
        return f"Not enough leave: requested {days} working days, available {available}."
    if days > 2 and working_days(today + timedelta(1), start - timedelta(1)) < 3:
        return "Policy: leave longer than 2 days needs at least 3 working days' notice."
    row = get_db().table("hr_leave_requests").insert({
        "emp_code": e["emp_code"], "start_date": start.isoformat(), "end_date": end.isoformat(),
        "days": days, "reason": reason,
    }).execute().data[0]
    return (f"Leave request #{row['id']} submitted: {days} working day(s) from {start} to {end}. "
            f"Status: pending approval by {e['manager'] or 'HR'}.")


@tool
def my_leave_requests(emp_code: str) -> str:
    """List an employee's leave requests and their status."""
    rows = (get_db().table("hr_leave_requests").select("id,start_date,end_date,days,status")
            .eq("emp_code", emp_code.strip().upper()).order("start_date", desc=True).execute().data)
    if not rows:
        return "No leave requests found."
    return "\n".join(f"#{r['id']}: {r['start_date']} to {r['end_date']} ({r['days']} days) - {r['status']}"
                     for r in rows)


HR_TOOLS = [get_employee, search_hr_policy, request_leave, my_leave_requests]
