"use client";

import { useState } from "react";
import { Link2, Check } from "lucide-react";

export default function SectionLinkButton({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      onClick={handleCopy}
      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded text-muted-foreground hover:text-foreground"
      aria-label="Salin link bagian ini"
    >
      {copied ? (
        <Check aria-hidden="true" className="h-4 w-4 text-primary" />
      ) : (
        <Link2 aria-hidden="true" className="h-4 w-4" />
      )}
    </button>
  );
}
