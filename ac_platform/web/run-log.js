/* Read-only event projection. Reconstructed entries are not live telemetry. */
let runStep=0,runTimer=null,selectedRunId=null;
function runEvidence(items,runId,eventId){return items.map((e,i)=>typeof e==='string'?`<span class="muted">${esc(e)}（文字定位）</span>`:`<button class="entry-link" data-evidence-run="${esc(runId)}" data-evidence-event="${esc(eventId)}" data-evidence-index="${i}">${esc(e.label||e.path)}</button>`).join(' · ')||'未记录';}
function bindRunEvidence(host){host.querySelectorAll('[data-evidence-run]').forEach(b=>b.onclick=async()=>{try{const url='/api/evidence?'+new URLSearchParams({run:b.dataset.evidenceRun,event:b.dataset.evidenceEvent,index:b.dataset.evidenceIndex});const response=await fetch(url),e=await response.json();if(!response.ok)throw Error(e.error||response.status);show(e.label,`<p class="muted">${esc(e.path)} · ${e.bytes} 字节<br>SHA256 ${esc(e.sha256)}${e.matchesExpected===false?'<br><b class="error">文件已变化：与事件绑定散列不同</b>':''}</p>${e.kind==='text'?doc(e.content):e.kind==='image'?`<img class="evidence-image" src="${esc(url+'&mode=image')}" alt="${esc(e.label)}">`:'<p>此文件使用本地应用打开；项目HTML不在管理页面执行。</p>'}${e.truncated?'<p>预览截取前128 KiB。</p>':''}<p><a href="${esc(url+'&mode=download')}" download>下载此证据文件</a></p>`);}catch(error){show('证据暂不可用',`<p>${esc(error.message)}</p>`);}});}
function stopRun(){if(runTimer)clearInterval(runTimer);runTimer=null;}
function renderRunLog(){
 const choices=data.runLogs?.length?data.runLogs:(data.runLog?[data.runLog]:[]);
 const log=choices.find(x=>x.id===selectedRunId)||data.runLog||choices[0],host=$('#content');
 if(!log){host.innerHTML=panel('工作轨迹','尚未绑定事件日志。配置 run_log 后显示真实记录；不自动编造执行次数。');return;}
 selectedRunId=log.id;
 const events=log.events||[];if(!events.length){host.innerHTML=panel('工作轨迹','已绑定日志，尚无事件。');return;}
 runStep=Math.min(runStep,events.length-1);
 const current=events[runStep],mods=log.modules||[];
 host.innerHTML=panel('模块关系与执行轨迹',`<p><b>${esc(log.title)}</b> · ${esc(log.mode==='reconstructed'?'历史重建／非实时监控':'事件记录／非代理自动探测')}</p><p class="muted">${esc(log.limitations)}。节点 ×N 为已记录事件的目标次数，不是代理启动次数、工具调用次数或完整执行次数。</p><div class="run-controls"><button id="runPlay">${runTimer?'暂停':'播放'}</button><button id="runPrev">上一步</button><button id="runNext">下一步</button><span id="runPosition"></span></div><div id="runGraph" class="run-graph"><svg class="run-lines" aria-hidden="true"></svg><div class="run-modules">${mods.map(m=>{const n=events.slice(0,runStep+1).filter(e=>e.to===m.id).length;return `<button class="run-module ${[current.from,current.to].includes(m.id)?'run-current':''}" data-module="${esc(m.id)}"><b>${esc(m.title)}</b><span>${esc(m.kind)} · 记录到达 ×${n}</span></button>`}).join('')}</div></div><div id="runDetail" role="status"></div>`)+panel('事件顺序 · 点击定位',`<ol class="run-events">${events.map((e,i)=>`<li><button data-run-event="${i}" ${i===runStep?'aria-current="step"':''}>${esc(e.id)} · ${esc(e.title)}</button><span class="muted">${esc(e.time||'时间未记录')} · ${esc(e.status)}</span></li>`).join('')}</ol>`);
 host.insertAdjacentHTML('afterbegin',`<label>实验记录 <select id="runChoice">${choices.map(x=>`<option value="${esc(x.id)}" ${x.id===log.id?'selected':''}>${esc(x.title)}</option>`).join('')}</select></label>`);
 $('#runChoice').onchange=e=>{stopRun();selectedRunId=e.target.value;runStep=0;renderRunLog();};
 const name=id=>mods.find(m=>m.id===id)?.title||id;
 $('#runPosition').textContent=`${runStep+1} / ${events.length}`;
 $('#runDetail').innerHTML=`<h3>${esc(current.id)} · ${esc(current.title)}</h3><p>${esc(name(current.from))} → ${esc(name(current.to))}</p><p>${esc(current.detail)}</p><div>证据：${runEvidence(current.evidence||[],log.id,current.id)}</div><p class="muted">记录性质：${esc(current.basis||'事件记录')}；发生时间：${esc(current.time||'未知')}</p>`;
 bindRunEvidence(host);
 $('#runPrev').disabled=runStep===0;$('#runNext').disabled=runStep===events.length-1;
 const select=i=>{stopRun();runStep=i;renderRunLog();};
 $('#runPrev').onclick=()=>select(Math.max(0,runStep-1));$('#runNext').onclick=()=>select(Math.min(events.length-1,runStep+1));
 host.querySelectorAll('[data-run-event]').forEach(b=>b.onclick=()=>select(+b.dataset.runEvent));
 host.querySelectorAll('[data-module]').forEach(b=>b.onclick=()=>{const m=mods.find(x=>x.id===b.dataset.module);const related=events.filter(e=>e.from===m.id||e.to===m.id);show(m.title,`<p>${esc(m.description||m.kind)}</p><p>已记录目标事件 ${events.filter(e=>e.to===m.id).length} 条；完整执行次数：${esc(m.executionsKnown??'未知')}。</p>${related.map(e=>`<p>${esc(e.id)} · ${esc(e.title)}</p>`).join('')}`)});
 $('#runPlay').onclick=()=>{if(runTimer){stopRun();renderRunLog();return;}if(runStep===events.length-1)runStep=0;runTimer=setInterval(()=>{if(active!==9){stopRun();return;}runStep++;if(runStep>=events.length-1){runStep=events.length-1;stopRun();}renderRunLog();},2200);renderRunLog();};
 requestAnimationFrame(drawRunLines);
 function drawRunLines(){
  const graph=$('#runGraph');if(!graph)return;const svg=graph.querySelector('svg'),box=graph.getBoundingClientRect();svg.setAttribute('width',box.width);svg.setAttribute('height',box.height);
  let edges=[];events.forEach(e=>{if(!edges.some(x=>x.from===e.from&&x.to===e.to))edges.push({from:e.from,to:e.to})});
  svg.innerHTML=edges.map(edge=>{const a=graph.querySelector(`[data-module="${CSS.escape(edge.from)}"]`),b=graph.querySelector(`[data-module="${CSS.escape(edge.to)}"]`);if(!a||!b)return '';let ar=a.getBoundingClientRect(),br=b.getBoundingClientRect(),x1=ar.left+ar.width/2-box.left,y1=ar.top+ar.height/2-box.top,x2=br.left+br.width/2-box.left,y2=br.top+br.height/2-box.top;const hit=edge.from===current.from&&edge.to===current.to;return `<path d="M ${x1} ${y1} L ${x2} ${y2}" class="${hit?'run-active-line':''}"/>${hit?`<text x="${(x1+x2)/2}" y="${(y1+y2)/2-6}" text-anchor="middle">${esc(current.id)}</text>`:''}`;}).join('');
 }
}
window.addEventListener('resize',()=>{if(active===9&&data)renderRunLog()});
