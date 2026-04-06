import numpy as np 
from faster_whisper import WhisperModel

class WhisperSTT:
    def __init__(self,model_size = "turbo"):
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        #Nyquist-Shannon Sampling Theorem
        #Whisper was trained on 16kHz audio
        self.sample_rate = 16000
    
    def transcribe(self,audio:np.ndarray) -> str:
        if len(audio) ==0:
            return ""
        segments,info= self.model.transcribe(
            audio,
            language = "en",
            beam_size =5,
            vad_filter = True,
            vad_parameters = {"min_silence_duration_ms":300}
        )
        return " ".join(s.text.strip() for s in segments).strip()