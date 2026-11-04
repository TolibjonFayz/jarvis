"""Kompyuterda ovoz: "Hey Jarvis" yoki Ctrl+Alt+J -> gapirasan -> FRIDAY karnaydan javob beradi.

Oqim (bot jarayonida, alohida fon oqimlarida):
- mikrofon doim o'qiladi (16 kHz), lekin LOKAL: openWakeWord "hey_jarvis" modeli faqat
  uyg'otuvchi so'zni qidiradi, ovoz hech qayerga ketmaydi;
- uyg'otuvchi so'z yoki hotkey -> qisqa signal -> gap yoziladi (jimlik bilan tugaydi) ->
  Groq Whisper (Telegram ovozli xabari bilan bir xil) -> agent -> edge-tts -> karnay.
- Javob paytida mikrofon e'tiborsiz qoldiriladi (o'z ovozidan uyg'onmasin).

Tashqi kutubxonalar: sounddevice, openwakeword (onnxruntime nudenet bilan allaqachon bor).
Ovoz chiqarish winmm MCI orqali (qo'shimcha pleersiz), signal winsound.Beep bilan.
"""
import asyncio
import ctypes
import ctypes.wintypes
import logging
import os
import tempfile
import threading
import time
import wave

import numpy as np

import config
import memory
import voice

log = logging.getLogger("jarvis")

SR = 16000
CHUNK = 1280                 # 80 ms — openWakeWord shuni kutadi
WAKE_MODEL = "hey_jarvis"
WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))
START_TIMEOUT = 5.0          # signal'dan keyin shuncha vaqt gapirilmasa — bekor
END_SILENCE = 1.0            # gapdan keyin shuncha jimlik — tugadi
MAX_UTTER = 15.0
MIN_SPEECH_RMS = 350         # shovqin past bo'lsa ham shundan baland bo'lishi kerak

# RegisterHotKey: Ctrl+Alt+J
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_J = 0x4A
WM_HOTKEY = 0x0312


def rms(a):
    return float(np.sqrt(np.mean(np.square(a.astype(np.float32))))) if len(a) else 0.0


FOLLOW_TIMEOUT = 4.0         # javobdan keyin qayta chaqirmasdan gapirish oynasi

# Jim/shovqinli audioda Whisper shularni o'ylab topadi (2026-11-03: "Thank you." deb yozilgan).
_HALLUCINATIONS = {
    "thank you", "thanks", "thank you for watching", "thanks for watching", "you", "bye",
    "subtitles by the amaraorg community", "продолжение следует", "субтитры сделал dimatorzok",
    "редактор субтитров асинкевич", "спасибо за просмотр",
}
# Chaqiruv so'zi gapga tushib qoladi: "Hei Jarvis" agentga savol bo'lib ketgan edi.
_WAKE_PREFIX_RE = __import__("re").compile(
    r"^\W*(?:(?:hey|hei|hay|hai|hi|xey|эй|хей)[\s,.!]*)?(?:jarvis|jarvys|jarviz|djarvis|джарвис|жарвис)\b[\s,.!?]*",
    __import__("re").IGNORECASE,
)


def clean_text(text):
    """(matn, holat): holat 'ok' | 'wake_only' | 'noise'."""
    t = (text or "").strip()
    norm = "".join(ch for ch in t.lower() if ch.isalnum() or ch.isspace()).strip()
    if not norm or norm in _HALLUCINATIONS:
        return "", "noise"
    rest = _WAKE_PREFIX_RE.sub("", t).strip()
    if rest != t and len(rest) < 2:
        return "", "wake_only"
    return rest, "ok"


