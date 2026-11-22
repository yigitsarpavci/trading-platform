"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/exchange/ui/PageHeader";
import { LoadingState, ErrorState } from "@/components/exchange/ui/States";
import { Card } from "@/components/exchange/ui/Card";
import { getTransactions } from "@/lib/exchange-api";
import { Search, Filter, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { isUnauthorized } from "@/lib/errors";
import type { Transaction } from "@/types/api";

export default function TransactionsPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  
  // Filtering
  const [filterType, setFilterType] = useState<"ALL" | "INCOME" | "EXPENSE">("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    const fetchData = async () => {
      try {
        const data = await getTransactions();
        setTransactions(data);
      } catch (err) {
        if (isUnauthorized(err)) {
          router.push("/login");
        } else {
          setError("Failed to fetch transactions");
        }
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [router]);

  if (loading) return <LoadingState title="Loading transactions..." />;
  if (error) return <ErrorState title="Error" description={error} />;

  // Sort by date descending
  const sortedTx = [...transactions].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  
  const filteredTx = sortedTx.filter(tx => {
    if (filterType !== "ALL" && tx.type !== filterType) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (tx.description?.toLowerCase().includes(q) || tx.category.toLowerCase().includes(q));
    }
    return true;
  });

  return (
    <div className="animate-in fade-in duration-500 pb-12">
      <PageHeader 
        title="Transactions History" 
        description="View and filter all your historical income and expenses."
      />

      <Card className="flex flex-col min-h-[600px]">
        {/* Toolbar */}
        <div className="p-4 border-b border-border flex flex-col sm:flex-row gap-4 justify-between items-center bg-card/40">
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/70" />
            <input 
              type="text" 
              placeholder="Search description or category..." 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-background border border-border rounded-lg text-sm text-foreground/90 focus:ring-1 focus:ring-ring outline-none"
            />
          </div>
          <div className="flex bg-background p-1 rounded-lg border border-border w-full sm:w-auto">
            <button onClick={() => setFilterType("ALL")} className={`flex-1 sm:px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${filterType === "ALL" ? "bg-muted text-foreground" : "text-muted-foreground/70 hover:text-foreground"}`}>All</button>
            <button onClick={() => setFilterType("INCOME")} className={`flex-1 sm:px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${filterType === "INCOME" ? "bg-emerald-500/20 text-emerald-400" : "text-muted-foreground/70 hover:text-foreground"}`}>Income</button>
            <button onClick={() => setFilterType("EXPENSE")} className={`flex-1 sm:px-4 py-1.5 rounded-md text-xs font-medium transition-colors ${filterType === "EXPENSE" ? "bg-rose-500/20 text-rose-400" : "text-muted-foreground/70 hover:text-foreground"}`}>Expense</button>
          </div>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-x-auto">
          {filteredTx.length === 0 ? (
            <div className="h-[400px] flex items-center justify-center text-muted-foreground/70 flex-col gap-2">
              <Filter className="w-8 h-8 text-muted-foreground/40" />
              <p>No transactions found for these filters.</p>
            </div>
          ) : (
            <table className="w-full text-sm text-left">
              <thead className="bg-card/40 text-muted-foreground border-b border-border sticky top-0">
                <tr>
                  <th className="font-medium p-4 whitespace-nowrap">Date</th>
                  <th className="font-medium p-4">Description</th>
                  <th className="font-medium p-4">Category</th>
                  <th className="font-medium p-4 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {filteredTx.map(tx => (
                  <tr key={tx.id} className="hover:bg-muted/30 transition-colors">
                    <td className="p-4 text-muted-foreground whitespace-nowrap">
                      {new Date(tx.date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}
                    </td>
                    <td className="p-4">
                      <div className="font-medium text-foreground/90">{tx.description || "—"}</div>
                    </td>
                    <td className="p-4">
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-muted text-foreground/80 border border-border">
                        {tx.category}
                      </span>
                    </td>
                    <td className={`p-4 text-right font-semibold whitespace-nowrap flex items-center justify-end gap-2 ${tx.type === 'INCOME' ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {tx.type === 'INCOME' ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                      ${tx.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>
    </div>
  );
}
