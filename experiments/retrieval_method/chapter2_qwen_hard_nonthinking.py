"""本地开发候选：使用 vLLM 模板开关明确关闭 Qwen3 思考。"""
from chapter2_qwen_structured_output import constrain_requests


def hard_nonthinking_requests(requests):
    result=constrain_requests(requests)
    for request in result:
        body=request['body']
        if body.get('enable_thinking',False) is not False:
            raise ValueError('This candidate preserves the registered non-thinking design')
        existing=body.get('chat_template_kwargs',{})
        if existing not in ({},{'enable_thinking':False}):
            raise ValueError('Conflicting or unregistered template override')
        body['chat_template_kwargs']={'enable_thinking':False}
    return result
