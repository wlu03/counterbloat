from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import importlib
import json
import os
import shutil
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from .sources import SOURCES, FINANCE_REV, LABELS, gh
from . import asa
from .io import download, read_rows, write_json, write_jsonl, digest, git_blob_hash, extract_json_archive
from .adapters import write_prepared, oracle_inputs
from .scoring import align, keyed, score_finqa, score_financebench, score_averitec, usable, canonical_label


def now():
    return datetime.now(timezone.utc).isoformat()


def prepared_files(root):
    return {str(p.relative_to(root)): digest(p) for base in ("runtime", "evaluator_only")
            for p in sorted((root/base).rglob("*")) if p.is_file()}


def prep(args, root, source):
    if not args.accept_license:
        raise ValueError(f"Read THIRD_PARTY_NOTICES.md; rerun with --accept-license. Terms: {source['license']}")
    downloads = []
    raw = root / "evaluator_only/upstream" / source["raw_name"]
    if args.input_file:
        original = Path(args.input_file)
        raw.parent.mkdir(parents=True, exist_ok=True)
        if original.resolve() != raw.resolve():
            shutil.copy2(original, raw)
        if source.get("git_blob_sha1") and git_blob_hash(raw) != source["git_blob_sha1"]:
            raise ValueError("Local source file does not match pinned Git blob hash")
        downloads.append({"local_input":str(original),"sha256":digest(raw)})
    else:
        downloads.append(download(source["data_url"], raw, blob_sha1=source.get("git_blob_sha1")))
    rows = read_rows(raw)
    inputs, refs = write_prepared(root, args.dataset, rows, source["expected_count"])
    # Reference-bearing source data never go under runtime/.
    if "metadata_url" in source:
        meta = root / "runtime/corpus/document_information.jsonl"
        if args.metadata_file:
            meta.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(args.metadata_file,meta)
        else:
            downloads.append(download(source["metadata_url"],meta))
        metadata = read_rows(meta)
        lookup = {r['doc_name'] for r in metadata}
        missing = {r['doc_name'] for r in inputs} - lookup
        if missing:
            raise ValueError(f"Document metadata missing named reports: {sorted(missing)}")
    warnings = []
    for key, filename in (("scorer_url", source.get("scorer_name", "scorer.py")),
                          ("license_url", "UPSTREAM_LICENSE.txt"),("readme_url", "UPSTREAM_README.md")):
        if key in source:
            try:
                dest = root / "evaluator_only/upstream" / filename
                downloads.append(download(source[key], dest))
            except RuntimeError as exc:
                warnings.append(str(exc))
    manifest = {"kit_version":"1.1.0", "prepared_at":now(), "dataset":args.dataset,
                "source":source, "count":len(inputs), "corpus_status":"included_excerpt" if args.dataset=="finqa" else "not_downloaded",
                "downloads":downloads,"warnings":warnings,"prepared_file_sha256":prepared_files(root),
                "dataset_bytes_were_bundled_in_original_kit":False,
                "inference_was_run":False,
                "split_note":"AVeriTeC dev is a local evaluation split, not a blind official test. FinanceBench is the public sample, not an official train/test split."}
    write_json(root/"manifest.json",manifest)
    validate(root,args.dataset)
    print(f"Prepared {len(inputs)} examples in {root}. No model inference has run.")
    if warnings:
        print("Some ancillary downloads failed; inspect manifest.json before official scoring.")


def validate(root,dataset,mode=None):
    if dataset == "asa":
        return asa.validate(root, mode)
    inputs = read_rows(root/"runtime/inputs.jsonl")
    refs = read_rows(root/"evaluator_only/references.jsonl")
    keyed(inputs,"inputs"); keyed(refs,"references")
    if [x['example_id'] for x in inputs] != [x['example_id'] for x in refs]:
        raise ValueError("Input/reference ID alignment failure")
    if len(inputs) != SOURCES[dataset]['expected_count']:
        raise ValueError("Unexpected prepared row count")
    allowed = {
        "finqa":{"example_id","dataset","task","question","pre_text","post_text","table"},
        "financebench":{"example_id","dataset","task","question","company","doc_name"},
        "averitec":{"example_id","dataset","task","claim_id","claim","claim_date","speaker","original_claim_url","cached_original_claim_url","reporting_source","location_ISO_code"},
    }[dataset]
    for row in inputs:
        if set(row)-allowed:
            raise ValueError(f"Non-allowlisted model input fields: {set(row)-allowed}")
    manifest = json.loads((root/"manifest.json").read_text())
    for name, expected in manifest.get("prepared_file_sha256",{}).items():
        path = root/name
        if not path.exists() or digest(path)!=expected:
            raise ValueError(f"Prepared file checksum failed: {name}")
    print(f"Validated {len(inputs)} {dataset} examples, exact input allowlists, ID alignment, and recorded checksums.")


