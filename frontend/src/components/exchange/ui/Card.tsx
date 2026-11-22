import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  noPadding?: boolean;
}

/** Panel in the terminal style shared with the bot pages. */
export function Card({ children, className = '', noPadding = false }: CardProps) {
  return (
    <div className={`bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden transition-all duration-200 ${className}`}>
      <div className={`${noPadding ? '' : 'p-5'}`}>
        {children}
      </div>
    </div>
  );
}
