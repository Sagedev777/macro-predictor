// frontend/src/pages/OverviewPage.tsx
import React from 'react';
import {
  Calendar,
  Crosshair,
  LineChart,
  History,
  Database,
  CheckCircle,
  Terminal,
  ArrowRight,
  Zap,
} from 'lucide-react';
import type {
  PageId,
  GoldForecastItem,
  CalEvent,
  GoldModelStatus,
  SystemStatusData,
  ModelActivityItem,
} from '../types';
import { formatTimestamp, formatPct, getDirectionBadge } from '../utils/formatters';

interface OverviewPageProps {
  onNavigate: (page: PageId) => void;
  onOpenEventDetail: (releaseId: string) => void;
  useUtc: boolean;
  latestForecast: GoldForecastItem | null;
  upcomingEvents: CalEvent[];
  recentForecasts: GoldForecastItem[];
  modelStatus: GoldModelStatus | null;
  systemStatus?: SystemStatusData | null;
  recentActivity: ModelActivityItem[];
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  onNavigate,
  onOpenEventDetail,
  useUtc,
  latestForecast,
  upcomingEvents,
  recentForecasts,
  modelStatus,
  recentActivity,
}) => {
  const pBullish = latestForecast?.probabilities?.bullish ?? latestForecast?.p_bullish ?? 0.33;
  const pNeutral = latestForecast?.probabilities?.neutral ?? latestForecast?.p_neutral ?? 0.34;
  const pBearish = latestForecast?.probabilities?.bearish ?? latestForecast?.p_bearish ?? 0.33;
  const badge = getDirectionBadge(latestForecast?.forecast_direction || latestForecast?.direction);

  const pendingCount = modelStatus?.pending_outcomes_count ?? 0;
  const completedCount = modelStatus?.total_graded_gold_outcomes ?? 0;
  const unavailableCount = modelStatus?.unavailable_outcomes_count ?? 0;

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Scope and Model Integrity Header Banner */}
      <div className="p-4 rounded-xl bg-gradient-to-r from-[#171920] to-[#131418] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Crosshair className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide flex items-center gap-2">
              MacroPredictor v4 — Live Monitoring & Transparency Interface
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Probabilistic 5-minute XAU/USD gold reactions conditioned exclusively on U.S. macroeconomic releases.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onNavigate('gold_model')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-zinc-950 hover:bg-amber-400 transition-colors"
          >
            <span>Gold Model Deep-Dive</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Top Status & Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Active Gold Forecast */}
        <div
          onClick={() => onNavigate('gold_model')}
          className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] hover:border-amber-500/40 transition-all cursor-pointer group flex flex-col justify-between"
        >
          <div>
            <div className="flex justify-between items-center text-xs text-zinc-400">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-amber-400" />
                Latest Gold Prediction
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
                {latestForecast?.event_family?.toUpperCase() || 'STANDBY'}
              </span>
            </div>

            <div className="mt-3 flex items-baseline gap-2">
              <span className={`text-xl font-bold px-2 py-0.5 rounded ${badge.className}`}>
                {badge.label}
              </span>
              <span className="text-xs text-zinc-400">5-minute horizon</span>
            </div>

            {/* Probability split */}
            <div className="mt-3 space-y-1">
              <div className="flex h-2 rounded-full overflow-hidden bg-zinc-800">
                <div style={{ width: `${(pBullish * 100).toFixed(0)}%` }} className="bg-emerald-500" />
                <div style={{ width: `${(pNeutral * 100).toFixed(0)}%` }} className="bg-zinc-500" />
                <div style={{ width: `${(pBearish * 100).toFixed(0)}%` }} className="bg-rose-500" />
              </div>
              <div className="flex justify-between text-[11px] font-mono text-zinc-400 pt-0.5">
                <span className="text-emerald-400">{(pBullish * 100).toFixed(0)}% Bull</span>
                <span className="text-zinc-400">{(pNeutral * 100).toFixed(0)}% Neut</span>
                <span className="text-rose-400">{(pBearish * 100).toFixed(0)}% Bear</span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#22242b] flex items-center justify-between text-[11px] text-zinc-400">
            <span>Cutoff: {formatTimestamp(latestForecast?.release_time_utc, useUtc)}</span>
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform text-amber-400" />
          </div>
        </div>

        {/* Card 2: Model Readiness vs Validation */}
        <div
          onClick={() => onNavigate('evaluation')}
          className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] hover:border-blue-500/40 transition-all cursor-pointer group flex flex-col justify-between"
        >
          <div>
            <div className="flex justify-between items-center text-xs text-zinc-400">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <CheckCircle className="w-3.5 h-3.5 text-blue-400" />
                Readiness vs Validation
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                READY
              </span>
            </div>

            <div className="mt-3">
              <div className="text-xs text-zinc-300 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block animate-pulse" />
                <span>Online Learning: <strong>Active</strong></span>
              </div>
              <div className="text-xs text-zinc-400 mt-1">
                Version: <span className="font-mono text-zinc-200">{modelStatus?.model_version || 'gold_arf_v1'}</span>
              </div>
              <div className="text-[11px] text-zinc-400 mt-2 bg-[#1a1c22] p-2 rounded border border-[#252830]">
                Predictive evidence must be verified via Walk-Forward Brier score, separate from pipeline health.
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#22242b] flex items-center justify-between text-[11px] text-zinc-400">
            <span>View Walk-Forward Metrics</span>
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform text-blue-400" />
          </div>
        </div>

        {/* Card 3: Historical Observations & Training */}
        <div
          onClick={() => onNavigate('gold_model')}
          className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] hover:border-emerald-500/40 transition-all cursor-pointer group flex flex-col justify-between"
        >
          <div>
            <div className="flex justify-between items-center text-xs text-zinc-400">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <History className="w-3.5 h-3.5 text-emerald-400" />
                Training Observations
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
                PERSISTED
              </span>
            </div>

            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-2xl font-bold font-mono text-white">
                {modelStatus?.unique_training_observations ?? 0}
              </span>
              <span className="text-xs text-zinc-400">learned release moments</span>
            </div>

            <div className="mt-2 text-xs text-zinc-400 space-y-1">
              <div className="flex justify-between">
                <span>Eligible observations:</span>
                <span className="text-zinc-200 font-mono font-medium">
                  {modelStatus?.eligible_observations ?? 0}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Last learned:</span>
                <span className="text-zinc-200 font-mono text-[11px]">
                  {modelStatus?.last_trained_utc ? formatTimestamp(modelStatus.last_trained_utc, useUtc) : 'None'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#22242b] flex items-center justify-between text-[11px] text-zinc-400">
            <span>Inspect Learning Ledger</span>
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform text-emerald-400" />
          </div>
        </div>

        {/* Card 4: Outcome Pipeline Status */}
        <div
          onClick={() => onNavigate('history')}
          className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] hover:border-purple-500/40 transition-all cursor-pointer group flex flex-col justify-between"
        >
          <div>
            <div className="flex justify-between items-center text-xs text-zinc-400">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <LineChart className="w-3.5 h-3.5 text-purple-400" />
                Outcome Pipeline
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
                XAU/USD
              </span>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 text-center">
              <div className="p-2 rounded bg-[#1c1e24] border border-[#2a2c34]">
                <div className="text-[10px] text-zinc-400">Graded</div>
                <div className="text-sm font-bold font-mono text-emerald-400 mt-0.5">{completedCount}</div>
              </div>
              <div className="p-2 rounded bg-[#1c1e24] border border-[#2a2c34]">
                <div className="text-[10px] text-zinc-400">Pending</div>
                <div className="text-sm font-bold font-mono text-amber-400 mt-0.5">{pendingCount}</div>
              </div>
              <div className="p-2 rounded bg-[#1c1e24] border border-[#2a2c34]">
                <div className="text-[10px] text-zinc-400">Unavailable</div>
                <div className="text-sm font-bold font-mono text-zinc-400 mt-0.5">{unavailableCount}</div>
              </div>
            </div>

            <div className="mt-2 text-[11px] text-zinc-400 text-center">
              35-minute post-release window required before grading
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-[#22242b] flex items-center justify-between text-[11px] text-zinc-400">
            <span>Forecast History & Filters</span>
            <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform text-purple-400" />
          </div>
        </div>
      </div>

      {/* Main Two-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column (2 spans): Upcoming USD Releases & Recent Gold Reactions */}
        <div className="lg:col-span-2 space-y-6">
          {/* Section: Next Relevant USD Economic Releases */}
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Calendar className="w-4 h-4 text-amber-400" />
                <h3 className="text-sm font-bold text-white tracking-wide">
                  Upcoming U.S. Economic Releases
                </h3>
              </div>
              <button
                onClick={() => onNavigate('calendar')}
                className="text-xs text-amber-400 hover:text-amber-300 font-semibold flex items-center gap-1"
              >
                <span>Full Calendar</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {upcomingEvents.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                    <tr>
                      <th className="py-2.5 px-3">Release Time</th>
                      <th className="py-2.5 px-3">Event Name</th>
                      <th className="py-2.5 px-3">Impact</th>
                      <th className="py-2.5 px-3">Forecast / Prev</th>
                      <th className="py-2.5 px-3">USD Prediction</th>
                      <th className="py-2.5 px-3 text-right">Gold Horizon</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#23252c]">
                    {upcomingEvents.slice(0, 5).map((ev, idx) => (
                      <tr key={idx} className="hover:bg-[#1a1c22] transition-colors">
                        <td className="py-3 px-3 font-mono text-[11px] text-zinc-300">
                          {formatTimestamp(ev.release_time_utc, useUtc)}
                        </td>
                        <td className="py-3 px-3">
                          <div className="font-semibold text-white">{ev.display_name || ev.event_name}</div>
                          {ev.is_simultaneous && (
                            <span className="text-[10px] px-1 py-0.2 rounded bg-blue-500/10 text-blue-400 font-mono">
                              Simultaneous Cluster
                            </span>
                          )}
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
                          {ev.forecast ?? '—'} / {ev.previous ?? '—'}
                        </td>
                        <td className="py-3 px-3">
                          {ev.prediction ? (
                            <span className="font-semibold text-zinc-200">
                              {ev.prediction.lean_direction} ({ev.prediction.confidence_pct.toFixed(0)}%)
                            </span>
                          ) : (
                            <span className="text-zinc-500">Standby (0-10m)</span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-zinc-400">
                          5m post
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-zinc-400">
                No high-impact U.S. economic events scheduled in immediate window.
              </div>
            )}
          </div>

          {/* Section: Recent Predictions Compared with Actual Reactions */}
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <History className="w-4 h-4 text-emerald-400" />
                <h3 className="text-sm font-bold text-white tracking-wide">
                  Recent Gold Predictions vs Real Outcomes
                </h3>
              </div>
              <button
                onClick={() => onNavigate('history')}
                className="text-xs text-emerald-400 hover:text-emerald-300 font-semibold flex items-center gap-1"
              >
                <span>View All History</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {recentForecasts.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                    <tr>
                      <th className="py-2.5 px-3">Release Time</th>
                      <th className="py-2.5 px-3">Family / Events</th>
                      <th className="py-2.5 px-3">Predicted</th>
                      <th className="py-2.5 px-3">Actual 5m Return</th>
                      <th className="py-2.5 px-3">Observed Label</th>
                      <th className="py-2.5 px-3">Learned?</th>
                      <th className="py-2.5 px-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#23252c]">
                    {recentForecasts.slice(0, 5).map((f, idx) => {
                      const dirBadge = getDirectionBadge(f.forecast_direction || f.direction);
                      const ret5m = f.actual_outcome?.change_5m_pct ?? f.gold_change_5m_pct;
                      return (
                        <tr key={idx} className="hover:bg-[#1a1c22] transition-colors">
                          <td className="py-3 px-3 font-mono text-[11px] text-zinc-300">
                            {formatTimestamp(f.release_time_utc, useUtc)}
                          </td>
                          <td className="py-3 px-3">
                            <span className="font-semibold text-zinc-200">
                              {f.event_family ? f.event_family.toUpperCase() : 'EVENT'}
                            </span>
                          </td>
                          <td className="py-3 px-3">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${dirBadge.className}`}>
                              {dirBadge.label}
                            </span>
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
                          <td className="py-3 px-3 font-semibold text-zinc-300">
                            {f.outcome_label || f.actual_outcome?.outcome_label || 'PENDING'}
                          </td>
                          <td className="py-3 px-3">
                            {f.training_ledger?.is_trained ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                                Yes
                              </span>
                            ) : (
                              <span className="text-[10px] text-zinc-500">No</span>
                            )}
                          </td>
                          <td className="py-3 px-3 text-right">
                            <button
                              onClick={() => onOpenEventDetail(f.release_moment_id || f.release_time_utc)}
                              className="text-[11px] text-amber-400 hover:text-amber-300 font-semibold"
                            >
                              Detail
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-zinc-400">
                No recent gold forecast records found.
              </div>
            )}
          </div>
        </div>

        {/* Right Column (1 span): System & Activity Stream */}
        <div className="space-y-6">
          {/* Data Sources Health Summary */}
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5 text-blue-400" />
                Data Providers Health
              </h3>
              <button
                onClick={() => onNavigate('sources')}
                className="text-[11px] text-blue-400 hover:text-blue-300 font-semibold"
              >
                Inspect
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                <span className="text-zinc-300">Twelve Data (XAU/USD)</span>
                <span className="text-emerald-400 font-medium">Connected</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                <span className="text-zinc-300">Forex Factory</span>
                <span className="text-emerald-400 font-medium">Connected</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                <span className="text-zinc-300">FRED (Yields)</span>
                <span className="text-emerald-400 font-medium">Connected</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                <span className="text-zinc-300">COMEX COT & Sentiment</span>
                <span className="text-emerald-400 font-medium">Connected</span>
              </div>
              <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22] opacity-70">
                <span className="text-zinc-400">FedWatch / Options IV</span>
                <span className="text-zinc-500 text-[10px] font-mono">Not Integrated</span>
              </div>
            </div>
          </div>

          {/* Model Activity Stream */}
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                <Terminal className="w-3.5 h-3.5 text-amber-400" />
                Model Activity Stream
              </h3>
              <button
                onClick={() => onNavigate('system')}
                className="text-[11px] text-amber-400 hover:text-amber-300 font-semibold"
              >
                Logs
              </button>
            </div>

            {recentActivity.length > 0 ? (
              <div className="space-y-3">
                {recentActivity.slice(0, 6).map((item, idx) => (
                  <div key={idx} className="text-xs border-l-2 border-[#2d3039] pl-3 py-0.5 space-y-0.5">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-zinc-200">{item.title}</span>
                      <span className="text-[10px] font-mono text-zinc-500">
                        {formatTimestamp(item.timestamp, useUtc)}
                      </span>
                    </div>
                    <p className="text-[11px] text-zinc-400">{item.description}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-6 text-center text-xs text-zinc-500">
                No recent system activity recorded.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
