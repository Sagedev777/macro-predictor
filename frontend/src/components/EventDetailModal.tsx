// frontend/src/components/EventDetailModal.tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  X,
  Clock,
  Cpu,
  TrendingUp,
  CheckCircle2,
  AlertTriangle,
  Info,
  Database,
} from 'lucide-react';
import type { GoldForecastItem } from '../types';
import { formatTimestamp, formatPct, getDirectionBadge } from '../utils/formatters';

interface EventDetailModalProps {
  releaseId: string | null;
  onClose: () => void;
  useUtc: boolean;
}

export const EventDetailModal: React.FC<EventDetailModalProps> = ({
  releaseId,
  onClose,
  useUtc,
}) => {
  const [data, setData] = useState<GoldForecastItem | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!releaseId) return;
    setLoading(true);
    setError(null);
    axios
      .get(`/api/gold/forecast/${encodeURIComponent(releaseId)}`)
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load event detail:', err);
        setError('Failed to fetch detailed event record from backend.');
        setLoading(false);
      });
  }, [releaseId]);

  if (!releaseId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/75 backdrop-blur-sm overflow-y-auto">
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-[#15171c] border border-[#2d3039] rounded-xl shadow-2xl flex flex-col overflow-hidden animate-fadeIn">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#26282e] bg-[#121316]">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-white tracking-wide">
                  Event Record & Feature Snapshot
                </h2>
                <span className="text-xs px-2 py-0.5 rounded bg-[#22252c] text-zinc-300 font-mono">
                  {data?.event_family ? data.event_family.toUpperCase() : 'EVENT'}
                </span>
              </div>
              <p className="text-xs text-zinc-400 font-mono mt-0.5">
                Moment ID: {releaseId}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-zinc-400 rounded-lg hover:text-white hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 p-6 space-y-6 overflow-y-auto">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-16 text-zinc-400">
              <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mb-3" />
              <p className="text-xs">Loading immutable point-in-time record...</p>
            </div>
          ) : error ? (
            <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : data ? (
            <>
              {/* Top Overview Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
                <div className="p-3.5 rounded-lg bg-[#1a1c22] border border-[#2d3039]">
                  <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Release Time</div>
                  <div className="text-xs font-semibold text-white mt-1 font-mono">
                    {formatTimestamp(data.release_time_utc, useUtc)}
                  </div>
                </div>

                <div className="p-3.5 rounded-lg bg-[#1a1c22] border border-[#2d3039]">
                  <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Forecast Direction</div>
                  <div className="flex items-center gap-2 mt-1">
                    {(() => {
                      const badge = getDirectionBadge(data.forecast_direction || data.direction);
                      return (
                        <span className={`px-2 py-0.5 text-xs font-bold rounded ${badge.className}`}>
                          {badge.label}
                        </span>
                      );
                    })()}
                    <span className="text-xs text-zinc-400 font-mono">
                      (5m horizon)
                    </span>
                  </div>
                </div>

                <div className="p-3.5 rounded-lg bg-[#1a1c22] border border-[#2d3039]">
                  <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Grading Status</div>
                  <div className="text-xs font-semibold text-white mt-1 flex items-center gap-1.5">
                    {data.outcome_status === 'ok' ? (
                      <span className="text-emerald-400 flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Graded (OK)
                      </span>
                    ) : data.outcome_status === 'pending' ? (
                      <span className="text-amber-400 flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" /> Pending Window
                      </span>
                    ) : (
                      <span className="text-zinc-400">Unavailable</span>
                    )}
                  </div>
                </div>

                <div className="p-3.5 rounded-lg bg-[#1a1c22] border border-[#2d3039]">
                  <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Training Ledger</div>
                  <div className="text-xs font-semibold mt-1">
                    {data.training_ledger?.is_trained ? (
                      <span className="text-emerald-400 flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Learned & Committed
                      </span>
                    ) : (
                      <span className="text-zinc-400">Not Trained Yet</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Probabilities Distribution Bar */}
              {data.probabilities && (
                <div className="p-4 rounded-lg bg-[#1a1c22] border border-[#2d3039] space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="font-semibold text-zinc-200">Point-in-Time Probability Distribution</span>
                    <span className="text-zinc-400 text-[11px]">Threshold: ±{data.threshold_pct ?? 0.15}%</span>
                  </div>
                  <div className="flex h-3 w-full rounded-full overflow-hidden bg-zinc-800">
                    <div
                      style={{ width: `${(data.probabilities.bullish * 100).toFixed(1)}%` }}
                      className="bg-emerald-500 transition-all"
                      title={`Bullish: ${(data.probabilities.bullish * 100).toFixed(1)}%`}
                    />
                    <div
                      style={{ width: `${(data.probabilities.neutral * 100).toFixed(1)}%` }}
                      className="bg-zinc-500 transition-all"
                      title={`Neutral: ${(data.probabilities.neutral * 100).toFixed(1)}%`}
                    />
                    <div
                      style={{ width: `${(data.probabilities.bearish * 100).toFixed(1)}%` }}
                      className="bg-rose-500 transition-all"
                      title={`Bearish: ${(data.probabilities.bearish * 100).toFixed(1)}%`}
                    />
                  </div>
                  <div className="flex justify-between text-xs font-mono pt-1 text-zinc-300">
                    <span className="text-emerald-400 font-semibold">
                      Bullish: {(data.probabilities.bullish * 100).toFixed(1)}%
                    </span>
                    <span className="text-zinc-400">
                      Neutral: {(data.probabilities.neutral * 100).toFixed(1)}%
                    </span>
                    <span className="text-rose-400 font-semibold">
                      Bearish: {(data.probabilities.bearish * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              )}

              {/* Multi-Horizon Real Outcome */}
              <div className="p-4 rounded-lg bg-[#1a1c22] border border-[#2d3039] space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                    <TrendingUp className="w-3.5 h-3.5 text-amber-400" />
                    Observed XAU/USD Returns & Excursion
                  </h3>
                  {data.actual_outcome?.recorded_at && (
                    <span className="text-[11px] text-zinc-400 font-mono">
                      Graded at: {formatTimestamp(data.actual_outcome.recorded_at, useUtc)}
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  <div className="p-2.5 rounded bg-[#131418] border border-[#24262c]">
                    <div className="text-[11px] text-zinc-400">1-Minute Return</div>
                    <div className={`font-mono font-bold mt-0.5 ${(data.actual_outcome?.change_1m_pct ?? data.gold_change_1m_pct ?? 0) > 0 ? 'text-emerald-400' : (data.actual_outcome?.change_1m_pct ?? data.gold_change_1m_pct ?? 0) < 0 ? 'text-rose-400' : 'text-zinc-300'}`}>
                      {formatPct(data.actual_outcome?.change_1m_pct ?? data.gold_change_1m_pct, 2, true)}
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-[#131418] border border-[#24262c]">
                    <div className="text-[11px] text-zinc-400 font-semibold text-amber-400">5-Minute Return (Target)</div>
                    <div className={`font-mono font-bold mt-0.5 ${(data.actual_outcome?.change_5m_pct ?? data.gold_change_5m_pct ?? 0) > 0 ? 'text-emerald-400' : (data.actual_outcome?.change_5m_pct ?? data.gold_change_5m_pct ?? 0) < 0 ? 'text-rose-400' : 'text-zinc-300'}`}>
                      {formatPct(data.actual_outcome?.change_5m_pct ?? data.gold_change_5m_pct, 2, true)}
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-[#131418] border border-[#24262c]">
                    <div className="text-[11px] text-zinc-400">15-Minute Return</div>
                    <div className={`font-mono font-bold mt-0.5 ${(data.actual_outcome?.change_15m_pct ?? data.gold_change_15m_pct ?? 0) > 0 ? 'text-emerald-400' : (data.actual_outcome?.change_15m_pct ?? data.gold_change_15m_pct ?? 0) < 0 ? 'text-rose-400' : 'text-zinc-300'}`}>
                      {formatPct(data.actual_outcome?.change_15m_pct ?? data.gold_change_15m_pct, 2, true)}
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-[#131418] border border-[#24262c]">
                    <div className="text-[11px] text-zinc-400">30-Minute Return</div>
                    <div className={`font-mono font-bold mt-0.5 ${(data.actual_outcome?.change_30m_pct ?? data.gold_change_30m_pct ?? 0) > 0 ? 'text-emerald-400' : (data.actual_outcome?.change_30m_pct ?? data.gold_change_30m_pct ?? 0) < 0 ? 'text-rose-400' : 'text-zinc-300'}`}>
                      {formatPct(data.actual_outcome?.change_30m_pct ?? data.gold_change_30m_pct, 2, true)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="p-2.5 rounded bg-[#131418] border border-[#24262c]">
                    <div className="text-[11px] text-zinc-400">5m Max Favorable Excursion (MFE)</div>
                    <div className="font-mono text-emerald-400 font-semibold mt-0.5">
                      {formatPct(data.actual_outcome?.max_favorable_5m_pct ?? data.max_favorable_5m_pct, 2, true)}
                    </div>
                  </div>
                  <div className="p-2.5 rounded bg-[#131418] border border-[#24262c]">
                    <div className="text-[11px] text-zinc-400">5m Max Adverse Excursion (MAE)</div>
                    <div className="font-mono text-rose-400 font-semibold mt-0.5">
                      {formatPct(data.actual_outcome?.max_adverse_5m_pct ?? data.max_adverse_5m_pct, 2, true)}
                    </div>
                  </div>
                </div>
              </div>

              {/* Immutable Point-in-Time Feature Snapshot */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider flex items-center gap-1.5">
                    <Database className="w-3.5 h-3.5 text-blue-400" />
                    Immutable Feature Snapshot (Available Inputs at Cutoff)
                  </h3>
                  <span className="text-[11px] text-zinc-400">Zero synthetic data</span>
                </div>

                {data.features && Object.keys(data.features).length > 0 ? (
                  <div className="overflow-x-auto border border-[#2d3039] rounded-lg">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#2d3039]">
                        <tr>
                          <th className="py-2.5 px-3">Feature Name</th>
                          <th className="py-2.5 px-3">Observed Value</th>
                          <th className="py-2.5 px-3">Data Source</th>
                          <th className="py-2.5 px-3">Availability / Observation Time</th>
                          <th className="py-2.5 px-3">Data Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#23252c] font-mono text-[11px]">
                        {Object.entries(data.features).map(([key, feat]) => (
                          <tr key={key} className="hover:bg-[#1a1c22]">
                            <td className="py-2 px-3 font-sans font-semibold text-zinc-200">{key}</td>
                            <td className="py-2 px-3 text-amber-300">
                              {feat.value !== null && feat.value !== undefined ? feat.value : 'null'}
                            </td>
                            <td className="py-2 px-3 text-zinc-400">{feat.source || '—'}</td>
                            <td className="py-2 px-3 text-zinc-400">
                              {formatTimestamp(feat.available_at || feat.observed_at || feat.captured_at, useUtc)}
                            </td>
                            <td className="py-2 px-3">
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] ${
                                  feat.status === 'observed' || feat.status === 'ok'
                                    ? 'bg-emerald-500/10 text-emerald-400'
                                    : feat.status === 'stale'
                                    ? 'bg-amber-500/10 text-amber-400'
                                    : 'bg-zinc-800 text-zinc-400'
                                }`}
                              >
                                {feat.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-4 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-xs text-zinc-400">
                    No raw feature snapshot available for this moment.
                  </div>
                )}
              </div>

              {/* Linked USD Predictions */}
              {data.linked_usd_predictions && data.linked_usd_predictions.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
                    Constituent USD Economic Releases & Consensus Surprises
                  </h3>
                  <div className="overflow-x-auto border border-[#2d3039] rounded-lg">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#2d3039]">
                        <tr>
                          <th className="py-2.5 px-3">Event Code</th>
                          <th className="py-2.5 px-3">Forecast</th>
                          <th className="py-2.5 px-3">Actual</th>
                          <th className="py-2.5 px-3">Surprise</th>
                          <th className="py-2.5 px-3">USD Lean</th>
                          <th className="py-2.5 px-3">15m USD Move</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#23252c] font-mono text-[11px]">
                        {data.linked_usd_predictions.map((p) => (
                          <tr key={p.id} className="hover:bg-[#1a1c22]">
                            <td className="py-2 px-3 font-sans font-medium text-zinc-200">
                              {p.event_display_name || p.event_code}
                            </td>
                            <td className="py-2 px-3 text-zinc-300">{p.forecast ?? '—'}</td>
                            <td className="py-2 px-3 text-amber-300 font-bold">{p.actual ?? '—'}</td>
                            <td className="py-2 px-3">
                              {p.surprise !== null && p.surprise !== undefined ? (
                                <span className={p.surprise > 0 ? 'text-emerald-400' : p.surprise < 0 ? 'text-rose-400' : 'text-zinc-300'}>
                                  {p.surprise > 0 ? `+${p.surprise}` : p.surprise}
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="py-2 px-3">
                              <span className="font-semibold text-zinc-300">{p.lean_direction}</span>
                            </td>
                            <td className="py-2 px-3 text-zinc-400">
                              {p.usd_move_15m !== null && p.usd_move_15m !== undefined ? `${p.usd_move_15m.toFixed(2)}%` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Model Transparency & Limitations Note */}
              <div className="p-3.5 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-xs text-zinc-400 space-y-1.5">
                <div className="flex items-center gap-1.5 font-semibold text-zinc-200">
                  <Info className="w-3.5 h-3.5 text-blue-400" />
                  Model Explanation & Architectural Honesty
                </div>
                <p className="text-[11px] leading-relaxed">
                  MacroPredictor uses an online streaming ensemble (River ARFClassifier). It does not compute synthetic post-hoc feature importance weights or fabricate reasoning chains. The displayed feature values above represent the exact point-in-time inputs captured prior to release cutoff. No future information was accessible at decision time.
                </p>
              </div>
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-[#26282e] bg-[#121316] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-semibold rounded-md bg-[#24262c] text-zinc-200 hover:bg-[#2d3039] hover:text-white transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
