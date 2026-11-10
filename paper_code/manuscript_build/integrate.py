"""Integrate M3/M5 into copies of the M2 manuscripts and verify preservation."""

import argparse
import copy
import difflib
import hashlib
import json
from pathlib import Path
import re
import zipfile

from docx import Document
from docx.enum.section import WD_SECTION_START, WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

import revision_content as content
from supplement_content import SUPPLEMENT_M3, RELATED_TABLE_INTRO
from related_work import RELATED, THIS_WORK

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'docs/m2_m5_20261016'
STUDY = ROOT / 'robustness_runs/m3_receipt_tamper_20261016'
MAIN = HERE / 'manuscript_integrated_M3_M5_20261017.docx'
SI = HERE / 'supplementary_information_M3_M5_20261017.docx'
INPUT_MAIN = BASE / 'manuscript_revised_M2_20261016.docx'
INPUT_SI = BASE / 'supplementary_information_M2_20261016.docx'
ARCHIVES = {
    'evidence/manuscript_revision_review_20261015.zip': ROOT / 'robustness_runs/manuscript_revision_review_20261015.zip',
    'evidence/M3_receipt_interventions_20261016.zip': ROOT / 'docs/M3离线实验报告与复现包_20261016.zip',
}
FAMILIES = [
    ('identity', 'Control: identity'), ('reorder', 'Control: list order'),
    ('whitespace', 'Control: quotation whitespace'),
    ('fabricated_quote', 'Constraint: fabricated quotation'),
    ('unknown_source', 'Constraint: unknown source'),
    ('unknown_passage', 'Constraint: unknown passage'),
    ('omit_source', 'Constraint: omitted source'),
    ('omit_unit', 'Constraint: omitted planned unit'),
    ('extra_unit', 'Constraint: extra unit'),
    ('duplicate_unit', 'Constraint: duplicate unit'),
    ('empty_support', 'Constraint: empty support'),
    ('locator_mismatch', 'Constraint: locator mismatch'),
    ('positive_labels_only', 'Positive verdicts only'),
    ('positive_labels_no_counter', 'Positive verdicts; remove counterevidence'),
    ('genuine_registry_support', 'Positive verdicts; remove counterevidence; genuine registry support'),
    ('completed_as_planned', 'Completed work relabeled as planned'),
]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def check_data():
    assert sha(STUDY / 'manifest.json') == (STUDY / 'manifest.sha256').read_text().strip()
    for name, digest in read(STUDY / 'manifest.json')['immutable'].items():
        assert sha(STUDY / name) == digest, name
    for name, digest in read(STUDY / 'result_manifest.json').items():
        assert sha(STUDY / name) == digest, name
    s = read(STUDY / 'summary.json')
    assert (s['pairs_evaluated'], s['rule_decisions'], s['faults'], s['model_api_calls']) == (371, 742, 0, 0)
    assert s['primary'] == dict(variants=77, parents=9, C_rejected=77, W_released=77,
                                C_only_rejected=77, contract_misses=[])
    assert s['controls'] == dict(variants=144, C_preserved=144, W_preserved=144)
    for key, n, c, w, bad in [('positive_labels_only',48,10,42,0),
                              ('positive_labels_no_counter',48,24,42,12),
                              ('genuine_registry_support',48,36,42,30),
                              ('completed_as_planned',6,0,6,0)]:
        v = s['families'][key]
        assert (v['n'],v['C_released'],v['W_released'],v['C_released_ineligible']) == (n,c,w,bad)
    cd = read(STUDY / 'source/summary.json')
    assert cd['C_receipt_diagnostic']['changed_decisions'] == 0
    for arm in ('C','D'):
        assert cd['groups'][arm]['eligible_release'] == 9
        assert cd['groups'][arm]['false_release'] == 0
    usage = read(BASE / 'M2_usage_audit.json')
    assert usage['arm_totals']['C']['total_tokens'] == 67118
    assert usage['arm_totals']['D']['total_tokens'] == 38125
    return s


