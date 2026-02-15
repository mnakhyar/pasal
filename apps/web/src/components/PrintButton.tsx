"use client";

import { Printer } from "lucide-react";

export default function PrintButton() {
  return (
    <button
      onClick={() => window.print()}
      className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors w-full"
    >
      <Printer size={16} aria-hidden="true" />
      Cetak halaman ini
    </button>
  );
}
