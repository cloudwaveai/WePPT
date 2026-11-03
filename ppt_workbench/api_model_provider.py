"""Bounded OpenAI-compatible text planning API; no tools, redirects or raw errors."""
import base64
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from .core import EngineError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def run_api_turn(prompt,context,profile,timeout, image_bytes=None):
    from .agent_bridge import INSTRUCTIONS, WIRE_SCHEMA, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, _loads, _decode_wire
    key=os.environ.get(profile['key_env'],'')
    if not key:raise EngineError('MODEL_AUTH_MISSING','该模型尚未配置 API 密钥。')
    data={'model':profile['model'],'messages':[{'role':'system','content':INSTRUCTIONS+'\nReturn JSON matching this schema: '+json.dumps(WIRE_SCHEMA)},
          {'role':'user','content':json.dumps({'user_message':prompt,'context':context},ensure_ascii=False)}],
          'response_format':{'type':'json_object'},'max_tokens':profile.get('max_tokens',8192),'stream':False}
    # Keep the selected model and token cap. Reserve the bounded response for
    # editable geometry instead of the provider's default high-effort reasoning.
    # Official DeepSeek control: https://api-docs.deepseek.com/guides/thinking_mode/
    if (urlsplit(profile['base_url']).hostname == 'api.deepseek.com'
            and profile['model']=='deepseek-flash'
            and (context.get('creationContract') == 'content-led-v1'
                 or context.get('generationTask',{}).get('kind') in {'template_adaptation','design_loop_review','deck_page','deck_review','deck_plan_review'})):
        data['reasoning_effort']='low'
    text_body=json.dumps(data,ensure_ascii=False).encode()
    if len(text_body)>MAX_INPUT_BYTES:raise EngineError('INVALID_INPUT','本轮文字上下文过大，请减少材料。')
    if image_bytes is not None:
        if not profile.get('vision') or len(image_bytes)>8*1024*1024 or not image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            raise EngineError('INVALID_REVIEW_IMAGE','模型或参考图不满足看图条件。')
        content=data['messages'][1]['content']
        data['messages'][1]['content']=[{'type':'text','text':content},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image_bytes).decode(),'detail':'original'}}]
    body=json.dumps(data,ensure_ascii=False).encode()
    if len(body)>14*1024*1024:raise EngineError('INVALID_INPUT','本轮上下文过大，请减少材料。')
    request=urllib.request.Request(profile['base_url'].rstrip('/')+'/chat/completions',data=body,
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request,timeout=timeout) as response:
            raw=response.read(MAX_OUTPUT_BYTES+1)
        if len(raw)>MAX_OUTPUT_BYTES:raise EngineError('MODEL_RESPONSE_TOO_LARGE','模型返回内容超过限制，未应用修改。')
        envelope=_loads(raw.decode("utf-8"))
        choice=envelope['choices'][0]
        if choice.get('finish_reason')=='length':raise EngineError('MODEL_OUTPUT_TRUNCATED','模型输出被长度限制截断，未应用修改。', {'maxTokens':data['max_tokens'],'completionTokens':envelope.get('usage',{}).get('completion_tokens')})
        if choice.get('finish_reason') not in ('stop',None) or choice['message'].get('tool_calls'):
            raise EngineError('INVALID_AGENT_OUTPUT','模型未返回完整的页面操作方案。')
        content=choice['message']['content']
        if not isinstance(content,str):raise ValueError
        return _decode_wire(_loads(content))
    except urllib.error.HTTPError as exc:
        code='MODEL_AUTH_FAILED' if exc.code in (401,403) else 'MODEL_RATE_LIMIT' if exc.code==429 else 'MODEL_API_FAILED'
        raise EngineError(code,'模型 API 请求失败，未应用修改。',{'status':exc.code}) from None
    except (OSError,TimeoutError):
        raise EngineError('MODEL_API_UNAVAILABLE','模型 API 连接失败或超时，未应用修改。') from None
    except (KeyError,IndexError,TypeError,ValueError,AttributeError):
        raise EngineError('INVALID_AGENT_OUTPUT','模型没有返回可解析的完整方案。') from None
