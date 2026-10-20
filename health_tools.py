"""Healthcare assistant tools: doctor search, availability, appointment booking."""
from datetime import date

from langchain_core.tools import tool
from postgrest.exceptions import APIError

from config import get_db


def _doctor(name: str) -> dict | None:
    cleaned = name.replace("Dr.", "").replace("Dr ", "").strip()
    rows = get_db().table("hc_doctors").select("*").ilike("name", f"%{cleaned}%").execute().data
    return rows[0] if len(rows) == 1 else None


def _booked_slots(doctor_id: int, day: str) -> set[str]:
    rows = (get_db().table("hc_appointments").select("appointment_time")
            .eq("doctor_id", doctor_id).eq("appointment_date", day).eq("status", "booked")
            .execute().data)
    return {r["appointment_time"] for r in rows}


@tool
def find_doctors(specialty: str = "") -> str:
    """List doctors, optionally filtered by specialty (e.g. Cardiologist, Dermatologist,
    General Physician, Orthopedic, Pediatrician), with their working days and slots."""
    query = get_db().table("hc_doctors").select("name,specialty,available_days,slots")
    if specialty:
        query = query.ilike("specialty", f"%{specialty.strip()}%")
    rows = query.order("name").execute().data
    if not rows:
        return f"No doctors found for '{specialty}'."
    return "\n".join(f"- {d['name']} ({d['specialty']}): {', '.join(d['available_days'])} "
                     f"at {', '.join(d['slots'])}" for d in rows)


@tool
def check_availability(doctor_name: str, appointment_date: str) -> str:
    """Show free slots for a doctor on a date (YYYY-MM-DD)."""
    d = _doctor(doctor_name)
    if not d:
        return f"Doctor '{doctor_name}' not found. Use find_doctors to see names."
    try:
        day = date.fromisoformat(appointment_date)
    except ValueError:
        return "Date must be YYYY-MM-DD."
    if day.strftime("%a") not in d["available_days"]:
        return f"{d['name']} does not work on {day:%A}. Working days: {', '.join(d['available_days'])}."
    free = [s for s in d["slots"] if s not in _booked_slots(d["id"], day.isoformat())]
    return f"{d['name']} on {day:%a %d %b}: " + (", ".join(free) if free else "fully booked")


@tool
def book_appointment(patient_name: str, patient_email: str, doctor_name: str,
                     appointment_date: str, appointment_time: str, reason: str) -> str:
    """Book an appointment. Date YYYY-MM-DD, time exactly as listed in the doctor's slots (e.g. 10:00)."""
    d = _doctor(doctor_name)
    if not d:
        return f"Doctor '{doctor_name}' not found."
    try:
        day = date.fromisoformat(appointment_date)
    except ValueError:
        return "Date must be YYYY-MM-DD."
    if day < date.today():
        return "The appointment date is in the past."
    if day.strftime("%a") not in d["available_days"] or appointment_time not in d["slots"]:
        return (f"{d['name']} is available {', '.join(d['available_days'])} at "
                f"{', '.join(d['slots'])}. Please pick one of those.")
    try:
        row = get_db().table("hc_appointments").insert({
            "patient_name": patient_name, "patient_email": patient_email.strip().lower(),
            "doctor_id": d["id"], "appointment_date": day.isoformat(),
            "appointment_time": appointment_time, "reason": reason,
        }).execute().data[0]
    except APIError:
        return "That slot was just taken. Please choose another time."
    return (f"Booked appointment #{row['id']} with {d['name']} on {day:%a %d %b %Y} at "
            f"{appointment_time}. Confirmation sent to {patient_email}.")


@tool
def my_appointments(patient_email: str) -> str:
    """List upcoming appointments for a patient email."""
    rows = (get_db().table("hc_appointments")
            .select("id,appointment_date,appointment_time,status,hc_doctors(name,specialty)")
            .eq("patient_email", patient_email.strip().lower())
            .gte("appointment_date", date.today().isoformat())
            .order("appointment_date").execute().data)
    if not rows:
        return "No upcoming appointments."
    return "\n".join(f"#{r['id']}: {r['appointment_date']} {r['appointment_time']} with "
                     f"{r['hc_doctors']['name']} ({r['hc_doctors']['specialty']}) - {r['status']}"
                     for r in rows)


@tool
def cancel_appointment(appointment_id: int, patient_email: str) -> str:
    """Cancel an appointment. The email must match the booking."""
    rows = (get_db().table("hc_appointments").update({"status": "cancelled"})
            .eq("id", appointment_id).eq("patient_email", patient_email.strip().lower())
            .eq("status", "booked").execute().data)
    return (f"Appointment #{appointment_id} cancelled." if rows
            else "No active appointment found with that id and email.")


HEALTH_TOOLS = [find_doctors, check_availability, book_appointment, my_appointments, cancel_appointment]
