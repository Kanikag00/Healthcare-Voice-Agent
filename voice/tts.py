from kokoro import KPipeline
import numpy as np
import sounddevice as sd


class KokoroTTS:
    def __init__(self):
        self.pipeline = KPipeline(lang_code='b')
            
    def dictate(self,text:str) -> np.ndarray :
        """returns raw audio"""
        chunks =[]
        generator = self.pipeline(text, voice='bf_emma')
        for gs, ps, audio in generator:
            chunks.append(audio)
        
        return np.concatenate(chunks)

    def speak(self,text:str):
        audio = self.dictate(text)
        if len(audio) >0:
            sd.play(audio,samplerate= 24000)
            sd.wait()
        