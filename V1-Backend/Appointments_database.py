from supabase import create_client, Client
import os
from dotenv import load_dotenv
from datetime import datetime
# import typing

load_dotenv()


class Database:

    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        self.client = create_client(url,key)

    def _log_audit(self,patient_id = None, session_id=None, phone_number=None, data_accessed = None,metadata=None){
        audit_info ={
            "timestamp" = datetime.now().isoformat(),
            "session_id" = session_id,
            "patient_id" = patient_id,
            "phone_number" = phone_number,
            "action_type" = 

        }

    }

    def get_patient_by_phone(self, phone_number):

        try:
            response = self.client.table("patients").select('*').eq("phone_number",phone_number).execute()

            if response.data and len(response.data)>0:
                patient = response.data[0]
                print("PATIENT FOUND")
                print(patient)
                return patient
            else:
                print("NO PATIENT FOUND")
                return None

        except Exception as e:
            print(f"Error fetching patient: {e}")
            return None
    
    def create_patient(self,phone_number,first_name,last_name,dob,email):

        patient_details = self.client.table("patients").insert({"phone_number":phone_number,
        "first_name":first_name,"last_name":last_name,"date_of_birth":dob,"email":email}).execute()

        return patient_details

    def get_doctors(self,specialty):

        doctors_details = self.client.table("doctors")
        

    def check_doctor_availability(self, doctor_id, date):

        return 








if __name__ == "__main__":

    db = Database()
    test_phone = "+91-98765-00197"
    patient = db.get_patient_by_phone(test_phone)
