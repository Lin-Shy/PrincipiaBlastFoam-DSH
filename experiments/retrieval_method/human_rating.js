'use strict';
// 本文件由生成器内嵌；页面不加载外部脚本，不调用模型。
const RatingCore = (() => {
  const fields = ['schema','binding','reviewer','rows','created_at','finalized_at','revision_phase','parent_seal_sha256'];
  const canonical = v => {
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    if (v !== null && typeof v === 'object') return '{' + Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',') + '}';
    return JSON.stringify(v);
  };
  const validScore = v => v === 'uncertain' || Number.isInteger(v) && v >= 1 && v <= 5;
  const complete = row => validScore(row.claim_correctness) && validScore(row.citation_support);
  const payload = d => Object.fromEntries(fields.map(k=>[k,d[k]]));
  async function hash(text) {
    if (!globalThis.crypto?.subtle) throw Error('当前浏览器不支持文件校验，请使用近期版本的Chrome、Edge或Firefox。');
    const bytes = typeof text === 'string' ? new TextEncoder().encode(text) : text;
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)), x=>x.toString(16).padStart(2,'0')).join('');
  }
  function time(value) {
    if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw Error('时间格式无效');
    return Date.parse(value);
  }
  async function validate(d, binding, ids) {
    if (!d || d.schema !== 'chapter2-human-rating-v1' || canonical(d.binding) !== canonical(binding)) throw Error('结果版本或冻结输入哈希不符');
    if (!['draft','sealed'].includes(d.status)) throw Error('结果状态非法');
    if (!d.reviewer || typeof d.reviewer.id !== 'string' || !d.reviewer.id.trim()) throw Error('结果缺少审阅者代号');
    for (const k of ['participated_in_development','previously_exposed']) {
      if (typeof d.reviewer[k] !== 'boolean' && !(d.status === 'draft' && d.reviewer[k] === null)) throw Error('审阅者背景字段无效');
    }
    if (!Array.isArray(d.rows) || d.rows.length !== ids.length || new Set(d.rows.map(r=>r.blind_id)).size !== ids.length || d.rows.some(r=>!ids.includes(r.blind_id))) throw Error('必须保留48份样本，不得增删或重复');
    const created = time(d.created_at);
    for (const row of d.rows) {
      for (const k of ['claim_correctness','citation_support']) if (!validScore(row[k]) && !(d.status === 'draft' && row[k] === null)) throw Error('非法分值：' + row.blind_id);
      if (typeof row.notes !== 'string') throw Error('备注必须为文本，可留空');
      if (row.updated_at !== null) time(row.updated_at);
      else if (row.claim_correctness !== null || row.citation_support !== null) throw Error('已评分记录缺少时间');
    }
    if (!['blind','post_unblind'].includes(d.revision_phase)) throw Error('修订阶段非法');
    if (d.revision_phase === 'blind' && d.parent_seal_sha256 !== null || d.revision_phase === 'post_unblind' && !/^[a-f0-9]{64}$/.test(d.parent_seal_sha256 || '')) throw Error('修订版本绑定无效');
    if (d.status === 'sealed') {
      const finalized = time(d.finalized_at);
      if (finalized < created || d.rows.some(r=>time(r.updated_at)>finalized)) throw Error('封存时间先于评分时间');
      if (d.sealed_payload_sha256 !== await hash(canonical(payload(d)))) throw Error('封存内容校验失败');
    } else if (d.finalized_at !== null || d.sealed_payload_sha256 !== null) throw Error('草稿不能声称已封存');
    return d;
  }
  function distribution(rows, key) {
    const values=rows.map(r=>r[key]), numeric=values.filter(Number.isInteger);
    return {counts:Object.fromEntries([1,2,3,4,5].map(v=>[v,values.filter(x=>x===v).length])),valid_scores:numeric.length,uncertain:values.filter(x=>x==='uncertain').length,mean:numeric.length?numeric.reduce((a,b)=>a+b,0)/numeric.length:null};
  }
  function csv(d) {
    const fields=['blind_id','reviewer_id','claim_correctness','citation_support','notes','updated_at','revision_phase','sealed_payload_sha256','sample_sha256'];
    const cell=v=>{let s=String(v??'');if (/^\s*[=+\-@]/.test(s)) s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
    return '\ufeff'+[fields.map(cell).join(','),...d.rows.map(r=>[r.blind_id,d.reviewer.id,r.claim_correctness,r.citation_support,r.notes,r.updated_at,d.revision_phase,d.sealed_payload_sha256,d.binding.sample_sha256].map(cell).join(','))].join('\r\n')+'\r\n';
  }
  return {canonical,validScore,complete,payload,hash,validate,distribution,csv};
})();
if (typeof module !== 'undefined') module.exports=RatingCore;
if (typeof document !== 'undefined') (() => {
  const data=JSON.parse(document.getElementById('review-data').textContent), ids=data.cases.map(c=>c.blind_id), $=id=>document.getElementById(id);
  const now=()=>new Date().toISOString(), clone=v=>JSON.parse(JSON.stringify(v));
  const prefix='ch2-rating:'+data.binding.sample_sha256+':'+data.binding.scores_sha256+':';
  let state={schema:data.schema,binding:data.binding,reviewer:{id:'',participated_in_development:null,previously_exposed:null},
    rows:ids.map(blind_id=>({blind_id,claim_correctness:null,citation_support:null,notes:'',updated_at:null})),created_at:now(),finalized_at:null,
    revision_phase:'blind',parent_seal_sha256:null,status:'draft',sealed_payload_sha256:null};
  let index=0, dimension='claim_correctness', unblind=null, exported=false, busy=false, cacheFailed=false, pendingImport=null, activeTab='review';
  const current=()=>state.rows.find(r=>r.blind_id===ids[index]);
  const elem=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const announce=(text,error=false)=>{ $('message').textContent=text;$('message').className=error?'error':''; };
  const locked=()=>state.status==='sealed'||busy;
  function save() {
    if (!state.reviewer.id.trim()) {announce('先填写审阅者代号再缓存；也可下载草稿备份。');return;}
    try {
      localStorage.setItem(prefix+'record:'+state.reviewer.id.trim(),JSON.stringify(state));
      localStorage.setItem(prefix+'last',state.reviewer.id.trim());
      if (!cacheFailed) announce(state.status==='sealed'?'本版本已封存，只读。':'已缓存进度；请定期下载草稿JSON。');
    } catch {cacheFailed=true;announce('浏览器缓存不可用，请下载草稿JSON备份。',true);}
  }
  function download(text,name,type='application/json') {
    const url=URL.createObjectURL(new Blob([text],{type})), a=elem('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
  function filename(ext) {
    const id=state.reviewer.id.replace(/[^\p{L}\p{N}_-]/gu,'_').slice(0,50)||'reviewer';
    return '人工评分_'+id+'_'+state.revision_phase+'_'+state.status+'_'+now().replace(/[:.]/g,'-')+'.'+ext;
  }
  function exportJSON() {download(JSON.stringify(state,null,2)+'\n',filename('json'));if(state.status==='sealed')exported=true;renderControls();}
  function profileValid() {
    if(!state.reviewer.id.trim())throw Error('请填写审阅者代号');
    if(['participated_in_development','previously_exposed'].some(k=>typeof state.reviewer[k]!=='boolean'))throw Error('请填写两项审阅者背景信息');
  }
  function score(key,value) {
    if(locked())return;dimension=key;current()[key]=value;current().updated_at=now();save();render();
  }
  function renderControls() {
    const count=state.rows.filter(RatingCore.complete).length;
    $('progress-label').textContent=`已完成 ${count} / 48`;$('progress').value=count;
    $('mode').textContent=state.revision_phase==='post_unblind'?(locked()?'解盲后修订 · 已封存':'解盲后修订'):state.status==='sealed'?'已封存':'盲审';
    $('reviewer').value=state.reviewer.id;$('development').value=state.reviewer.participated_in_development===null?'':String(state.reviewer.participated_in_development);$('exposed').value=state.reviewer.previously_exposed===null?'':String(state.reviewer.previously_exposed);
    for(const id of ['reviewer','development','exposed','notes'])$(id).disabled=locked();
    $('draft').textContent=state.status==='sealed'?'重新下载封存JSON':'下载草稿JSON';$('draft').disabled=busy;
    $('import').disabled=busy;$('csv').disabled=busy;$('revision').disabled=busy;
    $('seal').disabled=count!==48||locked();$('unblind').disabled=state.status!=='sealed'||!exported||busy;
    $('revision').hidden=!(unblind&&state.status==='sealed');$('comparison-tab').hidden=!unblind;
    $('previous').disabled=index===0;$('next').disabled=index===ids.length-1;$('next-pending').disabled=count===48;
  }
  function addEvidence(target,atoms,reference=false) {
    target.replaceChildren();
    if(!atoms.length){target.append(elem('p',reference?'没有可验证的结构化引用，请结合回答判断。':'没有必要证据。','muted'));return;}
    for(const a of atoms) {
      const detail=elem('details'), summary=elem('summary',`${reference?'引用['+a.index+'] · ':''}${a.path} L${a.start}–L${a.end}`);
      detail.append(summary);
      if(reference)detail.append(elem('p','断言：'+a.claim,'verbatim'));
      detail.append(elem('div',a.quote,'quote'),elem('p','SHA-256：'+(a.sha256||a.source_sha256||'未提供'),'meta'));
      detail.open=atoms.length<=2;target.append(detail);
    }
  }
  function renderList() {
    const list=$('case-list');list.replaceChildren();
    ids.forEach((id,i)=>{const row=state.rows.find(r=>r.blind_id===id),done=RatingCore.complete(row),f=$('filter').value;
      if(f==='done'&&!done||f==='pending'&&done)return;
      const b=elem('button',`${done?'✓':'○'} ${String(i+1).padStart(2,'0')} · ${id}`);b.setAttribute('aria-current',i===index?'true':'false');b.onclick=()=>{index=i;render();};list.append(b);
    });
    if(!list.childElementCount)list.append(elem('p','此筛选下没有样本','muted'));
  }
  const rubrics={claim_correctness:['主要错误或未回答','明显错误或遗漏','部分正确但有重要缺口','基本完整正确，有轻微问题','全部必要事实完整正确'],citation_support:['无有效支持','多数重要断言未获支持','部分支持，存在重要缺口','主要断言获支持，有轻微问题','全部需引用断言均获支持']};
  function renderRatings() {
    $('ratings').replaceChildren();
    for(const key of ['claim_correctness','citation_support']) {
      const box=elem('div',undefined,'rating'),title=elem('h3',(key==='claim_correctness'?'事实完整正确性':'引用支持性')+(dimension===key?' · 当前快捷键维度':''));
      const buttons=elem('div',undefined,'scores');buttons.setAttribute('role','group');buttons.setAttribute('aria-label',title.textContent);
      for(const v of [1,2,3,4,5,'uncertain']){const b=elem('button',v==='uncertain'?'无法判断':String(v));b.title=v==='uncertain'?'保留无法判断，不计入均分':rubrics[key][v-1];b.setAttribute('aria-pressed',current()[key]===v?'true':'false');b.disabled=locked();b.onclick=()=>score(key,v);buttons.append(b);}
      box.append(title,buttons,elem('p',rubrics[key].map((r,i)=>`${i+1} ${r}`).join('；'),'rubric'));$('ratings').append(box);
    }
    $('notes').value=current().notes;$('row-status').textContent=RatingCore.complete(current())?'本份已完成；备注可空。':'请选择两项分数，或明确选择“无法判断”。';
  }
  function render() {
    renderControls();renderList();const c=data.cases[index];$('case-title').textContent=`${index+1} / 48 · ${c.blind_id}`;
    if(unblind){const row=unblind.rows.find(r=>r.blind_id===c.blind_id);$('case-title').textContent+=' · '+unblind.labels[row.identity.arm];}
    $('question').textContent=c.question;$('answer').textContent=c.answer_text;
    $('requirements').replaceChildren(...c.gold_points.map(p=>elem('p',`[${p.index}] ${p.requirement}`)));
    $('constraints').replaceChildren();for(const [key,label] of [['allowed','允许回答'],['forbidden','禁止误解'],['ambiguity','歧义说明']])$('constraints').append(elem('h3',label),elem('div',Array.isArray(c[key])?c[key].map(v=>typeof v==='string'?v:JSON.stringify(v)).join('\n'):JSON.stringify(c[key],null,2),'verbatim'));
    addEvidence($('evidence'),c.gold_evidence);addEvidence($('references'),c.references,true);renderRatings();
    if(unblind)renderComparison();switchTab(activeTab);
  }
  function switchTab(tab) {activeTab=tab==='comparison'&&unblind?'comparison':'review';$('review').hidden=activeTab!=='review';$('comparison').hidden=activeTab!=='comparison';$('review-tab').classList.toggle('section-tab',activeTab==='review');$('comparison-tab').classList.toggle('section-tab',activeTab==='comparison');}
  function statText(rows,key) {const d=RatingCore.distribution(rows,key);return `${d.mean===null?'—':d.mean.toFixed(2)}（有效 ${d.valid_scores} / 无法判断 ${d.uncertain}；1–5分人数 ${Object.values(d.counts).join('/')}）`;}
  function renderComparison() {
    const table=elem('table'),head=elem('tr');for(const text of ['方法','事实评分','引用评分'])head.append(elem('th',text));table.append(head);
    const grouped=new Map();for(const row of unblind.rows){if(!grouped.has(row.identity.arm))grouped.set(row.identity.arm,[]);grouped.get(row.identity.arm).push(state.rows.find(r=>r.blind_id===row.blind_id));}
    for(const [arm,rows] of grouped){const tr=elem('tr');for(const text of [unblind.labels[arm],statText(rows,'claim_correctness'),statText(rows,'citation_support')])tr.append(elem('td',text));table.append(tr);}
    $('statistics').replaceChildren(table,elem('p','仅48采样会话的描述统计；同族相关，不计算二元一致率或推断全量收益。','muted'));
    const select=$('comparison-question'),prior=select.value;select.replaceChildren();
    const groups=new Map();for(const row of unblind.rows){const key=row.identity.question_id+' / r'+row.identity.repeat;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
    for(const [key,rows] of groups){const c=data.cases.find(c=>c.blind_id===rows[0].blind_id),o=elem('option',key+' · '+c.question);o.value=key;select.append(o);}if(groups.has(prior))select.value=prior;
    const panels=$('comparison-panels');panels.replaceChildren();for(const row of groups.get(select.value)||[]){const c=data.cases.find(c=>c.blind_id===row.blind_id),h=state.rows.find(r=>r.blind_id===row.blind_id),card=elem('article',undefined,'card');
      card.append(elem('h3',unblind.labels[row.identity.arm]),elem('p',`${row.blind_id} · 人工事实 ${h.claim_correctness==='uncertain'?'无法判断':h.claim_correctness??'未评分'} / 引用 ${h.citation_support==='uncertain'?'无法判断':h.citation_support??'未评分'}`,'identity'));
      const modelLabel={failure:'失败',model_claimed_success:'模型声称成功',unknown:'未知'}[row.model.strict_outcome];
      card.append(elem('p',`原模型严格判断：${modelLabel}；引用状态：${row.model.citation_state}；未知标准数：${row.model.unknown_criteria}`,'muted'),elem('div',c.answer_text,'verbatim'));
      const detail=elem('details');detail.append(elem('summary','查看原始引用'));const refs=elem('div');addEvidence(refs,c.references,true);detail.append(refs);card.append(detail);panels.append(card);
    }
  }
  async function acceptImport(imported) {
    await RatingCore.validate(imported,data.binding,ids);
    // 一旦当前页面已解盲，不允许重新将新评分标作盲审。
    if(unblind&&imported.status==='draft'&&imported.revision_phase==='blind')throw Error('本页面已解盲；请保留封存原版或建立解盲后修订。');
    if(state.rows.some(r=>r.updated_at!==null)||state.status==='sealed'||imported.reviewer.id!==state.reviewer.id&&state.reviewer.id){
      pendingImport=imported;$('conflict-text').textContent='导入版本来自 '+imported.reviewer.id+'，状态为 '+imported.status+'。选择完整保留当前或使用导入版本；不自动合并。';$('conflict').showModal();
    }else replace(imported);
  }
  function replace(imported) {state=clone(imported);exported=false;pendingImport=null;save();render();announce(state.status==='sealed'?'已载入封存版本；请重新下载JSON后加载解盲文件。':'已导入评分，可继续审阅。');}
  async function run(task){try{await task();}catch(e){announce(e.message||String(e),true);}}
  $('notes').oninput=()=>{if(locked())return;current().notes=$('notes').value;current().updated_at=now();save();};
  $('reviewer').onchange=()=>run(async()=>{
    if(locked())return;const id=$('reviewer').value.trim();if(id===state.reviewer.id)return;
    let cached=null;try{const raw=localStorage.getItem(prefix+'record:'+id);if(raw)cached=JSON.parse(raw);}catch{}
    if(cached){await acceptImport(cached);renderControls();return;}
    if(state.rows.some(r=>r.updated_at!==null)&&state.reviewer.id){renderControls();throw Error('当前已有评分；请导出后重新打开页面，用新代号开始独立审阅。');}
    state.reviewer.id=id;save();renderControls();
  });
  for(const [id,key] of [['development','participated_in_development'],['exposed','previously_exposed']])$(id).onchange=()=>{if(locked())return;state.reviewer[key]=$(id).value===''?null:$(id).value==='true';save();};
  $('filter').onchange=renderList;$('previous').onclick=()=>{if(index>0){index--;render();}};$('next').onclick=()=>{if(index<47){index++;render();}};
  $('next-pending').onclick=()=>{for(let n=1;n<=48;n++){const i=(index+n)%48;if(!RatingCore.complete(state.rows.find(r=>r.blind_id===ids[i]))){index=i;render();break;}}};
  $('draft').onclick=()=>run(async()=>{if(!state.reviewer.id.trim())throw Error('请先填写审阅者代号');exportJSON();announce('已请求下载JSON，请确认浏览器保存成功。');});
  $('csv').onclick=()=>{download(RatingCore.csv(state),filename('csv'),'text/csv;charset=utf-8');announce('已请求下载CSV；续审和正式分析请使用JSON。');};
  $('import').onclick=()=>{$('import-file').value='';$('import-file').click();};
  $('import-file').onchange=()=>run(async()=>{const f=$('import-file').files[0];if(f)await acceptImport(JSON.parse(await f.text()));});
  $('conflict-cancel').onclick=$('conflict-keep').onclick=()=>{pendingImport=null;$('conflict').close();renderControls();};
  $('conflict-replace').onclick=()=>{const d=pendingImport;$('conflict').close();if(d)replace(d);};
  $('seal').onclick=()=>run(async()=>{profileValid();if(!state.rows.every(RatingCore.complete))throw Error('需要完成全部48份评分');$('seal-dialog').showModal();});
  $('seal-cancel').onclick=()=>$('seal-dialog').close();
  $('seal-confirm').onclick=()=>run(async()=>{
    $('seal-dialog').close();busy=true;render();
    try{const sealed=clone(state);sealed.status='sealed';sealed.finalized_at=now();sealed.sealed_payload_sha256=await RatingCore.hash(RatingCore.canonical(RatingCore.payload(sealed)));await RatingCore.validate(sealed,data.binding,ids);state=sealed;save();exportJSON();announce('已封存并请求下载JSON，请确认文件已保存后解盲。');}finally{busy=false;render();}
  });
  $('unblind').onclick=()=>{if(state.status!=='sealed'||!exported)return;$('unblind-file').value='';$('unblind-file').click();};
  $('unblind-file').onchange=()=>run(async()=>{
    if(state.status!=='sealed'||!exported)throw Error('先完成48份并下载封存JSON');
    const f=$('unblind-file').files[0];if(!f)return;const bytes=await f.arrayBuffer();if(await RatingCore.hash(bytes)!==data.unblind_sha256)throw Error('解盲文件哈希不符');
    const d=JSON.parse(new TextDecoder().decode(bytes));if(d.schema!=='chapter2-human-rating-unblind-v1'||RatingCore.canonical(d.binding)!==RatingCore.canonical(data.binding)||d.rows.length!==48||new Set(d.rows.map(r=>r.blind_id)).size!==48||d.rows.some(r=>!ids.includes(r.blind_id)))throw Error('解盲文件样本不符');
    unblind=d;activeTab='comparison';render();announce('已解盲；封存评分只读，修改需建立解盲后修订。');
  });
  $('revision').onclick=()=>{if(!unblind||state.status!=='sealed')return;state=clone(state);state.parent_seal_sha256=state.sealed_payload_sha256;state.sealed_payload_sha256=null;state.status='draft';state.finalized_at=null;state.revision_phase='post_unblind';exported=false;activeTab='review';save();render();announce('已建立解盲后修订；请保留原封存下载文件，新版本明确标记为解盲后。');};
  $('review-tab').onclick=()=>switchTab('review');$('comparison-tab').onclick=()=>switchTab('comparison');$('comparison-question').onchange=renderComparison;
  document.addEventListener('keydown',event=>{
    if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)||event.ctrlKey||event.altKey||event.metaKey||$('conflict').open||$('seal-dialog').open||activeTab!=='review')return;
    const key=event.key.toLowerCase();if(key==='arrowleft')$('previous').click();else if(key==='arrowright')$('next').click();else if(key==='f'||key==='c'){dimension=key==='f'?'claim_correctness':'citation_support';renderRatings();}else if(/^[1-5]$/.test(key)||key==='u')score(dimension,key==='u'?'uncertain':Number(key));else return;event.preventDefault();
  });
  run(async()=>{
    try{const id=localStorage.getItem(prefix+'last'),raw=id&&localStorage.getItem(prefix+'record:'+id);if(raw){state=await RatingCore.validate(JSON.parse(raw),data.binding,ids);announce(state.status==='sealed'?'已恢复封存版本；重新下载JSON后可加载解盲文件。':'已恢复缓存，继续评分。');}}
    catch(e){cacheFailed=true;announce('缓存不可用或校验失败，请导入已下载JSON续审。',true);}
    render();
  });
})();
