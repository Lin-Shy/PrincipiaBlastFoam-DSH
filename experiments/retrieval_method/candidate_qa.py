"""完整候选与强无图共用的缺口驱动问答和回答前核验；总预算与统一基线相同。"""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
import time

import graphify_qa as base
import navigation_qa as qa
from index_free_graph_evidence import Engine as EvidenceEngine

DEFAULTS={'with_scope':True,'with_cross':True,'with_paths':True,'with_groups':True,
          'with_gap':True,'with_claim_verification':True,'navigation_only':True,
          'source_context_lines':16}
PLAN='检索阶段结束。只使用已读原文，列出拟写入最终答案的实质主张与逐条引用，输出JSON：{claims:[{text:"单一、原子化主张，包含适用条件和范围",references:[{path:"路径",start:行号,end:行号}]}],unknowns:["未能证实的具体内容"]}。不同文件、字段、数值、默认值或条件拆成不同主张，避免用一个引用支撑复合结论。若用手册模型解释实例参数，且已读到实例的模型选择器、启用条件或include指令，必须把这些配置链环节分别列为主张；不能只写公式和末端数值。不以gold、记忆或未读资料补全。控制篇幅，保留最关键的主张。'
DRAFT='检索和计划已结束。输出最终答复草稿JSON：{claims:[{text:"单一、原子化的完整中文主张，含适用对象、范围、数值、角色或条件",references:[{path:"来源相对路径",start:行号,end:行号}]}],unknowns:["具体未知"]}。最多10项主张，覆盖问题所需全部要点；不同文件、字段、数值、默认值及条件不得硬合并为一个复合主张。每项原则上只绑定一个能支持该项完整文字的连续原文范围；跨文件比较必须拆成各来源各自的单源主张，不再追加需要两个来源共同证明的总结句。手册模型与实例值同时出现时，已读到的模型选择器、启用条件和include指令属于必要证据链，必须各自保留为单源主张。不凭记忆补缺口。经下一步核验通过的主张将原样组成最终答案。'
VERIFY='请逐项核验刚才的答复草稿。程序结果只检查坐标与已读范围；你须仅根据附加的claim_evidence_packet，判断每项所引原文是否真正支持完整主张，尤其是角色、路径/位置、跨源对应、默认值、启用状态和必要条件。不得用该主张引用范围之外的聊天历史、目录列表、其他主张引用或记忆补全证据。若主张列举多个文件、字段、数值或对象，每个列举项都必须在该主张自己的精确引用原文中出现；仅引用一个文件的文件头、一个字段或一侧数值，不能支持完整目录清单、多对象列表或比较结论。若一句包含多个独立事实而引用只支持其中一部分，必须判为false。输出简短JSON：{claims:[{index:整数,supported:true或false,reason:"不超过20字的原文理由"}]}。每项恰好判定一次，不漏项；不能确定则false。不要添加新主张或改写草稿。'
MAX_VERIFICATION_QUOTE_CHARS=4000


def relation_complete_needs(question, needs):
    """Add generic relation slots for manual-formula-to-tutorial-value questions.

    The language model may ask only for the two endpoint facts.  The graph
    query must still expose the case-local selector and include/reference
    chain needed to justify that those endpoints belong together.  This is a
    query-local rule over the natural question, not a fitted vocabulary or an
    external retrieval index.
    """
    result = list(needs)
    folded = str(question or "").casefold()
    has_case = any(cue in folded for cue in ("教程", "算例", "tutorial", "case"))
    has_formula = any(cue in folded for cue in (
        "公式", "怎么算", "随温度", "模型", "formula", "calculate", "with temperature", "model",
    ))
    has_instance_value = any(cue in folded for cue in (
        "实际", "取值", "哪个文件", "哪里", "actual", "value", "which file", "where",
    ))
    if has_case and has_formula and has_instance_value:
        required = (
            "教程实例的模型选择配置（如phaseProperties/thermoType）及模型名或启用条件",
            "教程实例中包含或引用thermo/transport实际参数文件的include/引用指令",
        )
        folded_needs = " ".join(str(value).casefold() for value in result)
        for value in required:
            relation = "include" if "include" in value else "模型"
            if relation not in folded_needs and len(result) < 8:
                result.append(value)
                folded_needs += " " + value.casefold()
    return result