class Utterance:
    """Signal'dan keyingi bo'laklarni yig'adi va gap tugaganini aniqlaydi (sof mantiq)."""

    def __init__(self, noise, start_timeout=START_TIMEOUT):
        self.thr = max(noise * 3.0, MIN_SPEECH_RMS)
        self.start_timeout = start_timeout
        self.frames, self.t = [], 0.0
        self.started, self.silent = False, 0.0

    def feed(self, chunk):
        """'more' | 'done' | 'empty'."""
        dt = len(chunk) / SR
        self.t += dt
        self.frames.append(chunk)
        if rms(chunk) >= self.thr:
            self.started, self.silent = True, 0.0
        elif self.started:
            self.silent += dt
        if not self.started:
            return "empty" if self.t >= self.start_timeout else "more"
        if self.silent >= END_SILENCE or self.t >= MAX_UTTER:
            return "done"
        return "more"

    def audio(self):
        return np.concatenate(self.frames) if self.frames else np.zeros(0, np.int16)


def _beep(freq, ms=120):
    try:
        import winsound
        winsound.Beep(freq, ms)
    except Exception:
        pass


def _mci(cmd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.winmm.mciSendStringW(cmd, buf, 256, 0)
    return buf.value


def play_mp3(path):
    """Sinxron ijro (MCI 'wait') — chaqirgan oqim tugaguncha kutadi."""
    alias = f"fr{int(time.time() * 1000) % 100000}"
    _mci(f'open "{path}" type mpegvideo alias {alias}')
    _mci(f"play {alias} wait")
    _mci(f"close {alias}")


def say(text):
    speak = voice.speakable(text, limit=400)
    if not speak:
        return
    mp3 = os.path.join(tempfile.gettempdir(), f"friday_pc_{int(time.time() * 1000)}.mp3")
    try:
        asyncio.run(voice.tts(speak, mp3))
        play_mp3(mp3)
    finally:
        try:
            os.remove(mp3)
        except OSError:
            pass


def _wav(audio):
    path = os.path.join(tempfile.gettempdir(), f"friday_pc_in_{int(time.time() * 1000)}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(audio.astype(np.int16).tobytes())
    return path


class PcVoice:
    """on_text(matn) -> javob matni (bot beradi: agent + Telegram'ga nusxa)."""

    def __init__(self, on_text, chat_id):
        self.on_text = on_text
        self.chat_id = chat_id
        self.trigger = threading.Event()
        self.busy = False
        self.running = False
        self.model = None
        self._noise = []
        self._cfg = (0.0, True, True)

    # --- sozlamalar (har 3 s da bazadan) ---
    def _settings(self):
        ts, on, wake = self._cfg
        if time.time() - ts > 3:
            on = memory.get_setting(self.chat_id, "pc_voice_on", "1") == "1"
            wake = memory.get_setting(self.chat_id, "pc_wake_on", "1") == "1"
            self._cfg = (time.time(), on, wake)
        return on, wake

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._hotkey_loop, name="pc-voice-hotkey", daemon=True).start()
        threading.Thread(target=self._mic_loop, name="pc-voice-mic", daemon=True).start()

    def _hotkey_loop(self):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_J):
            log.warning("PC ovoz: Ctrl+Alt+J band — hotkey ishlamaydi (wake-word ishlaydi)")
            return
        msg = ctypes.wintypes.MSG()
        while self.running and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and self._settings()[0] and not self.busy:
                self.trigger.set()

    def _load_model(self):
        from openwakeword.model import Model
        return Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx")

    def _mic_loop(self):
        import sounddevice as sd
        while self.running:
            try:
                if self.model is None:
                    self.model = self._load_model()
                with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=CHUNK) as s:
                    log.info("PC ovoz: tinglayapman (Hey Jarvis / Ctrl+Alt+J)")
                    self._listen_forever(s)
            except Exception as e:
                log.warning("PC ovoz: mikrofon xatosi, 30 s dan keyin qayta: %s", str(e)[:120])
                time.sleep(30)

    def _listen_forever(self, s):
        while self.running:
            block, _ = s.read(CHUNK)
            a = block[:, 0]
            on, wake = self._settings()
            if not on:
                continue
            self._noise = (self._noise + [rms(a)])[-25:]  # ~2 s shovqin fon darajasi
            score = 0.0
            if wake:
                score = self.model.predict(a).get(WAKE_MODEL, 0.0)
            hotkey = self.trigger.is_set()
            if hotkey or score >= WAKE_THRESHOLD:
                self.trigger.clear()
                log.info("PC ovoz: chaqirildi (%s)", "Ctrl+Alt+J" if hotkey else f"wake {score:.2f}")
                self._session(s)
                self.model.reset()
                self._drain(s)

    @staticmethod
    def _drain(s):
        """Javob paytida yig'ilgan eski ovozni tashlaydi (o'z ovozini eshitmasin)."""
        while s.read_available >= CHUNK:
            s.read(CHUNK)

    def _record(self, s, start_timeout):
        noise = float(np.median(self._noise)) if self._noise else 0.0
        u = Utterance(noise, start_timeout)
        while True:
            block, _ = s.read(CHUNK)
            state = u.feed(block[:, 0].copy())
            if state != "more":
                break
        log.info("PC ovoz: sessiya %s, %.1f s, shovqin %.0f, chegara %.0f, eng baland %.0f",
                 state, u.t, noise, u.thr, max((rms(f) for f in u.frames), default=0))
        return state, u.audio()

    def _session(self, s):
        """Chaqiruvdan keyin suhbat: javobdan so'ng FOLLOW_TIMEOUT ichida gapirsang —
        qayta chaqirmasdan davom etadi (Jarvis kabi)."""
        self.busy = True
        try:
            first = True
            while self.running:
                _beep(880) if first else _beep(1046, 60)
                state, audio = self._record(s, START_TIMEOUT if first else FOLLOW_TIMEOUT)
                if state == "empty":
                    if first:
                        _beep(440, 90)
                    return
                _beep(660, 80)
                if not self._handle(audio):
                    return
                first = False
                self._drain(s)
        except Exception as e:
            log.warning("PC ovoz sessiyasi xatosi: %s", str(e)[:150])
        finally:
            self.busy = False

    def _handle(self, audio):
        """True — suhbat davom etadi (javob berildi yoki faqat chaqiruv so'zi aytildi)."""
        path = _wav(audio)
        try:
            raw = voice.transcribe(path)
        except Exception as e:
            log.warning("PC ovoz: STT xatosi: %s", str(e)[:120])
            say("Kechirasiz, ovozni tanib bo'lmadi.")
            return False
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        text, kind = clean_text(raw)
        log.info("PC ovoz: «%s» -> %s", (raw or "").strip()[:120], kind)
        if kind == "noise":
            _beep(440, 90)
            return False
        if kind == "wake_only":
            say("Ha bro, eshitaman.")
            return True
        reply = self.on_text(text)
        if reply:
            say(reply)
        return True


