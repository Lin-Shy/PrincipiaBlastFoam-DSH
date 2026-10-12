// 可选真实Chromium冒烟测试。全部评分为测试数据，只写临时目录。
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const [html,unblind,output]=process.argv.slice(2);
if(!html||!unblind||!output||!process.env.CH2_CHROMIUM)throw Error('用法：CH2_CHROMIUM=chromium node tests/human_rating_browser_smoke.mjs HTML 解盲JSON 临时输出目录');
await mkdir(output,{recursive:true});
const browser=spawn(process.env.CH2_CHROMIUM,['--headless=new','--no-sandbox','--disable-gpu',
  '--no-first-run','--disable-background-networking','--remote-debugging-pipe','--user-data-dir='+path.join(output,'profile')],
  {stdio:['ignore','ignore','pipe','pipe','pipe']});
const pending=new Map(),events=[],errors=[];let sequence=0,buffer=Buffer.alloc(0),session;
let browserLog='';browser.stderr.on('data',chunk=>{browserLog+=chunk.toString();});
for(const stream of [browser.stdio[3],browser.stdio[4]])stream.on('error',()=>{});
browser.on('exit',(code)=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Chromium退出 '+code+'：'+browserLog.slice(-1500)));}pending.clear();});
browser.stdio[4].on('data',chunk=>{
  buffer=Buffer.concat([buffer,chunk]);let end;
  while((end=buffer.indexOf(0))!==-1){const message=JSON.parse(buffer.subarray(0,end).toString());buffer=buffer.subarray(end+1);
    if(message.id){const p=pending.get(message.id);pending.delete(message.id);if(p){clearTimeout(p.timer);message.error?p.reject(Error(JSON.stringify(message.error))):p.resolve(message.result);}}
    else {events.push(message);if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails);}
  }
});
function cdp(method,params={},sessionId=session){return new Promise((resolve,reject)=>{const id=++sequence;
  const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},15000);
  pending.set(id,{resolve,reject,timer});browser.stdio[3].write(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})})+'\0');});}
