"""Comparable, source-readable retrieval packets under exact Unicode character budgets."""
from pathlib import Path
import json


def wire(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def source_item(corpus, evidence, max_chars=1200, margin=0, metadata=None):
    relative=evidence['path'];root=Path(corpus).resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root):raise ValueError('source outside corpus')
    text=path.read_text();lines=text.splitlines(keepends=True)
    if not (1 <= evidence['line_start'] <= evidence['line_end'] <= len(lines)):
        raise ValueError('source line range invalid')
    first=max(1,evidence['line_start']-margin);last=min(len(lines),evidence['line_end']+margin)
    offset=sum(len(x) for x in lines[:first-1]);end=sum(len(x) for x in lines[:last])
    end=min(end,offset+max_chars)
    excerpt=text[offset:end]
    item={'path':relative,'line_start':first,'line_end':first+excerpt.rstrip('\n').count('\n'),
          'char_start':offset,'char_end':end,'text':excerpt}
    if evidence.get('pdf_page'):
        item['pdf_page']=evidence['pdf_page'];item['image_path']=f"manual/images/pages/p{evidence['pdf_page']:03}.png"
    if metadata:item['context']=metadata
    return item


def pack(items,budget,status='ok'):
    if type(budget) is not int or budget<256:raise ValueError('budget must be at least 256 characters')
    unique=[];seen=set()
    for item in items:
        key=(item['path'],item['char_start'],item['char_end'])
        if key not in seen:unique.append(item);seen.add(key)
    packet={'status':status,'evidence':[],'omitted_items':len(unique)}
    for i,item in enumerate(unique):
        candidate={**packet,'evidence':packet['evidence']+[item],'omitted_items':len(unique)-i-1}
        if len(wire(candidate))>budget:break
        packet=candidate
    if not packet['evidence'] and items:packet['status']='budget_too_small_for_first_item'
    assert len(wire(packet))<=budget
    return packet


def semantic_items(response, corpus):
    items=[]
    for result in response['results']:
        card=result['card']
        metadata={'title':card['title'],'subject':card['subject'],'relation':card['relation'],
                  'object':card['object'],'conditions':card['conditions_zh'],
                  'visual_check_required':card['visual_check_required'],'review':'candidate_not_independently_reviewed'}
        for ev in card['evidence']:
            items.append(source_item(corpus,ev,margin=2,metadata=metadata))
    return items


def text_items(response,corpus):
    return [source_item(corpus,hit['evidence']) for hit in response['results']]


def merge_intervals(intervals):
    merged=[]
    for a,b in sorted(intervals):
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    return merged


def overlap(a,b):
    return max(0,min(a[1],b[1])-max(a[0],b[0]))


def gold_ranges(evidence,corpus):
    result={}
    for ev in evidence:
        text=(Path(corpus)/ev['path']).read_text();lines=text.splitlines(keepends=True)
        start=sum(len(x) for x in lines[:ev['line_start']-1]);end=sum(len(x) for x in lines[:ev['line_end']])
        quote=ev.get('quote')
        if quote:
            found=text.find(quote,start,end)
            if found<0:raise ValueError('gold quote no longer matches locator')
            start,end=found,found+len(quote)
        result.setdefault(ev['path'],[]).append((start,end))
    return {p:merge_intervals(v) for p,v in result.items()}


def measure(packet,annotation,corpus):
    items=packet['evidence'];gold=gold_ranges(annotation['evidence'],corpus)
    visible={};first=None;hit_items=0;min_complete=None;required=sum(b-a for ranges in gold.values() for a,b in ranges)
    for i,item in enumerate(items,1):
        span=(item['char_start'],item['char_end']);path=item['path']
        relevant=sum(overlap(span,g) for g in gold.get(path,[]))>0
        if relevant:hit_items+=1;first=first or i
        visible.setdefault(path,[]).append(span)
        if required:
            covered=sum(overlap(x,y) for p,ranges in gold.items() for x in ranges for y in merge_intervals(visible.get(p,[])))
            if covered>=required and min_complete is None:
                min_complete=len(wire({**packet,'evidence':items[:i],'omitted_items':packet['omitted_items']+len(items)-i}))
    unique={p:merge_intervals(r) for p,r in visible.items()}
    covered=sum(overlap(x,y) for p,ranges in gold.items() for x in ranges for y in unique.get(p,[]))
    source_chars=sum(i['char_end']-i['char_start'] for i in items)
    unique_chars=sum(b-a for r in unique.values() for a,b in r)
    actual=len(wire(packet));paths=set(visible);targets=set(gold)
    return {'context_characters':actual,'source_characters':source_chars,'evidence_items':len(items),
            'seed_path_recall':len(paths&targets)/len(targets) if targets else None,
            'seed_path_precision':len(paths&targets)/len(paths) if paths and targets else None,
            'seed_span_recall':covered/required if required else None,
            'all_seed_spans_covered':covered>=required if required else None,
            'first_seed_reciprocal_rank':1/first if first else 0 if required else None,
            'seed_relevant_item_fraction':hit_items/len(items) if items and required else None,
            'marked_evidence_character_fraction':covered/actual if required else None,
            'duplicate_source_character_fraction':(source_chars-unique_chars)/source_chars if source_chars else 0,
            'minimum_prefix_characters_for_all_seeds':min_complete,
            'empty_result':not items,
            'exact_absence_handled':packet['status']=='case_unavailable' if annotation['answerability']=='unavailable_exact_case' else None}
