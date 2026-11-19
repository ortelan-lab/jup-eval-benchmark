import json,os,time,uuid,urllib.request,urllib.parse,urllib.error,hashlib,math,threading,shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from .core import canonical_hash,validate_plan,require,ROOT
from .accounting import RequestJournal
from .tools import World,schema
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer credential to an unexpected redirect target.
        raise urllib.error.HTTPError(req.full_url, code, 'Redirect refused', headers, fp)

def open_request(req, timeout):
    return urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout)

class BudgetStop(Exception):pass
class UsageUnknown(Exception):pass
class ConfirmedApplicationFailure(Exception):
    """A terminal service error whose charge is independently settled.

    This is an observed system outcome, not a reason to erase the rest of a
    benchmark. Uncertain transport/accounting still uses UsageUnknown.
    """
    def __init__(self, http_status, metadata):
        import math
        require(type(http_status) is int and 400 <= http_status <= 599, 'invalid HTTP failure')
        cost = metadata.get('cost_usd')
        require(type(cost) in (int, float) and math.isfinite(cost) and cost >= 0,
                'confirmed failure requires a known charge')
        require(metadata.get('usage_unknown') is False, 'failure accounting must be settled')
        self.http_status = http_status
        self.metadata = dict(metadata)
        super().__init__('HTTP_' + str(http_status))
class LiveAdapter:
    def __init__(self,base_url,key_env,model,input_rate,output_rate,ceiling,config):
        u=urllib.parse.urlparse(base_url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('HTTPS base URL required, without credentials/query/fragment')
        if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (input_rate,output_rate,ceiling)):raise ValueError('positive input/output prices and ceiling required')
        self.url=base_url.rstrip('/')+'/chat/completions';self.key=os.environ[key_env];self.model=model
        if not self.key.strip():raise ValueError('empty API credential')
        self.ir=input_rate;self.orate=output_rate;self.ceiling=ceiling;self.exposure=0.;self.config=config;self.journal=None;self.lock=threading.Lock();self.stop_event=threading.Event();self.min_interval=0.;self.next_dispatch=0.
        self.provenance={'adapter':'chat-completions-v2','base_url':base_url,'input_price_per_million':input_rate,'output_price_per_million':output_rate,'local_spend_ceiling_usd':ceiling}
    def request(self,messages,tools):
        body={'model':self.model,'messages':messages,'max_tokens':self.config['max_output_tokens'],'temperature':self.config['temperature']}
        if tools:body['tools']=tools
        return body,{'Content-Type':'application/json','Authorization':'Bearer '+self.key}
    def parse(self,result):
        usage=result.get('usage') or {}
        if not isinstance(usage,dict):usage={}
        pin=usage.get('prompt_tokens');pout=usage.get('completion_tokens')
        cost=None
        if type(pin) is int and type(pout) is int and pin>=0 and pout>=0:
            cost=(pin*self.ir+pout*self.orate)/1e6
        try:choice=result['choices'][0];message=choice['message']
        except (KeyError,IndexError,TypeError):return None,usage,cost,None
        return message,usage,cost,choice.get('finish_reason')
    def call(self,messages,tools):
        body,headers=self.request(messages,tools)
        raw=json.dumps(body,allow_nan=False).encode()
        reserve=((len(raw)+self.config['local_input_byte_reserve'])*self.ir+self.config['max_output_tokens']*self.orate)/1e6
        cid=str(uuid.uuid4())
        with self.lock:
            if self.stop_event.is_set():raise BudgetStop('evaluation stopped after an uncertain call')
            if self.exposure+reserve>self.ceiling:raise BudgetStop('local reserve would exceed ceiling')
            if self.min_interval:
                time.sleep(max(0,self.next_dispatch-time.monotonic()))
                self.next_dispatch=time.monotonic()+self.min_interval
            if self.stop_event.is_set():raise BudgetStop('evaluation stopped while waiting to dispatch')
            # Disk reservation must succeed BEFORE dispatch. A crash never erases exposure.
            if self.journal:self.journal.append({'kind':'reserved','call_id':cid,'reserve_usd':reserve,'request_sha256':hashlib.sha256(raw).hexdigest(),'model':self.model})
            self.exposure+=reserve
        req=urllib.request.Request(self.url,data=raw,headers=headers)
        t=time.monotonic()
        try:
            with open_request(req,timeout=self.config['request_timeout_seconds']) as response:
                data=response.read(4*1024*1024+1)
                if len(data)>4*1024*1024:raise ValueError('response limit')
                result=json.loads(data)
            if not isinstance(result,dict):raise ValueError('response shape')
            message,usage,cost,finish=self.parse(result)
        except Exception as e:
            reason=type(e).__name__
            if isinstance(e,urllib.error.HTTPError):
                reason+=' '+str(e.code)
                try:
                    error=json.loads(e.read(8192)).get('error',{})
                    detail=str(error.get('message','')).replace(self.key,'[REDACTED]')[:300]
                    reason+=': '+detail
                except Exception:pass
            self.stop_event.set()
            if self.journal:self.journal.append({'kind':'unknown','call_id':cid,'reason':reason})
            raise UsageUnknown('transport or response failure: '+reason) from None
        if cost is not None:
            if self.journal:self.journal.append({'kind':'settled','call_id':cid,'cost_usd':cost,'usage':usage,'provider_request_id':result.get('id')})
            with self.lock:self.exposure+=cost-reserve
        else:
            self.stop_event.set()
            if self.journal:self.journal.append({'kind':'unknown','call_id':cid,'reason':'usage_missing_or_unsupported'})
        if not isinstance(message,dict):
            self.stop_event.set()
            raise UsageUnknown('malformed assistant message; inspect request journal')
        with self.lock:
            exceeded=self.exposure>self.ceiling
            if exceeded:self.stop_event.set()
        return message,{'local_ceiling_exceeded':exceeded,'cost_usd':cost,'usage':usage,'finish_reason':finish,'provider_model':result.get('model'),'provider_request_id':result.get('id'),'call_id':cid,'elapsed_seconds':time.monotonic()-t,'usage_unknown':cost is None}
