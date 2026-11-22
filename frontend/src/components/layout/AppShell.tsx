"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";
import { ScrollArea } from "@/components/ui/scroll-area";

const BARE_PAGES = new Set(["/", "/login", "/register"]);

/** Terminal shell (sidebar + top bar) for every page except sign-in and sign-up. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (BARE_PAGES.has(pathname)) {
    return <main className="min-h-screen flex flex-col">{children}</main>;
  }
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <ScrollArea className="flex-1">
          <main className="p-8 pb-16">{children}</main>
        </ScrollArea>
      </div>
    </div>
  );
}
