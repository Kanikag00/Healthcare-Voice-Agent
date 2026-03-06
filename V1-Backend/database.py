from supabase import create_client, Client
import os
from dotenv import load_dotenv
import json
from datetime import date

load_dotenv()


class Database:

    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        self.client = create_client(url, key)

    def _log_audit(self, log_entry: dict):
        try:
            self.client.table("audit_logs").insert(log_entry).execute()
        except Exception as e:
            print(f"Audit log failed (non-blocking): {e}")

    def get_patient_by_phone(self, phone_number):
        try:
            response = self.client.table("patients").select('*').eq("phone_number", phone_number).execute()

            if response.data and len(response.data) > 0:
                patient = response.data[0]
                return patient
            else:
                return None

        except Exception as e:
            print(f"Error fetching patient: {e}")
            return None

    def create_patient(self, phone_number, first_name, last_name, dob):
        try:
            patient_details = self.client.table("patients").insert({
                "phone_number": phone_number,
                "first_name": first_name,
                "last_name": last_name,
                "date_of_birth": dob,
            }).execute()

            return patient_details

        except Exception as e:
            print(f"Error fetching patient: {e}")
            return None


    def get_doctors_by_department(self, specialty):
        try:
            response = self.client.table("doctors").select('*').ilike("specialty", f"%{specialty}%").execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching doctors: {e}")
            return []

    def get_doctor_by_name(self,doctor_name):
        try:
            response = self.client.table("doctors").select('*').ilike("name", f"%{doctor_name}%").execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching doctor id: {e}")
            return None

    def get_booked_appointments(self, doctor_id, date):
        try:
            response = self.client.table("appointments").select("appointment_time").eq(
                "doctor_id", doctor_id
            ).eq(
                "appointment_date", date
            ).eq(
                "status", "scheduled"
            ).execute()
            return [row["appointment_time"] for row in response.data] if response.data else []
        except Exception as e:
            print(f"Error fetching booked appointments: {e}")
            return []

    def get_patient_appointments(self, patient_id):
        try:
            today = date.today().isoformat()
            response = self.client.table("appointments").select(
                "*, doctors(name, specialty)"
            ).eq(
                "patient_id", patient_id
            ).eq(
                "status", "scheduled"
            ).gte(
                "appointment_date", today
            ).execute()
            return response.data if response.data else []
        except Exception as e:
            print(f"Error fetching patient appointments: {e}")
            return []

    def cancel_appointment(self, appointment_id):
        try:
            response = self.client.table("appointments").update(
                {"status": "cancelled"}
            ).eq("id", appointment_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error cancelling appointment: {e}")
            return None

    def get_lab_reports_by_phone(self, phone_number):
        try:
            patient = self.get_patient_by_phone(phone_number)
            if not patient:
                return None, []
            response = self.client.table("lab_reports").select("*").eq(
                "patient_id", patient["id"]
            ).order("ordered_date", desc=True).execute()
            reports = response.data if response.data else []
            return patient, reports
        except Exception as e:
            print(f"Error fetching lab reports: {e}")
            return None, []

    def get_bills_by_phone(self, phone_number):
        try:
            patient = self.get_patient_by_phone(phone_number)
            if not patient:
                return None, []
            response = self.client.table("bills").select("*").eq(
                "patient_id", patient["id"]
            ).order("bill_date", desc=True).execute()
            bills = response.data if response.data else []
            return patient, bills
        except Exception as e:
            print(f"Error fetching bills: {e}")
            return None, []

    def create_appointment(self, patient_id, patient_name, doctor_id, doctor_name, appointment_date, appointment_time, reason=None):
        try:
            response = self.client.table("appointments").insert({
                "patient_id": patient_id,
                "patient_name": patient_name,
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "appointment_date": appointment_date,
                "appointment_time": appointment_time,
                "status": "scheduled",
                "reason": reason
            }).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            print(f"Error creating appointment: {e}")
            return None


if __name__ == "__main__":

    db = Database()
    # test_phone = "+91-98765-00197"
    # patient = db.get_patient_by_phone(test_phone)
    doctor_id = db.get_doctor_by_name("Dr. Rajesh")
    print(doctor_id)
    # print(db.get_doctors("cardio"))
