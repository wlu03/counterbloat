"""Local CLI integration checks; generated label-identity files are not model output."""
from pathlib import Path
import subprocess,sys,tempfile,json,zipfile,csv,hashlib
root=Path(__file__).resolve().parents[1]
records=[]

def run(name,*args,expected=0):
    command=[sys.executable,str(root/'benchmark.py'),*map(str,args)]
    p=subprocess.run(command,cwd=root,text=True,capture_output=True,timeout=30)
    rec={'name':name,'args':list(map(str,args)),'expected_exit':expected,'actual_exit':p.returncode,
         'passed':p.returncode==expected,'stdout':p.stdout,'stderr':p.stderr}
    records.append(rec)
    if p.returncode!=expected:raise AssertionError(json.dumps(rec,indent=2))
    return p

with tempfile.TemporaryDirectory(prefix='asa_cli_validation_') as tmp:
    out=Path(tmp);retro=root/'data/asa/retrospective';ind=root/'data/asa/independent'
    run('retrospective validation','validate','--dataset','asa','--mode','retrospective')
    run('independent candidate validation','validate','--dataset','asa','--mode','independent')
    run('mode is mandatory','validate','--dataset','asa',expected=2)
    run('old datasets do not accept ASA flags','validate','--dataset','finqa','--mode','retrospective',expected=2)
    run('prepare is idempotent','prepare','--dataset','asa','--mode','retrospective','--accept-license')
    run('local preparation with archive','prepare','--dataset','asa','--mode','retrospective','--input-file',root/'bundled/ASA_test_pack_2026-09-19.zip','--data-dir',out/'fresh','--accept-license')
    run('mode root mismatch rejected','validate','--dataset','asa','--mode','independent','--data-dir',retro,expected=1)
    run('template','template','--dataset','asa','--mode','retrospective','--output',out/'template.jsonl')
    run('default draft scoring refused','score','--dataset','asa','--mode','retrospective','--predictions',out/'template.jsonl','--output',out/'forbidden.metrics.json',expected=1)
    run('pending scores have zero coverage','score','--dataset','asa','--mode','retrospective','--allow-draft','--predictions',out/'template.jsonl','--output',out/'pending.metrics.json')
    metrics=json.loads((out/'pending.metrics.json').read_text());assert metrics['n']==30 and metrics['prediction_coverage']==0
    run('native null template import','import-predictions','--dataset','asa','--mode','retrospective','--predictions',out/'template.jsonl','--output',out/'imported.pending.jsonl')
    run('independent inference blocked','run','--dataset','asa','--mode','independent','--adapter','example_adapter:predict','--output',out/'independent.pred.jsonl',expected=1)
    run('independent scoring blocked','score','--dataset','asa','--mode','independent','--predictions',out/'template.jsonl','--output',out/'independent.metrics.json',expected=1)
    run('retrospective request builder and abstaining adapter','run','--dataset','asa','--mode','retrospective','--adapter','example_asa_adapter:predict','--output',out/'abstentions.jsonl')
    rows=[json.loads(s) for s in (out/'abstentions.jsonl').read_text().splitlines()];assert len(rows)==30 and all(r['request_evidence_count']==1 and r['status']=='abstained' for r in rows)
    run('score abstentions','score','--dataset','asa','--mode','retrospective','--allow-draft','--predictions',out/'abstentions.jsonl','--output',out/'abstentions.metrics.json')
    run('review sheet','review-sheet','--dataset','asa','--mode','retrospective','--predictions',out/'abstentions.jsonl','--output',out/'review.csv')
    with (out/'review.csv').open() as f:assert len(list(csv.DictReader(f)))==30
    run('retrospective runtime export','export-runtime','--dataset','asa','--mode','retrospective','--output',out/'retro.zip')
    run('independent candidate export','export-runtime','--dataset','asa','--mode','independent','--output',out/'ind.zip')
    with zipfile.ZipFile(out/'ind.zip') as z:
        assert z.read('runtime/corpus/passages.jsonl')==b''
        assert b'asa.org.uk' not in z.read('runtime/inputs.jsonl')
        assert all(n.startswith('runtime/') for n in z.namelist())
    run('no official ASA benchmark export','official-export','--dataset','asa','--mode','retrospective','--predictions',out/'template.jsonl','--output',out/'invalid_export',expected=1)
    run('no synthetic ASA corpus downloader','corpus','--dataset','asa','--mode','independent')
    run('declared pilot selection','select','--dataset','asa','--mode','retrospective','--count','5','--output',out/'pilot.ids.json')
    run('pilot adapter','run','--dataset','asa','--mode','retrospective','--ids',out/'pilot.ids.json','--adapter','example_asa_adapter:predict','--output',out/'pilot.pred.jsonl')
    run('pilot scoring denominator','score','--dataset','asa','--mode','retrospective','--allow-draft','--ids',out/'pilot.ids.json','--predictions',out/'pilot.pred.jsonl','--output',out/'pilot.metrics.json')
    assert json.loads((out/'pilot.metrics.json').read_text())['n']==5
    # Draft-identity fixtures are constructed from evaluator references solely to test
    # mapping, scoring and round trips. They are NOT predictions made by a model.
    refs=[json.loads(s) for s in (retro/'evaluator_only/references.jsonl').read_text().splitlines()]
    identity=[{'example_id':r['example_id'],'mode':'retrospective','status':'ok',
       'material_overstatement':r['draft_material_overstatement'],'evidence_status':r['draft_evidence_status'],
       'evidence_ids':r['allowed_evidence_ids'],'explanation':'IDENTITY FIXTURE, NOT MODEL OUTPUT'} for r in refs]
    (out/'identity.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in identity))
    run('draft identity fixture scorer','score','--dataset','asa','--mode','retrospective','--allow-draft','--predictions',out/'identity.jsonl','--output',out/'identity.metrics.json')
    checked=json.loads((out/'identity.metrics.json').read_text());assert checked['material_accuracy']==1 and checked['joint_accuracy']==1
    run('native roundtrip export','native-export','--dataset','asa','--mode','retrospective','--predictions',out/'identity.jsonl','--output',out/'native')
    run('native roundtrip import','import-predictions','--dataset','asa','--mode','retrospective','--predictions',out/'native/predictions.jsonl','--output',out/'roundtrip.jsonl')
    run('roundtrip scoring','score','--dataset','asa','--mode','retrospective','--allow-draft','--predictions',out/'roundtrip.jsonl','--output',out/'roundtrip.metrics.json')
    checked=json.loads((out/'roundtrip.metrics.json').read_text());assert checked['material_accuracy']==1 and checked['citation_id_validity_DIAGNOSTIC_ONLY']==1
    run('native export refuses missing records','native-export','--dataset','asa','--mode','retrospective','--predictions',out/'abstentions.jsonl','--output',out/'badnative',expected=1)
    run('runtime cannot be overwritten by review output','review-sheet','--dataset','asa','--mode','retrospective','--predictions',out/'template.jsonl','--output',retro/'runtime/answers.csv',expected=1)
    # Execute the inspected original scorer on the explicit identity fixture only.
    with zipfile.ZipFile(root/'bundled/ASA_test_pack_2026-09-19.zip') as z:
        script=out/'native/score.py';script.write_bytes(z.read('ASA_test_pack_2026-09-19/scripts/score.py'))
    p=subprocess.run([sys.executable,str(script),'--predictions',str(out/'native/predictions.jsonl'),
        '--references',str(out/'native/references.jsonl'),'--mode','retrospective','--allow-draft'],text=True,capture_output=True,timeout=30)
    assert p.returncode==0,p.stderr
    native=json.loads(p.stdout);assert native['material_accuracy']==checked['material_accuracy']==1
    assert native['evidence_status_accuracy']==checked['evidence_status_accuracy']==1
    records.append({'name':'original ASA scorer agreement on explicit identity fixture','passed':True,'actual_exit':0,'expected_exit':0,
                    'note':'Mapping test only; not model performance.'})

report={'kind':'CLI_SOFTWARE_VALIDATION_NOT_MODEL_EVALUATION','check_count':len(records),'checks_passed':sum(r['passed'] for r in records),
        'live_network_calls':0,'model_calls':0,'recorded_examples_are_test_fixtures':True,
        'checks':[{k:v for k,v in r.items() if k not in {'stdout','stderr'}} for r in records]}
(root/'validation/asa_cli_checks.json').write_text(json.dumps(report,indent=2)+'\n')
# Human readable results without exposing fake perfect-score outputs as an experiment.
(root/'validation/asa_cli_checks.txt').write_text('\n'.join(('PASS ' if r['passed'] else 'FAIL ')+r['name'] for r in records)+'\n\nThese are software checks, not model evaluations.\n')
print(json.dumps({k:v for k,v in report.items() if k!='checks'},indent=2))
