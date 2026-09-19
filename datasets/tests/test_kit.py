"""Offline tests use synthetic fixtures, never claim benchmark-model performance."""
import io
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from datasets.benchkit.adapters import convert, finqa_context, write_prepared, oracle_inputs
from datasets.benchkit.io import read_rows, write_jsonl, write_json, download, digest, git_blob_hash, extract_json_archive
from datasets.benchkit.scoring import align, numeric_value, numeric_equal, safe_program, score_finqa, score_averitec, score_financebench
from datasets.benchkit.cli import prediction_template, export_runtime
from datasets.benchkit.sources import LABELS
from types import SimpleNamespace


def finqa():
    return {'id':'SYNTHETIC/2020/page_1.pdf-0','pre_text':['Revenue rose.'],
            'post_text':['Same accounting basis.'],'table':[['Year','2019','2020'],['Revenue','100','110']],
            'qa':{'question':'What is the revenue growth fraction?','answer':'10%',
                  'exe_ans':0.1,'program':'divide(10, 100)','gold_inds':{'table_1':'SECRET_GOLD'},
                  'model_input':'SECRET_CONTEXT'},'model_input':'SECRET_TOP_LEVEL'}

def finance():
    return {'financebench_id':'SYNTHETIC_FB_1','company':'Fictional Co','doc_name':'Fictional_2020_10K',
            'question':'What is reported revenue?','answer':'110 million','justification':'SECRET_JUSTIFICATION',
            'evidence':[{'evidence_text':'Reported revenue was 110 million.', 'doc_name':'Fictional_2020_10K',
                         'evidence_page_num':0, 'evidence_text_full_page':'SECRET_FULL_PAGE'}]}

def aver(label='Supported'):
    return {'claim':'A fictional product is blue.','label':label,'justification':'SECRET_JUSTIFICATION',
            'claim_types':['SECRET_TYPE'],'fact_checking_strategies':['SECRET_STRATEGY'],
            'fact_checking_article':'https://example.org/answer-key',
            'questions':[{'question':'What color is it?','answers':[{'answer':'Blue','source_url':'https://example.org/source'}]}]}

class AdapterTests(unittest.TestCase):
    def test_finqa_leakage_allowlist(self):
        inp,ref,_=convert('finqa',[finqa()])
        self.assertNotIn('SECRET',json.dumps(inp))
        self.assertEqual(ref[0]['exe_ans'],0.1)
    def test_finance_leakage_allowlist(self):
        inp,ref,_=convert('financebench',[finance()])
        self.assertNotIn('SECRET',json.dumps(inp));self.assertNotIn('answer',inp[0])
    def test_averitec_leakage_allowlist(self):
        inp,ref,_=convert('averitec',[aver()])
        self.assertNotIn('SECRET',json.dumps(inp));self.assertNotIn('answer-key',json.dumps(inp))
        self.assertEqual(inp[0]['claim_id'],0)
    def test_deep_copy(self):
        r=finqa(); inp,_,_=convert('finqa',[r]);inp[0]['table'][0][0]='CHANGED'
        self.assertEqual(r['table'][0][0],'Year')
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):convert('finqa',[finqa(),finqa()])
    def test_unknown_label_rejected(self):
        with self.assertRaises(ValueError):convert('averitec',[aver('greenwashed')])
    def test_label_spelling_alias(self):
        _,r,_=convert('averitec',[aver('Conflicting Evidence/Cherry-picking')]);self.assertEqual(r[0]['label'],LABELS[3])
    def test_expected_count_fail(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):write_prepared(Path(d),'finqa',[finqa()],1147)
            self.assertFalse((Path(d)/'runtime/inputs.jsonl').exists())
    def test_prepared_references_separate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_prepared(root,'finqa',[finqa()],1)
            self.assertTrue((root/'evaluator_only/native_references.json').exists())
            self.assertNotIn('SECRET',(root/'runtime/inputs.jsonl').read_text())
    def test_table_format_independent_of_gold(self):
        inp,_,_=convert('finqa',[finqa()]);chunks=finqa_context(inp[0])
        self.assertEqual([c['chunk_id'] for c in chunks],['text_0','text_1','table_0','table_1'])
        self.assertEqual(chunks[-1]['text'],'Revenue | 100 | 110')
    def test_oracle_label_not_exposed(self):
        i,r,_=convert('averitec',[aver()]);o=oracle_inputs('averitec',i,r)
        self.assertIn('ORACLE',o[0]['evidence_setting']);self.assertNotIn('label',o[0]);self.assertNotIn('justification',o[0])
    def test_finance_oracle_doc_fallback(self):
        i,r,_=convert('financebench',[finance()]);o=oracle_inputs('financebench',i,r)
        self.assertEqual(o[0]['oracle_evidence'][0]['page_index'],0)
    def test_template_not_real_prediction(self):
        i,_,_=convert('averitec',[aver()]);t=prediction_template(i,'averitec')
        self.assertEqual(t[0]['status'],'pending');self.assertIsNone(t[0]['label'])

