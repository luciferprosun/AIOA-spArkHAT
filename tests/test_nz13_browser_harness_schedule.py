"""Exercise the actual harness driver against a deterministic delayed UI ACK.

This is a CDP/DOM scheduler mock, not Chrome, Native, Core or isolation evidence.
The old inline driver is extracted unchanged; the revised helper runs unchanged.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

HARNESS_PATH = Path(__file__).with_name('nz13_coding_browser_acceptance.py')
NODE = shutil.which('node')
RUNNER = r'''
const vm=require('node:vm');
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',s=>input+=s);
process.stdin.on('end',async()=>{
 const {expression,state}=JSON.parse(input),nodes={};
 const current=()=>({state:state.ui,authority:'NONE',receipt_present:true});
 const node=id=>nodes[id]||(nodes[id]={value:'',
   get textContent(){return JSON.stringify(current());},
   get disabled(){return state.ui==='CANCELLED';},
   onclick(){this.applyAction();return Promise.resolve();},
   click(){if(!this.disabled)return this.onclick();},
   applyAction(){
     if(id==='coding-create')state.ui='QUEUED';
     if(id==='coding-start')state.ui='RUNNING';
     if(id==='coding-stop'){
       state.posts++;if(state.posts>1)throw Error('Duplicate STOP');
       if(state.started)state.cancels++;
       state.canonical=state.unknown?'UNKNOWN':'CANCELLED';
       // A valid STOP ACK retains RUNNING; only explicit READ adopts terminal.
       state.ui='RUNNING';
     }
     if(id==='coding-refresh'){state.reads++;state.ui=state.canonical;}
   }});
 const context={document:{getElementById:node},localStorage:{length:0},
   sessionStorage:{length:0},setTimeout:callback=>{queueMicrotask(callback);return 0;}};
 try{const value=await vm.runInNewContext(expression,context,{timeout:1000});
   process.stdout.write(JSON.stringify({value,state}));
 }catch(error){process.stdout.write(JSON.stringify({exception:true,state}));}
});
'''


def lifecycle_driver(path):
    """Load a fixed trusted test helper; never evaluate a model-selected program."""
    spec = importlib.util.spec_from_file_location('nz13_bounded_browser_driver_fixture', path)
    if spec is None or spec.loader is None or Path(spec.origin).resolve() != path.resolve():
        raise AssertionError('Browser helper source origin mismatch')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous_path = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous_path
    driver = getattr(module, 'drive_coding_lifecycle', None)
    if not callable(driver):
        raise TypeError('Missing bounded driver helper')
    return driver

@dataclass
class FixtureTask:
    task_id: str = 'bounded-fixture-task'


class DelayedAckPipe:
    def __init__(self, *, unknown=False):
        self.state = {'ui': None, 'canonical': None, 'started': False,
                      'posts': 0, 'reads': 0, 'cancels': 0, 'unknown': unknown}

    def call(self, method, parameters, session):
        if method != 'Runtime.evaluate' or session != 'bounded-fixture-session':
            raise AssertionError('Unexpected mock CDP operation')
        environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG')
                       if key in os.environ}
        reply = subprocess.run([NODE, '-e', RUNNER],
                               input=json.dumps({'expression': parameters['expression'],
                                                 'state': self.state}).encode(),
                               capture_output=True,
                               env=environment, timeout=5, check=True)
        result = json.loads(reply.stdout)
        self.state = result['state']
        if result.get('exception'):
            return {'exceptionDetails': {'text': 'DELAYED_ACK_FIXTURE_FAILURE'}}
        return {'result': {'value': result['value']}}


class StartedCase:
    def __init__(self, pipe, *, refuse=False):
        self.pipe, self.refuse, self.waits = pipe, refuse, 0

    def wait_started(self, task):
        if task.task_id != FixtureTask().task_id:
            raise AssertionError('Wrong fixture task')
        self.waits += 1
        if self.refuse:
            raise RuntimeError('FIXTURE_START_BARRIER_FAILED')
        self.pipe.state['started'] = True


class BrowserHarnessScheduleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(NODE, 'Node is required by the declared qualification matrix')
        self.driver = lifecycle_driver(HARNESS_PATH)

    def test_started_worker_and_delayed_terminal_require_exactly_one_stop(self):
        pipe = DelayedAckPipe()
        case = StartedCase(pipe)
        try:
            result = self.driver(case, FixtureTask(), pipe, 'bounded-fixture-session')
        except AssertionError:
            result = None
        self.assertIsNotNone(result, 'Actual driver timed out on a valid delayed STOP ACK')
        self.assertEqual('CANCELLED', result['final'])
        self.assertEqual((1, 1, 1), (case.waits, pipe.state['posts'], pipe.state['cancels']))
        self.assertGreater(pipe.state['reads'], 0)

    def test_failed_start_barrier_prevents_stop_submission(self):
        pipe = DelayedAckPipe()
        case = StartedCase(pipe, refuse=True)
        try:
            self.driver(case, FixtureTask(), pipe, 'bounded-fixture-session')
        except (RuntimeError, AssertionError):
            pass
        self.assertEqual(1, case.waits)
        self.assertEqual(0, pipe.state['posts'])

    def test_unknown_is_read_but_never_promoted_to_cancelled_or_retried(self):
        pipe = DelayedAckPipe(unknown=True)
        case = StartedCase(pipe)
        completed = False
        try:
            self.driver(case, FixtureTask(), pipe, 'bounded-fixture-session')
            completed = True
        except AssertionError:
            pass
        self.assertFalse(completed)
        self.assertEqual(1, pipe.state['posts'])
        self.assertGreater(pipe.state['reads'], 0)
