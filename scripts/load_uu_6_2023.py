"""One-off local script to reload UU 6/2023 (Cipta Kerja ratification) from parsed JSON.

Re-loads the high-quality parsed data (parse confidence: 1.0, 1,349 nodes) and creates
bidirectional relationships with UU 13/2003 (Labor Law).

Usage:
    python scripts/load_uu_6_2023.py
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))

from loader.load_to_supabase import (
    init_supabase, load_work, cleanup_work_data, load_nodes_by_level
)

PARSED_JSON = Path(__file__).parent.parent / "data" / "parsed" / "akn_id_act_uu_2023_6.json"


def insert_uu6_relationships(sb):
    """Insert bidirectional relationships between UU 6/2023 and UU 13/2003."""
    # Fetch relationship type IDs
    rel_result = sb.table("relationship_types").select("id, code").execute()
    rel_map = {r["code"]: r["id"] for r in rel_result.data}

    if "mengubah" not in rel_map or "diubah_oleh" not in rel_map:
        print("  Warning: relationship types 'mengubah' or 'diubah_oleh' not found")
        return 0

    # Fetch work IDs by frbr_uri
    try:
        uu6 = sb.table("works").select("id").eq("frbr_uri", "/akn/id/act/uu/2023/6").single().execute()
        uu13 = sb.table("works").select("id").eq("frbr_uri", "/akn/id/act/uu/2003/13").single().execute()
    except Exception as e:
        print(f"  Warning: failed to fetch work IDs: {e}")
        return 0

    if not uu6.data or not uu13.data:
        print("  Warning: UU 6/2023 or UU 13/2003 not found in database")
        return 0

    # Upsert bidirectional relationship
    relationships = [
        (uu6.data["id"], uu13.data["id"], rel_map["mengubah"], "UU 6/2023 mengubah UU 13/2003"),
        (uu13.data["id"], uu6.data["id"], rel_map["diubah_oleh"], "UU 13/2003 diubah oleh UU 6/2023"),
    ]

    count = 0
    for src_id, tgt_id, rel_type_id, desc in relationships:
        try:
            sb.table("work_relationships").upsert(
                {
                    "source_work_id": src_id,
                    "target_work_id": tgt_id,
                    "relationship_type_id": rel_type_id,
                    "notes": desc,
                },
                on_conflict="source_work_id,target_work_id,relationship_type_id",
            ).execute()
            count += 1
            print(f"  ✓ {desc}")
        except Exception as e:
            print(f"  Error inserting relationship: {e}")

    return count


def main():
    print("=== Loading UU 6/2023 from parsed JSON ===\n")

    if not PARSED_JSON.exists():
        print(f"ERROR: Parsed JSON not found at {PARSED_JSON}")
        return 1

    print(f"Reading: {PARSED_JSON}")
    with open(PARSED_JSON) as f:
        law = json.load(f)

    print(f"  FRBR URI: {law.get('frbr_uri')}")
    print(f"  Title: {law.get('title_id')}")
    print(f"  Nodes: {len(law.get('nodes', []))}")
    print(f"  Parse confidence: {law.get('parse_confidence', 'N/A')}")

    # Initialize Supabase client
    sb = init_supabase()

    # 1. Upsert work metadata (idempotent on frbr_uri)
    print("\n--- Upserting work metadata ---")
    work_id = load_work(sb, law)
    if not work_id:
        print("ERROR: Failed to upsert work")
        return 1
    print(f"  Work ID: {work_id}")

    # 2. Clean existing data (delete suggestions → revisions → document_nodes)
    print("\n--- Cleaning existing data ---")
    cleanup_work_data(sb, work_id)
    print("  Cleaned suggestions, revisions, document_nodes")

    # 3. Insert all nodes in breadth-first batches
    print("\n--- Inserting document nodes ---")
    nodes = law.get("nodes", [])
    pasal_nodes = load_nodes_by_level(sb, work_id, nodes)
    print(f"  Inserted {len(pasal_nodes)} content nodes")

    # 4. Insert bidirectional relationships with UU 13/2003
    print("\n--- Inserting relationships ---")
    rel_count = insert_uu6_relationships(sb)
    print(f"  Inserted {rel_count} relationships")

    # 5. Verify data integrity
    print("\n--- Verifying data ---")
    node_count = sb.table("document_nodes").select("id", count="exact").eq("work_id", work_id).execute()
    pasal_count = sb.table("document_nodes").select("id", count="exact").eq("work_id", work_id).eq("node_type", "pasal").execute()

    print(f"  Total nodes: {node_count.count}")
    print(f"  Pasal nodes: {pasal_count.count}")

    if node_count.count != len(nodes):
        print(f"  Warning: Expected {len(nodes)} nodes, but inserted {node_count.count}")

    print("\n=== Done: UU 6/2023 loaded successfully ===")
    print(f"View at: https://pasal.id/peraturan/uu/uu-6-2023")
    return 0


if __name__ == "__main__":
    sys.exit(main())