class ScoreTests(unittest.TestCase):
    def test_numeric_percent_scale(self):self.assertEqual(numeric_value('10%'),.1)
    def test_numeric_no_prose_parsing(self):self.assertIsNone(numeric_value('It was 10%'))
    def test_numeric_no_bool(self):self.assertIsNone(numeric_value(True))
    def test_numeric_no_nonfinite(self):self.assertIsNone(numeric_value(float('inf')))
    def test_numeric_preserves_sign(self):self.assertFalse(numeric_equal('-10','10'))
    def test_numeric_rounded(self):self.assertTrue(numeric_equal(.10000000001,.1))
    def test_finqa_answer_mode_missing_denominator(self):
        refs=[{'example_id':'a','exe_ans':.1},{'example_id':'b','exe_ans':2}]
        out=score_finqa(align(refs,[{'example_id':'a','answer':'10%'}]),answer_only=True)
        self.assertEqual(out['accuracy'],.5);self.assertIn('NOT_official',out['metric'])
    def test_unknown_predictions_rejected(self):
        with self.assertRaises(ValueError):align([{'example_id':'a'}],[{'example_id':'b'}])
    def test_duplicate_predictions_rejected(self):
        with self.assertRaises(ValueError):align([{'example_id':'a'}],[{'example_id':'a'},{'example_id':'a'}])
    def test_empty_selection_rejected(self):
        with self.assertRaises(ValueError):align([{'example_id':'a'}],[],[])
    def test_valid_program(self):self.assertTrue(safe_program(['divide(','10','100',')','EOF'],[]))
    def test_table_program_none(self):self.assertTrue(safe_program(['table_sum(','Revenue','none',')','EOF'],[['Revenue','1','2']]))
    def test_program_no_forward_reference(self):self.assertFalse(safe_program(['add(','#0','1',')','EOF'],[]))
    def test_program_injection_rejected(self):self.assertFalse(safe_program(['eval(','__import__("os")','1',')','EOF'],[]))
    def test_empty_program_rejected(self):self.assertFalse(safe_program(['EOF'],[]))
    def test_averitec_missing_counts_wrong(self):
        _,refs,_=convert('averitec',[aver(),aver('Refuted')])
        p=[{'example_id':refs[0]['example_id'],'label':'Supported'}]
        out=score_averitec(align(refs,p));self.assertEqual(out['accuracy'],.5);self.assertEqual(out['prediction_coverage'],.5)
    def test_averitec_insufficient_to_refuted(self):
        _,r,_=convert('averitec',[aver('Not Enough Evidence')]);p=[{'example_id':r[0]['example_id'],'label':'Refuted'}]
        self.assertEqual(score_averitec(align(r,p))['insufficient_to_refuted_rate'],1)
    def test_averitec_probability_perfect(self):
        _,r,_=convert('averitec',[aver()]);p=[{'example_id':r[0]['example_id'],'label':'Supported','probabilities':{l:float(l=='Supported') for l in LABELS}}]
        self.assertEqual(score_averitec(align(r,p))['multiclass_brier'],0)
    def test_averitec_probability_bad_sum(self):
        _,r,_=convert('averitec',[aver()]);p=[{'example_id':r[0]['example_id'],'label':'Supported','probabilities':{l:.4 for l in LABELS}}]
        with self.assertRaises(ValueError):score_averitec(align(r,p))
    def test_averitec_invalid_label(self):
        _,r,_=convert('averitec',[aver()]);p=[{'example_id':r[0]['example_id'],'label':'deceptive'}]
        with self.assertRaises(ValueError):score_averitec(align(r,p))
    def test_finance_exact_not_claimed_semantic(self):
        _,r,_=convert('financebench',[finance()]);p=[{'example_id':r[0]['example_id'],'answer':'110 million','citations':[{'doc_name':'Fictional_2020_10K','page_index':0}]}]
        out=score_financebench(align(r,p));self.assertEqual(out['mean_annotated_citation_page_recall'],1)
        self.assertIsNone(out['human_answer_accuracy_full_set']);self.assertFalse(out['citation_entailment_automatically_established'])
    def test_finance_human_review(self):
        _,r,_=convert('financebench',[finance()]);p=[{'example_id':r[0]['example_id'],'answer':'110 million'}]
        review=[{'example_id':r[0]['example_id'],'answer_correct':'1','citation_supported':'0','evidence_sufficient':'0'}]
        out=score_financebench(align(r,p),review);self.assertEqual(out['human_answer_accuracy_full_set'],1);self.assertEqual(out['human_evidence_backed_accuracy_on_reviewed'],0)
    def test_finance_missing_cannot_pass_review(self):
        _,r,_=convert('financebench',[finance()]);review=[{'example_id':r[0]['example_id'],'answer_correct':'1','citation_supported':'1','evidence_sufficient':'1'}]
        self.assertEqual(score_financebench(align(r,[]),review)['human_answer_accuracy_full_set'],0)
    def test_finance_reject_one_based_marker_string(self):
        _,r,_=convert('financebench',[finance()]);p=[{'example_id':r[0]['example_id'],'answer':'110 million','citations':[{'doc_name':'d','page_index':'1'}]}]
        with self.assertRaises(ValueError):score_financebench(align(r,p))

