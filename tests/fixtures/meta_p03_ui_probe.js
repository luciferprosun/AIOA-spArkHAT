/* Trusted LOCAL UI test only. Never shipped as a Mission Control script. */
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const node = id => document.querySelector(`#meta-${id}`);
async function until(predicate) {
  for(let n=0;n<180;n++){
    if(predicate())return;
    // Only the isolated test worker exposes this wall-clock barrier. Keep
    // Chrome virtual time from racing the real cancellable fixture worker.
    await fetch('/p03-local-clock',{cache:'no-store'});await sleep(20);
  }
  throw new Error('LOCAL_UI_CONDITION_TIMEOUT');
}
const resultNode=document.createElement('pre');resultNode.id='p03-ui-proof';
resultNode.hidden=true;document.body.append(resultNode);
let stage='bootstrap';
try {
  await until(()=>node('transport').textContent==='mock'&&!document.querySelector('#meta-view').hidden);
  if(node('call-state').textContent!=='NOT_ATTEMPTED'||node('live-receipt').textContent!=='none')throw Error('FALSE_ACTUAL_RECEIPT');
  stage='preview';node('form').requestSubmit();await until(()=>node('state').textContent==='PREVIEWED');
  const task=node('task').textContent;
  stage='fixture-run';node('run').click();await until(()=>node('state').textContent==='OFFLINE_FIXTURE');
  const evidence=JSON.parse(node('evidence').textContent);
  if(evidence.live_verified!==false || !evidence.result.core_warrant_consumed)throw Error('FALSE_LIVE_OR_MISSING_CORE');
  stage='second-preview';node('form').requestSubmit();await until(()=>node('state').textContent==='PREVIEWED'&&node('task').textContent!==task);
  stage='second-run';node('run').click();await until(()=>node('state').textContent==='RUNNING');
  stage='stop';node('stop').click();await until(()=>node('state').textContent==='STOPPED');
  window.scrollTo(0,document.scrollingElement.scrollHeight);
  const viewport={width:innerWidth,height:innerHeight,scrollTop:document.scrollingElement.scrollTop,
    scrollHeight:document.scrollingElement.scrollHeight,clientHeight:document.scrollingElement.clientHeight,
    horizontalOverflow:document.documentElement.scrollWidth>innerWidth};
  if(viewport.scrollHeight>viewport.clientHeight&&viewport.scrollTop===0)throw Error('PAGE_CANNOT_SCROLL');
  if(viewport.horizontalOverflow)throw Error('HORIZONTAL_OVERFLOW');
  const visible=document.querySelector('#meta-view').innerText;
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(visible));
  const hash=Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
  resultNode.textContent=JSON.stringify({passed:true,environment:'OFFLINE_FIXTURE',model_label:node('provider').textContent,
    task_id:task,core_warrant_consumed:true,live_verified:false,stop_state:node('state').textContent,
    source_sha:evidence.source_sha,capsule_digest:evidence.capsule_digest,
    correlation_id:evidence.correlation_id,evidence_digest:evidence.result.evidence_digest,
    tool_call_id:evidence.provider_receipt.tool_call_id,viewport,visible_text_sha256:hash});
} catch(error) {resultNode.textContent=JSON.stringify({passed:false,error:String(error.message),stage,
  state:node('state')?.textContent,transport:node('transport')?.textContent,message:node('message')?.textContent});}
