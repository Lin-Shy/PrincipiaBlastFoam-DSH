"use strict";
const packet=JSON.parse(document.getElementById('packet').textContent);
const $=id=>document.getElementById(id), levels=packet.rules.levels;
const key='ch2-five-level-'+packet.packet_id;
let position=0, drafts={};
const fields=i=>i.criteria.map(c=>c.criterion_id).concat(['F'],i.conditional?['A']:[]);
function validScore(v){return typeof v==='number'&&levels.includes(v)||v==='unknown'||v===null;}
function initial(){const out={};for(const i of packet.items){const old=packet.ui.find(u=>u.sample_id===i.sample_id).legacy;const values=old?{...old.points,F:old.fact_gate}:Object.fromEntries(fields(i).map(k=>[k,null]));if(i.conditional&&old)values.A=old.applicability_gate;out[i.sample_id]={values,confirmed:Object.fromEntries(fields(i).map(k=>[k,false])),reason:'',legacy_note:old?old.reason:''};}return out;}
function validateExport(data){
 if(data.schema_version!==packet.schema_version||data.packet_id!==packet.packet_id)throw Error('文件属于旧规则或其他题集，请使用当前页面的评分JSON。');
 if(!data.drafts||typeof data.drafts!=='object'||Object.keys(data.drafts).sort().join()!==packet.items.map(i=>i.sample_id).sort().join())throw Error('回答集合不一致。');
 for(const i of packet.items){const d=data.drafts[i.sample_id],ks=fields(i).sort();if(!d||!d.values||!d.confirmed||Object.keys(d.values).sort().join()!==ks.join()||Object.keys(d.confirmed).sort().join()!==ks.join())throw Error('评分字段不一致。');for(const k of ks){if(!validScore(d.values[k])||typeof d.confirmed[k]!=='boolean'||d.confirmed[k]&&d.values[k]===null)throw Error('分数或确认状态不合法。');}if(typeof d.reason!=='string')throw Error('备注格式错误。');}
 return structuredClone(data.drafts);
}
function snapshot(){return {schema_version:packet.schema_version,packet_id:packet.packet_id,exported_utc:new Date().toISOString(),drafts:structuredClone(drafts)};}
function save(){try{localStorage.setItem(key,JSON.stringify(snapshot()));return true;}catch(e){$('message').textContent='浏览器无法保存本地草稿，请导出JSON保存。';return false;}}
function complete(i){const d=drafts[i.sample_id];return fields(i).every(k=>d.confirmed[k]&&d.values[k]!==null);}
function metric(i){const d=drafts[i.sample_id];const vs=fields(i).map(k=>d.confirmed[k]?d.values[k]:null);const interval=v=>v===null||v==='unknown'?[0,1]:[v,v];const kp=i.criteria.map(c=>interval(d.confirmed[c.criterion_id]?d.values[c.criterion_id]:null));const kb=[0,1].map(j=>kp.reduce((s,v)=>s+v[j],0)/kp.length);const dims=[kb,interval(d.confirmed.F?d.values.F:null)];if(i.conditional)dims.push(interval(d.confirmed.A?d.values.A:null));let ab=[0,1].map(j=>100*dims.reduce((s,v)=>s+v[j],0)/dims.length);let gb=[0,1].map(j=>100*Math.pow(dims.reduce((s,v)=>s*v[j],1),1/dims.length));let sb=[0,1].map(j=>+vs.every(v=>interval(v)[j]===1));const unknown=vs.some(v=>v===null||v==='unknown');if(i.generation_failed){ab=[0,0];gb=[0,0];sb=[0,0];}return {EAS_arith:unknown&&!i.generation_failed?null:ab[0],EAS_geo:unknown&&!i.generation_failed?null:gb[0],eas_arith_bounds:ab,eas_geo_bounds:gb,Strict:sb[0]===sb[1]?sb[0]:null};}
function display(v){return v==='unknown'?'Unknown':v==='not_applicable'?'N/A':String(v);}
function renderField(parent,k,title,dimension){
 const i=packet.items[position],d=drafts[i.sample_id],old=packet.ui.find(u=>u.sample_id===i.sample_id).legacy;
 const box=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=title;box.append(legend);
 if(old){const ref=document.createElement('div');ref.className='legacy';const ov=k==='F'?old.fact_gate:k==='A'?old.applicability_gate:old.points[k];ref.textContent='旧值参考：'+display(ov)+(k.startsWith('K')&&ov===.5?'（可细分为0.25 / 0.5 / 0.75）':'');box.append(ref);}
 for(const v of [...levels,'unknown']){const label=document.createElement('label');label.className='score';const input=document.createElement('input');input.type='radio';input.name=k;input.value=String(v);input.checked=d.values[k]===v;input.setAttribute('aria-label',title+' '+display(v));input.addEventListener('change',()=>{d.values[k]=v;d.confirmed[k]=true;save();render();});label.append(input,document.createTextNode(display(v)));if(v!=='unknown')label.title=packet.rules[dimension][levels.indexOf(v)];else label.title='确实无法判断；保留未知及上下界';box.append(label);}
 const status=document.createElement('span');status.className=d.confirmed[k]?'confirmed':'pending';status.textContent=d.confirmed[k]?' 已确认':' 待确认';box.append(status);parent.append(box);
}
function render(){
 const i=packet.items[position],u=packet.ui.find(u=>u.sample_id===i.sample_id),d=drafts[i.sample_id];$('position').textContent='第 '+(position+1)+' / '+packet.items.length+' 条';$('identity').textContent=u.group_id+' · '+(i.conditional?'条件题':'非条件题');$('question').textContent=i.question;$('answer-label').textContent=u.label;$('answer').textContent=i.answer;$('prev').disabled=position===0;$('next').disabled=position===packet.items.length-1;
 for(const id of ['criteria','fact','applicability','sources'])$(id).replaceChildren();
 for(const c of i.criteria)renderField($('criteria'),c.criterion_id,c.criterion_id+' · '+c.claim,'K');renderField($('fact'),'F','F · 事实正确性','F');if(i.conditional)renderField($('applicability'),'A','A · 条件适用性','A');else $('applicability').textContent='A · N/A（本题无条件判断，不参与分母）';
 for(const s of i.sources){const detail=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent=s.path;pre.textContent=s.text;detail.append(summary,pre);$('sources').append(detail);}
 $('note').value=d.reason;const n=packet.items.filter(complete).length;$('progress').max=packet.items.length;$('progress').value=n;$('completion').textContent='已确认 '+n+' / '+packet.items.length+' 条';
 $('notice').textContent=n===packet.items.length?'新版五档人工评分已完整确认，无需重复评分。当前可查看、保存和导出已有评分；正常评分无需备注，审计样本保持封存。':'当前已确认 '+n+' / '+packet.items.length+' 条。未确认的旧标签仅作预填参考；旧 K=0.5 可改为0.25/0.5/0.75，旧 F/A 的0或1也须确认。可确认本条全部分数，正常评分无需备注，审计样本保持封存。';
 if(packet.batch==='audit')$('notice').textContent='独立人工审计：只根据回答、Gold必要点和原文评分，不展示AI评分或旧标签。遗漏先反映K，不能因同一遗漏机械重复扣F/A；实质错误分别判断。已确认 '+n+' / '+packet.items.length+' 条，审计结果不用于优化Prompt。';
 const m=metric(i);$('result').textContent=['arith','geo'].map(n=>'EAS_'+n+': '+(m['EAS_'+n]===null?'Unknown':m['EAS_'+n].toFixed(2))+' ['+m['eas_'+n+'_bounds'].map(v=>v.toFixed(2)).join(', ')+']').join(' | ')+' | Strict: '+(m.Strict===null?'Unknown':m.Strict);
}
function download(){const blob=new Blob([JSON.stringify(snapshot(),null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=packet.batch==='audit'?'human_audit_five_level.json':'human_five_level.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('prev').onclick=()=>{save();position--;render();};$('next').onclick=()=>{save();position++;render();};$('save').onclick=()=>{if(save())$('message').textContent='草稿已保存在此浏览器；可导出JSON保存并重新导入。';};$('export').onclick=()=>{save();download();};
$('confirm').onclick=()=>{const i=packet.items[position],d=drafts[i.sample_id];if(fields(i).some(k=>d.values[k]===null)){$('message').textContent='请先选择未填项目的分数或Unknown。';return;}for(const k of fields(i))d.confirmed[k]=true;save();render();};
$('note').oninput=()=>{drafts[packet.items[position].sample_id].reason=$('note').value;save();};
$('import').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;const imported=validateExport(JSON.parse(await f.text()));drafts=imported;save();render();$('message').textContent='导入成功，分数与确认状态已恢复。';}catch(error){$('message').textContent='导入失败：'+error.message;}finally{e.target.value='';}};
for(const dim of ['K','F','A']){const div=document.createElement('div'),h=document.createElement('h3');h.textContent=dim;div.append(h);for(let n=0;n<levels.length;n++){const line=document.createElement('div');line.textContent=levels[n]+'：'+packet.rules[dim][n];div.append(line);}$('rules').append(div);}for(const line of packet.rules.instructions){const p=document.createElement('p');p.textContent=line;$('instructions').append(p);}
drafts=initial();try{if(packet.saved)drafts=validateExport(packet.saved);const stored=localStorage.getItem(key);if(stored){const data=JSON.parse(stored);if(!packet.saved||data.exported_utc>packet.saved.exported_utc)drafts=validateExport(data);}}catch(error){$('message').textContent='未恢复不兼容草稿：'+error.message;}
render();
window.HumanScoring={packet,snapshot,validateExport,metric,complete};