class NumberedSession(base.Session):
    def source_item(self,path,start,end):
        return {'path':path,'start':start,'end':end,
                'evidence_id':qa.digest(qa.wire([self.e.manifest[path]['sha256'],path,start,end]))[:24],
                'text':'\n'.join(f'{n}: {self.e.files[path][n-1]}' for n in range(start,end+1)),
                'complete_range':True,'line_numbered':True}

    def observe(self,result):
        items=list(result.get('items',[]));raw_evidence=result.get('evidence',{})
        for item in (raw_evidence.values() if isinstance(raw_evidence,dict) else []):
            items.append({**item,'path':result['sources'][item['source']],'line_numbered':True})
        for item in items:
            if not item.get('text') or item.get('path') not in self.e.files:continue
            path,start,end=item['path'],item['start'],item['end']
            if not 1<=start<=end<=len(self.e.files[path]):raise ValueError('invalid original evidence range')
            expected='\n'.join(f'{n}: {self.e.files[path][n-1]}' for n in range(start,end+1))
            if item.get('line_numbered') and item['text'].rstrip('\n')!=expected.rstrip('\n'):
                raise ValueError('numbered evidence differs from corpus')
            if not item.get('line_numbered'):raise ValueError('unrecognized evidence representation')
            self.seen.setdefault(path,{}).update({str(n):self.e.files[path][n-1] for n in range(start,end+1)})


def prompt(options):
    exploration=int(options.get('exploration_decisions',6))
    result=(qa.COMMON.replace('最多8次决策','最多8次模型决策')
            if exploration==6 else
            qa.COMMON.replace('最多8次决策',f'最多{exploration}次检索模型决策'))
    result+='locate调用格式：{action:"locate",translation:"可选忠实英文翻译",query:"本轮需补充的材料",needs:["尚缺的答案槽位"],reason:"理由"}。若问题出现案例名、求解器名、文件名或配置标识符，translation和query必须原样保留这些字面标识符（可在旁边补英文含义），不得只做意译。对于自然语言领域概念，可在translation中补充你高置信的常用化学式、字段名或配置名作为检索提示；提示本身不是答案证据，最终事实仍须由返回原文支持。第一步优先locate。只有原文支持事实；关系标签不证明条件满足或执行成功。\n'
    if options['navigation_only']:
        result+='locate只返回图节点、遍历关系和原始来源候选，不返回原文且不能作为答案证据。候选卡中的node/parent/children和关系端点标签都是图内的紧凑导航元数据；优先根据题目指定的案例、文件、字典路径及节点value选择，不要根据不相干案例中相同字段名猜测。必须从candidates中选择1到6个候选后调用{action:"read_sources",candidate_ids:["候选id"],reason:"选择理由"}批量读取权威原文；选择时应覆盖needs中的每个缺口，并在问题同时需要手册与教程、默认值与实例值或配置与条件时保留两侧候选。read_sources返回的text带逐行行号。图内value只用于选源，不得直接引用任何导航元数据。\n'
        context_lines=int(options.get('source_context_lines',0))
        if context_lines:
            result+=(f'read_sources会在字符预算允许时，为每个已选来源附带前后最多{context_lines}行的权威原文上下文；'
                    '上下文只帮助理解字典、条件和跨行配置，引用时仍应收窄到真正支持主张的精确行。\n')
    else:
        result+='locate返回混合检索证据组；sources把来源ID映射为路径，evidence为带逐行行号的原文。\n'
    if options['with_gap']:
        result+='每轮根据已读证据维护needs，明确还缺哪一侧来源、角色、条件或精确配置位置；locate会避免已返回组。不要重复检索已经完整支持的内容。\n'
        result+='只要仍有跨文件、手册与实例两侧或包含关系缺口，应继续调用locate并把每个缺口分别写入needs；search/source只用于核验locate已经给出的路径，不要用普通文本搜索替代图关系追踪。\n'
        result+='当问题把手册中的模型公式与教程中的实际参数联系起来时，needs必须把“模型选择器或启用条件”和“include/引用到参数文件的链”分别列为缺口；即使题面没有说出这些字段，也不能在只找到公式和末端数值后结束检索。\n'
    if options['with_claim_verification']:
        if exploration==6:
            result+='其中最多6次用于探索，保留2次模型决策给主张计划和草稿的语义核验。最终草稿最多2400输出token，只有已读引用及语义核验均通过的主张才会原样提交。原文返回预算预留800字符用于程序引用检查，总额仍为24000。\n'
        else:
            result+=f'其中最多{exploration}次用于探索，之后执行主张计划、草稿和语义核验。最终草稿最多2400输出token，只有已读引用及语义核验均通过的主张才会原样提交。原文返回预算预留800字符用于程序引用检查，总额仍为24000。\n'
    return result


