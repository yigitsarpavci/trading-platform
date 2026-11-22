import React from 'react';
import { LucideIcon } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string | number;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  icon?: LucideIcon;
  subtitle?: string;
}

/** Stat tile matching the bot terminal's StatCard. */
export function MetricCard({ title, value, trend, icon: Icon, subtitle }: MetricCardProps) {
  return (
    <div className="px-4 py-3.5 bg-white/[0.025] border border-white/[0.06] rounded-xl flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        {Icon && <Icon className="w-3.5 h-3.5 text-white/30" />}
        <span className="text-[9px] font-bold uppercase tracking-widest text-white/30">{title}</span>
      </div>
      <span className="text-2xl font-black font-mono tracking-tight">{value}</span>
      {(trend || subtitle) && (
        <div className="flex items-center gap-2">
          {trend && (
            <span className={`text-[11px] font-bold font-mono ${trend.isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
              {trend.isPositive ? '+' : ''}{trend.value}%
            </span>
          )}
          {subtitle && <span className="text-[10px] text-white/30">{subtitle}</span>}
        </div>
      )}
    </div>
  );
}
