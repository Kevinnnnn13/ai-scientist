"""Read supplied DOCX text, tables, tracked changes and comments without edits."""

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


def text(node, include_deleted=False):
    parts = []

    def visit(item):
        if item.tag == W + "del" and not include_deleted:
            return
        if item.tag in (W + "t", W + "delText"):
            parts.append(item.text or "")
        elif item.tag == W + "tab":
            parts.append("\t")
        elif item.tag in (W + "br", W + "cr"):
            parts.append("\n")
        for child in item:
            visit(child)

    visit(node)
    return "".join(parts)


def extract(path):
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        paragraphs, tables = [], []
        for i, paragraph in enumerate(document.findall(".//w:body//w:p", NS), 1):
            style = paragraph.find("w:pPr/w:pStyle", NS)
            paragraphs.append({
                "id": "p%04d" % i,
                "style_id": style.get(W + "val") if style is not None else "",
                "text": text(paragraph),
                "deleted_text": [text(n, True) for n in paragraph.findall(".//w:del", NS)],
                "comment_ids": [n.get(W + "id") for n in
                                paragraph.findall(".//w:commentRangeStart", NS)],
            })
        for i, table in enumerate(document.findall(".//w:body/w:tbl", NS), 1):
            tables.append({
                "id": "table%03d" % i,
                "rows": [[text(cell) for cell in row.findall("w:tc", NS)]
                         for row in table.findall("w:tr", NS)],
            })
        supplementary = {}
        for part in ("comments", "footnotes", "endnotes"):
            name = "word/" + part + ".xml"
            if name in archive.namelist():
                root = ET.fromstring(archive.read(name))
                supplementary[part] = [{"id": node.get(W + "id"), "text": text(node, True)}
                                       for node in root]
        return {
            "source_filename": path.name, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "paragraph_index_is_not_page_number": True,
            "text_view": "insertions included, deletions separately recorded",
            "paragraphs": paragraphs, "tables": tables,
            "tracked_insertions": len(document.findall(".//w:ins", NS)),
            "tracked_deletions": len(document.findall(".//w:del", NS)),
            **supplementary,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--feedback", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    for label in ("manuscript", "feedback"):
        document = extract(Path(getattr(args, label)))
        with (output / (label + ".json")).open("x", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        lines = ["# " + document["source_filename"], "",
                 "Paragraph identifiers below are text locators, not page numbers.", ""]
        for paragraph in document["paragraphs"]:
            if paragraph["text"].strip():
                lines += [paragraph["id"] + " [" + paragraph["style_id"] + "]",
                          paragraph["text"], ""]
        for key in ("comments", "footnotes", "endnotes"):
            for item in document.get(key, []):
                lines += [key + " " + str(item["id"]), item["text"], ""]
        with (output / (label + ".md")).open("x", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
        print(json.dumps({
            "source": label, "paragraphs": len(document["paragraphs"]),
            "tables": len(document["tables"]),
            "comments": len(document.get("comments", [])),
            "tracked_insertions": document["tracked_insertions"],
            "tracked_deletions": document["tracked_deletions"],
        }))


if __name__ == "__main__":
    main()