def decode(choice):
    if choice.get('finish_reason')!='stop':return None
    try:
        value=qa.decode_json_prefix(choice['message'].get('content') or '')
        return value if isinstance(value,dict) else None
    except (ValueError,TypeError):return None


def check_plan(plan,seen):
    invalid=[];count=0;claim_count=0
    if not isinstance(plan,dict) or not isinstance(plan.get('claims'),list):
        return {'schema_valid':False,'reason':'missing_or_truncated_claim_plan','all_ranges_valid':False}
    for ci,claim in enumerate(plan['claims']):
        claim_count+=1
        refs=claim.get('references') if isinstance(claim,dict) else None
        if not isinstance(refs,list) or not refs:
            invalid.append([ci,-1]);continue
        for ri,ref in enumerate(refs):
            count+=1
            if not isinstance(ref,dict):invalid.append([ci,ri]);continue
            path,a,b=ref.get('path'),ref.get('start'),ref.get('end')
            lines=seen.get(path,{}) if isinstance(path,str) else {}
            last=max((int(n) for n in lines),default=0)
            valid=type(a) is int and type(b) is int and 1<=a<=b<=last
            if valid:valid=all(str(n) in lines for n in range(a,b+1))
            if not valid:invalid.append([ci,ri])
    result={'schema_valid':True,'claims':claim_count,'references':count,'all_ranges_valid':bool(count) and not invalid,
            'invalid_count':len(invalid),'invalid_reference_indices':invalid[:12],
            'check':'coordinates_and_seen_lines_only_not_semantic_entailment'}
    if len(qa.wire(result))>800:raise AssertionError('citation checker budget')
    return result


def claim_evidence_packet(draft, seen):
    """Bind each draft claim to only its own exact, already-seen citation text.

    The semantic verifier previously had to recover the cited lines from a long
    conversation containing catalog output and evidence for other claims.  That
    let it incorrectly approve broad directory lists and comparisons from one
    narrow citation.  This packet is deterministic, query-local, and contains
    no corpus material beyond the lines already returned under the public
    retrieval budget.
    """
    claims=draft.get('claims') if isinstance(draft,dict) else None
    if not isinstance(claims,list):return {'claims':[],'schema_valid':False}
    packet=[]
    for index,claim in enumerate(claims):
        item={'index':index,'text':claim.get('text') if isinstance(claim,dict) else None,'references':[]}
        refs=claim.get('references') if isinstance(claim,dict) else None
        for ref in refs if isinstance(refs,list) else []:
            bound={k:ref.get(k) for k in ('path','start','end')} if isinstance(ref,dict) else {'invalid_reference':True}
            path,start,end=bound.get('path'),bound.get('start'),bound.get('end')
            lines=seen.get(path,{}) if isinstance(path,str) else {}
            valid=(type(start) is int and type(end) is int and 1<=start<=end
                   and all(str(number) in lines for number in range(start,end+1)))
            if valid:
                quote='\n'.join(f'{number}: {lines[str(number)]}' for number in range(start,end+1))
                if len(quote)<=MAX_VERIFICATION_QUOTE_CHARS:bound['quote']=quote
                else:bound['invalid_reason']='citation_range_too_broad_for_semantic_verification'
            else:bound['invalid_reason']='citation_not_in_already_seen_lines'
            item['references'].append(bound)
        packet.append(item)
    return {'schema':'claim-evidence-packet-v1','schema_valid':True,'claims':packet,
            'policy':'each claim may use only its own exact quoted references; no cross-claim or catalog completion'}


