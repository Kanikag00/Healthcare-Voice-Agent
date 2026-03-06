import redis
import json

class Session_Manager():

    """
    In memory cache to remember where each conversation is at,
    as it is a multi turn conversation

    """

    def __init__(self):
        self.redis_client = redis.Redis(host='localhost',port=6379,decode_responses = True)

    def get_session(self,session_id):
        session_details = self.redis_client.get(f"session:{session_id}")
        if session_details:
            return json.loads(session_details)
        return None

    def create_session(self, session_id, phone_number):
        """Created by voice_agent when a call comes in."""
        print("New session created")
        session_data = {
            "session_id": session_id,
            "phone_number": phone_number,
            "is_new_patient": None,
            "current_intent": None,
            "state": "INITIAL",
        }
        print(session_data)
        self.redis_client.setex(f"session:{session_id}", 1800, json.dumps(session_data))
        return session_data

    def add_appointment_data(self, session_id):
        """Called by appointment_agent when appointment flow starts."""
        print("ADDING APPOINTMENT DATA IN SESSION")
        session = self.get_session(session_id)
        if session is None:
            return None
        session.update({
            "sub_action": None,
            "appointment_details": {
                "doctor_name": None,
                "specialty": None,
                "preferred_date": None,
                "time_preference": None
            },
            "available_slots": [],
            "selected_slot": None,
            "existing_appointments": [],
            "selected_appointment": None,
            "patient_info": {
                "first_name": None,
                "last_name": None,
                "date_of_birth": None
            }
        })
        print(session)
        self.redis_client.setex(f"session:{session_id}", 1800, json.dumps(session))
        return session

    def update_session(self, session_id, **kwargs):
        print("UPDATE SESSION ")
        session = self.get_session(session_id)
        if session is None:
            return None
        for key, value in kwargs.items():
            session[key] = value
        
        print(session)
        self.redis_client.setex(f"session:{session_id}", 1800, json.dumps(session))
        return session

    def delete_session(self, session_id):
        self.redis_client.delete(f"session:{session_id}")