def selection(args):
    if not args.ids:
        return None
    obj = json.loads(Path(args.ids).read_text())
    if isinstance(obj, dict):
        if obj.get('dataset') not in (None, getattr(args, 'dataset', None)):
            raise ValueError('Selection file belongs to another dataset')
        if obj.get('mode') not in (None, getattr(args, 'mode', None)):
            raise ValueError('Selection file belongs to another ASA mode')
        obj = obj['example_ids']
    if not isinstance(obj, list) or not obj or any(not isinstance(i, str) for i in obj):
        raise ValueError('Selection must be a nonempty list of string example IDs')
    return obj


def subset_inputs(root,args):
    inputs = read_rows(root/"runtime/inputs.jsonl")
    ids = selection(args)
    if ids is None:
        return inputs
    lookup = keyed(inputs,"inputs")
    if len(set(ids))!=len(ids) or not ids or set(ids)-set(lookup):
        raise ValueError("Invalid selection IDs")
    return [lookup[i] for i in ids]


def prediction_template(rows,dataset):
    result=[]
    for row in rows:
        item={"example_id":row['example_id'],"status":"pending"}
        if dataset=='finqa':
            item.update(answer=None,predicted_program=None,evidence_ids=[])
        elif dataset=='financebench':
            item.update(answer=None,citations=[])
        else:
            item.update(label=None,evidence=[],probabilities=None)
        result.append(item)
    return result


def make_review(args,root):
    refs = read_rows(root/"evaluator_only/references.jsonl")
    preds = read_rows(Path(args.predictions))
    pairs=align(refs,preds,selection(args))
    questions={r['example_id']:r['question'] for r in read_rows(root/"runtime/inputs.jsonl")}
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    fields=["example_id","question","model_answer","reference_answer","model_citations","reference_evidence",
            "answer_correct","citation_supported","evidence_sufficient","reviewer","notes"]
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for ref,pred in pairs:
            writer.writerow({"example_id":ref['example_id'],"question":questions[ref['example_id']],
                "model_answer":pred.get('answer','') if pred else '',"reference_answer":ref['answer'],
                "model_citations":json.dumps(pred.get('citations',[]) if pred else [],ensure_ascii=False),
                "reference_evidence":json.dumps(ref.get('evidence',[]),ensure_ascii=False)})
    print(f"Wrote {len(pairs)} review rows to {path}. This file contains references: do not expose it to the model.")


def score(args,root):
    if args.dataset == 'asa':
        asa.validate(root, args.mode)
        asa.assert_runtime_mode(root, args.mode, require_ready=True)
        if args.reviews:
            raise ValueError('ASA review-sheet produces a review aid; automatic adjudication import is not implemented')
    refs=read_rows(root/"evaluator_only/references.jsonl")
    preds=read_rows(Path(args.predictions))
    pairs=align(refs,preds,selection(args))
    if args.dataset=='asa':
        result=asa.score(pairs, args.mode, args.allow_draft)
    elif args.dataset=='finqa':
        result=score_finqa(pairs,native=read_rows(root/"evaluator_only/native_references.json"),
            official_path=root/"evaluator_only/upstream/finqa_official.py",answer_only=args.answer_only)
    elif args.dataset=='averitec':
        result=score_averitec(pairs)
    else:
        if args.reviews:
            with Path(args.reviews).open(newline='',encoding='utf-8-sig') as f:
                reviews=list(csv.DictReader(f))
        else:
            reviews=[]
        result=score_financebench(pairs,reviews)
    result.update(dataset=args.dataset,scored_at=now(),prediction_file_sha256=digest(Path(args.predictions)),
                  declared_selection=selection(args),
                  note=("Provisional comparison with user-supplied ASA project-rubric drafts; not independent detection or official ASA labels."
                        if args.dataset == 'asa' else "Local benchmark measurements, not corporate-overstatement accuracy."))
    details=result.pop('details',None)
    write_json(Path(args.output),result)
    if details is not None:
        write_jsonl(Path(args.output).with_suffix('.details.jsonl'),details)
    print(json.dumps(result,indent=2,ensure_ascii=False))