class IOTests(unittest.TestCase):
    def test_jsonl_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.jsonl';write_jsonl(p,[{'text':'α\nβ'}]);self.assertEqual(read_rows(p),[{'text':'α\nβ'}])
    def test_download_mock_and_hash(self):
        with tempfile.TemporaryDirectory() as d:
            body=io.BytesIO(b'hello');body.status=200;body.headers={'Content-Length':'5'}
            with patch('urllib.request.urlopen',return_value=body):
                p=Path(d)/'x';out=download('https://example.org/x',p)
            self.assertEqual(p.read_bytes(),b'hello');self.assertEqual(out['sha256'],digest(p))
    def test_cached_download_hash_verified(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'x')
            with self.assertRaises(ValueError):download('https://example.org/x',p,sha256='0'*64)
    def test_download_bad_hash_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';body=io.BytesIO(b'bad');body.status=200;body.headers={}
            with patch('urllib.request.urlopen',return_value=body):
                with self.assertRaises(RuntimeError):download('https://example.org/x',p,sha256='0'*64,attempts=1)
            self.assertFalse(p.exists())
    def test_json_only_archive(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('0.json','{}');z.writestr('model.pkl','danger')
            self.assertEqual(extract_json_archive(p,Path(d)/'out'),1)
            self.assertFalse((Path(d)/'out/model.pkl').exists())
    def test_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../bad.json','{}')
            with self.assertRaises(ValueError):extract_json_archive(p,Path(d)/'out')
    def test_zip_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('a.json','{"long": "data"}')
            with self.assertRaises(ValueError):extract_json_archive(p,Path(d)/'out',max_bytes=1)
    def test_export_runtime_excludes_gold(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_prepared(root,'finqa',[finqa()],1)
            out=root/'export.zip';export_runtime(SimpleNamespace(output=str(out)),root)
            with zipfile.ZipFile(out) as z:
                self.assertTrue(all(n.startswith('runtime/') for n in z.namelist()))
                self.assertNotIn('SECRET',z.read('runtime/inputs.jsonl').decode())

if __name__=='__main__':unittest.main()


class ExportBoundaryTests(unittest.TestCase):
    def test_export_requires_prepared_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                export_runtime(SimpleNamespace(output=str(root / 'empty.zip')), root)

    def test_export_cannot_include_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_prepared(root, 'finqa', [finqa()], 1)
            with self.assertRaises(ValueError):
                export_runtime(SimpleNamespace(output=str(root / 'runtime/self.zip')), root)
