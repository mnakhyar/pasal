"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

export default function RevalidateButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<"idle" | "success" | "error">("idle");

  async function handleClick() {
    setLoading(true);
    setResult("idle");
    try {
      const res = await fetch("/api/admin/revalidate", { method: "POST" });
      setResult(res.ok ? "success" : "error");
    } catch {
      setResult("error");
    } finally {
      setLoading(false);
      setTimeout(() => setResult("idle"), 3000);
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
    >
      <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
      {loading
        ? "Memperbarui..."
        : result === "success"
          ? "Berhasil!"
          : result === "error"
            ? "Gagal"
            : "Refresh Cache"}
    </button>
  );
}
