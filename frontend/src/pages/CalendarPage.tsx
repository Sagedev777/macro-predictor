// frontend/src/pages/CalendarPage.tsx
import React, { useState } from 'react';
import {
  Calendar,
  Filter,
  RefreshCw,
} from 'lucide-react';
import type { CalEvent } from '../types';
import { formatTimestamp, getDirectionBadge } from '../utils/formatters';

interface CalendarPageProps {
  events: CalEvent[];
  onRefresh: () => void;
  isRefreshing: boolean;
  onOpenEventDetail: (releaseId: string) => void;
  useUtc: boolean;
}

export const CalendarPage: React.FC<CalendarPageProps> = ({
  events,
  onRefresh,
  isRefreshing,
  onOpenEventDetail,
  useUtc,
}) => {
  const [impactFilter, setImpactFilter] = useState<'ALL' | 'HIGH' | 'MEDIUM'>('ALL');
  const [search, setSearch] = useState<string>('');

  const filteredEvents = events.filter((ev) => {
    if (impactFilter !== 'ALL' && ev.impact !== impactFilter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const matchName = (ev.display_name || ev.event_name).toLowerCase().includes(q);
      const matchCode = (ev.event_code || '').toLowerCase().includes(q);
      if (!matchName && !matchCode) return false;
    }
    return true;
  });

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Decoupling Notice Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400">
            <Calendar className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">
              U.S. Macroeconomic Release Calendar & Consensus
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              USD economic surprise predictions are evaluated independently from XAU/USD gold reactions. A USD beat does not guarantee a lower gold price.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#20222a] text-zinc-300 hover:text-white hover:bg-[#282a34] border border-[#2e313d] transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Sync Releases</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Filter className="w-4 h-4 text-zinc-400 shrink-0" />
          <span className="text-xs font-semibold text-zinc-300">Filter Impact:</span>
          {(['ALL', 'HIGH', 'MEDIUM'] as const).map((imp) => (
            <button
              key={imp}
              onClick={() => setImpactFilter(imp)}
              className={`px-2.5 py-1 rounded text-xs font-semibold transition-all ${
                impactFilter === imp
                  ? 'bg-amber-500 text-zinc-950 font-bold'
                  : 'bg-[#1e2027] text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {imp}
            </button>
          ))}
        </div>

        <div className="w-full sm:w-64">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search release name or code..."
            className="w-full px-3 py-1.5 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/60"
          />
        </div>
      </div>

      {/* Events Table */}
      <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
        <div className="flex justify-between items-center mb-4">
          <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider">
            Scheduled USD Releases ({filteredEvents.length})
          </span>
          <span className="text-[11px] text-zinc-400">
            Source: Forex Factory Live RSS / Web Cache
          </span>
        </div>

        {filteredEvents.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                <tr>
                  <th className="py-2.5 px-3">Release Time</th>
                  <th className="py-2.5 px-3">Event Name</th>
                  <th className="py-2.5 px-3">Impact</th>
                  <th className="py-2.5 px-3">Consensus (Fcst)</th>
                  <th className="py-2.5 px-3">Previous</th>
                  <th className="py-2.5 px-3">Actual</th>
                  <th className="py-2.5 px-3">USD Learner Lean</th>
                  <th className="py-2.5 px-3">Linked Gold Prediction</th>
                  <th className="py-2.5 px-3 text-right">Moment Record</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#23252c]">
                {filteredEvents.map((ev, idx) => {
                  const surprise =
                    ev.actual !== null && ev.forecast !== null ? ev.actual - ev.forecast : null;
                  const goldBadge = getDirectionBadge(
                    ev.gold_forecast?.forecast_direction || ev.gold_forecast?.direction
                  );

                  return (
                    <tr key={idx} className="hover:bg-[#1a1c22] transition-colors">
                      <td className="py-3 px-3 font-mono text-[11px] text-zinc-300">
                        {formatTimestamp(ev.release_time_utc, useUtc)}
                      </td>
                      <td className="py-3 px-3">
                        <div className="font-semibold text-white">
                          {ev.display_name || ev.event_name}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-[10px] font-mono text-zinc-400">
                            {ev.event_code || 'USD'}
                          </span>
                          {ev.is_simultaneous && (
                            <span className="text-[9px] px-1 py-0.2 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
                              Simultaneous Release
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            ev.impact === 'HIGH'
                              ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                              : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                          }`}
                        >
                          {ev.impact}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-mono text-zinc-300">
                        {ev.forecast !== null ? ev.forecast : '—'}
                      </td>
                      <td className="py-3 px-3 font-mono text-zinc-400">
                        {ev.previous !== null ? ev.previous : '—'}
                      </td>
                      <td className="py-3 px-3 font-mono font-bold">
                        {ev.actual !== null ? (
                          <div className="flex items-center gap-1.5">
                            <span className="text-amber-300">{ev.actual}</span>
                            {surprise !== null && (
                              <span
                                className={`text-[10px] ${
                                  surprise > 0
                                    ? 'text-emerald-400'
                                    : surprise < 0
                                    ? 'text-rose-400'
                                    : 'text-zinc-400'
                                }`}
                              >
                                ({surprise > 0 ? `+${surprise.toFixed(2)}` : surprise.toFixed(2)})
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-zinc-500">Pending</span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        {ev.prediction ? (
                          <div className="text-xs">
                            <span
                              className={`font-bold ${
                                ev.prediction.lean_direction === 'BEAT'
                                  ? 'text-emerald-400'
                                  : ev.prediction.lean_direction === 'MISS'
                                  ? 'text-rose-400'
                                  : 'text-zinc-300'
                              }`}
                            >
                              {ev.prediction.lean_direction}
                            </span>{' '}
                            <span className="text-[11px] text-zinc-400">
                              ({ev.prediction.confidence_pct.toFixed(0)}%)
                            </span>
                          </div>
                        ) : (
                          <span className="text-zinc-500 text-[11px]">Standby</span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        {ev.gold_forecast ? (
                          <div className="flex items-center gap-1.5">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${goldBadge.className}`}>
                              {goldBadge.label}
                            </span>
                            <span className="text-[10px] text-zinc-400 font-mono">5m</span>
                          </div>
                        ) : (
                          <span className="text-zinc-500 text-[11px]">Pre-release</span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-right">
                        {ev.gold_forecast ? (
                          <button
                            onClick={() =>
                              onOpenEventDetail(
                                ev.gold_forecast?.release_moment_id || ev.release_time_utc
                              )
                            }
                            className="text-[11px] text-amber-400 hover:text-amber-300 font-semibold"
                          >
                            Snapshot
                          </button>
                        ) : (
                          <span className="text-zinc-600 text-[11px]">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center text-xs text-zinc-400">
            No economic events match the current filter.
          </div>
        )}
      </div>
    </div>
  );
};
