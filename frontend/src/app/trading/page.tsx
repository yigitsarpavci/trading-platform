"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/exchange/ui/PageHeader";
import { LoadingState, ErrorState } from "@/components/exchange/ui/States";
import { Card } from "@/components/exchange/ui/Card";
import { ArrowRightLeft, ActivitySquare, TrendingUp, BookOpen } from "lucide-react";
import { getUserOrders, getOrderBook, getUserTrades, createOrder, getMarketPrices } from "@/lib/exchange-api";
import type { MarketPrice } from "@/lib/exchange-api";
import { getErrorMessage, isUnauthorized } from "@/lib/errors";
import type { Order, OrderBook, Trade } from "@/types/api";

export default function TradingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [orderBook, setOrderBook] = useState<OrderBook>({ bids: [], asks: [] });
  const [orders, setOrders] = useState<Order[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);

  // Form state
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [submitting, setSubmitting] = useState(false);
  
  // Markets are the assets with a reference price; the bot publishes BTC, ETH, SOL, LINK and LTC.
  const [markets, setMarkets] = useState<MarketPrice[]>([]);
  const [ticker, setTicker] = useState("BTC");
  const market = markets.find((m) => m.ticker_symbol === ticker) ?? markets[0];
  const ASSET_ID = market?.asset_id;
  const symbol = market?.ticker_symbol ?? ticker;

  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let active = true;
    Promise.all([
      getMarketPrices(),
      ASSET_ID ? getOrderBook(ASSET_ID) : Promise.resolve({ bids: [], asks: [] } as OrderBook),
      getUserOrders(),
      getUserTrades(),
    ])
      .then(([marketData, bookData, ordersData, tradesData]) => {
        if (!active) return;
        setMarkets(marketData);
        setOrderBook(bookData);
        setOrders(ordersData);
        setTrades(tradesData);
      })
      .catch((err) => {
        if (!active) return;
        if (isUnauthorized(err)) router.push("/login");
        else setError("Failed to fetch trading data");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [router, refreshKey, ASSET_ID]);

  // In a real app we'd use WebSockets. For this MVP simulator, poll every 5s in addition to after-trade refreshes.
  useEffect(() => {
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!price || !quantity || !ASSET_ID) return;
    setSubmitting(true);
    try {
      await createOrder({
        asset_id: ASSET_ID,
        side,
        price: parseFloat(price),
        quantity: parseFloat(quantity)
      });
      // Refresh immediately
      refresh();
      setPrice("");
      setQuantity("");
    } catch (err) {
      alert(getErrorMessage(err, "Failed to place order"));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && orders.length === 0) return <LoadingState title="Loading trading engine..." />;
  if (error) return <ErrorState title="Simulator Error" description={error} />;

  const openOrders = orders.filter(o => o.status === "OPEN");

  return (
    <div className="animate-in fade-in duration-500 pb-12">
      <PageHeader 
        title="Order Book" 
        description="Price-time priority limit-order book. The trading bot and the market maker trade here too."
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        
        {/* Left Column: Place Order & Explanation */}
        <div className="space-y-6">
          <Card>
            <div className="p-5 border-b border-border flex items-center justify-between">
              <h3 className="text-[11px] font-black uppercase tracking-widest text-white/50 flex items-center gap-2">
                <ArrowRightLeft className="w-4 h-4 text-emerald-400" />
                Place Limit Order
              </h3>
              <select
                value={symbol}
                onChange={(e) => setTicker(e.target.value)}
                className="text-[11px] font-bold uppercase tracking-widest bg-muted border border-border rounded px-2 py-1 outline-none"
              >
                {markets.map((m) => (
                  <option key={m.asset_id} value={m.ticker_symbol}>{m.ticker_symbol}/USD</option>
                ))}
              </select>
            </div>
            <form onSubmit={handleSubmit} className="p-5 space-y-4">
              <div className="flex bg-background p-1 rounded-lg border border-border">
                <button
                  type="button"
                  onClick={() => setSide("BUY")}
                  className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${side === "BUY" ? "bg-emerald-500/20 text-emerald-400" : "text-muted-foreground/70 hover:text-foreground"}`}
                >
                  Buy
                </button>
                <button
                  type="button"
                  onClick={() => setSide("SELL")}
                  className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${side === "SELL" ? "bg-rose-500/20 text-rose-400" : "text-muted-foreground/70 hover:text-foreground"}`}
                >
                  Sell
                </button>
              </div>

              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Price (USD)</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={price}
                  onChange={e => setPrice(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg text-foreground focus:border-ring focus:ring-1 focus:ring-ring"
                  placeholder={market?.reference_price ? market.reference_price.toFixed(2) : "e.g. 60000"}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Quantity ({symbol})</label>
                <input
                  type="number"
                  step="0.00000001"
                  required
                  value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  className="w-full px-3 py-2 bg-background border border-border rounded-lg text-foreground focus:border-ring focus:ring-1 focus:ring-ring"
                  placeholder="e.g. 0.5"
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                className={`w-full py-2.5 font-medium rounded-lg transition-colors disabled:opacity-50 mt-2 ${side === "BUY" ? "bg-emerald-500 hover:bg-emerald-600 text-foreground" : "bg-rose-500 hover:bg-rose-600 text-foreground"}`}
              >
                {submitting ? "Placing..." : `Place ${side} Order`}
              </button>
            </form>
          </Card>

          <div className="p-5 bg-sky-500/10 border border-sky-500/20 rounded-xl">
            <h4 className="text-sm font-semibold text-sky-400 flex items-center gap-2 mb-2">
              <BookOpen className="w-4 h-4" />
              How the matching engine works
            </h4>
            <p className="text-xs text-sky-200/70 leading-relaxed mb-2">
              This simulator uses a <strong>Price-Time Priority</strong> matching algorithm similar to real exchanges.
            </p>
            <ul className="text-xs text-sky-200/70 space-y-1 list-disc list-inside">
              <li><strong>Buy orders</strong> match with the lowest available sell order price.</li>
              <li><strong>Sell orders</strong> match with the highest available buy order price.</li>
              <li>Partial fills happen if opposite quantity is smaller.</li>
            </ul>
          </div>
        </div>

        {/* Middle Column: Order Book */}
        <Card className="flex flex-col h-[500px]">
          <div className="p-4 border-b border-border flex justify-between items-center bg-card/40">
            <h3 className="text-[11px] font-black uppercase tracking-widest text-white/50 flex items-center gap-2">
              <ActivitySquare className="w-4 h-4 text-muted-foreground" />
              Order Book ({symbol}/USD)
            </h3>
            {market?.reference_price != null && (
              <span className="text-[11px] font-mono font-bold text-muted-foreground">
                ref {market.reference_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </span>
            )}
          </div>
          
          <div className="flex-1 flex flex-col overflow-hidden font-mono text-sm">
            {/* Table Header */}
            <div className="grid grid-cols-2 px-4 py-2 border-b border-border text-xs text-muted-foreground/70">
              <div>Price (USD)</div>
              <div className="text-right">Quantity</div>
            </div>

            {/* Asks (Sells) - Show bottom 8 */}
            <div className="flex-1 overflow-hidden flex flex-col-reverse justify-start">
              {orderBook.asks.slice(0, 8).reverse().map((ask, i) => (
                <div key={`ask-${i}`} className="grid grid-cols-2 px-4 py-1.5 hover:bg-rose-500/10 cursor-pointer transition-colors group">
                  <div className="text-rose-400">{ask.price.toFixed(2)}</div>
                  <div className="text-right text-foreground/80">{ask.quantity.toFixed(4)}</div>
                </div>
              ))}
            </div>

            {/* Spread Indicator */}
            <div className="py-2 px-4 bg-background/50 border-y border-border flex items-center justify-between text-xs font-semibold text-muted-foreground">
              <div className="flex items-center gap-1">Spread <TrendingUp className="w-3 h-3" /></div>
              <div>---</div>
            </div>

            {/* Bids (Buys) - Show top 8 */}
            <div className="flex-1 overflow-hidden flex flex-col justify-start">
              {orderBook.bids.slice(0, 8).map((bid, i) => (
                <div key={`bid-${i}`} className="grid grid-cols-2 px-4 py-1.5 hover:bg-emerald-500/10 cursor-pointer transition-colors group">
                  <div className="text-emerald-400">{bid.price.toFixed(2)}</div>
                  <div className="text-right text-foreground/80">{bid.quantity.toFixed(4)}</div>
                </div>
              ))}
            </div>
          </div>
        </Card>

        {/* Right Column: User Open Orders & Trades */}
        <div className="space-y-6 h-[500px] flex flex-col">
          <Card className="flex-1 flex flex-col min-h-0">
            <div className="p-4 border-b border-border">
              <h3 className="text-[11px] font-black uppercase tracking-widest text-white/50">Your Open Orders</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              {openOrders.length === 0 ? (
                <div className="h-full flex items-center justify-center text-xs text-muted-foreground/70">No open orders</div>
              ) : (
                <div className="space-y-2">
                  {openOrders.map(o => (
                    <div key={o.id} className="bg-background p-3 rounded-lg border border-border text-xs">
                      <div className="flex justify-between mb-1">
                        <span className={`font-bold ${o.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>{o.side}</span>
                        <span className="text-muted-foreground">{new Date(o.created_at).toLocaleTimeString()}</span>
                      </div>
                      <div className="flex justify-between font-mono">
                        <span className="text-foreground/80">${o.price.toFixed(2)}</span>
                        <span className="text-foreground/80">{o.quantity - o.filled_quantity} left</span>
                      </div>
                      <div className="mt-2 w-full h-1 bg-muted rounded-full overflow-hidden">
                        <div 
                          className={`h-full ${o.side === 'BUY' ? 'bg-emerald-500' : 'bg-rose-500'}`} 
                          style={{width: `${(o.filled_quantity / o.quantity) * 100}%`}}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          <Card className="flex-1 flex flex-col min-h-0">
            <div className="p-4 border-b border-border">
              <h3 className="text-[11px] font-black uppercase tracking-widest text-white/50">Trade History</h3>
            </div>
            <div className="flex-1 overflow-y-auto">
              {trades.length === 0 ? (
                <div className="h-full flex items-center justify-center text-xs text-muted-foreground/70">No trades yet</div>
              ) : (
                <table className="w-full text-xs text-left">
                  <thead className="bg-card sticky top-0">
                    <tr className="text-muted-foreground/70">
                      <th className="font-medium p-3">Time</th>
                      <th className="font-medium p-3 text-right">Price</th>
                      <th className="font-medium p-3 text-right">Qty</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {trades.map(t => (
                      <tr key={t.id} className="border-t border-border hover:bg-muted/30">
                        <td className="p-3 text-muted-foreground">{new Date(t.executed_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'})}</td>
                        <td className="p-3 text-right text-foreground/90">${t.price.toFixed(2)}</td>
                        <td className="p-3 text-right text-muted-foreground">{t.quantity.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        </div>

      </div>
    </div>
  );
}
