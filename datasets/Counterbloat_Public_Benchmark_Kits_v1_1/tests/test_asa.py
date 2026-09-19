"""ASA mapping, readiness, leakage and scoring tests. Not model performance."""
import copy
import csv
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from benchkit import asa
from benchkit.io import read_rows, write_json, write_jsonl
from benchkit.scoring import align
from benchkit.cli import export_runtime, run_adapter

BASE = Path(__file__).resolve().parents[1]
ARCHIVE = BASE/'bundled/ASA_test_pack_2026-09-19.zip'


def fixture():
    common = {'claim_id':'ASA-SYNTHETIC', 'company':'Fictional company','brand':'Fictional',
        'product':'Fictional product','ad_variant':'headline','original_claim_excerpt':'A measured result.',
        'claim_representation':'explicit_excerpt','context_paraphrase':'A neutral context.',
        'original_claim_is_excerpt':True,'full_original_ad_available':False,
        'observed_date':'2026-01','observed_date_precision':'month','first_publication_date':None}
    inp = dict(common, independent_assessment_cutoff=None, allowed_independent_evidence_documents=[])
    retro = dict(common, mode='retrospective_explanation',assessment_cutoff='2026-03-01',
        allowed_evidence_documents=[{'document_id':'R1-summary','type':'compiler_paraphrase_of_ASA_assessment',
             'source_url':'https://example.org/ruling','source_date':'2026-03-01','locator':'Assessment',
             'text':'ANSWER_BEARING_SYNTHETIC_SUMMARY','answer_bearing':True,'full_ruling_reproduced':False}])
    ref = dict(common, draft_material_overstatement='Present',draft_evidence_status='Mixed',
        reviewed_reference_assessment=None,review_status='unreviewed_compiler_draft',
        independent_readiness='blocked',independent_assessment_cutoff=None,
        company_group='fictional',campaign_group='R1',ruling_id='R1',
        asa_url='https://example.org/ruling',native_ruling_decision='Upheld in part',
        asa_assessment_paraphrase='ANSWER_BEARING_SYNTHETIC_SUMMARY')
    return {'claim_inputs':[inp],'retrospective_inputs':[retro],'references':[ref]}


def prediction(ref, **changes):
    p={'example_id':ref['example_id'],'mode':'retrospective','status':'ok',
       'material_overstatement':ref['draft_material_overstatement'],
       'evidence_status':ref['draft_evidence_status'],'evidence_ids':ref['allowed_evidence_ids']}
    p.update(changes)
    return p


