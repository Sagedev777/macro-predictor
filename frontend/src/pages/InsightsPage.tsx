// frontend/src/pages/InsightsPage.tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  LineChart,
  AlertTriangle,
  Info,
  ShieldAlert,
} from 'lucide-react';
import type { ModelInsightsData } from '../types';
import { formatPct } from '../utils/formatters';

interface InsightsPageProps {
  useUtc?: boolean;
}

export const InsightsPage: React.FC<InsightsPageProps> = () => {
  const [data, setData] = useState<ModelInsightsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    axios
      .get('/api/gold/insights')
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load insights:', err);
        setError('Failed to fetch historical model insights from backend.');
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-zinc-400">
        <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mb-3" />
        <p className="text-xs">Computing empirical reaction distributions...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 shrink-0" />
        <span>{error || 'Unable to load insights data.'}</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Header Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
            <LineChart className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">
              Empirical Historical Evidence & Gold Reactions
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Empirical summaries computed strictly from persisted historical release outcomes.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-zinc-400">
          <span>Sample Size: <strong>{data.sample_size}</strong> graded events</span>
        </div>
      </div>

      {/* Insufficient Data Guard */}
      {!data.has_sufficient_data ? (
        <div className="p-8 rounded-xl bg-[#15171c] border border-[#26282e] text-center space-y-3">
          <ShieldAlert className="w-10 h-10 text-amber-400 mx-auto" />
          <h3 className="text-sm font-bold text-white">
            Insufficient Historical Sample
          </h3>
          <p className="text-xs text-zinc-400 max-w-md mx-auto leading-relaxed">
            {data.message ||
              'At least 3 graded release outcomes are required to compute statistically non-trivial reaction percentiles and empirical distributions.'}
          </p>
          <div className="text-[11px] text-zinc-500">
            As live economic events occur and are graded after 35 minutes, empirical summaries will automatically populate here.
          </div>
        </div>
      ) : (
        <>
          {/* Key Empirical Metrics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* 5-Minute Return Distribution */}
            <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
              <div className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center justify-between">
                <span>5m Return Distribution</span>
                <span className="text-[10px] text-zinc-500 font-mono">XAU/USD %</span>
              </div>

              {data.return_distribution && (
                <div className="space-y-2 text-xs font-mono">
                  <div className="flex justify-between py-1 border-b border-[#22242a]">
                    <span className="text-zinc-400">Minimum:</span>
                    <span className="text-rose-400 font-semibold">{formatPct(data.return_distribution.min, 2, true)}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-[#22242a]">
                    <span className="text-zinc-400">25th Percentile:</span>
                    <span className="text-zinc-300">{formatPct(data.return_distribution.p25, 2, true)}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-[#22242a]">
                    <span className="text-zinc-200 font-bold">Median (50th):</span>
                    <span className="text-amber-300 font-bold">{formatPct(data.return_distribution.median, 2, true)}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-[#22242a]">
                    <span className="text-zinc-400">75th Percentile:</span>
                    <span className="text-zinc-300">{formatPct(data.return_distribution.p75, 2, true)}</span>
                  </div>
                  <div className="flex justify-between py-1">
                    <span className="text-zinc-400">Maximum:</span>
                    <span className="text-emerald-400 font-semibold">{formatPct(data.return_distribution.max, 2, true)}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Historical Direction Frequencies */}
            <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
              <div className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center justify-between">
                <span>Historical Direction Frequencies</span>
                <span className="text-[10px] text-zinc-500 font-mono">5m Labels</span>
              </div>

              {data.direction_frequencies && (
                <div className="space-y-3 pt-1">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-emerald-400 font-semibold">Bullish</span>
                      <span className="text-zinc-300 font-mono">
                        {data.direction_frequencies.percentages.BULLISH}% ({data.direction_frequencies.counts.BULLISH})
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        style={{ width: `${data.direction_frequencies.percentages.BULLISH}%` }}
                        className="h-full bg-emerald-500"
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-zinc-400 font-semibold">Neutral</span>
                      <span className="text-zinc-300 font-mono">
                        {data.direction_frequencies.percentages.NEUTRAL}% ({data.direction_frequencies.counts.NEUTRAL})
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        style={{ width: `${data.direction_frequencies.percentages.NEUTRAL}%` }}
                        className="h-full bg-zinc-500"
                      />
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-rose-400 font-semibold">Bearish</span>
                      <span className="text-zinc-300 font-mono">
                        {data.direction_frequencies.percentages.BEARISH}% ({data.direction_frequencies.counts.BEARISH})
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        style={{ width: `${data.direction_frequencies.percentages.BEARISH}%` }}
                        className="h-full bg-rose-500"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Reactions by Surprise Category */}
            <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
              <div className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center justify-between">
                <span>Reaction by Surprise Category</span>
                <span className="text-[10px] text-zinc-500 font-mono">Median Move</span>
              </div>

              {data.by_surprise && (
                <div className="space-y-2 text-xs">
                  {Object.entries(data.by_surprise).map(([cat, stat]) => (
                    <div key={cat} className="p-2.5 rounded bg-[#1a1c22] border border-[#262830]">
                      <div className="flex justify-between font-semibold uppercase text-zinc-200">
                        <span>USD {cat}</span>
                        <span className="font-mono text-zinc-400 text-[11px]">n={stat.count}</span>
                      </div>
                      <div className="flex justify-between mt-1 text-[11px] font-mono text-zinc-400">
                        <span>Median 5m:</span>
                        <span className="text-amber-300 font-bold">{formatPct(stat.median_return_pct, 2, true)}</span>
                      </div>
                      <div className="flex justify-between text-[11px] font-mono text-zinc-400">
                        <span>Avg Absolute Move:</span>
                        <span className="text-zinc-300">{formatPct(stat.avg_abs_move_pct, 2)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Breakdown by USD Event Family */}
          <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e]">
            <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider mb-4">
              Gold Reactions by USD Event Family
            </h3>

            {data.by_family && Object.keys(data.by_family).length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                    <tr>
                      <th className="py-2.5 px-3">Event Family</th>
                      <th className="py-2.5 px-3">Observed Events (n)</th>
                      <th className="py-2.5 px-3">Median 5m Return</th>
                      <th className="py-2.5 px-3">Avg Absolute Move</th>
                      <th className="py-2.5 px-3">Bullish</th>
                      <th className="py-2.5 px-3">Bearish</th>
                      <th className="py-2.5 px-3">Neutral</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#23252c] font-mono text-[11px]">
                    {Object.entries(data.by_family).map(([fam, fstat]) => (
                      <tr key={fam} className="hover:bg-[#1a1c22]">
                        <td className="py-3 px-3 font-sans font-semibold text-zinc-200 uppercase">
                          {fam}
                        </td>
                        <td className="py-3 px-3 text-zinc-300">{fstat.count}</td>
                        <td className="py-3 px-3 font-bold text-amber-300">
                          {formatPct(fstat.median_return_5m_pct, 2, true)}
                        </td>
                        <td className="py-3 px-3 text-zinc-300">
                          {formatPct(fstat.avg_abs_move_pct, 2)}
                        </td>
                        <td className="py-3 px-3 text-emerald-400 font-bold">{fstat.bullish_count}</td>
                        <td className="py-3 px-3 text-rose-400 font-bold">{fstat.bearish_count}</td>
                        <td className="py-3 px-3 text-zinc-400">{fstat.neutral_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-zinc-500">
                No event family groups populated yet.
              </div>
            )}
          </div>

          {/* Research & Integrity Disclaimer */}
          <div className="p-4 rounded-lg bg-[#1a1c22] border border-[#2d3039] text-xs text-zinc-400 space-y-1.5">
            <div className="flex items-center gap-1.5 font-semibold text-zinc-200">
              <Info className="w-3.5 h-3.5 text-blue-400" />
              Empirical Honesty & Limitations Note
            </div>
            <p className="text-[11px] leading-relaxed">
              {data.disclaimer ||
                'Descriptive historical findings based exclusively on persisted release observations. Small-sample patterns are not predictive trading rules and should not be used as guaranteed trade signals.'}
            </p>
          </div>
        </>
      )}
    </div>
  );
};
