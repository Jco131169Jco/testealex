import os, json, time, logging, requests, re
from datetime import datetime, timedelta
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

def _wrap_ssml(text: str) -> str:
    safe = (text or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    return f"<speak><prosody rate='medium'>{safe}</prosody></speak>"

def _truncate_for_alexa(text: str, limit: int = 7000) -> str:
    if text and len(text) > limit:
        return text[:limit-20].rstrip() + "…"
    return text

def _get_device_timezone(handler_input: HandlerInput) -> str:
    import requests as r
    try:
        sys = handler_input.request_envelope.context.system
        api_endpoint = sys.api_endpoint
        device_id    = sys.device.device_id
        token        = sys.api_access_token
        url = f"{api_endpoint}/v2/devices/{device_id}/settings/System.timeZone"
        res = r.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=3)
        if res.status_code == 200:
            try:
                j = res.json()
                return j if isinstance(j, str) else j.get("setting", "America/Sao_Paulo")
            except Exception:
                return (res.text or "America/Sao_Paulo").strip('"')
    except Exception:
        pass
    return "America/Sao_Paulo"

def _saudacao_agora(tzname: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        hour = datetime.now(ZoneInfo(tzname)).hour
    except Exception:
        hour = (datetime.utcnow().hour - 3) % 24
    if 5 <= hour <= 11:
        return "Bom dia"
    if 12 <= hour <= 17:
        return "Boa tarde"
    return "Boa noite"

def _call_gemini(prompt_ptbr: str) -> str:
    if not GEMINI_API_KEY:
        return "A chave do Gemini não está configurada."
    system = ("Você é um assistente em português do Brasil. Responda de forma objetiva e educada. "
              "Quando fizer sentido, traga passos práticos.")
    body = {"contents": [{"role":"user","parts":[{"text": f"{system}\n\nPergunta: {prompt_ptbr}"}]}]}
    try:
        r = requests.post(GEMINI_URL, json=body, timeout=12)
        r.raise_for_status()
        data = r.json()
        text = (data.get("candidates",[{}])[0]
                    .get("content",{}).get("parts",[{}])[0]
                    .get("text","Desculpe, não consegui responder agora."))
        return text.strip()
    except Exception:
        logger.exception("Erro Gemini")
        return "Desculpe, tive um problema para consultar o Gemini agora."

class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, hi):
        return hi.request_envelope.request.object_type == "LaunchRequest"
    def handle(self, hi):
        tz = _get_device_timezone(hi)
        saud = _saudacao_agora(tz)
        text = f"{saud}! Eu sou seu assistente com Gemini. O que você quer saber?"
        return hi.response_builder.speak(_wrap_ssml(text)).ask(_wrap_ssml("Pode repetir sua pergunta?")).response

class AskGeminiIntentHandler(AbstractRequestHandler):
    def can_handle(self, hi):
        req = hi.request_envelope.request
        return req.object_type == "IntentRequest" and req.intent.name == "AskGeminiIntent"
    def handle(self, hi):
        slots = hi.request_envelope.request.intent.slots or {}
        utter = (slots.get("utterance").value if "utterance" in slots else "") or ""
        utter = utter.strip()
        if not utter:
            return hi.response_builder.speak(_wrap_ssml("Pode repetir a pergunta?")).ask(_wrap_ssml("Como posso ajudar?")).response
        answer = _call_gemini(utter)
        answer = _truncate_for_alexa(answer)
        return hi.response_builder.speak(_wrap_ssml(answer)).ask(_wrap_ssml("Quer saber mais alguma coisa?")).response

class HelpHandler(AbstractRequestHandler):
    def can_handle(self, hi):
        req = hi.request_envelope.request
        return req.object_type == "IntentRequest" and req.intent.name == "AMAZON.HelpIntent"
    def handle(self, hi):
        txt = "Você pode fazer perguntas ao Gemini. Por exemplo: qual é o passo a passo para abrir MEI?"
        return hi.response_builder.speak(_wrap_ssml(txt)).ask(_wrap_ssml("Qual sua pergunta?")).response

class CancelStopHandler(AbstractRequestHandler):
    def can_handle(self, hi):
        req = hi.request_envelope.request
        return req.object_type == "IntentRequest" and req.intent.name in ["AMAZON.CancelIntent","AMAZON.StopIntent"]
    def handle(self, hi):
        return hi.response_builder.speak(_wrap_ssml("Até logo!")).response

class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, hi):
        req = hi.request_envelope.request
        return req.object_type == "IntentRequest" and req.intent.name == "AMAZON.FallbackIntent"
    def handle(self, hi):
        return hi.response_builder.speak(_wrap_ssml("Desculpe, não entendi. Pode repetir de outro jeito?")).ask(_wrap_ssml("Como posso ajudar?")).response

class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, hi):
        return hi.request_envelope.request.object_type == "SessionEndedRequest"
    def handle(self, hi):
        return hi.response_builder.response

sb = SkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(AskGeminiIntentHandler())
sb.add_request_handler(HelpHandler())
sb.add_request_handler(CancelStopHandler())
sb.add_request_handler(FallbackHandler())
sb.add_request_handler(SessionEndedHandler())
lambda_handler = sb.lambda_handler()