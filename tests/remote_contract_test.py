#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime
from jsonschema import validate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / 'scripts' / 'reproctl.py'
sys.path.insert(0, str(ROOT/'scripts'))
import runtime_engine as rte
PYTHON = os.environ.get('PYTHON', 'python')
TIME_KEYS = {'generated_at','started_at','finished_at','created_at','updated_at','resolved_at','estimated_finish_at','ts','stopped_at'}

def run(args, env, cwd=None, check=True):
    p = subprocess.run([PYTHON, str(CTL), *args], env=env, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError(f"rc={p.returncode}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p

def load(p):
    return json.loads(p.stdout)

def schema(name):
    return json.loads((ROOT/'schemas'/name).read_text(encoding='utf-8'))

def assert_rfc3339_offsets(value, key=None):
    if isinstance(value, dict):
        for k,v in value.items(): assert_rfc3339_offsets(v,k)
    elif isinstance(value, list):
        for v in value: assert_rfc3339_offsets(v,key)
    elif value is not None and isinstance(value,str) and (key in TIME_KEYS or (isinstance(key,str) and key.endswith('_at'))):
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        assert dt.tzinfo is not None and dt.utcoffset() is not None, (key,value)
        assert re.search(r'[+-]\d\d:\d\d$', value), (key,value)

def event_num(event_id):
    return int(event_id.split('-',1)[1])

def main():
    with tempfile.TemporaryDirectory(prefix='paper-repro-remote-contract-') as td:
        t = Path(td)
        control=t/'conda/control'; project_env=t/'conda/project'; fake=t/'bin'; project=t/'project'
        for d in [control/'bin', control/'conda-meta', project_env/'bin', project_env/'conda-meta', fake, project]: d.mkdir(parents=True, exist_ok=True)
        (control/'bin/python').symlink_to(Path(os.sys.executable))
        (project_env/'bin/python').symlink_to(Path(os.sys.executable))
        conda=fake/'conda'
        conda.write_text(f'''#!/usr/bin/env bash\nset -euo pipefail\nif [[ "${{1:-}} ${{2:-}} ${{3:-}}" == "env list --json" ]]; then echo '{{"envs":["{control}","{project_env}"]}}'; exit 0; fi\nif [[ "${{1:-}}" == "run" ]]; then shift; while [[ $# -gt 0 ]]; do case "$1" in --no-capture-output) shift;; -p) shift 2;; *) break;; esac; done; exec "$@"; fi\nexit 2\n''')
        conda.chmod(0o755)
        subprocess.run(['git','init','-q'], cwd=project, check=True)
        env=os.environ.copy(); env.update({
            'PATH': f"{fake}:{env.get('PATH','')}", 'CONDA_PREFIX': str(control), 'CONDA_DEFAULT_ENV':'paper-repro-control-test',
            'XDG_STATE_HOME': str(t/'state'), 'PAPER_REPRO_CONFIG_HOME': str(t/'config'), 'PAPER_REPRO_CONFIG_FILE': str(t/'config/config.json')
        })
        run(['--workspace',str(project),'init','--repository','smoke','--paper','smoke.pdf'],env)
        run(['--workspace',str(project),'env','use','--prefix',str(project_env)],env)

        caps=load(run(['remote','capabilities','--json'],env))
        validate(caps, schema('remote_capabilities.schema.json'))
        assert caps['contract']['status']=='frozen' and caps['contract']['major']==1
        assert caps['capabilities']['snapshot']==1 and caps['capabilities']['session_hint']==1
        assert caps['cursor_scope']=='run' and caps['id_scopes']['task_id']=='run-unique-never-reused'
        assert caps['consumer_rules']['ignore_unknown_fields'] is True
        assert_rfc3339_offsets(caps)

        discover=load(run(['remote','discover','--json'],env))
        validate(discover, schema('remote_discover.schema.json'))
        workspace_id=discover['workspaces'][0]['workspace_id']
        assert re.fullmatch(r'ws-[0-9a-f]{12}',workspace_id)

        d=load(run(['--workspace',str(project),'decisions','assess','--title','远程范围','--question','smoke or full?','--category','experiment-scope','--stage','execution','--impact','high','--reversibility','reversible','--confidence','0.9','--changes-results','--options-json','[{"id":"smoke","label":"Smoke","recommended":true},{"id":"full","label":"Full"}]','--default-option','smoke','--recommended-option','smoke'],env))
        did=d['decision_id']
        decs=load(run(['--workspace',str(project),'remote','decisions','--json'],env))
        validate(decs, schema('remote_decisions.schema.json'))
        assert decs['workspace_id']==workspace_id
        assert decs['decisions'][0]['decision_id']==did and decs['decisions'][0]['allow_custom_answer'] is False
        assert_rfc3339_offsets(decs)

        resolved=load(run(['--workspace',str(project),'remote','decide',did,'smoke','--json'],env))
        validate(resolved, schema('remote_decide_response.schema.json'))
        assert resolved['ok'] and resolved['code']=='resolved' and resolved['resolved_option']=='smoke'
        idem=load(run(['--workspace',str(project),'remote','decide',did,'smoke','--json'],env))
        validate(idem, schema('remote_decide_response.schema.json'))
        assert idem['ok'] and idem['code']=='already_resolved' and idem['conflict'] is False
        conflict=run(['--workspace',str(project),'remote','decide',did,'full','--json'],env,check=False)
        conflict_payload=load(conflict)
        validate(conflict_payload, schema('remote_decide_response.schema.json'))
        assert conflict.returncode==4 and conflict_payload['code']=='already_resolved' and conflict_payload['resolved_option']=='smoke' and conflict_payload['conflict'] is True

        session=load(run(['--workspace',str(project),'remote','session','bind','--session-id','ses_test','--directory',str(project),'--json'],env))
        validate({'schema_version':1,'workspace_id':session['workspace_id'],'run_id':session['run_id'],'opencode':session['opencode']}, schema('remote_session_hint.schema.json'))
        shown=load(run(['--workspace',str(project),'remote','session','show','--json'],env))
        validate(shown, schema('remote_session_hint.schema.json'))
        assert shown['opencode']['hint_only'] is True

        # Create a runtime task directly: scheduler behavior has its own dedicated test;
        # this contract test focuses on stable task semantics and remote serialization.
        run_root=(project/'.paper-repro/current').resolve()
        runtime=rte.RuntimePaths(run_root)
        task_id='TASK-CONTRACT-001'
        created=rte.add_task(
            runtime, display_name='remote-contract-task', stage='execution', command='true',
            workspace=str(project), execution_env={'name':'project','prefix':str(project_env)},
            timeout_seconds=30, estimate_seconds=60, gpu_count=0, task_id=task_id,
            progress_adapter={'type':'native','unit':'item'},
        )
        rte.update_task(runtime, task_id, state='running', started_at=rte.utc_now(), progress={
            'current': 1, 'total': 2, 'percent': 50.0, 'speed': 1.0, 'speed_unit': 'item/s',
            'eta_seconds': 1, 'eta_confidence': 'high', 'eta_source': 'rolling-throughput',
            'estimated_finish_at': rte._estimated_finish(1), 'source': 'native-REPRO_PROGRESS', 'message': 'half',
        })
        rte.emit_event(runtime, 'task.started', task_id=task_id, data={'gpu_ids':[]})
        rte.emit_event(runtime, 'task.progress', task_id=task_id, data={'current':1,'total':2,'percent':50.0,'eta_seconds':1})
        rte.update_task(runtime, task_id, state='succeeded', finished_at=rte.utc_now(), exit_code=0, progress={
            'current': 2, 'total': 2, 'percent': 100.0, 'eta_seconds': 0, 'eta_confidence': 'high',
            'eta_source': 'rolling-throughput', 'estimated_finish_at': rte.utc_now(),
            'source': 'native-REPRO_PROGRESS', 'message': 'done',
        })
        rte.emit_event(runtime, 'task.completed', task_id=task_id, data={'exit_code':0})
        estimate_task='TASK-ESTIMATE-001'
        rte.add_task(
            runtime, display_name='estimate-only', stage='execution', command='true',
            workspace=str(project), execution_env={'name':'project','prefix':str(project_env)},
            timeout_seconds=600, estimate_seconds=120, gpu_count=0, task_id=estimate_task,
        )
        try:
            rte.add_task(
                runtime, display_name='duplicate', stage='execution', command='true',
                workspace=str(project), execution_env={'name':'project','prefix':str(project_env)},
                gpu_count=0, task_id=task_id,
            )
            raise AssertionError('task_id reuse was accepted')
        except rte.RuntimeErrorEx as exc:
            assert 'already exists' in str(exc)

        snap=load(run(['--workspace',str(project),'remote','snapshot','--json'],env))
        validate(snap, schema('remote_snapshot.schema.json'))
        assert snap['workspace']==str(project.resolve()) and snap['workspace_id']==workspace_id
        assert snap['opencode']['session_id']=='ses_test' and snap['opencode']['hint_only'] is True
        assert set(snap['tasks'])=={'active','queued','recent_completed'}
        assert any(x['task_id']==task_id for x in snap['tasks']['recent_completed'])
        estimated=next(x for x in snap['tasks']['queued'] if x['task_id']==estimate_task)
        assert estimated['startup_estimate_seconds']==120 and estimated['progress']['eta_seconds'] is None
        assert estimated['progress']['confidence']=='unknown'
        assert all(x['progress']['confidence'] in {'high','medium','low','unknown'} for group in snap['tasks'].values() for x in group)
        assert 'gpu_telemetry' not in snap
        assert snap['contract']['status']=='frozen'
        assert_rfc3339_offsets(snap)

        missing=load(run(['--workspace',str(project),'remote','events','--after','EVT-999999999999','--json'],env))
        validate(missing, schema('remote_events.schema.json'))
        assert missing['cursor_scope']=='run' and missing['cursor_found'] is False and missing['workspace_id']==workspace_id
        all_events=load(run(['--workspace',str(project),'remote','events','--json'],env))
        validate(all_events, schema('remote_events.schema.json'))
        event_types={x['type'] for x in all_events['events']}
        assert 'decision.created' in event_types and 'decision.resolved' in event_types and 'task.completed' in event_types
        ids=[event_num(x['event_id']) for x in all_events['events']]
        assert ids==sorted(ids) and len(ids)==len(set(ids))
        assert_rfc3339_offsets(all_events)

        # If event-seq.txt is lost, the next ID must continue after the largest existing event.
        max_before=max(ids)
        runtime.event_seq.unlink(missing_ok=True)
        recovered_event=rte.emit_event(runtime, 'contract.seq_recovered', data={})
        assert event_num(recovered_event['event_id']) > max_before

        cmdrec=load(run(['--workspace',str(project),'remote','command','record','--request-id','RCMD-1','--target','opencode','--type','prompt','--state','queued','--requires-idle','--idempotency-key','k1','--summary','safe summary','--json'],env))
        validate({k:v for k,v in cmdrec.items() if k not in {'ok','code'}}, schema('remote_command_audit.schema.json'))

        # accepted does not mean completed; lifecycle is explicit and terminal states cannot be rewritten.
        accepted=load(run(['--workspace',str(project),'remote','command','record','--request-id','RCMD-1','--target','opencode','--type','prompt','--state','accepted','--requires-idle','--idempotency-key','k1','--summary','safe summary','--json'],env))
        assert accepted['state']=='accepted'
        completed=load(run(['--workspace',str(project),'remote','command','record','--request-id','RCMD-1','--target','opencode','--type','prompt','--state','completed','--requires-idle','--idempotency-key','k1','--summary','safe summary','--json'],env))
        assert completed['state']=='completed'
        invalid=run(['--workspace',str(project),'remote','command','record','--request-id','RCMD-1','--target','opencode','--type','prompt','--state','cancelled','--requires-idle','--idempotency-key','k1','--summary','safe summary','--json'],env,check=False)
        assert invalid.returncode==4 and load(invalid)['code']=='invalid_state_transition'
        idem_conflict=run(['--workspace',str(project),'remote','command','record','--request-id','RCMD-2','--target','opencode','--type','prompt','--state','queued','--idempotency-key','k1','--summary','same action different request','--json'],env,check=False)
        assert idem_conflict.returncode==4 and load(idem_conflict)['code']=='idempotency_conflict'
        cmds=load(run(['--workspace',str(project),'remote','command','list','--json'],env))
        validate(cmds, schema('remote_commands.schema.json'))
        assert cmds['commands'][0]['state']=='completed'
        assert_rfc3339_offsets(cmds)

        # Persisted workspace_id survives a directory move.
        moved=t/'project-moved'
        shutil.move(str(project), str(moved))
        moved_snap=load(run(['--workspace',str(moved),'remote','snapshot','--json'],env))
        assert moved_snap['workspace_id']==workspace_id and moved_snap['workspace']==str(moved.resolve())

        print('REMOTE_CONTRACT_TEST_OK')

if __name__ == '__main__': main()