def release_verified(draft,verdict,seen):
    """No model generates new prose after this check: only approved, cited claim text is released."""
    claims=draft.get('claims') if isinstance(draft,dict) else None
    votes=verdict.get('claims') if isinstance(verdict,dict) else None
    # The prompt asks for at most ten claims.  Accept up to twelve as a narrow
    # fail-safe when the provider slightly overruns that presentation limit;
    # every claim still needs a complete verifier vote and valid seen citation.
    if not isinstance(claims,list) or not isinstance(votes,list) or len(claims)>12:
        return {'answer':'','references':[],'unknowns':['草稿或语义核验未完整返回']},False
    indices=[v.get('index') for v in votes if isinstance(v,dict)]
    if any(type(i) is not int for i in indices) or len(votes)!=len(claims) or len(set(indices))!=len(claims) or set(indices)!=set(range(len(claims))):
        return {'answer':'','references':[],'unknowns':['语义核验未覆盖全部主张']},False
    by_index={v['index']:v for v in votes}
    unknowns=draft.get('unknowns',[])
    if not isinstance(unknowns,list) or any(not isinstance(s,str) for s in unknowns):
        return {'answer':'','references':[],'unknowns':['草稿未知项格式无效']},False
    texts=[];refs=[];unknowns=list(unknowns)
    for i,claim in enumerate(claims):
        v=by_index[i]
        if type(v.get('supported')) is not bool or not isinstance(claim,dict) or not isinstance(claim.get('text'),str):
            return {'answer':'','references':[],'unknowns':['草稿或核验格式无效']},False
        ranges=check_plan({'claims':[claim]},seen)
        if v['supported'] and ranges['all_ranges_valid']:
            texts.append(claim['text'])
            refs.extend({**ref,'supports':claim['text']} for ref in claim['references'])
        else:unknowns.append(f"未证实第{i+1}项："+str(v.get('reason','引用未通过核验')))
    return {'answer':'\n'.join(texts),'references':refs,'unknowns':unknowns},True


