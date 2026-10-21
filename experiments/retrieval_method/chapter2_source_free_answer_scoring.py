"""Development v6: source-free coverage with registered non-thinking Qwen14B.

The provider rejected enable_thinking for the registered model. This version
uses its supported mode, keeps source-free coverage and independent truth audit,
and never silently switches to a separately named model.
"""
from chapter2_reasoning_answer_scoring import reasoning_requests,parse_reasoning_judgments,COVERAGE_PROMPT,SOURCE_PROMPT

def source_free_requests(payload):
    requests=reasoning_requests(payload)
    for request in requests:request['body'].update(enable_thinking=False,max_tokens=4096)
    return requests

def parse_source_free_judgments(responses,payload):
    result=parse_reasoning_judgments(responses,payload,requests=source_free_requests(payload))
    if result['status']=='judged':result.update(rubric_version='source_free_v6',enable_thinking=False)
    return result