class SourceTests(unittest.TestCase):
    def test_pinned_uploaded_archive_and_inner_hashes(self):
        s=asa.load_source(ARCHIVE)
        self.assertEqual(len(s['references']),30)
        self.assertEqual(len({r['ruling_id'] for r in s['references']}),24)
    def test_tampered_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.zip';p.write_bytes(b'not the source')
            with self.assertRaises(ValueError):asa.load_source(p)
    def test_required_explicit_mode(self):
        with self.assertRaises(ValueError):asa.convert(fixture(),None)
    def test_independent_has_no_answers_or_source_urls(self):
        inputs,refs,docs,_=asa.convert(fixture(),'independent')
        text=json.dumps(inputs)
        self.assertNotIn('ANSWER_BEARING',text);self.assertNotIn('example.org',text)
        self.assertNotIn('Upheld',text);self.assertEqual(docs,[])
        self.assertEqual(inputs[0]['allowed_evidence_ids'],[])
    def test_retrospective_summary_is_explicit_and_not_label_field(self):
        inp,refs,docs,_=asa.convert(fixture(),'retrospective')
        self.assertNotIn('draft_material_overstatement',inp[0])
        self.assertTrue(docs[0]['answer_bearing'])
        self.assertEqual(inp[0]['evidence_setting'],'RETROSPECTIVE_ANSWER_BEARING_SUMMARY')
    def test_case_identity_and_date_precision_preserved(self):
        inp,_,_,_=asa.convert(fixture(),'independent')
        self.assertEqual(inp[0]['example_id'],'ASA-SYNTHETIC')
        self.assertEqual(inp[0]['observed_date'],'2026-01')
        self.assertEqual(inp[0]['observed_date_precision'],'month')
        self.assertIsNone(inp[0]['assessment_cutoff'])
    def test_native_partial_upheld_not_collapsed(self):
        _,refs,_,_=asa.convert(fixture(),'retrospective')
        self.assertEqual(refs[0]['native_ruling_decision'],'Upheld in part')
        self.assertEqual(refs[0]['draft_evidence_status'],'mixed')
    def test_duplicate_claim_rejected(self):
        s=fixture();s['claim_inputs'].append(s['claim_inputs'][0])
        with self.assertRaises(ValueError):asa.convert(s,'retrospective')
    def test_misaligned_files_rejected(self):
        s=fixture();s['references'][0]['claim_id']='other'
        with self.assertRaises(ValueError):asa.convert(s,'retrospective')
    def test_mode_content_mismatch_rejected(self):
        s=fixture();s['retrospective_inputs'][0]['context_paraphrase']='Different wording'
        with self.assertRaises(ValueError):asa.convert(s,'retrospective')
    def test_different_summaries_same_native_doc_id_are_namespaced(self):
        s=fixture()
        for name in ('claim_inputs','retrospective_inputs','references'):
            row=copy.deepcopy(s[name][0]);row['claim_id']='ASA-SECOND'
            s[name].append(row)
        s['retrospective_inputs'][1]['allowed_evidence_documents'][0]['text']='OTHER_SUMMARY'
        inp,_,docs,_=asa.convert(s,'retrospective')
        self.assertEqual(len({d['document_id'] for d in docs}),2)
        self.assertEqual(len({d['source_document_id'] for d in docs}),1)
    def test_actual_pack_summary_identity_integrity(self):
        inp,refs,docs,mappings=asa.convert(asa.load_source(ARCHIVE),'retrospective')
        self.assertEqual(len(docs),30);self.assertEqual(len({d['document_id'] for d in docs}),30)
        self.assertEqual(sum(r['draft_material_overstatement']=='present' for r in refs),20)
        self.assertEqual(sum(r['draft_material_overstatement']=='absent' for r in refs),7)
        self.assertEqual(sum(r['draft_material_overstatement']=='undetermined' for r in refs),3)
        self.assertEqual(len({m['company_group'] for m in mappings}),23)
    def test_conversion_does_not_mutate_source(self):
        s=fixture();before=copy.deepcopy(s);asa.convert(s,'retrospective');self.assertEqual(s,before)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.inputs,self.refs,self.docs,_=asa.convert(fixture(),'retrospective')
        self.r=self.refs[0];self.p=prediction(self.r)
    def score(self,p=None,refs=None,**kwargs):
        return asa.score(align(refs or self.refs,p if p is not None else [self.p]),'retrospective',**kwargs)
    def test_default_refuses_unreviewed_references(self):
        with self.assertRaises(ValueError):self.score()
    def test_draft_identity_only_checks_plumbing(self):
        r=self.score(allow_draft=True)
        self.assertEqual(r['material_accuracy'],1);self.assertEqual(r['joint_accuracy'],1)
        self.assertFalse(r['independent_detection_evaluated'])
        self.assertIn('PROVISIONAL',r['reference_status']);self.assertIsNone(r['evidence_backed_correctness'])
    def test_missing_prediction_stays_in_denominator(self):
        r=self.score([],allow_draft=True)
        self.assertEqual(r['n'],1);self.assertEqual(r['material_accuracy'],0);self.assertEqual(r['prediction_coverage'],0)
        self.assertEqual(r['material_confusion']['present']['__MISSING__'],1)
    def test_failed_abstained_pending_are_not_verdicts(self):
        for status in ('error','abstained','pending'):
            p={'example_id':self.r['example_id'],'mode':'retrospective','status':status}
            self.assertEqual(self.score([p],allow_draft=True)['material_accuracy'],0)
    def test_error_with_status_ok_cannot_score_correct(self):
        p=dict(self.p,error='provider failure')
        self.assertEqual(self.score([p],allow_draft=True)['prediction_coverage'],0)
    def test_undetermined_is_a_completed_native_decision(self):
        r=copy.deepcopy(self.r);r['draft_material_overstatement']='undetermined'
        out=self.score([prediction(r)],refs=[r],allow_draft=True)
        self.assertEqual(out['prediction_coverage'],1);self.assertEqual(out['determinate_prediction_rate'],0)
    def test_invalid_completed_labels_fail(self):
        with self.assertRaises(ValueError):self.score([dict(self.p,material_overstatement='Upheld')],allow_draft=True)
    def test_mode_mismatch_fails(self):
        with self.assertRaises(ValueError):self.score([dict(self.p,mode='independent')],allow_draft=True)
    def test_missing_mode_fails(self):
        p=copy.deepcopy(self.p);p.pop('mode')
        with self.assertRaises(ValueError):self.score([p],allow_draft=True)
    def test_false_adverse_and_two_dimensions_separate(self):
        r=dict(self.r,draft_material_overstatement='absent',draft_evidence_status='supported')
        p=dict(self.p,evidence_status='supported')
        out=self.score([p],refs=[r],allow_draft=True)
        self.assertEqual(out['false_adverse_finding_rate_on_absent'],1)
        self.assertEqual(out['evidence_status_accuracy'],1);self.assertEqual(out['joint_accuracy'],0)
    def test_cross_case_citation_is_invalid_diagnostic(self):
        r=self.score([dict(self.p,evidence_ids=['OTHER:R1-summary'])],allow_draft=True)
        self.assertEqual(r['citation_id_validity_DIAGNOSTIC_ONLY'],0)
        self.assertTrue(r['details'][0]['invalid_evidence_ids'])
    def test_empty_citations_do_not_pass_vacuously(self):
        r=self.score([dict(self.p,evidence_ids=[])],allow_draft=True)
        self.assertIsNone(r['citation_id_validity_DIAGNOSTIC_ONLY']);self.assertEqual(r['citation_coverage'],0)
    def test_valid_citation_is_not_entailment_grade(self):
        r=self.score(allow_draft=True)
        self.assertEqual(r['citation_id_validity_DIAGNOSTIC_ONLY'],1);self.assertIsNone(r['explanation_correctness'])
    def test_probability_identity(self):
        p=dict(self.p,probabilities={'present':1.0,'absent':0.0,'undetermined':0.0})
        r=self.score([p],allow_draft=True)
        self.assertEqual(r['multiclass_brier'],0);self.assertEqual(r['probability_coverage'],1)
    def test_bad_probabilities_rejected(self):
        for prob in ({'present':True,'absent':0,'undetermined':0},
                     {'present':float('nan'),'absent':0,'undetermined':0},
                     {'present':.6,'absent':.6,'undetermined':0},
                     {'present':.1,'absent':.8,'undetermined':.1}, {'present':1}):
            with self.assertRaises(ValueError):self.score([dict(self.p,probabilities=prob)],allow_draft=True)
    def test_adjudication_mode_is_not_interchangeable(self):
        r=dict(self.r,review_status='adjudicated',reviewed_reference_assessment={
            'mode':'independent','material_overstatement':'present','evidence_status':'mixed'})
        with self.assertRaises(ValueError):self.score(refs=[r],allow_draft=True)
    def test_independent_scoring_refused_even_for_missing_predictions(self):
        _,refs,_,_=asa.convert(fixture(),'independent')
        with self.assertRaises(ValueError):asa.score(align(refs,[]),'independent')
    def test_readiness_flag_alone_cannot_unlock(self):
        _,refs,_,_=asa.convert(fixture(),'independent')
        refs[0]['independent_readiness']='ready'
        with self.assertRaises(ValueError):asa.score(align(refs,[]),'independent')
    def test_draft_forbidden_in_independent(self):
        _,refs,_,_=asa.convert(fixture(),'independent')
        with self.assertRaises(ValueError):asa.score(align(refs,[]),'independent',True)
    def test_unknown_and_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):align(self.refs,[dict(self.p,example_id='other')])
        with self.assertRaises(ValueError):align(self.refs,[self.p,self.p])


