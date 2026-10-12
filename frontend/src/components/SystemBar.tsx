// frontend/src/components/SystemBar.tsx
import React, { useEffect, useState } from 'react';
import { Menu, RefreshCw, Clock, Activity, CheckCircle } from 'lucide-react';
import type { SystemStatusData } from '../types';

interface SystemBarProps {
  title: string;
  subtitle?: string;
  onOpenMobileSidebar: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  useUtc: boolean;
  onToggleTimezone: () => void;
  systemStatus: SystemStatusData | null;
}

export const SystemBar: React.FC<SystemBarProps> = ({
  title,
  subtitle,
  onOpenMobileSidebar,
  onRefresh,
  isRefreshing,
  useUtc,
  onToggleTimezone,
  systemStatus,
}) => {
  const [currentTime, setCurrentTime] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      if (useUtc) {
        const h = String(now.getUTCHours()).padStart(2, '0');
        const m = String(now.getUTCMinutes()).padStart(2, '0');
        const s = String(now.getUTCSeconds()).padStart(2, '0');
        setCurrentTime(`${h}:${m}:${s} UTC`);
      } else {
        const h = String(now.getHours()).padStart(2, '0');
        const m = String(now.getMinutes()).padStart(2, '0');
        const s = String(now.getSeconds()).padStart(2, '0');
        setCurrentTime(`${h}:${m}:${s} Local`);
      }
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, [useUtc]);

  const isSchedulerRunning = systemStatus?.scheduler?.is_running ?? true;

  return (
    <header className="sticky top-0 z-30 flex items-center justify-between px-4 lg:px-8 py-3 bg-[#121316]/90 backdrop-blur-md border-b border-[#26282e]">
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenMobileSidebar}
          className="p-2 text-zinc-400 rounded-lg hover:text-white hover:bg-zinc-800 lg:hidden"
          aria-label="Open sidebar"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div>
          <h1 className="text-base lg:text-lg font-bold text-white tracking-tight flex items-center gap-2">
            {title}
          </h1>
          {subtitle && (
            <p className="text-xs text-zinc-400 hidden sm:block">{subtitle}</p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2.5 sm:gap-4">
        {/* System Health Pills */}
        <div className="hidden md:flex items-center gap-2 text-xs">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-medium">
            <CheckCircle className="w-3 h-3 text-emerald-400" />
            <span>API Online</span>
          </div>
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium ${
              isSchedulerRunning
                ? 'bg-blue-500/10 border border-blue-500/30 text-blue-400'
                : 'bg-amber-500/10 border border-amber-500/30 text-amber-400'
            }`}
          >
            <Activity className="w-3 h-3" />
            <span>Scheduler: {isSchedulerRunning ? 'Active (1m)' : 'Paused'}</span>
          </div>
        </div>

        {/* Timezone Switcher */}
        <button
          onClick={onToggleTimezone}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-[#1a1c22] border border-[#2d3039] text-zinc-300 hover:text-white hover:border-zinc-500 transition-colors"
          title="Toggle between UTC and your local timezone"
        >
          <Clock className="w-3.5 h-3.5 text-zinc-400" />
          <span className="font-mono text-[11px] font-semibold">{currentTime}</span>
          <span className="text-[10px] px-1 py-0.2 rounded bg-zinc-800 text-zinc-400 uppercase">
            {useUtc ? 'UTC' : 'Local'}
          </span>
        </button>

        {/* Manual Refresh Button */}
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-md bg-amber-500/15 border border-amber-500/30 text-amber-300 hover:bg-amber-500/25 hover:text-amber-200 transition-colors disabled:opacity-50"
          title="Refresh real-time data from backend"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          <span className="hidden sm:inline">Refresh</span>
        </button>
      </div>
    </header>
  );
};
