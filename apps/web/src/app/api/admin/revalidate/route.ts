import { NextRequest, NextResponse } from "next/server";
import { revalidateTag, revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { isAdminEmail } from "@/lib/admin-auth";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user || !isAdminEmail(user.email)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { tags, paths } = await request.json();

  const revalidated: { tags: string[]; paths: string[] } = {
    tags: [],
    paths: [],
  };

  if (Array.isArray(tags)) {
    for (const tag of tags) {
      if (typeof tag === "string") {
        revalidateTag(tag, { expire: 0 });
        revalidated.tags.push(tag);
      }
    }
  }

  if (Array.isArray(paths)) {
    for (const path of paths) {
      if (typeof path === "string") {
        revalidatePath(path);
        revalidated.paths.push(path);
      }
    }
  }

  // Default: always revalidate landing stats and home page
  if (!tags && !paths) {
    revalidateTag("landing-stats", { expire: 0 });
    revalidatePath("/");
    revalidated.tags.push("landing-stats");
    revalidated.paths.push("/");
  }

  return NextResponse.json({ ok: true, revalidated });
}
