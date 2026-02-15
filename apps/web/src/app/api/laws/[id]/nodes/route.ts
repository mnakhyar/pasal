import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const revalidate = 86400; // Cache for 24 hours

/**
 * GET /api/laws/[id]/nodes
 *
 * Returns paginated document nodes for a specific law.
 *
 * Query parameters:
 * - limit: number of nodes to return (default: 30, max: 100)
 * - offset: number of nodes to skip (default: 0)
 * - bab_id: optional filter by parent BAB ID
 *
 * Response:
 * {
 *   total: number,
 *   limit: number,
 *   offset: number,
 *   nodes: DocumentNode[]
 * }
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const workId = parseInt(id);
  if (isNaN(workId)) {
    return NextResponse.json({ error: "Invalid work ID" }, { status: 400 });
  }

  const searchParams = request.nextUrl.searchParams;
  const limitParam = searchParams.get("limit");
  const offsetParam = searchParams.get("offset");
  const babIdParam = searchParams.get("bab_id");

  // Validate and clamp limit
  let limit = limitParam ? parseInt(limitParam) : 30;
  if (isNaN(limit) || limit < 1) {
    limit = 30;
  }
  if (limit > 100) {
    limit = 100;
  }

  // Validate offset
  let offset = offsetParam ? parseInt(offsetParam) : 0;
  if (isNaN(offset) || offset < 0) {
    offset = 0;
  }

  const supabase = await createClient();

  try {
    // Build query for pasal nodes
    let query = supabase
      .from("document_nodes")
      .select(
        "id, node_type, number, heading, parent_id, sort_order, content_text, pdf_page_start, pdf_page_end",
        { count: "exact" }
      )
      .eq("work_id", workId)
      .eq("node_type", "pasal")
      .order("sort_order");

    // Optional filter by parent BAB
    if (babIdParam) {
      const babId = parseInt(babIdParam);
      if (!isNaN(babId)) {
        query = query.eq("parent_id", babId);
      }
    }

    // Apply pagination
    query = query.range(offset, offset + limit - 1);

    const { data, count, error } = await query;

    if (error) {
      console.error("Error fetching nodes:", error);
      return NextResponse.json(
        { error: "Failed to fetch nodes" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      total: count || 0,
      limit,
      offset,
      nodes: data || [],
    });
  } catch (error) {
    console.error("Unexpected error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