async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function click(id){return evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);}
async function input(id,value){return evaluate(`(()=>{const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);}
async function until(expression){for(let i=0;i<80;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,50));}throw Error('Condition not met: '+expression);}
async function fileInput(id,file){await evaluate(`document.getElementById(${JSON.stringify(id)}).value=''`);const d=await cdp('DOM.getDocument');const n=await cdp('DOM.querySelector',{nodeId:d.root.nodeId,selector:'#'+id});await cdp('DOM.setFileInputFiles',{nodeId:n.nodeId,files:[path.resolve(file)]});}
const checks=[];
try {
  await cdp('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:path.join(output,'downloads'),eventsEnabled:true},null);
  const target=await cdp('Target.createTarget',{url:'about:blank'},null);
  session=(await cdp('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
  await cdp('Runtime.enable');await cdp('Page.enable');await cdp('Network.enable');
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1080,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:pathToFileURL(path.resolve(html)).href});
  await until(`document.getElementById('case-list')?.children.length===48`);
  assert.equal(await evaluate(`document.getElementById('progress').value`),0);
  assert.equal(await evaluate(`document.getElementById('unblind').disabled`),true);
  assert.equal(await evaluate(`typeof crypto.subtle`),'object');checks.push('file://加载48样本，初始无评分，解盲禁用');
  const screenshot=await cdp('Page.captureScreenshot',{format:'png'});
  await writeFile(path.join(output,'preview.png'),Buffer.from(screenshot.data,'base64'));
  await input('reviewer','smoke-test-only');await input('development','false');await input('exposed','false');
  await evaluate(`document.querySelectorAll('#ratings .scores')[0].children[4].click();document.querySelectorAll('#ratings .scores')[1].children[5].click()`);
  assert.equal(await evaluate(`document.getElementById('progress').value`),1);
  assert.equal(await evaluate(`document.getElementById('notes').value`),'');checks.push('点击分数与无法判断，空备注完成');
  await cdp('Page.reload');await until(`document.getElementById('progress')?.value===1`);
  assert.equal(await evaluate(`document.getElementById('reviewer').value`),'smoke-test-only');checks.push('缓存恢复');
  await input('filter','done');assert.equal(await evaluate(`document.getElementById('case-list').children.length`),1);
  await input('filter','pending');assert.equal(await evaluate(`document.getElementById('case-list').children.length`),47);
  await input('filter','all');checks.push('已完成/未完成筛选');
  await click('next-pending');assert.match(await evaluate(`document.getElementById('case-title').textContent`),/^2 \/ 48/);
  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'3',bubbles:true}));document.dispatchEvent(new KeyboardEvent('keydown',{key:'c',bubbles:true}));document.dispatchEvent(new KeyboardEvent('keydown',{key:'4',bubbles:true}));`);
  assert.equal(await evaluate(`document.getElementById('progress').value`),2);checks.push('快捷键两维评分与下一未完成');
  // 通过真实按钮完成余下46份，而不是注入应用状态。
  await evaluate(`for(let i=2;i<48;i++){document.querySelectorAll('#case-list button')[i].click();document.querySelectorAll('#ratings .scores')[0].children[i%5].click();document.querySelectorAll('#ratings .scores')[1].children[(i+1)%5].click();}`);
  assert.equal(await evaluate(`document.getElementById('progress').value`),48);
  await click('seal');await click('seal-confirm');await until(`document.getElementById('mode').textContent==='已封存'`);
  assert.equal(await evaluate(`document.getElementById('notes').disabled`),true);
  assert.equal(await evaluate(`document.getElementById('unblind').disabled`),false);checks.push('48份全完成，封存下载与只读');
  for(let i=0;i<50&&!events.some(e=>e.method==='Browser.downloadProgress'&&e.params.state==='completed');i++)await new Promise(r=>setTimeout(r,50));
  const downloads=await readdir(path.join(output,'downloads'));const jsonFile=downloads.find(n=>n.endsWith('.json'));
  assert.ok(jsonFile,'JSON下载完成');const sealed=JSON.parse(await readFile(path.join(output,'downloads',jsonFile),'utf8'));
  assert.equal(sealed.status,'sealed');assert.equal(sealed.rows.length,48);assert.ok(sealed.rows.every(r=>r.notes===''));
  await writeFile(path.join(output,'sealed-test-only.json'),JSON.stringify(sealed,null,2)+'\n');
  await fileInput('unblind-file',unblind);await until(`document.getElementById('comparison-panels').children.length===6`);
  assert.equal(await evaluate(`document.getElementById('comparison-question').children.length`),8);checks.push('解盲后8题组、每组6方法');
  await click('revision');assert.equal(await evaluate(`document.getElementById('mode').textContent`),'解盲后修订');
  assert.equal(await evaluate(`document.getElementById('notes').disabled`),false);
  await click('draft');checks.push('建立解盲后修订，不修改原封存对象');
  // 导入损坏分数必须拒绝，封存导入遇冲突不自动覆盖。
  const invalid=structuredClone(sealed);invalid.rows[0].claim_correctness=6;
  await writeFile(path.join(output,'invalid.json'),JSON.stringify(invalid));
  await fileInput('import-file',path.join(output,'invalid.json'));await until(`document.getElementById('message').className==='error'`);
  assert.match(await evaluate(`document.getElementById('message').textContent`),/非法分值/);
  await fileInput('import-file',path.join(output,'sealed-test-only.json'));await until(`document.getElementById('conflict').open`);
  await click('conflict-keep');assert.equal(await evaluate(`document.getElementById('mode').textContent`),'解盲后修订');checks.push('非法导入拒绝，冲突保留当前');
  await fileInput('import-file',path.join(output,'sealed-test-only.json'));await until(`document.getElementById('conflict').open`);
  await click('conflict-replace');assert.equal(await evaluate(`document.getElementById('mode').textContent`),'已封存');
  assert.equal(await evaluate(`document.getElementById('notes').disabled`),true);checks.push('封存JSON导入只读');
  await click('csv');checks.push('CSV下载');
  // 浏览器缓存被禁止时仍可以人工评分与下载备份。
  await evaluate('localStorage.clear()');
  await cdp('Page.reload');await until(`document.getElementById('case-list')?.children.length===48`);
  await evaluate(`Storage.prototype.setItem=function(){throw Error('test denied')}`);
  await input('reviewer','cache-denied-test-only');
  await evaluate(`document.querySelectorAll('#ratings .scores')[0].children[2].click()`);
  assert.match(await evaluate(`document.getElementById('message').textContent`),/缓存不可用/);
  await click('draft');checks.push('缓存不可用时提示、仍可评分与下载草稿');
  const requests=events.filter(e=>e.method==='Network.requestWillBeSent').map(e=>e.params.request.url);
  assert.ok(requests.every(u=>u.startsWith('file:')||u.startsWith('data:')||u.startsWith('blob:')),'页面没有网络请求');
  assert.deepEqual(errors,[],'页面无JavaScript异常');
  await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  assert.ok(await evaluate(`document.documentElement.scrollWidth<=window.innerWidth`),'窄屏没有横向溢出');checks.push('离线无网络请求、无脚本异常、窄屏适配');
  await writeFile(path.join(output,'validation.json'),JSON.stringify({status:'passed',test_only:true,checks},null,2)+'\n');
  console.log(JSON.stringify({status:'passed',checks}));
} finally {
  try{await cdp('Browser.close',{},null);}catch{}browser.kill();for(const p of pending.values())clearTimeout(p.timer);
}