def preserve_paths():
    return [INPUT_MAIN, INPUT_SI, BASE/'manuscript.md', BASE/'supplement.md',
            BASE/'literature.json', BASE/'M2_usage_audit.json', *ARCHIVES.values(),
            STUDY/'manifest.json', STUDY/'result_manifest.json', STUDY/'summary.json']


def reset_text(paragraph, text):
    props = copy.deepcopy(paragraph.runs[0]._r.rPr) if paragraph.runs and paragraph.runs[0]._r.rPr is not None else None
    paragraph.clear()
    run = paragraph.add_run(text)
    if props is not None:
        run._r.insert(0, props)


def table(doc, headers, rows, widths, prose=False):
    tbl = doc.add_table(rows=0, cols=len(headers))
    tbl.autofit = False
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    for col, width in zip(tbl.columns, widths):
        col.width = Cm(width)
    pr = tbl._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ['top','bottom','left','right','insideH','insideV']:
        el = OxmlElement('w:' + edge)
        for attr, value in [('val','single'),('sz','4'),('color','D9D9D9')]:
            el.set(qn('w:' + attr), value)
        borders.append(el)
    pr.append(borders)
    margins = OxmlElement('w:tblCellMar')
    for edge, value in [('top','85'),('bottom','85'),('left','90'),('right','90')]:
        el = OxmlElement('w:' + edge)
        el.set(qn('w:w'), value)
        el.set(qn('w:type'), 'dxa')
        margins.append(el)
    pr.append(margins)
    for i, values in enumerate([headers] + rows):
        row = tbl.add_row()
        rp = row._tr.get_or_add_trPr()
        rp.append(OxmlElement('w:cantSplit'))
        if i == 0:
            rp.append(OxmlElement('w:tblHeader'))
        for j, (cell, value, width) in enumerate(zip(row.cells, values, widths)):
            cell.width = Cm(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.05
            p.paragraph_format.keep_with_next = i == 0
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 or prose else WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(str(value))
            r.font.size = Pt(9.5 if prose else 10)
            r.bold = i == 0
            if i == 0:
                shade = OxmlElement('w:shd')
                shade.set(qn('w:fill'), 'EAECEF')
                cell._tc.get_or_add_tcPr().append(shade)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return tbl


def insert_table(doc, key, summary):
    if key == 'related_work':
        rows = [[p['key'] + ' [' + str(p['ref']) + ']', *p['cells']] for p in RELATED]
        rows.append(THIS_WORK)
        return table(doc, ['Work','Verification object','Decision basis','Trust boundary','Resources','Empirical coverage'],
                     rows, [2.6,3.7,5,5,4.2,5.6], prose=True)
    families = FAMILIES if key == 'm3_all' else FAMILIES[-4:]
    assert key in ('m3_all', 'm3_boundary')
    caption = 'Supplementary Table 4  Complete receipt intervention results' if key == 'm3_all' else 'Table 3  Boundary interventions on saved verifier receipts'
    doc.add_paragraph(caption, 'Caption')
    rows = []
    for name, label in families:
        f = summary['families'][name]
        bad = f['ineligible']
        rows.append([label, f['n'], f"{f['C_released']}/{f['n']}", f"{f['W_released']}/{f['n']}",
                     f"{f['C_released_ineligible']}/{bad}" if bad else '-',
                     f"{f['W_released_ineligible']}/{bad}" if bad else '-'])
    return table(doc, ['Intervention','n','C total releases','W total releases','C ineligible releases','W ineligible releases'],
                 rows, [6,1.1,2.25,2.25,2.9,2.9])


def add_blocks(doc, text, summary):
    before = set(doc._element.body)
    for block in text.strip().split('\n\n'):
        if block.startswith('[[TABLE:'):
            insert_table(doc, block[8:-2], summary)
        elif block.startswith('## '):
            doc.add_paragraph(block[3:], 'Heading 1')
        elif block.startswith('### '):
            doc.add_paragraph(block[4:], 'Heading 2')
        else:
            doc.add_paragraph(block)
    return [el for el in doc._element.body if el not in before]


class Editor:
    def __init__(self, docx, markdown, summary):
        self.doc = Document(docx)
        self.text = markdown.read_text(encoding='utf-8')
        self.summary = summary
        self.changes = []

    def paragraph(self, text):
        matches = [p for p in self.doc.paragraphs if p.text == text]
        assert len(matches) == 1, ('paragraph not unique', text[:100], len(matches))
        return matches[0]

    def replace(self, prefix, replacement):
        blocks = self.text.strip().split('\n\n')
        hits = [b for b in blocks if b.startswith(prefix)]
        assert len(hits) == 1, prefix
        old = hits[0]
        p = self.paragraph(old)
        elements = add_blocks(self.doc, replacement, self.summary)
        for el in elements:
            p._p.addprevious(el)
        p._p.getparent().remove(p._p)
        self.text = self.text.replace(old, replacement, 1)
        self.changes.append(dict(action='replace', locator=prefix))

    def insert_before(self, anchor, text):
        assert self.text.count(anchor) == 1, anchor
        visible = re.sub(r'^#{1,3} ', '', anchor)
        p = self.paragraph(visible)
        for el in add_blocks(self.doc, text, self.summary):
            p._p.addprevious(el)
        self.text = self.text.replace(anchor, text.strip() + '\n\n' + anchor, 1)
        self.changes.append(dict(action='insert_before', locator=anchor))

    def append_after(self, exact, text):
        p = self.paragraph(exact)
        for el in add_blocks(self.doc, text, self.summary):
            p._p.addnext(el)
            p = type(p)(el, p._parent)
        assert self.text.count(exact) == 1
        self.text = self.text.replace(exact, exact + '\n\n' + text.strip(), 1)


def reference_update(editor):
    old = [p for p in editor.doc.paragraphs if re.match(r'^\d+\. ', p.text)]
    assert len(old) == 21
    final = [p.text for p in old[:20]]
    anchor = old[-1]
    assert anchor.text.startswith('21. Yao,')
    for record in RELATED:
        if 'reference' not in record:
            continue
        text = str(record['ref']) + '. ' + record['reference']
        paragraph = editor.doc.add_paragraph()
        paragraph._p.insert(0, copy.deepcopy(anchor._p.pPr))
        r = paragraph.add_run(text)
        r.font.size = Pt(10)
        anchor._p.addprevious(paragraph._p)
        final.append(text)
    reset_text(anchor, '30. ' + anchor.text[4:])
    final.append(anchor.text)
    assert len(final) == 30
    editor.text = editor.text.replace('[[REFERENCES:1-21]]', '\n\n'.join(final))
    return final


def table_texts(doc):
    return [[[c.text for c in r.cells] for r in t.rows] for t in doc.tables]


def preserved_parts(source, output):
    checked = []
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
        for name in a.namelist():
            preserve = name.startswith('word/media/') or name.startswith('word/header') or name.startswith('word/footer') or name in ('word/styles.xml','word/numbering.xml','word/theme/theme1.xml')
            if preserve:
                assert a.read(name) == b.read(name), ('changed preserve-only part', name)
                checked.append(name)
    return checked


def validate_outputs():
    main, sup = Document(MAIN), Document(SI)
    prior_main, prior_sup = Document(INPUT_MAIN), Document(INPUT_SI)
    assert table_texts(main)[:3] == table_texts(prior_main)
    assert table_texts(sup)[:3] == table_texts(prior_sup)
    assert len(main.tables) == 4 and len(sup.tables) == 5
    assert len(main.inline_shapes) == 3 and len(sup.inline_shapes) == 4
    assert len(main.sections) == 1 and len(sup.sections) == 2
    assert sup.sections[-1].orientation == WD_ORIENT.LANDSCAPE
    for attr in ('page_width','page_height','top_margin','bottom_margin','left_margin','right_margin'):
        assert getattr(main.sections[0],attr) == getattr(prior_main.sections[0],attr)
        assert getattr(sup.sections[0],attr) == getattr(prior_sup.sections[0],attr)
    texts = ['\n'.join(p.text for p in d.paragraphs) for d in (main,sup)]
    for d, old, text in zip((main,sup),(prior_main,prior_sup),texts):
        assert '[[' not in text and '0.0355' not in text
        assert not d.styles.element.xpath('.//w:pBdr')
        before = set(re.findall(r'\[[A-Z_]{8,}\]', '\n'.join(p.text for p in old.paragraphs)))
        assert set(re.findall(r'\[[A-Z_]{8,}\]', text)) == before
    refs = [p.text for p in main.paragraphs if re.match(r'^\d+\. ',p.text)]
    assert [int(r.split('.')[0]) for r in refs] == list(range(1,31))
    before_refs = texts[0].split('\nReferences\n')[0]
    seen = []
    for match in re.findall(r'\[([\d, -]+)\]',before_refs):
        for item in match.split(','):
            ends = [int(n) for n in item.strip().split('-')]
            for n in range(ends[0],ends[-1]+1):
                if n not in seen:
                    seen.append(n)
    assert seen == list(range(1,31)), seen
    assert '0/48' in texts[0] and '12/36' in texts[0] and '30/36' in texts[0]
    assert len(sup.tables[-1].rows) == 14
    return dict(main_reference_count=len(refs), citation_order_verified=True,
                preserved_existing_tables=True, preserved_author_placeholders=True,
                preserved_main_parts=preserved_parts(INPUT_MAIN, MAIN),
                preserved_supplement_parts=preserved_parts(INPUT_SI, SI),
                figures={'main':3,'supplement':4}, tables={'main':4,'supplement':5})


def build():
    summary = check_data()
    before = {str(p):sha(p) for p in preserve_paths()}
    main = Editor(INPUT_MAIN, BASE/'manuscript.md', summary)
    main.replace('Scientific planning agents need', content.ABSTRACT)
    main.replace('The formal comparison shows', content.INTRO_END)
    # ReAct moves after the nine new references; all prior 1-20 remain unchanged.
    old_impl = next(b for b in main.text.split('\n\n') if b.startswith('The research-planning agent is implemented'))
    main.replace('The research-planning agent is implemented', old_impl.replace('[21]','[30]'))
    main.insert_before('## Results', content.RELATED_WORK)
    main.replace('A further diagnostic reused', content.NATURAL_ABLATION)
    main.insert_before('### Historical planning runs provide context rather than pooled validation', content.M3_RESULTS)
    main.replace('This supports a practical distinction', content.DISCUSSION_SEPARATION)
    main.insert_before('### Interpreting safe narrowing and comparative gains', content.SEMANTIC_EXTENSION)
    main.replace('The threat model covers prescribed', content.THREAT_LIMITS)
    main.replace('Overall, the study provides bounded', content.CONCLUSION)
    old_policy = next(b for b in main.text.split('\n\n') if b.startswith('C used the frozen selective-release-v1 policy.'))
    assert 'A separate model call examined every' in old_policy
    main.replace('C used the frozen selective-release-v1 policy.', old_policy.replace(
        'A separate model call examined every', 'A separate model call was instructed to examine every'))
    main.replace('The controller checked that the receipt', content.CONTROLLER_MECHANICS)
    main.insert_before('### Model calls and resource reporting', content.M3_METHODS)
    main.insert_before('### Statistical Analyses', 'Offline fairness checks, the unmodified-receipt diagnostic and the subsequent receipt interventions made no new model calls; they do not add to these API or token totals.')
    main.insert_before('### Audit and reproducibility', content.M3_STATISTICS)
    main.insert_before('## Data availability', content.M3_AUDIT)
    main.insert_before('## Code availability', content.M3_DATA)
    old_legend = next(b for b in main.text.split('\n\n') if b.startswith('Table 2. Separate post hoc'))
    main.append_after(old_legend.rstrip(), content.M3_LEGEND)
    references = reference_update(main)
    main.doc.save(MAIN)
    (HERE/'manuscript.md').write_text(main.text.rstrip()+'\n',encoding='utf-8')

    sup = Editor(INPUT_SI, BASE/'supplement.md', summary)
    add_blocks(sup.doc, SUPPLEMENT_M3, summary)
    sup.text = sup.text.rstrip() + '\n\n' + SUPPLEMENT_M3 + '\n'
    sup.paragraph('Supplementary Methods for receipt interventions').paragraph_format.page_break_before = True
    sec = sup.doc.add_section(WD_SECTION_START.NEW_PAGE)
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21)
    add_blocks(sup.doc, RELATED_TABLE_INTRO, summary)
    sup.text += '\n' + RELATED_TABLE_INTRO + '\n'
    sup.doc.save(SI)
    (HERE/'supplement.md').write_text(sup.text,encoding='utf-8')

    diffs = []
    for name in ('manuscript.md','supplement.md'):
        diffs.extend(difflib.unified_diff((BASE/name).read_text(encoding='utf-8').splitlines(True),
                                         (HERE/name).read_text(encoding='utf-8').splitlines(True),
                                         fromfile='M2_20261016/'+name,tofile='M3_M5_20261017/'+name))
    (HERE/'revision.diff').write_text(''.join(diffs),encoding='utf-8')
    write_json(HERE/'related_work_sources.json',dict(review_date='2026-10-17',
               scope='Focused primary-source comparison; fixed versions; not a systematic review',
               dimensions=['verification object','decision basis','trust boundary','resources','empirical coverage'],
               papers=RELATED, main_references=references))
    validations = validate_outputs()
    assert before == {str(p):sha(p) for p in preserve_paths()}
    manifest = dict(date='2026-10-17', new_experiment_calls=0,
                    M2_preserved=True,M3_integrated=True,M5_integrated=True,
                    outputs=[dict(file=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in (MAIN,SI)],
                    preserved_sources=before,validation=validations,operations=main.changes)
    write_json(HERE/'build_manifest.json',manifest)
    print(json.dumps(dict(outputs=manifest['outputs'],validation=validations),indent=2))


def raster():
    import pypdfium2 as pdfium
    for name in ('manuscript','supplement'):
        path = HERE/'qa'/(name+'.pdf')
        dest = path.with_suffix('')
        dest.mkdir(exist_ok=True)
        pdf = pdfium.PdfDocument(path)
        rows = []
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=1.5)
            bitmap.to_pil().save(dest/f'page-{i+1:02d}.png')
            text_page = page.get_textpage()
            text = text_page.get_text_range()
            rows.append(dict(page=i+1,characters=len(text),text=text))
            text_page.close()
            bitmap.close()
            page.close()
        pdf.close()
        write_json(dest/'pages.json',rows)
        print(json.dumps(dict(document=name,pages=[dict(page=r['page'],characters=r['characters'],
                           start=r['text'][:70],end=r['text'][-80:]) for r in rows]),indent=2))


