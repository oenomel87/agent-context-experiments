// Official SDK bridge. The worker retains role threads and never shares thread IDs.
import {Codex} from '@openai/codex-sdk';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const sessions=new Map();
const workspace=fs.mkdtempSync('/private/tmp/luna-ts-roles-');
let index=0;
function fail(code){const error=new Error(code);error.code=code;return error;}
const features=['shell_tool','unified_exec','view_image','apps','plugins','multi_agent','multi_agent_v2','browser_use','computer_use','in_app_browser','image_generation','goals','sleep_tool','skill_search','skill_mcp_dependency_install','hooks','memories','workspace_dependencies','code_mode','code_mode_host','tool_suggest','default_mode_request_user_input'];
function overrides(instructionPath){return [
 ...features.map(k=>`features.${k}=false`),
 'default_permissions="luna-locked"',
 `permissions.luna-locked.filesystem={":root"="deny",":minimal"="read",":workspace_roots"={"."="read"},":tmpdir"="deny",":slash_tmp"="deny",${JSON.stringify(os.homedir())}="deny"}`,
 'permissions.luna-locked.network.enabled=false','project_doc_max_bytes=0','project_doc_fallback_filenames=[]',
 `model_instructions_file=${JSON.stringify(instructionPath)}`,'developer_instructions=""',
 'include_apps_instructions=false','include_collaboration_mode_instructions=false','include_environment_context=false',
 'forced_login_method="chatgpt"','service_tier="default"','web_search="disabled"',
 'model_reasoning_effort="medium"','approval_policy="never"',
 'model_auto_compact_token_limit=250000','model_post_turn_compact_threshold_percent=100',
 ];}
function findRollout(dir,id){
 if(!fs.existsSync(dir))return null;
 for(const ent of fs.readdirSync(dir,{withFileTypes:true})){
  const child=path.join(dir,ent.name);
  if(ent.isDirectory()){const match=findRollout(child,id);if(match)return match;}
  else if(ent.name.includes(id)&&ent.name.endsWith('.jsonl'))return child;
 }
 return null;
}
function metadata(id){
 const home=process.env.CODEX_HOME ?? path.join(os.homedir(),'.codex');
 const file=findRollout(path.join(home,'sessions'),id);
 if(!file)throw fail('missing_session_metadata');
 let selected=null,cliVersion=null;
 for(const line of fs.readFileSync(file,'utf8').split('\n')){
  if(!line.trim())continue;
  const record=JSON.parse(line);
  if(record.type==='session_meta')cliVersion=record.payload.cli_version;
  if(record.type==='event_msg'&&record.payload?.type==='context_compacted')throw fail('compaction');
  if(record.type==='turn_context'){
   const p=record.payload;
   selected={selected_model:p.model,turn_id:p.turn_id,effort:p.effort,approval_policy:p.approval_policy,
    permission_profile:p.permission_profile,active_permission_profile:p.active_permission_profile,
    file_system_sandbox_policy:p.file_system_sandbox_policy,sandbox_policy:p.sandbox_policy};
  }
 }
 if(cliVersion!=='0.159.3')throw fail('cli_version_mismatch');
 if(!selected||selected.selected_model!=='gpt-6-luna'||selected.effort!=='medium')throw fail('model_or_effort_mismatch');
 const profile=selected.permission_profile;
 const entries=profile?.file_system?.entries??[];
 const deniedHome=entries.some(e=>e.access==='deny'&&e.path?.type==='path'&&e.path.path===os.homedir());
 const deniedRoot=entries.some(e=>e.access==='deny'&&e.path?.value?.kind==='root');
 const deniedTmp=['tmpdir','slash_tmp'].every(kind=>entries.some(e=>e.access==='deny'&&e.path?.value?.kind===kind));
 if(profile?.network!=='restricted'||!deniedHome||!deniedRoot||!deniedTmp||selected.active_permission_profile?.id!=='luna-locked'||entries.some(e=>e.access==='write'))throw fail('permissions_mismatch');
 return {...selected,cli_version:cliVersion};
}
async function command(request){
 if(request.op==='start'){
  const key=String(++index),cwd=path.join(workspace,`role-${key}`);fs.mkdirSync(cwd);
  const instructions=path.join(cwd,'role-instructions.txt');fs.writeFileSync(instructions,request.instructions);
  const codex=new Codex({codexPathOverride:path.join(root,'src/sdk_exec_wrapper.py'),configOverrides:overrides(instructions)});
  const thread=codex.startThread({model:'gpt-6-luna',workingDirectory:cwd,skipGitRepoCheck:true,modelReasoningEffort:'medium',approvalPolicy:'never'});
  sessions.set(key,{thread,role:request.role});
  return {session_key:key};
 }
 if(request.op==='step'){
  const s=sessions.get(request.session_key);if(!s)throw Error('Unknown role session');
  let text=null,usage=null,status='failed',failure=null;const events=[];
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),request.timeout_seconds*1000);
  try{
   const stream=await s.thread.runStreamed(request.prompt,{outputSchema:request.output_schema,signal:controller.signal});
   for await(const event of stream.events){
    const clean={type:event.type};
    if(event.thread_id)clean.thread_id=event.thread_id;
    if(event.item){
     clean.item_type=event.item.type;clean.item_id=event.item.id;
     if(event.item.type==='agent_message'){clean.text=event.item.text;if(event.type==='item.completed')text=event.item.text;}
     // Nonfatal SDK runtime warning messages are counted, never treated as model decisions.
     if(!['agent_message','reasoning','error'].includes(event.item.type)){
      events.push(clean);controller.abort();throw fail('builtin_tool_invocation');
     }
    }
    if(event.usage){usage=event.usage;clean.usage=event.usage;}
    events.push(clean);
    if(event.type==='turn.completed')status='completed';
    if(event.type==='turn.failed'||event.type==='error')throw fail('sdk_failure');
   }
   if(status!=='completed')throw fail('missing_completed_event');
   const observed=metadata(s.thread.id);
   return {text,usage,status,thread_id:s.thread.id,events,...observed};
  }catch(error){
   failure=error.code??(controller.signal.aborted?'timeout':'sdk_failure');
   let observed={};try{if(s.thread.id)observed=metadata(s.thread.id);}catch{}
   return {text,usage,status:'failed',thread_id:s.thread.id,events,error_type:failure,...observed};
  }finally{clearTimeout(timer);}
 }
 if(request.op==='close'){return {closed:true};}
 throw Error('Unknown bridge operation');
}
const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
try{
 for await(const line of rl){
  let result;try{result=await command(JSON.parse(line));}catch{result={status:'failed',error_type:'bridge_error'};}
  process.stdout.write(JSON.stringify(result)+'\n');
  if(result.closed)break;
 }
}finally{fs.rmSync(workspace,{recursive:true,force:true});}