def official_export(args,root):
    refs=read_rows(root/"evaluator_only/references.jsonl")
    pairs=align(refs,read_rows(Path(args.predictions)),selection(args))
    native=read_rows(root/"evaluator_only/native_references.json")
    native_by_id={r['example_id']:n for r,n in zip(refs,native)}
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    predictions=[]
    for ref,p in pairs:
        if args.dataset=='finqa':
            pred=p.get('predicted_program',p.get('predicted')) if usable(p) else None
            predictions.append({'id':ref['example_id'],'predicted':pred or ['EOF']})
        elif args.dataset=='averitec':
            label=canonical_label(p.get('label',p.get('pred_label'))) if usable(p) else '__MISSING__'
            ev=p.get('evidence',[]) if usable(p) else []
            for item in ev:
                if not all(isinstance(item.get(k),str) for k in ('question','answer','url')):
                    raise ValueError('Official AVeriTeC evidence requires question, answer, url strings')
            predictions.append({'claim_id':ref['claim_id'],'pred_label':label or '__MISSING__',
                                'evidence':ev or [{'question':'','answer':'','url':''}]})
        else:
            raise ValueError('FinanceBench needs human correctness review; no equivalent official export is provided.')
    write_json(out/'predictions.json',predictions)
    write_json(out/'references.json',[native_by_id[r['example_id']] for r,p in pairs])
    if args.dataset=='finqa':
        command=f'python "{root / "evaluator_only/upstream/finqa_official.py"}" "{out / "predictions.json"}" "{out / "references.json"}"'
    else:
        command=f'python "{root / "evaluator_only/upstream/averitec_official.py"}" --prediction_file "{out / "predictions.json"}" --label_file "{out / "references.json"}"'
    (out/'COMMAND.txt').write_text(command+'\n',encoding='utf-8')
    print(command)
    print('Export preserves the declared denominator. Empty AVeriTeC evidence uses an empty placeholder for scorer compatibility.')


def corpus(args,root,source):
    if args.dataset=='asa':
        meta=asa.assert_runtime_mode(root,args.mode)
        print(meta['warning'])
        print(f"Supplied corpus has {meta['evidence_documents']} passages. No full ruling, advertisement, or independent document download is supplied.")
        return
    if args.dataset=='finqa':
        print('FinQA supplied excerpts are already included by prepare; full reports are not part of this test package.')
        return
    if not args.accept_license:
        raise ValueError('Read the dataset/source terms and pass --accept-license.')
    records=[]
    if args.dataset=='averitec':
        print(source['corpus_note'])
        print(source['corpus_url'])
        if not args.confirm_large_download:
            print('Planning only. To download, rerun with --confirm-large-download; add --extract to unpack JSON safely.')
            return
        archive=root/'downloads/dev_knowledge_store.zip'
        records.append(download(source['corpus_url'],archive,sha256=source['corpus_sha256']))
        if args.extract:
            count=extract_json_archive(archive,root/'runtime/corpus/knowledge_store_raw')
            print(f'Extracted {count} JSON/JSONL members; no pickle files were loaded. Import/index the per-claim source files in your retriever.')
        status='raw_knowledge_store_extracted_requires_indexing' if args.extract else 'archive_downloaded_not_extracted'
    else:
        tree_path=root/'downloads/financebench_tree.json'
        records.append(download(source['tree_url'],tree_path))
        tree=json.loads(tree_path.read_text())
        if tree.get('truncated'):
            raise ValueError('GitHub tree is truncated; refusing an incomplete corpus')
        pdfs=[x for x in tree['tree'] if x.get('type')=='blob' and x['path'].startswith('pdfs/') and x['path'].lower().endswith('.pdf')]
        if not pdfs:
            raise ValueError('No PDF files discovered in the pinned repository')
        print(f"Pinned public repository: {len(pdfs)} PDF files; {sum(x.get('size',0) for x in pdfs)/1024**2:.1f} MiB Git-reported size.")
        if not args.confirm_large_download:
            print('Planning only. Add --confirm-large-download to fetch the entire PDF collection; --extract also creates a page-text corpus.')
            return
        for n,item in enumerate(pdfs,1):
            path=Path(item['path'])
            if '..' in path.parts or path.is_absolute():
                raise ValueError('Unsafe upstream path')
            url=gh('patronus-ai/financebench',FINANCE_REV,quote(item['path'],safe='/'))
            dest=root/'runtime/corpus'/path
            rec=download(url,dest,blob_sha1=item['sha'])
            with dest.open('rb') as handle:
                signature = handle.read(5)
            if signature != b'%PDF-':
                raise ValueError(f'Not PDF bytes (possibly an LFS pointer): {dest}')
            records.append(rec)
            print(f'[{n}/{len(pdfs)}] {path.name}',flush=True)
        if args.extract:
            extract_finance_pdfs(root)
        status='full_report_pages_extracted' if args.extract else 'full_report_pdfs_downloaded'
    write_json(root/'corpus_manifest.json',{'dataset':args.dataset,'at':now(),'status':status,'downloads':records,
               'historical_availability_verified':False,'corpus_content_manually_reviewed':False})
    print(f'Corpus status: {status}')


