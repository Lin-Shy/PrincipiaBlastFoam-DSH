/* Local, isolated Chromium smoke test. Synthetic F/A only; never Human labels. */
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process');const {pathToFileURL}=require('node:url');
const assert=require('node:assert/strict');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,timeout=15000){const start=Date.now();while(Date.now()-start<timeout){const value=await fn();if(value)return value;await wait(100);}throw Error('Timed out waiting for local browser state');}
(async()=>{
 const workspace=path.resolve(__dirname,'../../..');
 const run=path.join(workspace,'graduation-experiment-results/chapter2_retrieval/rerun_dev40_test160_20261021_v1');
 const output=path.join(run,'scoring/verification/browser');
 await fs.mkdir(output,{recursive:true});
 const source=path.join(run,'scoring/human/index.html');
 const pageFile=path.join(output,'resume_test_page.html');
 // Test a fresh transition in a COPY, even after real Human submission is loaded.
 const production=await fs.readFile(source,'utf8');
 const match=production.match(/<script type="application\/json" id="packet">([\s\S]*?)<\/script>/);
 assert.ok(match,'embedded scoring packet');
 const packet=JSON.parse(match[1]);packet.saved=null;
 await fs.writeFile(pageFile,production.replace(match[1],JSON.stringify(packet).replaceAll('<','\\u003c')));
 const profile=path.join(workspace,'.codex_tmp','five_level_browser');await fs.mkdir(profile,{recursive:true});
 await fs.rm(path.join(profile,'DevToolsActivePort'),{force:true});
 const downloads=path.join(output,'roundtrip_downloads');await fs.mkdir(downloads,{recursive:true});
 const executable='C:/Program Files/Google/Chrome/Application/chrome.exe';
 const browser=spawn(executable,['--headless','--no-sandbox','--disable-gpu-sandbox','--in-process-gpu','--disable-gpu','--no-first-run','--disable-background-networking','--disable-component-update','--disable-extensions','--disable-domain-reliability','--disable-features=Translate,MediaRouter,OptimizationHints','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',`--user-data-dir=${profile}`],{windowsHide:true,stdio:['ignore','ignore','pipe']});
 let stderr='';browser.stderr.on('data',d=>{stderr+=d.toString();});let ws;const checks=[];const exceptions=[];
 try{
  const port=await until(async()=>{try{return (await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split(/\r?\n/);}catch{return null;}});
  ws=new WebSocket(`ws://127.0.0.1:${port[0]}${port[1]}`);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let ordinal=0;const pending=new Map();
  ws.onmessage=event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);if(m.error)p.reject(Error(JSON.stringify(m.error)));else p.resolve(m.result);}else if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);};
  ws.onclose=()=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Browser connection closed: '+stderr.slice(-1500)));}pending.clear();};
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++ordinal;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout '+method+' '+stderr.slice(-1500)));},15000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
  const target=await send('Target.createTarget',{url:'about:blank'});const attached=await send('Target.attachToTarget',{targetId:target.targetId,flatten:true});const sid=attached.sessionId;
  const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},sid);if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
  await send('Page.enable',{},sid);await send('Runtime.enable',{},sid);await send('Emulation.setDeviceMetricsOverride',{width:1460,height:1100,deviceScaleFactor:1,mobile:false},sid);
  await send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads,eventsEnabled:true});

  await send('Page.navigate',{url:pathToFileURL(pageFile).href},sid);await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
  await evaluate('localStorage.clear();true');await send('Page.reload',{},sid);await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
  assert.equal(await evaluate('HumanScoring.packet.items.length'),18);
  assert.equal(await evaluate('HumanScoring.packet.audit_included'),false);
  assert.equal(await evaluate('document.getElementById("progress").value'),0);
  assert.equal(await evaluate('document.querySelectorAll("input[name=F]").length'),6);
  assert.ok((await evaluate('document.getElementById("result").textContent')).includes('Unknown'));
  checks.push('old_KFA_preloaded_but_unconfirmed_no_audit');
  await fs.writeFile(path.join(output,'initial.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
  await evaluate(`document.querySelector('input[name=K001][value="0.25"]').click();document.querySelector('input[name=F][value="0.75"]').click();document.getElementById('confirm').click();true`);
  assert.equal(await evaluate('document.getElementById("progress").value'),1);
  assert.ok(!(await evaluate('document.getElementById("result").textContent')).includes('Unknown'));
  await evaluate('document.getElementById("save").click();true');
  await send('Page.reload',{},sid);await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
  assert.equal(await evaluate('document.getElementById("progress").value'),1);
  checks.push('five_level_edit_confirm_empty_note_save_reload');
  await evaluate('document.getElementById("export").click();true');
  const download=await until(async()=>{const names=(await fs.readdir(downloads)).filter(n=>n.endsWith('.json'));return names.length===1&&names[0];});
  const exported=path.join(output,'roundtrip.json');await until(async()=>{try{await fs.rename(path.join(downloads,download),exported);return true;}catch{return false;}});
  const first=JSON.parse(await fs.readFile(exported,'utf8'));assert.equal(Object.keys(first.drafts).length,18);
  await evaluate('localStorage.clear();true');await send('Page.reload',{},sid);await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
  assert.equal(await evaluate('document.getElementById("progress").value'),0);
  const doc=await send('DOM.getDocument',{},sid);const input=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#import'},sid);
  await send('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[exported]},sid);
  await until(()=>evaluate('document.getElementById("progress").value===1'));
  const restored=await evaluate('HumanScoring.snapshot()');assert.deepEqual(restored.drafts,first.drafts);
  checks.push('actual_download_file_import_restores_values_and_confirmation');
  const bad=path.join(output,'invalid_import.json');await fs.writeFile(bad,JSON.stringify({...first,schema_version:'ch2_judge_contract_v1'}));
  await send('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[bad]},sid);await wait(150);
  assert.equal(await evaluate('document.getElementById("progress").value'),1);assert.deepEqual((await evaluate('HumanScoring.snapshot()')).drafts,first.drafts);
  checks.push('legacy_import_rejected_without_mutation');
  await evaluate(`document.querySelector('input[name=F][value="unknown"]').click();document.getElementById('confirm').click();true`);
  const unknown=await evaluate('HumanScoring.metric(HumanScoring.packet.items[0])');
  assert.equal(unknown.EAS_arith,null);assert.equal(unknown.EAS_geo,null);assert.ok(unknown.eas_arith_bounds[1]>unknown.eas_arith_bounds[0]);
  await evaluate(`document.querySelector('input[name=F][value="0"]').click();true`);
  const zero=await evaluate('HumanScoring.metric(HumanScoring.packet.items[0])');
  assert.equal(zero.EAS_geo,0);assert.ok(zero.EAS_arith>0);
  checks.push('Unknown_bounds_and_natural_zero_geo_without_arithmetic_gate');
  for(let n=0;n<18;n++){
    await evaluate(`for(const c of HumanScoring.packet.items[${n}].criteria){document.querySelector('input[name='+c.criterion_id+'][value="0.5"]').click();}document.querySelector('input[name=F][value="0.75"]').click();var a=document.querySelector('input[name=A][value="0.25"]');if(a)a.click();document.getElementById('confirm').click();true`);
    if(n<17)await evaluate('document.getElementById("next").click();true');
  }
  assert.equal(await evaluate('document.getElementById("progress").value'),18);
  const synthetic=await evaluate('HumanScoring.snapshot()');await fs.writeFile(path.join(output,'synthetic_complete.json'),JSON.stringify(synthetic,null,2));
  const metrics=await evaluate('HumanScoring.packet.items.map(i=>({sample_id:i.sample_id,...HumanScoring.metric(i)}))');
  await fs.writeFile(path.join(output,'synthetic_metrics.json'),JSON.stringify(metrics,null,2));
  checks.push('all_18_joint_KFA_complete_without_notes_both_metrics');
  await fs.writeFile(path.join(output,'filled.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
  assert.equal(exceptions.length,0);
  const actualSaved=JSON.parse(match[1]).saved;
  if(actualSaved){
   // Read-only verification of the imported real submission, still in a COPY.
   await evaluate('localStorage.clear();true');await fs.writeFile(pageFile,production);
   await send('Page.reload',{ignoreCache:true},sid);await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
   assert.deepEqual((await evaluate('HumanScoring.snapshot()')).drafts,actualSaved.drafts);
   const completeCount=await evaluate('HumanScoring.packet.items.filter(HumanScoring.complete).length');
   assert.equal(await evaluate('document.getElementById("progress").value'),completeCount);
   if(completeCount===18)assert.ok((await evaluate('document.getElementById("notice").textContent')).includes('无需重复评分'));
   await fs.writeFile(path.join(output,'human_imported.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
   checks.push('real_imported_human_preloaded_without_changing_scores');
  }
  // Audit UI uses synthetic IDs/packet binding, so test exports cannot be imported
  // as actual audit evidence. Original sealed answer files are never changed.
  const auditPacket=structuredClone(packet);auditPacket.batch='audit';auditPacket.audit_included=true;auditPacket.human_blind=true;
  auditPacket.packet_id='SYNTHETIC_AUDIT_UI_ONLY';auditPacket.saved=null;
  auditPacket.items=auditPacket.items.slice(0,12).map((i,n)=>({...i,sample_id:'SYNTHETIC_AUDIT_'+n}));
  auditPacket.ui=auditPacket.items.map((i,n)=>({sample_id:i.sample_id,group_id:'A'+n,label:'answer',legacy:null}));
  const auditHTML=production.replace(match[1],JSON.stringify(auditPacket).replaceAll('<','\\u003c')).replace('Dev校准6题18答','独立审计4题12答');
  await fs.writeFile(pageFile,auditHTML);await evaluate('localStorage.clear();true');
  await send('Page.reload',{ignoreCache:true},sid);await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
  assert.equal(await evaluate('document.getElementById("progress").max'),12);
  assert.equal(await evaluate('document.querySelectorAll("input[type=radio]:checked").length'),0);
  assert.equal(await evaluate('document.querySelectorAll(".legacy").length'),0);
  for(let n=0;n<12;n++){
   await evaluate(`for(const c of HumanScoring.packet.items[${n}].criteria){document.querySelector('input[name='+c.criterion_id+'][value="0.5"]').click();}document.querySelector('input[name=F][value="0.75"]').click();var a=document.querySelector('input[name=A][value="0.25"]');if(a)a.click();document.getElementById('confirm').click();true`);
   if(n<11)await evaluate('document.getElementById("next").click();true');
  }
  assert.equal(await evaluate('document.getElementById("progress").value'),12);
  await evaluate('document.getElementById("export").click();true');
  const auditDownload=await until(async()=>{const names=await fs.readdir(downloads);return names.find(n=>n==='human_audit_five_level.json');});
  const auditExport=JSON.parse(await fs.readFile(path.join(downloads,auditDownload),'utf8'));
  assert.equal(auditExport.packet_id,'SYNTHETIC_AUDIT_UI_ONLY');assert.equal(Object.keys(auditExport.drafts).length,12);
  await fs.rename(path.join(downloads,auditDownload),path.join(output,'synthetic_audit_complete.json'));
  checks.push('synthetic_12_audit_blank_blind_joint_fill_export_no_legacy');
  if(await fs.stat(path.join(run,'scoring/audit/packet.json')).then(()=>true,()=>false)){
   await evaluate('localStorage.clear();true');
   await send('Page.navigate',{url:pathToFileURL(path.join(run,'scoring/audit/index.html')).href},sid);
   await until(()=>evaluate('typeof window.HumanScoring!=="undefined"'));
   const actual=await evaluate('HumanScoring.packet');
   assert.equal(actual.items.length,12);assert.equal(actual.human_blind,true);
   assert.ok(actual.ui.every(u=>u.legacy===null));assert.equal('private' in actual,false);
   assert.equal(JSON.stringify(actual).includes('"judge_id"'),false);
   await fs.writeFile(path.join(output,'audit.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
   checks.push('actual_released_audit_12_readonly_blind_no_AI_scores');
  }
  await send('Page.navigate',{url:pathToFileURL(path.join(run,'scoring/review.html')).href},sid);
  await until(()=>evaluate('document.querySelectorAll("select[data-id]").length===4'));
  assert.ok((await evaluate('document.body.textContent')).includes('Gold'));
  assert.equal(await evaluate('document.querySelectorAll("article").length'),9);
  assert.equal(await evaluate('document.querySelectorAll("section[id]").length'),4);
  await fs.writeFile(path.join(output,'review.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
  checks.push('professional_review_three_questions_nine_answers_Gold_Human_sources');
  await fs.writeFile(path.join(output,'test.json'),JSON.stringify({status:'passed',checks,synthetic_labels_only:true,production_human_scores_modified:false},null,2));
  await send('Page.navigate',{url:pathToFileURL(path.join(run,'scoring/results/index.html')).href},sid);
  await until(()=>evaluate('document.querySelectorAll("tr[data-metric]").length>0'));
  await evaluate(`document.getElementById('metric').value='EAS_geo';document.getElementById('metric').dispatchEvent(new Event('change'));true`);
  assert.equal(await evaluate('Array.from(document.querySelectorAll("tr[data-metric]")).filter(r=>!r.hidden).every(r=>r.dataset.metric==="EAS_geo")'),true);
  await fs.writeFile(path.join(output,'results.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
  checks.push('results_dashboard_dual_metrics_filter_and_strict');
  await send('Page.navigate',{url:pathToFileURL(path.join(run,'03_dev_experiments/dev40/results/index.html')).href},sid);
  await until(()=>evaluate('document.querySelectorAll("tr[data-model]").length===26'));
  await evaluate(`document.getElementById('model').value='qwen3-14b';document.getElementById('model').dispatchEvent(new Event('change'));true`);
  assert.equal(await evaluate('Array.from(document.querySelectorAll("tr[data-model]")).filter(r=>!r.hidden).length'),13);
  assert.ok((await evaluate('document.body.textContent')).includes('Unknown'));
  const auditLink=await evaluate('document.querySelector("a").getAttribute("href")');
  assert.equal(path.resolve(run,'03_dev_experiments/dev40/results',auditLink),path.resolve(run,'scoring/audit/results/acceptance.md'));
  await fs.writeFile(path.join(output,'dev40.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
  checks.push('dev40_26_configs_13_per_model_unknown_scores_audit_link');
  await send('Page.navigate',{url:pathToFileURL(path.join(run,'03_dev_experiments/dev40/results/scoring.html')).href},sid);
  await until(()=>evaluate('document.querySelectorAll("tr[data-model]").length===78'));
  await evaluate(`document.getElementById('model').value='qwen3-14b';document.getElementById('model').dispatchEvent(new Event('change'));true`);
  assert.equal(await evaluate('Array.from(document.querySelectorAll("tr[data-model]")).filter(r=>!r.hidden).length'),39);
  assert.ok((await evaluate('document.body.textContent')).includes('EAS_arith'));
  assert.ok((await evaluate('document.body.textContent')).includes('EAS_geo'));
  await fs.writeFile(path.join(output,'dev40_scoring.png'),Buffer.from((await send('Page.captureScreenshot',{format:'png'},sid)).data,'base64'));
  checks.push('dev40_two_judges_and_per_answer_mean_dual_metric_dashboard');
  await fs.writeFile(path.join(output,'test.json'),JSON.stringify({status:'passed',checks,synthetic_labels_only:true,production_human_scores_modified:false},null,2));
  console.log(JSON.stringify({status:'passed',checks}));await send('Browser.close');
 }finally{if(ws)ws.close();if(browser.exitCode===null)browser.kill();await fs.writeFile(path.join(output,'browser_stderr.txt'),stderr);}
})().catch(error=>{console.error(error);process.exitCode=1;});
