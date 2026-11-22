"use client";

import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/exchange-api";

export function Topbar() {
  const [time, setTime] = useState(new Date());
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    fetchAPI<{ email?: string }>("/auth/me")
      .then((me) => setEmail(me?.email ?? null))
      .catch(() => setEmail(null));
  }, []);

  return (
    <header className="h-12 border-b border-border bg-background/30 backdrop-blur-md flex items-center justify-between px-8 sticky top-0 z-10">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_#10b981]" />
          <span className="text-[10px] font-bold text-emerald-500 uppercase tracking-widest">Live</span>
        </div>
        <div className="px-3 py-1 bg-muted/20 border border-border rounded-full">
          <span suppressHydrationWarning className="text-[10px] font-mono font-bold text-muted-foreground tracking-widest">
            {time.toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        </div>
      </div>

      {email && (
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-muted flex items-center justify-center text-[10px] font-bold text-muted-foreground uppercase">
            {email[0]}
          </div>
          <span className="text-[12px] font-bold">{email}</span>
        </div>
      )}
    </header>
  );
}
