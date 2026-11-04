// Isolated headless Chromium, CDP only; never touches the user's browser profile.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawn} from 'node:child_process';
import {pathToFileURL,fileURLToPath} from 'node:url';
const work=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const review=path.join(work,'graduation-datasets/chapter02_knowledge_qa/open/review/calibration');
const out=process.argv[3]?path.resolve(process.argv[3]):path.join(work,'graduation-experiment-results/chapter2_retrieval/release/validation');
const originalPacketBytes=fs.readFileSync(path.join(review,'calibration/packets.json'));
const executable=process.argv[2];if(!executable||!fs.existsSync(executable))throw Error('Pass the existing headless Chromium executable');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'ch2-human-form-'));
const child=spawn(executable,['--remote-debugging-port=0','--no-first-run','--no-default-browser-check',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
let ws;const wait=ms=>new Promise(r=>setTimeout(r,ms));
try{
  const active=path.join(profile,'DevToolsActivePort');for(let n=0;!fs.existsSync(active)&&n<100;n++)await wait(100);
  const port=fs.readFileSync(active,'utf8').split('\n')[0],targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  let seq=0;const pending=new Map();ws.onmessage=e=>{const v=JSON.parse(e.data);if(v.id){const p=pending.get(v.id);pending.delete(v.id);v.error?p.reject(Error(JSON.stringify(v.error))):p.resolve(v.result)}};
  function cdp(method,params={}){const id=++seq;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(Error('CDP timeout: '+method))}},10000).unref()})}
  async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value}
  await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:pathToFileURL(path.join(review,'index.html')).href});
  for(let n=0;n<50;n++){if(await evaluate("document.readyState==='complete'"))break;await wait(100)}
  async function load(filename){const {root}=await cdp('DOM.getDocument');const {nodeId}=await cdp('DOM.querySelector',{nodeId:root.nodeId,selector:'#packets'});await cdp('DOM.setFileInputFiles',{nodeId,files:[filename]});await wait(250)}
  await load(path.join(review,'acceptance/packets.json'));
  const acceptanceLocked=await evaluate("document.getElementById('message').textContent.includes('尚未解锁') && packet===null");
  await load(path.join(review,'calibration/packets.json'));
  const currentCounts=await evaluate("({samples:packet.samples.length,valid_answers:packet.samples.filter(p=>p.binding_status==='bound'&&!p.generation_failed).length,failed:packet.samples.filter(p=>p.generation_failed).length,human_completed:labels.filter((l,i)=>complete(packet.samples[i],l)).length})");
  const exportInitiallyBlocked=await evaluate("document.getElementById('export').disabled");
  await evaluate("window.savedFirstPacket=structuredClone(packet.samples[0]);packet.samples[0].binding_status='awaiting_generation';draw()");
  const pendingBlocked=await evaluate("document.getElementById('export').disabled && document.querySelectorAll('select').length>0 && [...document.querySelectorAll('select')].every(x=>x.disabled)");
  await evaluate("packet.samples[0]=window.savedFirstPacket;draw()");
  const anonymous=await evaluate("!document.getElementById('sample').textContent.includes('qwen3') && !document.getElementById('sample').textContent.includes('llama3.1') && !document.getElementById('sample').textContent.includes('bm25')");
  const screenshot=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(out,'human_form_preview.png'),Buffer.from(screenshot.data,'base64'));
  // The following answer/labels exist only in this disposable browser memory.
  await evaluate("for(let i=0;i<60;i++){const p=packet.samples[i],l=labels[i];p.answer='SYNTHETIC_UI_TEST_ONLY';p.answer_sha256='synthetic';p.binding_status='bound';p.generation_failed=false;l.reviewer='SYNTHETIC_UI_TEST_ONLY';l.record.points.forEach(x=>x.score=1);l.record.fact_gate=1;l.record.applicability_gate=p.conditional?1:'not_applicable'};document.getElementById('reviewer').value='SYNTHETIC_UI_TEST_ONLY';update();URL.createObjectURL=b=>{window.exportBlob=b;return 'blob:synthetic'};URL.revokeObjectURL=()=>{};HTMLAnchorElement.prototype.click=()=>{};");
  await evaluate('download(true)');
  const exported=await evaluate("exportBlob.text().then(t=>{const d=JSON.parse(t);return {schema:d.schema,phase:d.phase,count:d.labels.length,complete:d.labels.every(l=>l.record.status==='complete'),first_packet_hash:d.labels[0].packet_sha256}})");
  const digestMatches=exported.first_packet_hash===await evaluate('digest(packet.samples[0])');
  const filesUnchanged=originalPacketBytes.equals(fs.readFileSync(path.join(review,'calibration/packets.json')));
  const report={acceptanceLocked,pendingBlocked,anonymous,digestMatches,currentCounts,exportInitiallyBlocked,exported_count:exported.count,exported_complete:exported.complete,actual_packets_unchanged:filesUnchanged,synthetic_labels_written:false,passed:acceptanceLocked&&pendingBlocked&&anonymous&&digestMatches&&exportInitiallyBlocked&&exported.count===60&&exported.complete&&filesUnchanged};
  fs.writeFileSync(path.join(out,'human_form_checks.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
}finally{if(ws)ws.close();child.kill();await wait(500);}
// Temporary Chromium profile is outside the project; OS temp cleanup may reclaim
// locked transient files. Never recursively remove a computed Windows path here.