class NativeConversionTests(unittest.TestCase):
    def setUp(self):
        self.inputs,self.refs,self.docs,_=asa.convert(fixture(),'retrospective')
        self.native={'claim_id':'ASA-SYNTHETIC','material_overstatement':'Present','evidence_status':'Mixed',
          'probabilities':{'Present':1.,'Absent':0.,'Undetermined':0.},'explanation':'Synthetic test.',
          'evidence_ids':['R1-summary']}
    def test_native_roundtrip(self):
        p=asa.import_native([self.native],self.inputs,self.docs,'retrospective')
        self.assertEqual(p[0]['evidence_ids'],['ASA-SYNTHETIC:R1-summary'])
        out=asa.export_native(align(self.refs,p),self.docs,'retrospective')
        self.assertEqual(out,[self.native])
    def test_original_null_template_stays_pending(self):
        n=dict(self.native,material_overstatement=None,evidence_status=None,probabilities=None,evidence_ids=[])
        out=asa.import_native([n],self.inputs,self.docs,'retrospective')
        self.assertEqual(out[0]['status'],'pending')
    def test_conflicting_native_id_rejected(self):
        with self.assertRaises(ValueError):asa.import_native([dict(self.native,example_id='other')],self.inputs,self.docs,'retrospective')
    def test_native_unknown_citation_rejected(self):
        with self.assertRaises(ValueError):asa.import_native([dict(self.native,evidence_ids=['other'])],self.inputs,self.docs,'retrospective')
    def test_native_export_will_not_drop_failed_cases(self):
        with self.assertRaises(ValueError):asa.export_native(align(self.refs,[]),self.docs,'retrospective')


class PreparedPacketTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'packet'
        asa.prepare(self.root,ARCHIVE,'retrospective',True)
    def tearDown(self):self.tmp.cleanup()
    def test_mode_cannot_be_reused_in_same_root(self):
        with self.assertRaises(ValueError):asa.prepare(self.root,ARCHIVE,'independent',True)
    def test_repeat_preparation_is_idempotent(self):
        before=(self.root/'manifest.json').read_bytes()
        asa.prepare(self.root,ARCHIVE,'retrospective',True)
        self.assertEqual(before,(self.root/'manifest.json').read_bytes())
    def test_tamper_detected_before_scoring(self):
        with (self.root/'runtime/inputs.jsonl').open('a') as f:f.write('{}\n')
        with self.assertRaises((ValueError,KeyError)):asa.validate(self.root,'retrospective')
    def test_extra_reference_file_in_runtime_rejected(self):
        (self.root/'runtime/answers.txt').write_text('accidental answer key')
        with self.assertRaises(ValueError):asa.validate(self.root,'retrospective')
    def test_export_contains_only_one_mode_runtime(self):
        out=Path(self.tmp.name)/'export.zip'
        export_runtime(SimpleNamespace(output=str(out)),self.root)
        with zipfile.ZipFile(out) as z:
            self.assertTrue(all(n.startswith('runtime/') for n in z.namelist()))
            self.assertNotIn('references.jsonl',' '.join(z.namelist()))
            self.assertEqual(json.loads(z.read('runtime/metadata.json'))['mode'],'retrospective')
    def test_runner_does_not_read_references(self):
        def fake(example,runtime_dir):
            return {'status':'abstained','reason':'Synthetic adapter boundary test'}
        args=SimpleNamespace(dataset='asa',mode='retrospective',ids=None,adapter='synthetic:predict',output=str(Path(self.tmp.name)/'pred.jsonl'))
        # If the runner read evaluator references it would fail after we remove them.
        import shutil
        shutil.rmtree(self.root/'evaluator_only')
        with patch('benchkit.cli.importlib.import_module',return_value=SimpleNamespace(predict=fake)):
            run_adapter(args,self.root)
        rows=read_rows(Path(args.output))
        self.assertEqual(len(rows),30);self.assertTrue(all(r['status']=='abstained' for r in rows))
        self.assertTrue(all(r['mode']=='retrospective' for r in rows))
    def test_runner_catches_bad_output_as_error(self):
        args=SimpleNamespace(dataset='asa',mode='retrospective',ids=None,adapter='synthetic:predict',output=str(Path(self.tmp.name)/'bad.jsonl'))
        with patch('benchkit.cli.importlib.import_module',return_value=SimpleNamespace(predict=lambda a,b: {'status':'ok','material_overstatement':'Upheld'})):
            run_adapter(args,self.root)
        self.assertTrue(all(r['status']=='error' for r in read_rows(Path(args.output))))
    def test_independent_metadata_flag_alone_not_ready(self):
        root=Path(self.tmp.name)/'independent';asa.prepare(root,ARCHIVE,'independent',True)
        meta=json.loads((root/'runtime/metadata.json').read_text());meta['independent_scoring_ready']=True
        write_json(root/'runtime/metadata.json',meta)
        with self.assertRaises(ValueError):asa.assert_runtime_mode(root,'independent',require_ready=True)
    def test_prepare_requires_license_ack(self):
        with self.assertRaises(ValueError):asa.prepare(Path(self.tmp.name)/'new',ARCHIVE,'retrospective',False)
    def test_review_sheet_is_blank_not_adjudication(self):
        refs=read_rows(self.root/'evaluator_only/references.jsonl');inputs=read_rows(self.root/'runtime/inputs.jsonl')
        p=Path(self.tmp.name)/'review.csv';asa.review_sheet(p,align(refs,[]),inputs)
        with p.open() as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),30)
        self.assertTrue(all(r['adjudicated_material']=='' for r in rows))


if __name__=='__main__':unittest.main()