def extract_finance_pdfs(root):
    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError('Install requirements-corpus.txt for PDF text extraction') from exc
    pdfs=sorted((root/'runtime/corpus/pdfs').rglob('*.pdf'))
    if not pdfs:
        raise ValueError('No local FinanceBench PDFs')
    def pages():
        for path in pdfs:
            with pymupdf.open(path) as doc:
                for index,page in enumerate(doc):
                    text=page.get_text('text',sort=True)
                    yield {'document_id':path.stem,'page_index':index,'text':text,
                           'pdf_path':str(path.relative_to(root/'runtime')),
                           'extraction':'pymupdf text sort=True; table layout not guaranteed',
                           'quality_flags':['low_text'] if len(text.strip())<30 else []}
    write_jsonl(root/'runtime/corpus/pages.jsonl',pages())


def run_adapter(args,root):
    if args.dataset == 'asa':
        asa.assert_runtime_mode(root, args.mode, require_ready=True)
    if ':' not in args.adapter:
        raise ValueError('Adapter must be module:function, e.g. my_adapter:predict')
    module,name=args.adapter.split(':',1)
    function=getattr(importlib.import_module(module),name)
    rows=subset_inputs(root,args)
    out=Path(args.output)
    if out.exists():
        raise ValueError(f'Refusing to overwrite predictions: {out}')
    out.parent.mkdir(parents=True,exist_ok=True)
    started=now()
    with out.open('w',encoding='utf-8') as f:
        for i,row in enumerate(rows,1):
            start=time.monotonic()
            try:
                # This is an interface boundary, not a sandbox. Mount runtime/ separately
                # for enforced isolation. The runner itself never opens references.
                result=function(copy.deepcopy(row),root/'runtime')
                if not isinstance(result,dict):
                    raise ValueError('Adapter returned a non-dictionary')
                if result.get('example_id',row['example_id']) != row['example_id']:
                    raise ValueError('Adapter returned the wrong example ID')
                result={'example_id':row['example_id'],**result}
                result.setdefault('status','ok')
                if args.dataset == 'asa':
                    if result.get('mode', args.mode) != args.mode or result.get('dataset', 'asa') != 'asa':
                        raise ValueError('Adapter returned a conflicting dataset or mode')
                    result.update(mode=args.mode, dataset='asa')
                    asa.check_prediction(result, args.mode)
                json.dumps(result,allow_nan=False)
            except Exception as exc:
                result={'example_id':row['example_id'],'status':'error','error':str(exc)}
            if args.dataset == 'asa':
                result.update(mode=args.mode, dataset='asa')
            result['elapsed_seconds']=time.monotonic()-start
            f.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n');f.flush()
            print(f"[{i}/{len(rows)}] {row['example_id']}: {result['status']}",flush=True)
    write_json(out.with_suffix('.run.json'),{'dataset':args.dataset,'started':started,'finished':now(),
        'mode':getattr(args,'mode',None), 'adapter':args.adapter,'input_sha256':digest(root/'runtime/inputs.jsonl'),
        'example_ids':[r['example_id'] for r in rows], 'prediction_sha256':digest(out),
        'automatic_paid_provider_calls_by_kit':False,
        'note':'Any model/API calls and costs depend on the user-supplied adapter.'})


