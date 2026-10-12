/* 用安全 DOM 展示原文；公式解释交给离线 KaTeX，原始数学字符串保持不变。 */
function renderManualMarkdown(raw){
 const root=document.createElement('div');root.className='markdown-view';
 function element(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n}
 function math(text,display){const n=element(display?'div':'span');n.className='math-render';n.dataset.math=text;try{katex.render(text,n,{displayMode:display,throwOnError:true,trust:false,strict:'ignore'})}catch(e){n.className+=' math-error';n.textContent=(display?'$$':'$')+text+(display?'$$':'$');n.title=String(e)}return n}
 function inline(text,parent){const regex=/(`+)([\s\S]*?)\1|\$([^$\n]+)\$|\*\*([^*]+)\*\*/g;let last=0,m;while((m=regex.exec(text))){parent.append(document.createTextNode(text.slice(last,m.index)));parent.append(m[1]?element('code',m[2]):m[3]!==undefined?math(m[3],false):element('strong',m[4]));last=regex.lastIndex}parent.append(document.createTextNode(text.slice(last)))}
 const lines=raw.split(/\r?\n/);let i=0;
 while(i<lines.length){let s=lines[i].trim();if(!s){i++;continue}
  if(/^(`{3,}|~{3,})/.test(s)){const marker=s.match(/^(`{3,}|~{3,})/)[1];let code=[];i++;while(i<lines.length&&!lines[i].trim().startsWith(marker))code.push(lines[i++]);i++;const pre=element('pre');pre.append(element('code',code.join('\n')));root.append(pre);continue}
  if(s.startsWith('$$')){let text=s.slice(2);i++;if(text.includes('$$'))text=text.slice(0,text.indexOf('$$'));else{let parts=text?[text]:[];while(i<lines.length&&!lines[i].includes('$$'))parts.push(lines[i++]);if(i<lines.length)parts.push(lines[i++].split('$$')[0]);text=parts.join('\n').trim()}root.append(math(text,true));continue}
  if(s.startsWith('|')){const table=element('table');let row=0;while(i<lines.length&&lines[i].trim().startsWith('|')){const value=lines[i++].trim();if(/^\|[\s:|\-]+\|$/.test(value))continue;const tr=element('tr');for(const cell of value.slice(1).replace(/\|$/,'').split(/(?<!\\)\|/)){const td=element(row===0?'th':'td');inline(cell.trim(),td);tr.append(td)}table.append(tr);row++}root.append(table);continue}
  const img=s.match(/^!\[([^\]]*)\]\(([^)]+)\)/);if(img){if(/^figures\/[A-Za-z0-9_.-]+$/.test(img[2])){const n=element('img');n.src=img[2];n.alt=img[1];root.append(n)}else root.append(element('p',s));i++;continue}
  const heading=s.match(/^(#{1,6})\s+(.*)$/);if(heading){const n=element('h'+Math.min(6,heading[1].length+1));inline(heading[2],n);root.append(n);i++;continue}
  let paragraph=[lines[i++]];while(i<lines.length&&lines[i].trim()&&!/^(?:#{1,6}\s|```|~~~|\$\$|\||!\[)/.test(lines[i].trim()))paragraph.push(lines[i++]);
  const quote=s.startsWith('>');const n=element(quote?'blockquote':'p');inline(paragraph.map(l=>quote?l.replace(/^>\s?/,''):l).join('\n'),n);root.append(n);
 }
 return root;
}