class Session(NumberedSession):
    def __init__(self,engine,method,question):
        super().__init__(engine,method,question)
        self.options=engine.options;self.seen_groups=set();self.needs=[]
        self.candidate_sources={}

    def restore(self,action,result):
        self.observe(result)
        self.seen_requests.add(qa.wire({k:v for k,v in action.items() if k!='reason'}))
        if self.options['with_gap']:
            self.seen_groups.update(g['id'] for g in result.get('groups',[]))
            self.seen_groups.update(g['id'] for g in result.get('candidates',[]))
            if isinstance(action.get('needs'),list):
                self.needs=relation_complete_needs(self.question,action['needs'])
        for candidate in result.get('candidates',[]):
            candidate_id=candidate.get('id') if isinstance(candidate,dict) else None
            sources=candidate.get('sources') if isinstance(candidate,dict) else None
            if isinstance(candidate_id,str) and isinstance(sources,list):
                self.candidate_sources[candidate_id]=sources

    def contextual_source_items(self, ranges, context_lines):
        """Expand selected original ranges fairly, then merge overlaps per file."""
        by_path={};path_order=[]
        for path,start,end in ranges:
            if path not in by_path:
                by_path[path]=[];path_order.append(path)
            by_path[path].append((
                max(1,start-context_lines),
                min(len(self.e.files[path]),end+context_lines),
            ))
        items=[]
        for path in path_order:
            merged=[]
            for start,end in sorted(by_path[path]):
                if merged and start<=merged[-1][1]+1:
                    merged[-1]=(merged[-1][0],max(merged[-1][1],end))
                else:merged.append((start,end))
            items.extend(self.source_item(path,start,end) for start,end in merged)
        return items

    def read_sources(self,action,cap):
        begin=time.monotonic();self.calls['read_sources']+=1
        identity=qa.wire({k:v for k,v in action.items() if k!='reason'})
        repeat=identity in self.seen_requests;self.seen_requests.add(identity)
        try:
            candidate_ids=action.get('candidate_ids')
            if (not isinstance(candidate_ids,list) or not 1<=len(candidate_ids)<=6
                    or any(not isinstance(value,str) for value in candidate_ids)):
                raise ValueError('candidate_ids must contain one to six candidate ids')
            if len(set(candidate_ids))!=len(candidate_ids):
                raise ValueError('duplicate candidate id')
            missing=[value for value in candidate_ids if value not in self.candidate_sources]
            if missing:raise ValueError('unknown candidate id')
            ranges=[];coordinates=set();read_paths=set()
            for candidate_id in candidate_ids:
                for source in self.candidate_sources[candidate_id]:
                    path,start,end=(source.get('path'),source.get('start'),source.get('end'))
                    if (path not in self.e.files or type(start) is not int or type(end) is not int
                            or not 1<=start<=end<=len(self.e.files[path])):
                        raise ValueError('invalid candidate source range')
                    coordinate=(path,start,end)
                    if coordinate in coordinates:continue
                    coordinates.add(coordinate)
                    if path not in read_paths:
                        raw=(self.e.corpus/path).read_bytes()
                        if qa.digest(raw)!=self.e.manifest[path]['sha256']:
                            raise ValueError('source changed')
                        read_paths.add(path)
                    ranges.append(coordinate)
            requested_context=int(self.options.get('source_context_lines',0))
            if not 0<=requested_context<=80:
                raise ValueError('source_context_lines must be between zero and 80')
            result=None;applied_context=0;contextual_fit=False
            if requested_context:
                # Use one shared window so no selected source silently receives a
                # larger context allowance than another.  Shrink deterministically
                # until every selected range fits the current response budget.
                for window in range(requested_context,-1,-1):
                    expanded=self.contextual_source_items(ranges,window)
                    proposed={'status':'ok','items':expanded,'next_offset':None,
                              'selected_candidate_ids':candidate_ids,
                              'context_lines_requested':requested_context,
                              'context_lines_applied':window}
                    if len(qa.wire(proposed))<=cap:
                        result=proposed;applied_context=window;contextual_fit=True;break
            items=[self.source_item(path,start,end) for path,start,end in ranges]
            if result is None:
                result={'status':'ok','items':[],'next_offset':None,
                        'selected_candidate_ids':candidate_ids}
                if requested_context:
                    result.update(context_lines_requested=requested_context,
                                  context_lines_applied=0)
            for index,item in enumerate(items[:30]):
                if contextual_fit:
                    break
                proposed={**result,'items':result['items']+[item],
                          'next_offset':index+1 if index+1<len(items) else None}
                if len(qa.wire(proposed))>cap:
                    result['next_offset']=index
                    if not result['items']:result['status']='item_exceeds_budget'
                    break
                result=proposed
            self.observe(result)
            accounting={'seconds':time.monotonic()-begin,'repeat':repeat,
                        'content':{'source_file_read_operations':len(read_paths),
                                   'source_ranges_requested':len(items),
                                   'source_ranges_returned':len(result['items']),
                                   'source_context_lines_requested':requested_context,
                                   'source_context_lines_applied':applied_context},
                        'candidate_audit':None,'initialization':None,
                        'initialization_time_included':False,
                        'actual_graph_loaded':self.e.graph_path is not None}
            return result,accounting
        except (ValueError,TypeError,KeyError) as error:
            result={'status':'tool_error','reason':str(error)[:160]}
            return result,{'seconds':time.monotonic()-begin,'repeat':repeat,'content':{},
                           'candidate_audit':None,'initialization':None,
                           'initialization_time_included':False,
                           'actual_graph_loaded':self.e.graph_path is not None}

    def dispatch(self,action,cap):
        if action.get('action')=='read_sources':return self.read_sources(action,cap)
        if action.get('action')!='locate':return super().dispatch(action,cap)
        begin=time.monotonic();identity=qa.wire({k:v for k,v in action.items() if k!='reason'})
        repeat=identity in self.seen_requests;self.seen_requests.add(identity);self.calls['locate']+=1
        audit=None;init=None
        try:
            translation=action.get('translation','');gap=action.get('query','');needs=action.get('needs',[])
            if not isinstance(translation,str) or not isinstance(gap,str) or not isinstance(needs,list) or len(needs)>8 or any(not isinstance(n,str) or len(n)>120 for n in needs):
                raise ValueError('invalid translation/query/needs')
            if self.options['with_gap']:
                self.needs=relation_complete_needs(self.question,needs)
            with self.e.graph_lock:
                if self.e.backend is None:
                    self.e.backend=EvidenceEngine(self.e.corpus,self.e.graph_path)
                    init=self.e.backend.initialization
                    qa.write(self.e.run/f'candidate-initialization-{time.time_ns()}.json',init)
                result,audit=self.e.backend.query(self.question,translation=translation,
                    gap=gap if self.options['with_gap'] else '',slots=self.needs,
                    seen_groups=self.seen_groups if self.options['with_gap'] else (),cap=cap,
                    response_mode='navigation' if self.options['navigation_only'] else 'evidence',
                    navigation_extra_candidates=self.options.get('navigation_extra_candidates',0),
                    **{k:self.options[k] for k in ['with_scope','with_cross','with_paths','with_groups','with_gap']})
            self.restore(action,result)
        except (ValueError,TypeError,KeyError) as error:
            result={'status':'tool_error','reason':str(error)[:160]}
        if len(qa.wire(result))>cap:raise AssertionError('shared returned budget')
        return result,{'seconds':time.monotonic()-begin,'repeat':repeat,'content':audit['recall'].get('work',{}) if audit else {},
                       'candidate_audit':audit,'initialization':init,'initialization_time_included':init is not None,
                       'actual_graph_loaded':self.e.graph_path is not None}


