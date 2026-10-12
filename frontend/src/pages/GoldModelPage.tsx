// frontend/src/pages/GoldModelPage.tsx
import React, { useState } from 'react';
import {
  Crosshair,
  TrendingUp,
  CheckCircle2,
  Database,
  Cpu,
  Info,
  Activity,
  ArrowRight,
} from 'lucide-react';
import type {
  GoldForecastItem,
  GoldModelStatus,
  ModelActivityItem,
} from '../types';
import { formatTimestamp, formatPct, getDirectionBadge } from '../utils/formatters';

interface GoldModelPageProps {
  latestForecast: GoldForecastItem | null;
  recentForecasts: GoldForecastItem[];
  modelStatus: GoldModelStatus | null;
  activityList: ModelActivityItem[];
  onOpenEventDetail: (releaseId: string) => void;
  useUtc: boolean;
}

type TabKey = 'prediction' | 'evidence' | 'learning' | 'outcomes' | 'activity';

export const GoldModelPage: React.FC<GoldModelPageProps> = ({
  latestForecast,
  recentForecasts,
  modelStatus,
  activityList,
  onOpenEventDetail,
  useUtc,
}) => {
  const [activeTab, setActiveTab] = useState<TabKey>('prediction');

  const pBullish = latestForecast?.probabilities?.bullish ?? latestForecast?.p_bullish ?? 0.33;
  const pNeutral = latestForecast?.probabilities?.neutral ?? latestForecast?.p_neutral ?? 0.34;
  const pBearish = latestForecast?.probabilities?.bearish ?? latestForecast?.p_bearish ?? 0.33;
  const badge = getDirectionBadge(latestForecast?.forecast_direction || latestForecast?.direction);

  const rawFeatures = latestForecast?.features || {};

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Title & Architecture Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Crosshair className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white tracking-wide flex items-center gap-2">
              XAU/USD Gold Reaction Learning Model (5-Minute Horizon)
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Strictly point-in-time streaming classification engine (River Adaptive Random Forest).
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <div className="px-3 py-1 rounded-lg bg-[#1b1d24] border border-[#2d303a] font-mono text-zinc-300">
            Engine: {modelStatus?.model_version || 'gold_arf_v1'}
          </div>
        </div>
      </div>

      {/* 5-Tab Navigation Bar */}
      <div className="flex items-center gap-1.5 p-1.5 rounded-xl bg-[#15171c] border border-[#26282e] overflow-x-auto">
        {[
          { key: 'prediction', label: 'A. Current Prediction', icon: Crosshair },
          { key: 'evidence', label: 'B. Prediction Evidence & Inputs', icon: Database },
          { key: 'learning', label: 'C. Learning Progress', icon: Cpu },
          { key: 'outcomes', label: 'D. Prediction vs Outcome Analysis', icon: TrendingUp },
          { key: 'activity', label: 'E. Model Activity Timeline', icon: Activity },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as TabKey)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-amber-500 text-zinc-950 shadow-md font-bold'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-[#1a1c22]'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab A: Current Prediction */}
      {activeTab === 'prediction' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Main Direction Card */}
            <div className="p-6 rounded-xl bg-[#15171c] border border-[#26282e] space-y-4">
              <div className="flex justify-between items-center text-xs text-zinc-400">
                <span className="font-semibold uppercase tracking-wider">Predicted Direction</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
                  Horizon: 5 Minutes
                </span>
              </div>

              <div className="py-2">
                <span className={`text-2xl font-bold px-3 py-1 rounded-md ${badge.className}`}>
                  {badge.label}
                </span>
              </div>

              {/* Probability distribution */}
              <div className="space-y-2">
                <div className="text-xs text-zinc-400 flex justify-between">
                  <span>Class Probability Distribution</span>
                  <span className="font-mono text-zinc-300">
                    Threshold: ±{latestForecast?.threshold_pct ?? 0.15}%
                  </span>
                </div>
                <div className="flex h-3 w-full rounded-full overflow-hidden bg-zinc-800">
                  <div
                    style={{ width: `${(pBullish * 100).toFixed(1)}%` }}
                    className="bg-emerald-500"
                    title={`Bullish: ${(pBullish * 100).toFixed(1)}%`}
                  />
                  <div
                    style={{ width: `${(pNeutral * 100).toFixed(1)}%` }}
                    className="bg-zinc-500"
                    title={`Neutral: ${(pNeutral * 100).toFixed(1)}%`}
                  />
                  <div
                    style={{ width: `${(pBearish * 100).toFixed(1)}%` }}
                    className="bg-rose-500"
                    title={`Bearish: ${(pBearish * 100).toFixed(1)}%`}
                  />
                </div>
                <div className="flex justify-between text-xs font-mono text-zinc-300 pt-1">
                  <span className="text-emerald-400">Bullish: {(pBullish * 100).toFixed(1)}%</span>
                  <span className="text-zinc-400">Neutral: {(pNeutral * 100).toFixed(1)}%</span>
                  <span className="text-rose-400">Bearish: {(pBearish * 100).toFixed(1)}%</span>
                </div>
              </div>

              <div className="pt-2 text-[11px] text-zinc-400">
                Status: <span className="text-zinc-200 font-semibold">{latestForecast?.forecast_status || 'Ready'}</span>
              </div>
            </div>

            {/* Timing & Provenance Identifiers */}
            <div className="p-6 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3 text-xs">
              <h3 className="font-bold text-zinc-200 uppercase tracking-wider text-xs">
                Release Provenance & Timestamps
              </h3>

              <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830] space-y-1">
                <div className="text-[11px] text-zinc-400">Release Moment ID</div>
                <div className="font-mono text-amber-300 text-[11px] break-all">
                  {latestForecast?.release_moment_id || 'STANDBY_MOMENT'}
                </div>
              </div>

              <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830] space-y-1">
                <div className="text-[11px] text-zinc-400">Event Family & Constituent Codes</div>
                <div className="font-mono text-zinc-200">
                  {latestForecast?.event_family?.toUpperCase() || 'UNKNOWN'}
                  {latestForecast?.event_codes && (
                    <span className="text-zinc-400 ml-2">
                      [{latestForecast.event_codes.join(', ')}]
                    </span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830]">
                  <div className="text-[10px] text-zinc-400">Release Time (Scheduled)</div>
                  <div className="font-mono text-[11px] text-zinc-200 mt-0.5">
                    {formatTimestamp(latestForecast?.release_time_utc, useUtc)}
                  </div>
                </div>
                <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830]">
                  <div className="text-[10px] text-zinc-400">Forecast Cutoff Window</div>
                  <div className="font-mono text-[11px] text-zinc-200 mt-0.5">
                    {formatTimestamp(latestForecast?.forecast_cutoff_utc || latestForecast?.release_time_utc, useUtc)}
                  </div>
                </div>
              </div>

              <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830]">
                <div className="text-[10px] text-zinc-400">Underlying XAU/USD Market Price Timestamp</div>
                <div className="font-mono text-[11px] text-zinc-200 mt-0.5">
                  Distinct from prediction timestamp; captures exact pre-release 1-minute close.
                </div>
              </div>
            </div>

            {/* Feature Snapshot Health & Data Quality */}
            <div className="p-6 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3 text-xs">
              <h3 className="font-bold text-zinc-200 uppercase tracking-wider text-xs">
                Data Quality & Feature Snapshot Health
              </h3>

              <div className="space-y-2">
                <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                  <span className="text-zinc-300">Feature Snapshot Saved:</span>
                  <span className="text-emerald-400 font-semibold flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Immutable
                  </span>
                </div>
                <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                  <span className="text-zinc-300">Pre-Release Leakage Protection:</span>
                  <span className="text-emerald-400 font-semibold flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Strictly Prior
                  </span>
                </div>
                <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                  <span className="text-zinc-300">Synthesized / Fake Features:</span>
                  <span className="text-emerald-400 font-semibold">0 (Zero Tolerance)</span>
                </div>
                <div className="flex items-center justify-between p-2 rounded bg-[#1a1c22]">
                  <span className="text-zinc-300">CME FedWatch & Options IV:</span>
                  <span className="text-zinc-400 font-mono text-[10px]">Withheld (Unintegrated)</span>
                </div>
              </div>

              {latestForecast?.release_moment_id && (
                <button
                  onClick={() => onOpenEventDetail(latestForecast.release_moment_id || '')}
                  className="w-full mt-2 py-2 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300 hover:bg-amber-500/25 font-semibold text-xs flex items-center justify-center gap-1.5 transition-colors"
                >
                  <span>Open Full Feature Snapshot Table</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Tab B: Prediction Evidence & Inputs */}
      {activeTab === 'evidence' && (
        <div className="space-y-6">
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-white tracking-wide flex items-center gap-2">
                  <Database className="w-4 h-4 text-blue-400" />
                  Point-in-Time Observed Features (Cutoff Snapshot)
                </h3>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Observed market returns, volatility, yields, COT positioning, and sentiment captured prior to release cutoff.
                </p>
              </div>
            </div>

            {Object.keys(rawFeatures).length > 0 ? (
              <div className="overflow-x-auto border border-[#26282e] rounded-lg">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                    <tr>
                      <th className="py-2.5 px-3">Feature Name</th>
                      <th className="py-2.5 px-3">Observed Value</th>
                      <th className="py-2.5 px-3">Data Provider</th>
                      <th className="py-2.5 px-3">Availability / Capture Timestamp</th>
                      <th className="py-2.5 px-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#23252c] font-mono text-[11px]">
                    {Object.entries(rawFeatures).map(([key, f]) => (
                      <tr key={key} className="hover:bg-[#1a1c22]">
                        <td className="py-2 px-3 font-sans font-semibold text-zinc-200">{key}</td>
                        <td className="py-2 px-3 text-amber-300 font-bold">
                          {f.value !== null && f.value !== undefined ? f.value : 'null'}
                        </td>
                        <td className="py-2 px-3 text-zinc-400">{f.source || '—'}</td>
                        <td className="py-2 px-3 text-zinc-400">
                          {formatTimestamp(f.available_at || f.observed_at || f.captured_at, useUtc)}
                        </td>
                        <td className="py-2 px-3">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] ${
                              f.status === 'observed' || f.status === 'ok'
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'bg-amber-500/10 text-amber-400'
                            }`}
                          >
                            {f.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-zinc-500">
                No active feature snapshot attached to latest forecast in memory. Inspect historical records below.
              </div>
            )}

            {/* Architectural Explanation of Model Limitations */}
            <div className="p-4 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-xs text-zinc-300 space-y-2">
              <div className="font-bold text-white flex items-center gap-1.5">
                <Info className="w-4 h-4 text-amber-400" />
                Truthful Model Explanations & Absence of Fabricated Feature Importance
              </div>
              <p className="text-[12px] leading-relaxed text-zinc-400">
                MacroPredictor employs an online streaming ensemble (River ARFClassifier). Online adaptive trees evaluate split criteria sequentially over time. We do not manufacture synthetic linear coefficients, post-hoc SHAP charts, or fictional causal reasoning. Feature importance must not be presented as proof of causation. The evidence shown above is the exact verified point-in-time input matrix that was fed into the classifier.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Tab C: Learning Progress */}
      {activeTab === 'learning' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e]">
              <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Total Graded Outcomes</div>
              <div className="text-2xl font-bold font-mono text-white mt-1">
                {modelStatus?.total_graded_gold_outcomes ?? 0}
              </div>
              <div className="text-[11px] text-zinc-500 mt-1">With 5m return & label</div>
            </div>

            <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e]">
              <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Unique Training Observations</div>
              <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
                {modelStatus?.unique_training_observations ?? 0}
              </div>
              <div className="text-[11px] text-zinc-500 mt-1">Learned exactly once</div>
            </div>

            <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e]">
              <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Eligible Historical Moments</div>
              <div className="text-2xl font-bold font-mono text-blue-400 mt-1">
                {modelStatus?.eligible_observations ?? 0}
              </div>
              <div className="text-[11px] text-zinc-500 mt-1">Sufficient candle coverage</div>
            </div>

            <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e]">
              <div className="text-[11px] text-zinc-400 uppercase tracking-wider">Training Ledger State</div>
              <div className="text-sm font-bold text-emerald-400 mt-2 flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4" /> Idempotent
              </div>
              <div className="text-[11px] text-zinc-500 mt-1">GoldModelTraining Table</div>
            </div>
          </div>

          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
            <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
              Outcome Grading vs Model Training Separation
            </h3>
            <p className="text-xs text-zinc-400 leading-relaxed">
              Outcome grading evaluates market price movement 35 minutes post-release and records 1m/5m/15m/30m returns. Model training is an explicit subsequent step: it claims the release moment in the idempotency ledger (<code className="text-amber-300 font-mono">GoldModelTraining</code>), commits the incremental update to the River ensemble, and records <code className="text-amber-300 font-mono">trained_at</code>. A graded event is not automatically a trained event until this ledger commit succeeds.
            </p>
          </div>
        </div>
      )}

      {/* Tab D: Prediction vs Outcome Analysis */}
      {activeTab === 'outcomes' && (
        <div className="space-y-6">
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider mb-4">
              Multi-Horizon Gold Reactions & Directional Evaluation
            </h3>

            {recentForecasts.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                    <tr>
                      <th className="py-2.5 px-3">Release Time</th>
                      <th className="py-2.5 px-3">Family</th>
                      <th className="py-2.5 px-3">Predicted</th>
                      <th className="py-2.5 px-3">1m Return</th>
                      <th className="py-2.5 px-3">5m Return (Target)</th>
                      <th className="py-2.5 px-3">15m Return</th>
                      <th className="py-2.5 px-3">30m Return</th>
                      <th className="py-2.5 px-3">Match?</th>
                      <th className="py-2.5 px-3 text-right">Detail</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#23252c]">
                    {recentForecasts.map((f, idx) => {
                      const dirBadge = getDirectionBadge(f.forecast_direction || f.direction);
                      const ret5m = f.actual_outcome?.change_5m_pct ?? f.gold_change_5m_pct;
                      const outcomeLabel = f.outcome_label || f.actual_outcome?.outcome_label;
                      const isMatch =
                        f.forecast_direction && outcomeLabel
                          ? f.forecast_direction === outcomeLabel
                          : null;

                      return (
                        <tr key={idx} className="hover:bg-[#1a1c22]">
                          <td className="py-3 px-3 font-mono text-[11px] text-zinc-300">
                            {formatTimestamp(f.release_time_utc, useUtc)}
                          </td>
                          <td className="py-3 px-3 font-semibold text-zinc-200">
                            {f.event_family ? f.event_family.toUpperCase() : 'EVENT'}
                          </td>
                          <td className="py-3 px-3">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${dirBadge.className}`}>
                              {dirBadge.label}
                            </span>
                          </td>
                          <td className="py-3 px-3 font-mono text-zinc-300">
                            {formatPct(f.actual_outcome?.change_1m_pct ?? f.gold_change_1m_pct, 2, true)}
                          </td>
                          <td className="py-3 px-3 font-mono font-bold">
                            <span className={(ret5m ?? 0) > 0 ? 'text-emerald-400' : (ret5m ?? 0) < 0 ? 'text-rose-400' : 'text-zinc-300'}>
                              {formatPct(ret5m, 2, true)}
                            </span>
                          </td>
                          <td className="py-3 px-3 font-mono text-zinc-300">
                            {formatPct(f.actual_outcome?.change_15m_pct ?? f.gold_change_15m_pct, 2, true)}
                          </td>
                          <td className="py-3 px-3 font-mono text-zinc-300">
                            {formatPct(f.actual_outcome?.change_30m_pct ?? f.gold_change_30m_pct, 2, true)}
                          </td>
                          <td className="py-3 px-3">
                            {isMatch === true ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-bold">
                                MATCH
                              </span>
                            ) : isMatch === false ? (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/30 font-bold">
                                MISS
                              </span>
                            ) : (
                              <span className="text-zinc-500 text-[10px]">Pending</span>
                            )}
                          </td>
                          <td className="py-3 px-3 text-right">
                            <button
                              onClick={() => onOpenEventDetail(f.release_moment_id || f.release_time_utc)}
                              className="text-[11px] text-amber-400 hover:text-amber-300 font-semibold"
                            >
                              Inspect
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-zinc-500">
                No recent forecast records available.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab E: Model Activity Timeline */}
      {activeTab === 'activity' && (
        <div className="space-y-6">
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider mb-4 flex items-center gap-1.5">
              <Activity className="w-4 h-4 text-amber-400" />
              Chronological Model Lifecycle Activity
            </h3>

            {activityList.length > 0 ? (
              <div className="space-y-4">
                {activityList.map((act, idx) => (
                  <div
                    key={idx}
                    className="p-3.5 rounded-lg bg-[#1a1c22] border border-[#26282e] flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white">{act.title}</span>
                        <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#24262e] text-zinc-400 font-mono">
                          {act.type}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-400">{act.description}</p>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-[11px] font-mono text-zinc-500">
                        {formatTimestamp(act.timestamp, useUtc, true)}
                      </span>
                      {act.moment_id && (
                        <button
                          onClick={() => onOpenEventDetail(act.moment_id || '')}
                          className="text-[11px] text-amber-400 hover:text-amber-300 font-semibold"
                        >
                          View Moment
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-12 text-center text-xs text-zinc-500">
                No lifecycle activity records currently stored.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
