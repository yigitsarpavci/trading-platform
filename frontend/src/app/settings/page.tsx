"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/exchange/ui/PageHeader";
import { Card } from "@/components/exchange/ui/Card";
import { User, Mail, Shield, Bell, Key, LogOut } from "lucide-react";
import { getCurrentUser } from "@/lib/exchange-api";
import type { User as AppUser } from "@/types/api";

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<AppUser | null>(null);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const data = await getCurrentUser();
        setUser(data);
      } catch {
        router.push("/login");
      }
    };
    fetchUser();
  }, [router]);

  const handleLogout = () => {
    localStorage.removeItem("auth_token");
    router.push("/login");
  };

  return (
    <div className="animate-in fade-in duration-500 max-w-4xl pb-12">
      <PageHeader 
        title="Settings" 
        description="Manage your account preferences and personal information."
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mt-8">
        
        {/* Sidebar inside settings */}
        <div className="space-y-2">
          <button className="w-full flex items-center gap-3 px-4 py-3 bg-emerald-500/10 text-emerald-400 font-medium rounded-lg transition-colors border border-emerald-500/20">
            <User className="w-5 h-5" /> Account Profile
          </button>
          <button className="w-full flex items-center gap-3 px-4 py-3 text-muted-foreground hover:text-foreground hover:bg-muted/50 font-medium rounded-lg transition-colors">
            <Shield className="w-5 h-5" /> Security
          </button>
          <button className="w-full flex items-center gap-3 px-4 py-3 text-muted-foreground hover:text-foreground hover:bg-muted/50 font-medium rounded-lg transition-colors">
            <Bell className="w-5 h-5" /> Notifications
          </button>
        </div>

        {/* Content */}
        <div className="md:col-span-2 space-y-6">
          <Card className="p-6">
            <h3 className="text-lg font-semibold text-foreground mb-6">Profile Information</h3>
            
            <div className="space-y-6">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center text-xl font-bold text-foreground/80 border border-border">
                  {user?.email?.[0].toUpperCase() || "U"}
                </div>
                <div>
                  <button className="px-4 py-2 bg-muted hover:bg-muted text-foreground/90 text-sm font-medium rounded-lg transition-colors">
                    Change Avatar
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4">
                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-1">Email Address</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/70" />
                    <input 
                      type="text" 
                      disabled 
                      value={user?.email || "Loading..."}
                      className="w-full pl-10 pr-4 py-2 bg-card/40 border border-border rounded-lg text-foreground/80 opacity-70 cursor-not-allowed"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground/70 mt-1">Your email address cannot be changed.</p>
                </div>
              </div>

              <div className="pt-4 border-t border-border">
                <button className="px-6 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground font-medium rounded-lg transition-colors">
                  Save Changes
                </button>
              </div>
            </div>
          </Card>

          <Card className="p-6 border-rose-500/20">
            <h3 className="text-lg font-semibold text-rose-400 mb-2">Danger Zone</h3>
            <p className="text-sm text-muted-foreground mb-6">These actions are permanent and cannot be undone.</p>
            
            <div className="flex flex-col sm:flex-row gap-4">
              <button 
                onClick={handleLogout}
                className="flex items-center justify-center gap-2 px-4 py-2 bg-card hover:bg-muted border border-border text-foreground/80 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" /> Sign Out
              </button>
              <button className="flex items-center justify-center gap-2 px-4 py-2 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-400 rounded-lg transition-colors">
                <Key className="w-4 h-4" /> Delete Account
              </button>
            </div>
          </Card>
        </div>

      </div>
    </div>
  );
}