def package():
    manifest = read(HERE/'build_manifest.json')
    for p,digest in manifest['preserved_sources'].items():
        assert sha(Path(p)) == digest
    for item in manifest['outputs']:
        assert sha(HERE/item['file']) == item['sha256']
    qa = read(HERE/'QA_VERIFICATION.json')
    assert qa['all_pages_visually_checked'] and qa['status'] == 'passed'
    names = [MAIN.name,SI.name,'manuscript.md','supplement.md','revision.diff',
             'REVISION_NOTES.md','README.md','artifact.md','related_work_sources.json',
             'build_manifest.json','QA_VERIFICATION.json','integrate.py',
             'revision_content.py','supplement_content.py','related_work.py']
    files = {name:(HERE/name).read_bytes() for name in names}
    files['M2_usage_audit.json'] = (BASE/'M2_usage_audit.json').read_bytes()
    files.update({name:p.read_bytes() for name,p in ARCHIVES.items()})
    inventory = {name:dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
                 for name,data in sorted(files.items())}
    files['package_manifest.json'] = (json.dumps(inventory,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    output = HERE.parent/'manuscript_integrated_M3_M5_20261017.zip'
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in files.items():
            z.writestr(name,data)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None and len(z.namelist()) == len(files)
        for name,data in files.items():
            assert z.read(name) == data
    result = dict(path=str(output),bytes=output.stat().st_size,sha256=sha(output),
                  members=len(files),member_hashes_verified=True,source_archives_unchanged=True)
    write_json(HERE/'package_verification.json',result)
    output.with_suffix('.zip.sha256').write_text(sha(output)+'  '+output.name+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','raster','package'])
    args = parser.parse_args()
    {'build':build,'raster':raster,'package':package}[args.action]()
