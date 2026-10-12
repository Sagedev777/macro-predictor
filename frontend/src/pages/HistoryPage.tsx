// frontend/src/pages/HistoryPage.tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  History,
  Search,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react';
import type { GoldForecastItem } from '../types';
import { formatTimestamp, formatPct, getDirectionBadge } from '../utils/formatters';

interface HistoryPageProps {
  onOpenEventDetail: (releaseId: string) => void;
  useUtc: boolean;
}

export const HistoryPage: React.FC<HistoryPageProps> = ({
  onOpenEventDetail,
  useUtc,
}) => {
  const [forecasts, setForecasts] = useState<GoldForecastItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [offset, setOffset] = useState<number>(0);
  const limit = 25;

  const [familyFilter, setFamilyFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [directionFilter, setDirectionFilter] = useState<string>('');
  const [search, setSearch] = useState<string>('');

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchForecasts = () => {
    setLoading(true);
    setError(null);
    const params: Record<string, any> = {
      limit,
      offset,
    };
    if (familyFilter) params.event_family = familyFilter;
    if (statusFilter) params.status = statusFilter;
    if (directionFilter) params.direction = directionFilter;
    if (search.trim()) params.search = search.trim();

    axios
      .get('/api/gold/forecasts', { params })
      .then((res) => {
        setForecasts(res.data.forecasts || []);
        setTotal(res.data.total || res.data.count || 0);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to fetch forecasts:', err);
        setError('Failed to fetch historical forecast records from backend.');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchForecasts();
  }, [offset, familyFilter, statusFilter, directionFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
    fetchForecasts();
  };

  const totalPages = Math.ceil(total / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-400">
            <History className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">
              Historical Gold Predictions & Evaluated Outcomes
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Every row corresponds to an immutable point-in-time snapshot and verified post-release price outcome.
            </p>
          </div>
        </div>

        <div className="text-xs font-mono text-zinc-400">
          Showing <strong>{forecasts.length}</strong> of <strong>{total}</strong> records
        </div>
      </div>

      {/* Filter and Search Controls */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-3">
          {/* Search Bar */}
          <form onSubmit={handleSearchSubmit} className="flex-1 flex gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-zinc-500 absolute left-3 top-2.5" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search moment ID, event code, or release name..."
                className="w-full pl-9 pr-3 py-1.5 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-purple-500/60"
              />
            </div>
            <button
              type="submit"
              className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-[#22252e] text-zinc-200 hover:bg-[#2b2e38] transition-colors"
            >
              Search
            </button>
          </form>

          {/* Dropdown Filters */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {/* Family Filter */}
            <select
              value={familyFilter}
              onChange={(e) => {
                setFamilyFilter(e.target.value);
                setOffset(0);
              }}
              className="px-2.5 py-1.5 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-zinc-300 focus:outline-none"
            >
              <option value="">All Families</option>
              <option value="employment">Employment / NFP</option>
              <option value="cpi">CPI Inflation</option>
              <option value="ppi">PPI</option>
              <option value="retail_sales">Retail Sales</option>
              <option value="gdp">GDP</option>
              <option value="ism">ISM PMI</option>
              <option value="fed">Federal Reserve</option>
            </select>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setOffset(0);
              }}
              className="px-2.5 py-1.5 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-zinc-300 focus:outline-none"
            >
              <option value="">All Statuses</option>
              <option value="graded">Graded (Outcome OK)</option>
              <option value="pending">Pending Window</option>
              <option value="unavailable">Unavailable / Incomplete</option>
            </select>

            {/* Direction Filter */}
            <select
              value={directionFilter}
              onChange={(e) => {
                setDirectionFilter(e.target.value);
                setOffset(0);
              }}
              className="px-2.5 py-1.5 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-zinc-300 focus:outline-none"
            >
              <option value="">All Directions</option>
              <option value="BULLISH">Bullish</option>
              <option value="BEARISH">Bearish</option>
              <option value="NEUTRAL">Neutral</option>
            </select>
          </div>
        </div>
      </div>

      {/* Forecast Table */}
      <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 text-zinc-400">
            <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mb-3" />
            <p className="text-xs">Loading historical records...</p>
          </div>
        ) : error ? (
          <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : forecasts.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                <tr>
                  <th className="py-2.5 px-3">Release Time</th>
                  <th className="py-2.5 px-3">Moment ID</th>
                  <th className="py-2.5 px-3">Family & Codes</th>
                  <th className="py-2.5 px-3">Prediction</th>
                  <th className="py-2.5 px-3">Probabilities</th>
                  <th className="py-2.5 px-3">5m Return</th>
                  <th className="py-2.5 px-3">15m / 30m</th>
                  <th className="py-2.5 px-3">Observed Label</th>
                  <th className="py-2.5 px-3">Grading</th>
                  <th className="py-2.5 px-3">Trained</th>
                  <th className="py-2.5 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#23252c]">
                {forecasts.map((f, idx) => {
                  const dirBadge = getDirectionBadge(f.forecast_direction || f.direction);
                  const ret5m = f.actual_outcome?.change_5m_pct ?? f.gold_change_5m_pct;
                  const ret15m = f.actual_outcome?.change_15m_pct ?? f.gold_change_15m_pct;
                  const ret30m = f.actual_outcome?.change_30m_pct ?? f.gold_change_30m_pct;

                  return (
                    <tr
                      key={idx}
                      className="hover:bg-[#1a1c22] transition-colors cursor-pointer"
                      onClick={() => onOpenEventDetail(f.release_moment_id || f.release_time_utc)}
                    >
                      <td className="py-3 px-3 font-mono text-[11px] text-zinc-300">
                        {formatTimestamp(f.release_time_utc, useUtc)}
                      </td>
                      <td className="py-3 px-3 font-mono text-[10px] text-zinc-400 max-w-[120px] truncate">
                        {f.release_moment_id || '—'}
                      </td>
                      <td className="py-3 px-3">
                        <div className="font-semibold text-zinc-200">
                          {f.event_family ? f.event_family.toUpperCase() : 'EVENT'}
                        </div>
                        {f.event_codes && (
                          <div className="text-[10px] font-mono text-zinc-500">
                            {f.event_codes.join(', ')}
                          </div>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${dirBadge.className}`}>
                          {dirBadge.label}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-mono text-[10px] text-zinc-400">
                        {f.probabilities ? (
                          <span>
                            {(f.probabilities.bullish * 100).toFixed(0)}% /{' '}
                            {(f.probabilities.neutral * 100).toFixed(0)}% /{' '}
                            {(f.probabilities.bearish * 100).toFixed(0)}%
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="py-3 px-3 font-mono font-bold">
                        <span
                          className={
                            (ret5m ?? 0) > 0
                              ? 'text-emerald-400'
                              : (ret5m ?? 0) < 0
                              ? 'text-rose-400'
                              : 'text-zinc-400'
                          }
                        >
                          {formatPct(ret5m, 2, true)}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-mono text-[11px] text-zinc-400">
                        {formatPct(ret15m, 2, true)} / {formatPct(ret30m, 2, true)}
                      </td>
                      <td className="py-3 px-3 font-semibold text-zinc-300">
                        {f.outcome_label || f.actual_outcome?.outcome_label || 'PENDING'}
                      </td>
                      <td className="py-3 px-3">
                        {f.outcome_status === 'ok' ? (
                          <span className="text-emerald-400 font-semibold flex items-center gap-1 text-[11px]">
                            <CheckCircle2 className="w-3 h-3" /> OK
                          </span>
                        ) : f.outcome_status === 'pending' ? (
                          <span className="text-amber-400 text-[11px]">Pending</span>
                        ) : (
                          <span className="text-zinc-500 text-[11px]">Unavailable</span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        {f.training_ledger?.is_trained ? (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                            Learned
                          </span>
                        ) : (
                          <span className="text-[10px] text-zinc-500">No</span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenEventDetail(f.release_moment_id || f.release_time_utc);
                          }}
                          className="text-[11px] text-purple-400 hover:text-purple-300 font-semibold flex items-center gap-1 justify-end ml-auto"
                        >
                          <span>Inspect</span>
                          <ExternalLink className="w-3 h-3" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-16 text-center text-xs text-zinc-500">
            No forecast records found matching current query.
          </div>
        )}

        {/* Pagination Footer */}
        {total > limit && (
          <div className="flex items-center justify-between pt-4 mt-4 border-t border-[#26282e] text-xs">
            <span className="text-zinc-400">
              Page {currentPage} of {totalPages}
            </span>

            <div className="flex items-center gap-2">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="flex items-center gap-1 px-3 py-1 rounded bg-[#1e2027] text-zinc-300 hover:bg-[#272a33] disabled:opacity-40 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                <span>Prev</span>
              </button>
              <button
                disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}
                className="flex items-center gap-1 px-3 py-1 rounded bg-[#1e2027] text-zinc-300 hover:bg-[#272a33] disabled:opacity-40 transition-colors"
              >
                <span>Next</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