_instance = None


def start(on_text, chat_id):
    """Bot ishga tushganda chaqiriladi. Kutubxona yo'q bo'lsa jimgina o'chiq qoladi."""
    global _instance
    if os.name != "nt" or not config.PC_VOICE:
        return None
    try:
        import sounddevice  # noqa: F401
        import openwakeword  # noqa: F401
    except ImportError as e:
        log.warning("PC ovoz o'chiq: %s", e)
        return None
    _instance = PcVoice(on_text, chat_id)
    _instance.start()
    return _instance


def status_text(chat_id):
    on = memory.get_setting(chat_id, "pc_voice_on", "1") == "1"
    wake = memory.get_setting(chat_id, "pc_wake_on", "1") == "1"
    alive = bool(_instance and _instance.running)
    lines = [f"🎙 **Kompyuter ovozi**: {'yoqilgan' if on else 'o‘chirilgan'}"
             + ("" if alive else " (ishga tushmagan — logni ko'ring)"),
             "Chaqirish: Ctrl+Alt+J" + (" yoki «Hey Jarvis»" if wake else " (wake-word o'chiq)"),
             "Mikrofon lokal tinglanadi; faqat chaqirgandan keyingi gap Whisper'ga ketadi.",
             "\n/ovoz on|off · /ovoz wake on|off · /ovoz test — karnayni sinash"]
    return "\n".join(lines)
