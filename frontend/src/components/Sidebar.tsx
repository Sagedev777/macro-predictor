// frontend/src/components/Sidebar.tsx
import React from 'react';
import {
  LayoutDashboard,
  Calendar,
  Crosshair,
  LineChart,
  History,
  Database,
  CheckCircle2,
  Terminal,
  ChevronRight,
  ShieldCheck,
  X,
} from 'lucide-react';
import type { PageId } from '../types';

interface SidebarProps {
  activePage: PageId;
  onSelectPage: (page: PageId) => void;
  isOpenMobile: boolean;
  onCloseMobile: () => void;
}

const NAV_ITEMS: Array<{ id: PageId; label: string; icon: React.ElementType; badge?: string }> = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'calendar', label: 'USD Calendar', icon: Calendar },
  { id: 'gold_model', label: 'Gold Model', icon: Crosshair, badge: '5m XAU' },
  { id: 'insights', label: 'Model Insights', icon: LineChart },
  { id: 'history', label: 'Forecast History', icon: History },
  { id: 'sources', label: 'Data & Sources', icon: Database },
  { id: 'evaluation', label: 'Model Evaluation', icon: CheckCircle2 },
  { id: 'system', label: 'System & Logs', icon: Terminal },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activePage,
  onSelectPage,
  isOpenMobile,
  onCloseMobile,
}) => {
  return (
    <>
      {/* Mobile backdrop */}
      {isOpenMobile && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={onCloseMobile}
        />
      )}

      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 flex flex-col w-64 bg-[#121316] border-r border-[#26282e] transition-transform duration-200 ease-in-out lg:translate-x-0 ${
          isOpenMobile ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#26282e]">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 font-bold text-sm tracking-wider">
              XAU
            </div>
            <div>
              <div className="text-sm font-semibold text-white tracking-wide flex items-center gap-1.5">
                MacroPredictor <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#26282e] text-zinc-300">v4</span>
              </div>
              <div className="text-[11px] text-zinc-400 font-medium">USD & Gold Reaction Engine</div>
            </div>
          </div>
          <button
            onClick={onCloseMobile}
            className="p-1 text-zinc-400 rounded hover:text-white hover:bg-zinc-800 lg:hidden"
            aria-label="Close sidebar"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* System scope indicator */}
        <div className="px-4 py-2.5 mx-3 mt-3 rounded-md bg-[#181a1f] border border-[#26282e] text-[11px] text-zinc-400 flex items-center gap-2">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
          <span>Restricted Scope: <strong>USD Macro → XAU/USD</strong></span>
        </div>

        {/* Navigation list */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activePage === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  onSelectPage(item.id);
                  onCloseMobile();
                }}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-amber-500/10 text-amber-300 border border-amber-500/30 font-semibold'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-[#1a1c22]'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon
                    className={`w-4 h-4 ${
                      isActive ? 'text-amber-400' : 'text-zinc-400'
                    }`}
                  />
                  <span>{item.label}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  {item.badge && (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                      {item.badge}
                    </span>
                  )}
                  {isActive && <ChevronRight className="w-3.5 h-3.5 text-amber-400" />}
                </div>
              </button>
            );
          })}
        </nav>

        {/* Footer meta */}
        <div className="p-4 border-t border-[#26282e] text-[11px] text-zinc-400 space-y-1">
          <div className="flex justify-between">
            <span>Model:</span>
            <span className="text-zinc-300 font-mono">River ARF v1</span>
          </div>
          <div className="flex justify-between">
            <span>Horizon:</span>
            <span className="text-zinc-300 font-mono">5-minute post-release</span>
          </div>
        </div>
      </aside>
    </>
  );
};
