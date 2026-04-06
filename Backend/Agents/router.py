import ollama
import json
import os
from dotenv import load_dotenv

load_dotenv()


class Router:
    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "llama3.1:8b")

    def requirement(self,patient_message:str):
        print("getting the intent")

        prompt = f"""You are a hospital call routing system.
        The patient has requested: "{patient_message}"

        Classify the request into one of these categories:
        - Appointment (Scheduling, Rescheduling or Cancellation)
        - Lab Report (checking test results, lab report status)
        - Billing (payment questions, bill, insurance)
        - Emergency (urgent medical needs, severe pain, life-threatening)
        - CallEnd (patient says goodbye, thanks, "that's it", "nothing else", wants to end the call)
        - Other (general questions, visiting hours, directions)

        You must analyze the patient's message and return ALL THREE fields:
        1. requirement: The category name from the list above that best matches
        2. confidence: A decimal number between 0 and 1 indicating how confident you are (e.g., 0.95)
        3. summary: A brief one-sentence description of what the patient needs

        CRITICAL: Return ONLY raw JSON with ALL THREE fields. No markdown, no code blocks, no extra text.
        Example format:
        {{
          "requirement": "Appointment",
          "confidence": 0.95,
          "summary": "Patient wants to schedule a cardiology appointment"
        }}
        """
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.1, "num_predict": 500}
            )

            text = response["message"]["content"].strip()

            if not text:
                print("ERROR: Empty response from Ollama")
                raise ValueError("Empty response from API")

            result = json.loads(text)
            print("output from model: ", result)
            return result

        except Exception as e:
            print(f"Error classifying intent: {e}")
            return {
                "requirement": "error",
                "confidence": 0.0,
                "summary": "Could not understand request"
            }

if __name__ == "__main__":
    router = Router()
    test_message = "I want to see a cardiologist?"
    result = router.requirement(test_message)
    print(result)
    print(type(result)) 