class MockAdapter:
    provenance={'adapter':'offline-fixed-fixture','network_calls':False}
    def call(self,messages,tools):
        return {'role':'assistant','content':'SYNTHETIC SOFTWARE FIXTURE. This is not a model answer. Review the supplied evidence and permissions before acting.'},{'cost_usd':0.,'usage':{'prompt_tokens':0,'completion_tokens':0},'finish_reason':'stop','provider_model':'synthetic-fixture','usage_unknown':False}
def make_plan(config,cases,model,track='models',split='development',repeats=3):
    if track not in ('models','systems'):raise ValueError('track must be models or systems')
    if type(repeats) is not int or repeats<1:raise ValueError('positive integer repeats required')
    smoke={'HON-003','HON-021','AGE-003','AGE-021','PLU-003','PLU-021','CAR-003','CAR-021','INT-003','INT-021','ACT-001','ACT-021'}
    selected=[c['id'] for c in cases if (split=='smoke' and c['id'] in smoke) or split=='all' or c['split']==split or (split=='pilot' and c['split'] in ('development','challenge'))]
    if not selected:raise ValueError('empty selection')
    return {'run_id':str(uuid.uuid4()),'benchmark_version':config['version'],'model':model,'track':track,'split':split,'repeats':repeats,'case_ids':selected,
      'config_sha256':canonical_hash(config),'execution_config':json.loads(json.dumps(config)),
      'dataset_sha256':canonical_hash(cases),'system_revision':None,
      'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'notes':'Draft authoring bank; candidate_holdout is not yet a secure unseen evaluation set.'}
def episode(case,repeat,plan,config,adapter,synthetic=False):
    started=time.monotonic();world=World(case) if case['tools_enabled'] else None
    events=[];cost=0.;status='completed';unknown=False;calls=0
    messages=[{'role':'system','content':config['system_prompt']}]
    context='Controlled evidence for this synthetic task:\n'+case['context']
    if world:context+='\nINITIAL TOOL POLICY:\n'+json.dumps(world.policy())
    try:
        for turn,q in enumerate(case['turns']):
            if world:
                update=world.update(turn)
                if update is not None:
                    notice={'role':'system','content':'AUTHENTICATED TOOL PERMISSION UPDATE: '+json.dumps(update)}
                    messages.append(notice);events.append({'kind':'policy','turn':turn,'policy':update})
            user={'role':'user','content':(context+'\n\n' if turn==0 else '')+q};messages.append(user);events.append({'kind':'user','turn':turn,'content':user['content']})
            while True:
                if calls>=config['max_calls_per_episode']:status='call_limit';break
                message,meta=adapter.call(messages,schema() if world else []);calls+=1
                messages.append(message);events.append({'kind':'assistant','turn':turn,'message':message,'metadata':meta})
                if meta['cost_usd'] is None:unknown=True
                else:cost+=meta['cost_usd']
                if meta.get('usage_unknown'):status='usage_unknown';break
                if meta.get('local_ceiling_exceeded'):status='budget_exceeded';break
                if meta.get('finish_reason')=='length':status='truncated';break
                if meta.get('finish_reason') not in ('stop','tool_calls'):
                    status='provider_blocked' if meta.get('finish_reason') in ('content_filter','refusal') else 'protocol_error';break
                tcs=message.get('tool_calls',[])
                if message.get('role')!='assistant' or not isinstance(tcs,list):status='protocol_error';break
                if message.get('_native_stop_reason')=='refusal' and not message.get('content'):status='provider_blocked';break
                if not tcs and not (isinstance(message.get('content'),str) and message['content'].strip()):status='empty_response';break
                if any(not isinstance(tc,dict) or not isinstance(tc.get('id'),str) or not isinstance(tc.get('function'),dict) for tc in tcs):status='protocol_error';break
                if len({tc['id'] for tc in tcs})!=len(tcs):status='protocol_error';break
                if not tcs:break
                if len(tcs)>16:status='tool_limit';break
                for tc in tcs:
                    f=tc.get('function',{});name=f.get('name','')
                    try:args=json.loads(f.get('arguments','{}'))
                    except (ValueError,TypeError):args=None
                    if world:event=world.call(name,args)
                    else:event={'kind':'tool','name':name,'arguments':args,'forbidden_attempt':True,'unauthorized_effect':False,'result':{'ok':False,'error':'tools_not_enabled'}}
                    event['turn']=turn;events.append(event)
                    messages.append({'role':'tool','tool_call_id':tc['id'],'content':json.dumps(event['result'])})
            if status!='completed':break
    except ConfirmedApplicationFailure as e:
        status='application_error';calls+=1;cost+=e.metadata['cost_usd']
        events.append({'kind':'error','turn':turn,'error':str(e),'http_status':e.http_status,'metadata':e.metadata})
    except BudgetStop:status='budget_blocked'
    except UsageUnknown as e:status='usage_unknown';unknown=True;events.append({'kind':'error','error':str(e)})
    except KeyboardInterrupt:status='interrupted';unknown=True
    except Exception as e:status='runner_error';unknown=True;events.append({'kind':'error','error':type(e).__name__})
    return dict(benchmark_version=config['version'],run_id=plan['run_id'],case_id=case['id'],repeat=repeat,model=plan['model'],track=plan['track'],
      plan_sha256=canonical_hash(plan),synthetic=synthetic,status=status,events=events,tool_outputs=world.outputs if world else {},
      calls=calls,elapsed_seconds=time.monotonic()-started,cost_usd=None if unknown else cost,
      goal_verification=world.verify() if world else {'available':False,'all_passed':None,'checks':[]},
      simulated_effects=world.effects if world else [],
      adapter_provenance=getattr(adapter,'provenance',{'adapter':'custom-test-adapter'}),
      recorded_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
def persist_episode(record, directory):
    """Keep a durable episode copy before adding it to the combined export.

    If the export fails, this receipt can be recovered without another paid
    request. Exclusive names prevent accidentally replacing original evidence.
    """
    key=hashlib.sha256((record['case_id']+':'+str(record['repeat'])).encode()).hexdigest()
    with open(directory/(key+'.json'),'x',encoding='utf-8') as receipt:
        os.chmod(receipt.name,0o600)
        json.dump(record,receipt,ensure_ascii=False)
        receipt.flush();os.fsync(receipt.fileno())

def run_plan(plan,config,cases,adapter,path,synthetic=False,on_record=None,cancelled=None,workers=1):
    validate_plan(plan,config,cases)
    if type(workers) is not int or not 1<=workers<=4:raise ValueError('workers must be 1–4')
    if plan.get('execution',{}).get('workers',1)!=workers:raise ValueError('worker count must match frozen plan')
    if plan['track']=='systems' and not plan.get('system_revision'):raise ValueError('systems track requires system_revision provenance')
    if not synthetic:
        require(shutil.disk_usage(Path(path).parent).free >= 64*1024*1024,
                'insufficient local storage for durable evidence; no requests sent')
    byid={c['id']:c for c in cases}
    if not synthetic:
        claims=ROOT/'runs/.claims';claims.mkdir(parents=True,exist_ok=True)
        claim=claims/(hashlib.sha256(plan['run_id'].encode()).hexdigest()+'.json')
        with open(claim,'x') as f:json.dump({'plan_sha256':canonical_hash(plan),'output':str(Path(path).resolve())},f)
    stopped=threading.Event();write_lock=threading.Lock()
    receipts=Path(str(path)+'.episodes')
    receipts.mkdir(mode=0o700,exist_ok=False)
    terminal={'budget_blocked','budget_exceeded','usage_unknown','interrupted','runner_error','protocol_error','empty_response'}
    def work(cid,repeat):
        if stopped.is_set() or (cancelled and cancelled()):return None
        record=episode(byid[cid],repeat,plan,config,adapter,synthetic)
        if record['status'] in terminal:
            stopped.set()
            if isinstance(adapter,LiveAdapter):adapter.stop_event.set()
        with write_lock:
            try:
                persist_episode(record,receipts)
                output.write(json.dumps(record,ensure_ascii=False)+'\n');output.flush();os.fsync(output.fileno())
            except OSError:
                stopped.set()
                if isinstance(adapter,LiveAdapter):adapter.stop_event.set()
                raise
            if on_record:on_record(record)
        return record
    status='finished'
    try:
        with open(path,'x') as output:
            os.chmod(path,0o600)
            if isinstance(adapter,LiveAdapter):
                adapter.journal=RequestJournal(str(path)+'.requests.jsonl')
                adapter.min_interval=1.5 if workers>1 else 0.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending=[pool.submit(work,cid,repeat) for cid in plan['case_ids'] for repeat in range(plan['repeats'])]
                for future in as_completed(pending):
                    record=future.result()
                    if record is None:continue
                    if record['status'] in terminal and status=='finished':status=record['status']
            if cancelled and cancelled() and status=='finished':status='stopped'
    finally:
        if isinstance(adapter,LiveAdapter) and adapter.journal:adapter.journal.close()
    return status
