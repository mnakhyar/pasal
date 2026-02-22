"""Batch ingest local PDF files into the database.

Reads PDFs from a local directory, runs them through the parser
pipeline, and writes structured data to PostgreSQL (or Supabase).

Usage:
    python ingest_local_pdfs.py --dry-run
    python ingest_local_pdfs.py --file UU_1_2009.pdf
    python ingest_local_pdfs.py --output-json debug.json
    python ingest_local_pdfs.py
"""
import csv
import json
import logging
import sys
from pathlib import Path

from scripts.parser.classify_pdf import classify_pdf_quality
from scripts.parser.extract_pymupdf import extract_text_pymupdf
from scripts.parser.ocr_correct import correct_ocr_errors
from scripts.parser.parse_structure import parse_structure, count_pasals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

PDF_DIR = Path("data/regulations")
METADATA_CSV = PDF_DIR / "metadata.csv"


def load_metadata() -> dict[str, dict]:
    """Read regulation metadata from the CSV file.

    Required columns: filename, type, number, year, title
    Optional columns: status, about, source_url
    """
    if not METADATA_CSV.exists():
        log.error(f"Missing metadata file: {METADATA_CSV}")
        sys.exit(1)

    metadata = {}
    with open(METADATA_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"filename", "type", "number", "year", "title"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            log.error(f"CSV is missing columns: {missing}")
            sys.exit(1)

        for row in reader:
            filename = row["filename"].strip()
            if not filename or filename.startswith("#"):
                continue
            metadata[filename] = {
                "type": row["type"].strip().upper(),
                "number": row["number"].strip(),
                "year": int(row["year"].strip()),
                "title": row["title"].strip(),
                "status": row.get("status", "in_force").strip(),
                "about": row.get("about", "").strip(),
                "source_url": row.get("source_url", "").strip(),
            }

    log.info(f"Loaded {len(metadata)} entries from metadata CSV")
    return metadata


def process_pdf(pdf_path: Path) -> dict | None:
    """Run a single PDF through the full pipeline.

    Steps: classify -> extract text -> OCR correct -> parse structure
    """
    quality, confidence = classify_pdf_quality(pdf_path)
    log.info(f"  classify: {quality} ({confidence:.2f})")

    if quality == "image_only":
        log.warning(f"  image-only PDF, skipping (run ocrmypdf first)")
        return None

    text, stats = extract_text_pymupdf(pdf_path)

    if not text or len(text.strip()) < 100:
        log.warning(f"  extracted text too short ({len(text)} chars), skipping")
        return None

    log.info(f"  extract: {stats['page_count']} pages, {stats['char_count']} chars")

    text = correct_ocr_errors(text)
    nodes = parse_structure(text)
    pasal_count = count_pasals(nodes)
    log.info(f"  parse: {len(nodes)} top-level nodes, {pasal_count} pasal")

    return {
        "quality": quality,
        "quality_confidence": confidence,
        "text": text,
        "stats": stats,
        "nodes": nodes,
        "pasal_count": pasal_count,
    }


def make_slug(meta: dict) -> str:
    reg_type = meta["type"].lower()
    return f"{reg_type}-{meta['number']}-tahun-{meta['year']}"


def insert_to_database(meta: dict, parsed: dict, dry_run: bool = False):
    """Write a parsed regulation into the database.

    Uncomment the backend you need (Supabase or raw PostgreSQL).
    """
    slug = make_slug(meta)

    if dry_run:
        log.info(f"  [dry-run] {slug} | {meta['title']} | {parsed['pasal_count']} pasal")
        return

    # --- Supabase ----------------------------------------------------------
    # import os
    # from supabase import create_client
    #
    # sb = create_client(os.environ["SUPABASE_URL"],
    #                    os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    #
    # reg = sb.table("regulations").upsert({
    #     "type": meta["type"].lower(),
    #     "number": meta["number"],
    #     "year": meta["year"],
    #     "title": meta["title"],
    #     "slug": slug,
    #     "status": meta["status"],
    #     "about": meta.get("about", ""),
    #     "source_url": meta.get("source_url", ""),
    #     "pasal_count": parsed["pasal_count"],
    #     "pdf_quality": parsed["quality"],
    # }, on_conflict="type,number,year").execute()
    #
    # reg_id = reg.data[0]["id"]
    #
    # def _insert_nodes(nodes, parent_id=None):
    #     for node in nodes:
    #         children = node.pop("children", [])
    #         res = sb.table("document_nodes").insert({
    #             "regulation_id": reg_id,
    #             "parent_id": parent_id,
    #             **node,
    #         }).execute()
    #         if children:
    #             _insert_nodes(children, parent_id=res.data[0]["id"])
    #
    # _insert_nodes(parsed["nodes"])

    # --- PostgreSQL (psycopg2) ---------------------------------------------
    # import os, psycopg2
    #
    # conn = psycopg2.connect(os.environ["DATABASE_URL"])
    # cur = conn.cursor()
    #
    # cur.execute("""
    #     INSERT INTO regulations (type,number,year,title,slug,status,about,pasal_count)
    #     VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    #     ON CONFLICT (type,number,year) DO UPDATE SET
    #         title=EXCLUDED.title, status=EXCLUDED.status,
    #         pasal_count=EXCLUDED.pasal_count
    #     RETURNING id
    # """, (meta["type"].lower(), meta["number"], meta["year"],
    #        meta["title"], slug, meta["status"],
    #        meta.get("about",""), parsed["pasal_count"]))
    # reg_id = cur.fetchone()[0]
    #
    # cur.execute("DELETE FROM document_nodes WHERE regulation_id=%s", (reg_id,))
    #
    # def _insert_nodes(nodes, parent_id=None):
    #     for n in nodes:
    #         children = n.pop("children", [])
    #         cur.execute("""
    #             INSERT INTO document_nodes
    #                 (regulation_id,parent_id,type,number,heading,content,sort_order)
    #             VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
    #         """, (reg_id, parent_id, n["type"], n.get("number",""),
    #               n.get("heading",""), n.get("content",""), n["sort_order"]))
    #         nid = cur.fetchone()[0]
    #         if children:
    #             _insert_nodes(children, parent_id=nid)
    #
    # _insert_nodes(parsed["nodes"])
    # conn.commit()
    # cur.close()
    # conn.close()

    log.info(f"  inserted: {slug} ({parsed['pasal_count']} pasal)")


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Ingest local regulation PDFs")
    ap.add_argument("--dry-run", action="store_true", help="Parse only, skip DB writes")
    ap.add_argument("--file", type=str, help="Process one file instead of the whole directory")
    ap.add_argument("--output-json", type=str, help="Dump parsed output to JSON")
    args = ap.parse_args()

    metadata = load_metadata()

    if args.file:
        targets = [PDF_DIR / args.file]
        if not targets[0].exists():
            log.error(f"Not found: {targets[0]}")
            sys.exit(1)
    else:
        targets = sorted(PDF_DIR.glob("*.pdf"))

    if not targets:
        log.error(f"No PDFs in {PDF_DIR}")
        sys.exit(1)

    log.info(f"files: {len(targets)}  mode: {'dry-run' if args.dry_run else 'live'}")

    results = []
    ok, skip, fail = 0, 0, 0

    for pdf in targets:
        name = pdf.name
        log.info(f"\n--- {name}")

        if name not in metadata:
            log.warning(f"  no metadata entry, skipping")
            skip += 1
            continue

        meta = metadata[name]
        log.info(f"  {meta['type']} {meta['number']}/{meta['year']} - {meta['title']}")

        try:
            parsed = process_pdf(pdf)
            if parsed is None:
                skip += 1
                continue

            insert_to_database(meta, parsed, dry_run=args.dry_run)
            ok += 1

            if args.output_json:
                results.append({
                    "filename": name,
                    "metadata": meta,
                    "quality": parsed["quality"],
                    "pasal_count": parsed["pasal_count"],
                    "stats": parsed["stats"],
                    "nodes": parsed["nodes"],
                })

        except Exception as e:
            log.error(f"  failed: {e}", exc_info=True)
            fail += 1

    if args.output_json and results:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info(f"wrote {args.output_json}")

    log.info(f"\ndone - ok:{ok}  skip:{skip}  fail:{fail}  total:{len(targets)}")


if __name__ == "__main__":
    main()
