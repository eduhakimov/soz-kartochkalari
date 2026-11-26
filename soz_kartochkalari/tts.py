"""Windows SAPI orqali offline talaffuz (pywin32). SAPI bo'lmasa — jim ishlaydi."""
import logging
import sys

_log = logging.getLogger("tts")

SVSF_ASYNC = 1
SVSF_PURGE = 2


class Speaker:
    def __init__(self):
        self._voice = None
        self._voices = []
        self.error = None
        try:
            import pythoncom  # noqa: F401
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            tokens = self._voice.GetVoices()
            for i in range(tokens.Count):
                t = tokens.Item(i)
                try:
                    lang = t.GetAttribute("Language")
                except Exception:
                    lang = ""
                self._voices.append((t.GetDescription(), lang, t))
            self.select(self.default_voice())
        except Exception as ex:      # SAPI yoki pywin32 yo'q
            self.error = str(ex)
            _log.warning("SAPI unavailable: %s", ex)
            self._voice = None

    @property
    def available(self) -> bool:
        return self._voice is not None

    def voices(self):
        return [v[0] for v in self._voices]

    @staticmethod
    def is_english(lang: str) -> bool:
        """SAPI Language atributi: o'n oltilik LCID ro'yxati, masalan '409' (en-US) yoki '809' (en-GB)."""
        for part in (lang or "").split(";"):
            try:
                if int(part.strip(), 16) & 0x3FF == 0x09:
                    return True
            except ValueError:
                continue
        return False

    def default_voice(self) -> str:
        for name, lang, _ in self._voices:
            if self.is_english(lang):
                return name
        return self._voices[0][0] if self._voices else ""

    def select(self, name: str):
        if not self._voice:
            return
        for n, _, tok in self._voices:
            if n == name:
                try:
                    self._voice.Voice = tok
                except Exception as ex:
                    _log.warning("voice select: %s", ex)
                return

    def set_rate(self, rate: int):
        if self._voice:
            try:
                self._voice.Rate = max(-10, min(10, int(rate)))
            except Exception:
                pass

    def speak(self, text: str):
        if not self._voice or not text or "pytest" in sys.modules or "--screenshot" in sys.argv:
            return
        try:
            self._voice.Speak(text, SVSF_ASYNC | SVSF_PURGE)
        except Exception as ex:
            _log.warning("speak: %s", ex)
