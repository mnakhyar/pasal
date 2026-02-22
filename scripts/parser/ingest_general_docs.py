"""Batch ingest general (non-legal) PDFs into the knowledge base.

For documents like ESG roadmaps, SOPs, policies, guidelines, etc.
that don't follow the BAB/Pasal/Ayat structure.

Reuses classify_pdf, extract_pymupdf, and ocr_correct from the
parser package. Skips parse_structure (that's for legal docs only)
and instead chunks the text by paragraphs for vector embedding.

Usage:
    python ingest_general_docs.py --dry-run
    python ingest_general_docs.py --file esg_roadmap_2024.pdf
    python ingest_general_docs.py
"""
import csv
import json
import logging
import re
import sys
from pathlib import Path

from scripts.parser.classify_pdf import classify_pdf_quality
from scripts.parser.extract_pymupdf import extract_text_pymupdf
from scripts.parser.ocr_correct import correct_ocr_errors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

PDF_DIR = Path("data/documents")
METADATA_CSV = PDF_DIR / "metadata.csv"

CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
APPROX_CHARS_PER_TOKEN = 4


def load_metadata() -> dict[str, dict]:
    """Read document metadata from the CSV file.

    Required columns: filename, title, category
    Optional columns: subcategory, tags, year, entity, status, source_url
    """
    if not METADATA_CSV.exists():
        log.error(f"Missing metadata file: {METADATA_CSV}")
        sys.exit(1)

    metadata = {}
    with open(METADATA_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)

        required = {"filename", "title", "category"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            log.error(f"CSV is missing columns: {missing}")
            sys.exit(1)

        for row in reader:
            filename = row["filename"].strip()
            if not filename or filename.startswith("#"):
                continue
            metadata[filename] = {
                "title": row["title"].strip(),
                "category": row["category"].strip(),
                "subcategory": row.get("subcategory", "").strip(),
                "tags": [t.strip() for t in row.get("tags", "").split(",") if t.strip()],
                "year": int(row["year"]) if row.get("year", "").strip() else None,
                "entity": row.get("entity", "").strip(),
                "status": row.get("status", "active").strip(),
                "source_url": row.get("source_url", "").strip(),
            }

    log.info(f"Loaded {len(metadata)} entries from metadata CSV")
    return metadata


def chunk_text(text: str, max_chars: int = None, overlap_chars: int = None) -> list[dict]:
    """Split text into overlapping chunks by paragraph boundaries.

    Tries to break at paragraph boundaries (\n\n). Falls back to
    sentence boundaries if a single paragraph exceeds max_chars.
    """
    if max_chars is None:
        max_chars = CHUNK_MAX_TOKENS * APPROX_CHARS_PER_TOKEN
    if overlap_chars is None:
        overlap_chars = CHUNK_OVERLAP_TOKENS * APPROX_CHARS_PER_TOKEN

    paragraphs = re.split(r'\n{2,}', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks = []
    current = ""

    for para in paragraphs:
        # if adding this paragraph exceeds the limit, flush
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            # keep tail for overlap
            overlap = current[-overlap_chars:] if len(current) > overlap_chars else current
            current = overlap + "\n\n" + para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    # return with index metadata
    return [
        {"chunk_index": i, "total_chunks": len(chunks), "text": c}
        for i, c in enumerate(chunks)
    ]


def process_pdf(pdf_path: Path) -> dict | None:
    """Extract and chunk a general PDF.

    Pipeline: classify -> extract -> OCR correct -> chunk
    (no structural parsing — that's for legal docs)
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
    chunks = chunk_text(text)
    log.info(f"  chunked into {len(chunks)} segments")

    return {
        "quality": quality,
        "quality_confidence": confidence,
        "full_text": text,
        "stats": stats,
        "chunks": chunks,
    }


def make_doc_id(filename: str) -> str:
    return Path(filename).stem.lower().replace(" ", "-")


def insert_to_database(meta: dict, parsed: dict, filename: str, dry_run: bool = False):
    """Write document metadata + chunks to the database.

    Uncomment the backend you need.
    """
    doc_id = make_doc_id(filename)

    if dry_run:
        log.info(f"  [dry-run] {doc_id} | {meta['title']} | {len(parsed['chunks'])} chunks")
        return

    # --- Supabase ----------------------------------------------------------
    # import os
    # from supabase import create_client
    #
    # sb = create_client(os.environ["SUPABASE_URL"],
    #                    os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    #
    # doc = sb.table("documents").upsert({
    #     "slug": doc_id,
    #     "title": meta["title"],
    #     "category": meta["category"],
    #     "subcategory": meta.get("subcategory", ""),
    #     "tags": meta.get("tags", []),
    #     "year": meta.get("year"),
    #     "entity": meta.get("entity", ""),
    #     "status": meta.get("status", "active"),
    #     "chunk_count": len(parsed["chunks"]),
    #     "pdf_quality": parsed["quality"],
    # }, on_conflict="slug").execute()
    #
    # doc_db_id = doc.data[0]["id"]
    #
    # # clear old chunks
    # sb.table("document_chunks").delete().eq("document_id", doc_db_id).execute()
    #
    # for chunk in parsed["chunks"]:
    #     sb.table("document_chunks").insert({
    #         "document_id": doc_db_id,
    #         "chunk_index": chunk["chunk_index"],
    #         "content": chunk["text"],
    #     }).execute()

    # --- PostgreSQL (psycopg2) ---------------------------------------------
    # import os, psycopg2
    #
    # conn = psycopg2.connect(os.environ["DATABASE_URL"])
    # cur = conn.cursor()
    #
    # cur.execute("""
    #     INSERT INTO knowledge.documents
    #         (slug,title,category,subcategory,tags,year,entity,status,chunk_count)
    #     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    #     ON CONFLICT (slug) DO UPDATE SET
    #         title=EXCLUDED.title, category=EXCLUDED.category,
    #         chunk_count=EXCLUDED.chunk_count
    #     RETURNING id
    # """, (doc_id, meta["title"], meta["category"],
    #        meta.get("subcategory",""), meta.get("tags",[]),
    #        meta.get("year"), meta.get("entity",""),
    #        meta.get("status","active"), len(parsed["chunks"])))
    # doc_db_id = cur.fetchone()[0]
    #
    # cur.execute("DELETE FROM knowledge.document_chunks WHERE document_id=%s", (doc_db_id,))
    #
    # for chunk in parsed["chunks"]:
    #     cur.execute("""
    #         INSERT INTO knowledge.document_chunks (document_id,chunk_index,content)
    #         VALUES (%s,%s,%s)
    #     """, (doc_db_id, chunk["chunk_index"], chunk["text"]))
    #
    # conn.commit()
    # cur.close()
    # conn.close()

    log.info(f"  inserted: {doc_id} ({len(parsed['chunks'])} chunks)")


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Ingest general document PDFs")
    ap.add_argument("--dry-run", action="store_true", help="Parse only, skip DB writes")
    ap.add_argument("--file", type=str, help="Process one file only")
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
        log.info(f"  [{meta['category']}] {meta['title']}")

        try:
            parsed = process_pdf(pdf)
            if parsed is None:
                skip += 1
                continue

            insert_to_database(meta, parsed, name, dry_run=args.dry_run)
            ok += 1

            if args.output_json:
                results.append({
                    "filename": name,
                    "metadata": meta,
                    "quality": parsed["quality"],
                    "chunk_count": len(parsed["chunks"]),
                    "stats": parsed["stats"],
                    "chunks": parsed["chunks"],
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
