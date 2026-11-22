"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Activity,
  ArrowLeftRight,
  Bot,
  LayoutDashboard,
  List,
  LogOut,
  PieChart,
  Receipt,
  Settings,
  ShieldAlert,
  Sparkles,
  Terminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type NavItem = { name: string; href: string; icon: LucideIcon };

const sections: { title: string; items: NavItem[] }[] = [
  {
    title: "Exchange",
    items: [
      { name: "Overview", href: "/dashboard", icon: LayoutDashboard },
      { name: "Order Book", href: "/trading", icon: ArrowLeftRight },
      { name: "Portfolio Risk", href: "/portfolio", icon: ShieldAlert },
    ],
  },
  {
    title: "Finance",
    items: [
      { name: "Transactions", href: "/transactions", icon: Receipt },
      { name: "Personal Finance", href: "/finance", icon: PieChart },
      { name: "AI Assistant", href: "/ai-assistant", icon: Sparkles },
    ],
  },
  {
    title: "Bot",
    items: [
      { name: "Terminal", href: "/bot", icon: Activity },
      { name: "Watchlist", href: "/bot/watchlist", icon: List },
      { name: "Risk Control", href: "/bot/settings", icon: Bot },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const logout = () => {
    try {
      localStorage.removeItem("auth_token");
    } catch {}
    router.push("/login");
  };

  const link = (item: NavItem) => {
    const isActive = pathname === item.href;
    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          "flex items-center gap-3 px-4 py-2 rounded-md text-[13px] font-bold transition-all group",
          isActive ? "bg-primary/10 text-primary" : "text-muted-foreground/70 hover:bg-muted/50 hover:text-foreground"
        )}
      >
        <item.icon className={cn("w-4 h-4", isActive ? "text-primary" : "text-muted-foreground/50 group-hover:text-foreground/70")} />
        {item.name}
      </Link>
    );
  };

  return (
    <aside className="w-64 shrink-0 border-r border-border bg-card/20 flex flex-col h-screen sticky top-0">
      <div className="p-8 flex items-center gap-3">
        <div className="w-9 h-9 bg-primary flex items-center justify-center rounded">
          <Terminal className="w-5 h-5 text-primary-foreground" />
        </div>
        <div className="flex flex-col">
          <span className="font-bold tracking-tight text-base leading-none uppercase">AlphaTrigger</span>
          <span className="text-[10px] font-medium text-muted-foreground tracking-widest uppercase opacity-60">Trading Platform</span>
        </div>
      </div>

      <nav className="flex-1 px-4 space-y-5 overflow-y-auto custom-scrollbar">
        {sections.map((section) => (
          <div key={section.title} className="space-y-0.5">
            <p className="px-4 pb-1 text-[9px] font-bold uppercase tracking-widest text-white/25">{section.title}</p>
            {section.items.map(link)}
          </div>
        ))}
      </nav>

      <div className="p-4 space-y-1 border-t border-white/5">
        {link({ name: "Settings", href: "/settings", icon: Settings })}
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-4 py-2 rounded-md text-[13px] font-bold text-muted-foreground/70 hover:bg-muted/50 hover:text-foreground transition-all"
        >
          <LogOut className="w-4 h-4 text-muted-foreground/50" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