class Engine(base.Engine):
    def __init__(self,run,variant,graph_path,options=None):
        super().__init__(run,variant)
        self.graph_path=Path(graph_path)
        self.options={**DEFAULTS,**(options or {})}


def run_one(engine,question,method,key,replicate=1,replay=False):
    folder=engine.run/'sessions'/f"{question['id']}--{method}--r{replicate}"
    session_type=getattr(engine,'session_type',Session)
    prompt_function=getattr(engine,'prompt_function',prompt)
    session=session_type(engine,method,question['question']);options=engine.options
    messages=[{'role':'system','content':prompt_function(options)},{'role':'user','content':question['question']}]
    events=[];used=0;reserve=800 if options['with_claim_verification'] else 0
    exploration=(int(options.get('exploration_decisions',6))
                 if options['with_claim_verification'] else 8)
    if not 1<=exploration<=8:raise ValueError('exploration_decisions must be one to eight')
    def fetch(name,extra=None,final=False):
        body=qa.request(messages+([{'role':'user','content':extra}] if extra else []),final=final)
        response=base.fetch(folder,name,body,None if replay else key)
        return qa.choice(response)
    for step in range(1,exploration+1):
        cap=min(6000,24000-used-reserve)
        if cap<400:break
        c=fetch(f'step-{step:02}');content=c['message'].get('content') or '';action=qa.decode_action(c)
        messages.append({'role':'assistant','content':content})
        event={'step':step,'action':action,'response_file':f'step-{step:02}.json'}
        if action.get('action')=='finish':events.append(event);break
        saved=folder/'tool_events'/f'step-{step:02}.json'
        if saved.exists() and not replay:
            old=qa.read(saved)
            if old['action']!=action:raise ValueError('saved candidate tool request changed')
            result,accounting=old['result'],old['accounting'];session.restore(action,result)
        else:result,accounting=session.dispatch(action,cap)
        returned=qa.wire(result);used+=len(returned)
        event.update(result=result,accounting=accounting,returned_characters=len(returned));events.append(event)
        if not replay:qa.write(saved,event)
        suffix=f'\nRemaining retrieval decisions: {exploration-step}; remaining returned characters: {24000-used-reserve}'
        if options['with_gap']:suffix+='\nCurrent unresolved slots: '+qa.wire(session.needs)
        # Slot state is model-authored metadata, not extra corpus evidence.
        messages.append({'role':'user','content':'Tool result: '+returned+suffix})
    plan=None;verification=None;plan_checks=None
    if options['with_claim_verification']:
        c=fetch('plan',PLAN);plan=decode(c)
        messages.extend([{'role':'user','content':PLAN},{'role':'assistant','content':c['message'].get('content') or ''}])
        draft_choice=fetch('final',DRAFT,final=True);draft=decode(draft_choice)
        messages.extend([{'role':'user','content':DRAFT},{'role':'assistant','content':draft_choice['message'].get('content') or ''}])
        plan_checks=check_plan(draft,session.seen);used+=len(qa.wire(plan_checks))
        messages.append({'role':'user','content':'Tool result: '+qa.wire(plan_checks)})
        evidence_packet=claim_evidence_packet(draft,session.seen)
        verify_request=VERIFY+'\nclaim_evidence_packet: '+qa.wire(evidence_packet)
        c=fetch('claim-check',verify_request);verification=decode(c)
        messages.extend([{'role':'user','content':verify_request},{'role':'assistant','content':c['message'].get('content') or ''}])
        parsed,verified=release_verified(draft,verification,session.seen)
        answer=qa.wire(parsed);c=draft_choice
    else:
        c=fetch('final',qa.FINAL,final=True);answer=c['message'].get('content') or '';parsed=decode(c);verified=parsed is not None
    final_checks=check_plan({'claims':[{'references':parsed.get('references',[])}]},session.seen) if parsed else {'all_ranges_valid':False}
    result={'id':question['id'],'item_id':question['item_id'],'method':method,'replicate':replicate,
        'question':question['question'],'events':events,'answer':answer,'parsed_answer':parsed,
        'status':'complete' if qa.valid_answer(parsed) and verified else 'incomplete_answer','finish_reason':c.get('finish_reason'),
        'seen_lines':session.seen,'returned_characters':used,
        'first_policy_complied':bool(events and events[0]['action'].get('action')=='locate'),
        'claim_plan':plan,'plan_citation_checks':plan_checks,'claim_evidence_packet':evidence_packet if options['with_claim_verification'] else None,
        'claim_verification':verification,
        'final_citation_checks':final_checks,'unresolved_slots':session.needs,'options':options,
        'budget_identity':{'maximum_model_calls':exploration+3,
                           'maximum_generated_tokens':exploration*700+3800,
                           'returned_characters':24000,
                           'retrieval_decisions':exploration,'reserved_check_decisions':2 if options['with_claim_verification'] else 0},
        'graph_used':engine.graph_path is not None}
    if used>24000:raise AssertionError('total returned budget')
    if replay:
        old=qa.read(folder/'result.json')
        def comparable(row):return {**row,'events':[{k:v for k,v in e.items() if k!='accounting'} for e in row['events']]}
        if comparable(old)!=comparable(result):raise ValueError('candidate zero-model replay mismatch')
    else:qa.write(folder/'result.json',result)
    return result
