/**
 * Centralized URL utility for regulation pages.
 *
 * Replaces scattered inline slug constructions like `${type}-${number}-${year}`
 * which break when `number` contains `-` or `/`.
 */

interface WorkLike {
  slug?: string | null;
  number: string;
  year: number;
}

/** Return the URL-safe slug for a work.
 *  Prefers `work.slug` (from DB). Falls back to generated slug. */
export function workSlug(work: WorkLike, typeCode: string): string {
  if (work.slug) return work.slug;
  const sanitizedNumber = work.number.replace(/\//g, "-").toLowerCase();
  return `${typeCode.toLowerCase()}-${sanitizedNumber}-${work.year}`;
}

/** Return the full path for a regulation detail page. */
export function workPath(work: WorkLike, typeCode: string): string {
  return `/peraturan/${typeCode.toLowerCase()}/${workSlug(work, typeCode)}`;
}
