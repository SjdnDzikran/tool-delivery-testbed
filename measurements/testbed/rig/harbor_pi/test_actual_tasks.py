import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import runner
from harbor_pi import actual_tasks as actual
from harbor_pi.adapter import checked_spec
from harbor_pi.pilot import matrix_specs


class ActualTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ref = {'task_id':'fixture-id','question':'Synthetic fixture?', 'reference_answer':'fixture'}
        (self.root/'reference.json').write_text(json.dumps(self.ref))
        for name in ('instruction.md','verify.py','oracle.json','fixture'):
            (self.root/name).write_text('fixture')
        digest = hashlib.sha256(json.dumps(self.ref, sort_keys=True).encode()).hexdigest()
        (self.root/'receipt.json').write_text(json.dumps({'verified':True,'checks':[{
            'task_id':'fixture-id','candidate_sha256':digest,'question_equal':True,
            'reference_equal':True,'level_equal':True}]}))
        self.manifest = self.root/'manifest.toml'
        self.manifest.write_text('''schema_version=1
[harness]
binary="/bin/true"
required_version="1.0.4"
harbor_pilot_image="fixture"
harbor_actual_tasks=true
gaia_verification_receipt="receipt.json"
[paths]
skills_dir="skills"
[models.glm53flash]
provider="zai"
id="glm-5.3-flash"
thinking="max"
[catalog]
[capabilities]
[tasks.gaia_1]
instruction="instruction.md"
capabilities=[]
catalog=[]
assets={reference="reference.json",verifier="verify.py",oracle="oracle.json"}
[matrix]
modes=["eager","deferred","cli"]
models=["glm53flash"]
catalogs=["required"]
reps=1
''')

    def test_assets_and_receipt_resolved_and_hashed(self):
        m=runner.load_manifest(self.manifest)
        self.assertEqual(m['tasks']['gaia_1']['assets']['reference'],str(self.root/'reference.json'))
        # The normalized manifest digest must change when a verifier asset changes.
        before=runner.sha256_json(m)
        (self.root/'verify.py').write_text('changed fixture')
        self.assertNotEqual(before,runner.sha256_json(runner.load_manifest(self.manifest)))

    def test_explicit_admission_and_three_cells_for_one_task(self):
        m=runner.load_manifest(self.manifest)
        self.assertEqual(len(matrix_specs(m)),3)
        checked_spec(m,'gaia_1','cli','glm53flash','required')
        m['harness']['harbor_actual_tasks']=False
        with self.assertRaises(ValueError): checked_spec(m,'gaia_1','cli','glm53flash','required')

    def test_primary_receipt_is_bound_to_current_candidate(self):
        m=runner.load_manifest(self.manifest)
        actual.validate(m,'gaia_1')
        self.ref['question']='changed question'
        (self.root/'reference.json').write_text(json.dumps(self.ref))
        with self.assertRaises(ValueError): actual.validate(m,'gaia_1')

    def test_missing_asset_rejected(self):
        m=runner.load_manifest(self.manifest)
        (self.root/'verify.py').unlink()
        with self.assertRaises(ValueError): actual.validate(m,'gaia_1')

    def test_v2_contract_is_general_and_v1_remains_available(self):
        from harbor_pi.route_contract import instruction_for
        task='Synthetic task text, preserved verbatim.'
        v1=instruction_for({'harness':{'harbor_route_contract':'declared-route-v1'}},task)
        v2=instruction_for({'harness':{'harbor_route_contract':'declared-route-v2'}},task)
        self.assertTrue(v1.endswith(task) and v2.endswith(task))
        self.assertNotIn('Artifact completion contract',v1)
        self.assertIn('Artifact completion contract',v2)
        self.assertNotIn('ANSWER.md',v2)
        self.assertNotIn('index.md',v2)

    def test_composites_require_both_skills_and_two_routes(self):
        from harbor_pi.bridge import RIG
        from harbor_pi.exposure_audit import audit,programs_for
        m=runner.load_manifest(RIG/'examples/harbor-real-composites-glm.toml')
        self.assertEqual(len(matrix_specs(m)),6)
        for task in ('composite_1','composite_2'):actual.validate(m,task)
        self.assertEqual(programs_for('composite_1'),['bx','psql'])
        self.assertTrue(actual.has_family('composite_2','github'))
        first={'system':'<skill><name>brave-search</name></skill><skill><name>psql</name></skill>'}
        messages=[]
        for n,folder in enumerate(('bx-search','psql')):
            messages.extend([{'role':'assistant','content':[{'type':'toolCall','name':'read','id':str(n),
                'arguments':{'path':'/home/study/skills/'+folder+'/SKILL.md'}}]},
                {'role':'toolResult','toolCallId':str(n),'isError':False}])
        messages.append({'role':'assistant','content':[{'type':'toolCall','name':'bash','id':'run',
            'arguments':{'command':'bx web fixture; psql -Atc fixture'}}]})
        row={'task':'composite_1','mode':'cli','catalog':'required'}
        self.assertTrue(audit(row,first,messages,[])['skill_read_before_cli'])
        self.assertFalse(audit(row,first,messages[:2]+messages[4:],[])['skill_read_before_cli'])

    def test_actual_overlay_is_root_protected_and_dump_removed(self):
        agent=SimpleNamespace(manifest={'tasks':{'employee_demographics_report':{
            'deadline_s':1800,'assets':{'fixture':str(self.root/'fixture')}}},
            'budget':{'max_total_tokens':2000000}},spec={'task':'employee_demographics_report'},_exec=AsyncMock())
        env=SimpleNamespace(upload_file=AsyncMock(),exec=AsyncMock(return_value=SimpleNamespace(return_code=0)))
        asyncio.run(actual.setup_inputs(agent,env))
        calls='\n'.join(str(c) for c in agent._exec.call_args_list)
        self.assertIn('PI_TRIAL_DEADLINE_S=1790',calls)
        self.assertIn('PI_TRIAL_BUDGET_TOKENS=2000000',calls)
        self.assertIn('pg_restore --exit-on-error --no-owner --no-acl',calls)
        self.assertIn('rm /home/study/initial-fixture',calls)
        self.assertEqual(env.exec.call_args.kwargs['user'],'root')


if __name__=='__main__': unittest.main()