def export_runtime(args,root):
    if not (root/'runtime/inputs.jsonl').is_file():
        raise ValueError('Prepare the dataset before exporting runtime inputs')
    target=Path(args.output)
    if target.resolve().is_relative_to((root/'runtime').resolve()):
        raise ValueError('Runtime export ZIP must be outside runtime/')
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((root/'runtime').rglob('*')):
            if p.is_file():
                z.write(p,p.relative_to(root))
    print(f'Exported runtime only to {target}; references, oracle material, and raw answer keys excluded.')


def main():
    base=Path(__file__).resolve().parents[1]
    defaults=json.loads((base/'package.json').read_text()) if (base/'package.json').exists() else {}
    p=argparse.ArgumentParser(description='Unified benchmark interfaces. ASA is bundled; the original three datasets download on your machine.')
    p.add_argument('command',choices=['prepare','validate','select','template','run','score','review-sheet','oracle','official-export','corpus','extract-pdfs','export-runtime','import-predictions','native-export'])
    p.add_argument('--dataset',choices=list(SOURCES),default=defaults.get('default_dataset'))
    p.add_argument('--data-dir',type=Path)
    p.add_argument('--mode',choices=asa.MODES,help='Required for ASA: keeps answer-bearing retrospective and claim-only independent packets separate')
    p.add_argument('--allow-draft',action='store_true',help='Explicitly permit a provisional ASA retrospective draft comparison; never independent scoring')
    p.add_argument('--accept-license',action='store_true')
    p.add_argument('--input-file',type=Path,help='Optional locally downloaded original source file')
    p.add_argument('--metadata-file',type=Path,help='Optional FinanceBench document metadata JSONL')
    p.add_argument('--predictions',type=str)
    p.add_argument('--output',type=str)
    p.add_argument('--ids',type=str,help='Predeclared selection JSON created by select')
    p.add_argument('--count',type=int,default=25)
    p.add_argument('--seed',default='20260919')
    p.add_argument('--answer-only',action='store_true',help='FinQA numeric diagnostic, not official program execution')
    p.add_argument('--reviews',type=str)
    p.add_argument('--adapter',type=str)
    p.add_argument('--acknowledge-oracle',action='store_true')
    p.add_argument('--confirm-large-download',action='store_true')
    p.add_argument('--extract',action='store_true')
    args=p.parse_args()
    if not args.dataset:
        p.error('Choose --dataset finqa, financebench, averitec, or asa')
    if args.dataset == 'asa' and args.mode is None:
        p.error('ASA requires --mode retrospective or --mode independent')
    if args.dataset != 'asa' and (args.mode is not None or args.allow_draft):
        p.error('--mode and --allow-draft apply only to ASA')
    root=args.data_dir or (base/'data'/'asa'/args.mode if args.dataset=='asa' else base/'data'/args.dataset)
    source=SOURCES[args.dataset]
    try:
        output_commands={'select','template','run','score','review-sheet','oracle','official-export','export-runtime','import-predictions','native-export'}
        if args.command in output_commands and not args.output:
            raise ValueError('--output is required')
        if args.command in {'score','review-sheet','official-export','import-predictions','native-export'} and not args.predictions:
            raise ValueError('--predictions is required')
        if args.output:
            dest=Path(args.output).resolve()
            if any(dest.is_relative_to((root/name).resolve()) for name in ('runtime','evaluator_only')):
                raise ValueError('Output must not overwrite or add files inside a prepared runtime/reference packet')
        if args.dataset=='asa' and args.command in {'official-export','oracle'}:
            raise ValueError('ASA has no official benchmark export. Use native-export for its original local scorer, or explicit --mode retrospective for supplied summaries.')
        if args.dataset=='asa' and args.command not in {'prepare','validate'}:
            asa.assert_runtime_mode(root,args.mode)
        if args.command=='prepare':
            if args.dataset=='asa':
                archive=args.input_file or base/source['source_archive']
                asa.prepare(root,archive,args.mode,args.accept_license)
            else:
                prep(args,root,source)
        elif args.command=='validate': validate(root,args.dataset,args.mode)
        elif args.command=='select':
            rows=read_rows(root/'runtime/inputs.jsonl')
            if not 1<=args.count<=len(rows):
                raise ValueError('--count must be between 1 and the dataset size')
            ids=[r['example_id'] for r in sorted(rows,key=lambda r:hashlib.sha256((args.seed+'|'+r['example_id']).encode()).hexdigest())[:args.count]]
            write_json(Path(args.output),{'dataset':args.dataset,'mode':args.mode,'seed':args.seed,'selection':'SHA256(seed|id), no label access','example_ids':ids})
        elif args.command=='template':
            rows=subset_inputs(root,args)
            template=asa.template(rows,args.mode) if args.dataset=='asa' else prediction_template(rows,args.dataset)
            write_jsonl(Path(args.output),template)
        elif args.command=='run':
            if not args.adapter: raise ValueError('--adapter is required')
            run_adapter(args,root)
        elif args.command=='score': score(args,root)
        elif args.command=='review-sheet':
            if args.dataset=='asa':
                refs=read_rows(root/'evaluator_only/references.jsonl')
                pairs=align(refs,read_rows(Path(args.predictions)),selection(args))
                asa.review_sheet(Path(args.output),pairs,read_rows(root/'runtime/inputs.jsonl'))
                print('ASA review CSV created. It contains draft references; never send it to the inference model. No adjudication has occurred.')
            elif args.dataset=='financebench':
                make_review(args,root)
            else: raise ValueError('review-sheet is for FinanceBench or ASA')
        elif args.command=='oracle':
            if not args.acknowledge_oracle:raise ValueError('Oracle evidence supplies annotated answers/evidence. Pass --acknowledge-oracle, and never report this as retrieval.')
            dest=Path(args.output)
            if dest.resolve().is_relative_to((root/'runtime').resolve()):
                raise ValueError('Oracle output must be outside runtime/')
            write_jsonl(dest,oracle_inputs(args.dataset,subset_inputs(root,args),read_rows(root/'evaluator_only/references.jsonl')))
        elif args.command=='official-export': official_export(args,root)
        elif args.command=='corpus': corpus(args,root,source)
        elif args.command=='extract-pdfs':
            if args.dataset!='financebench':raise ValueError('extract-pdfs is for FinanceBench')
            extract_finance_pdfs(root)
        elif args.command=='export-runtime':
            if args.dataset=='asa':
                asa.validate(root,args.mode)
            export_runtime(args,root)
            if args.dataset=='asa': print('ASA export mode:',args.mode,'; only this mode is included. See runtime/metadata.json for evidence limitations.')
        elif args.command=='import-predictions':
            if args.dataset!='asa': raise ValueError('import-predictions currently converts native ASA files only')
            rows=asa.import_native(read_rows(Path(args.predictions)),read_rows(root/'runtime/inputs.jsonl'),read_rows(root/'runtime/corpus/passages.jsonl'),args.mode)
            write_jsonl(Path(args.output),rows)
            print(f'Converted {len(rows)} native ASA predictions; no inference performed.')
        elif args.command=='native-export':
            if args.dataset!='asa': raise ValueError('native-export is for ASA; use official-export for FinQA/AVeriTeC')
            refs=read_rows(root/'evaluator_only/references.jsonl')
            pairs=align(refs,read_rows(Path(args.predictions)),selection(args))
            rows=asa.export_native(pairs,read_rows(root/'runtime/corpus/passages.jsonl'),args.mode)
            dest=Path(args.output);dest.mkdir(parents=True,exist_ok=True)
            native={r['claim_id']:r for r in read_rows(root/'evaluator_only/native_references.json')}
            write_jsonl(dest/'predictions.jsonl',rows)
            write_jsonl(dest/'references.jsonl',[native[r['example_id']] for r,p in pairs])
            print('Exported native ASA predictions and references for the original local scorer, not an official ASA benchmark.')
    except (ValueError,RuntimeError,OSError,KeyError,ImportError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
    return 0
