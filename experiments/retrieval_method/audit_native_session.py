"""Audit all zstd frames of a native DSH session without exporting prompt content."""
import argparse
from collections import Counter
import json
from pathlib import Path
import zstandard


def has_user_task(events, task):
    """Identify the submitted task, not marker text seen in a tool's output."""
    return any(event['type']=='user/message' and any(
        isinstance(part,dict) and part.get('type')=='text' and part.get('text')==task
        for part in event.get('data',{}).get('content',[])) for event in events)


def read_events(path):
    with Path(path).open('rb') as file:
        with zstandard.ZstdDecompressor().stream_reader(file,read_across_frames=True) as reader:
            return [json.loads(line) for line in reader.read().decode().splitlines() if line.strip()]


def audit(events):
    tools=Counter();usage=Counter();errors=0;retries=0;results=0;skills=[];terminal=[]
    call_names={};text_chars=Counter()
    for event in events:
        kind=event['type'];data=event.get('data',{})
        if kind=='tool/call':
            tools[data['name']]+=1
            if data.get('callId'):call_names[data['callId']]=data['name']
            if data['name']=='skill':
                args=data['arguments']
                if isinstance(args,str):args=json.loads(args)
                skills.append(args.get('name'))
        elif kind=='tool/result':
            for part in data.get('message',{}).get('content',[]):
                if isinstance(part,dict) and part.get('type')=='tool-result':
                    results+=1;errors+=bool(part.get('isError'))
                    name=call_names.get(part.get('toolCallId'),'unknown')
                    text_chars[name]+=sum(len(c.get('text','')) for c in part.get('content',[])
                                          if isinstance(c,dict) and c.get('type')=='text')
        elif kind=='assistant/message':
            usage.update({k:v for k,v in (data.get('usage') or {}).items()
                          if isinstance(v,(int,float)) and not isinstance(v,bool)})
        elif kind=='llm/retry':retries+=1
        elif kind=='turn/end':terminal.append(data.get('reason'))
    return {'events':len(events),'tool_calls':sum(tools.values()),'tools':dict(tools),
            'tool_results':results,'tool_errors':errors,'loaded_skills':skills,
            'all_tool_text_characters':sum(text_chars.values()),'tool_text_characters':dict(text_chars),
            'tool_text_scope':'tool-result text content counted once; excludes reasoning and structured duplicates; characters, not tokens',
            'reported_usage':dict(usage),'llm_retries':retries,'turn_end':terminal,
            'usage_scope':'sum of assistant/message usage only; failed attempts may be missing; '
                          'cacheReadTokens and reasoningTokens are separate reported fields, not automatically added to totalTokens'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('session',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();result=audit(read_events(args.session))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
