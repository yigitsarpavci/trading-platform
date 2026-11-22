import React from 'react';
import { Card } from './Card';

interface ChartContainerProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  height?: number | string;
}

export function ChartContainer({ title, subtitle, children, height = 300 }: ChartContainerProps) {
  return (
    <Card>
      <div className="mb-5">
        <h3 className="text-[11px] font-black uppercase tracking-widest text-white/50">{title}</h3>
        {subtitle && <p className="text-[11px] text-white/30 mt-1">{subtitle}</p>}
      </div>
      <div style={{ height }}>
        {children}
      </div>
    </Card>
  );
}
