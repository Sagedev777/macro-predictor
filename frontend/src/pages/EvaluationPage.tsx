// frontend/src/pages/EvaluationPage.tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  CheckCircle2,
  AlertTriangle,
  Info,
  ShieldAlert,
  RefreshCw,
} from 'lucide-react';
import type { ModelEvaluationData } from '../types';
import { formatNumber } from '../utils/formatters';

interface EvaluationPageProps {
  useUtc?: boolean;
}

export const EvaluationPage: React.FC<EvaluationPageProps> = () => {
  const [data, setData] = useState<ModelEvaluationData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchEvaluation = () => {
    setLoading(true);
    setError(null);
    axios
      .get('/api/gold/evaluation')
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load evaluation:', err);
        setError('Failed to fetch walk-forward evaluation metrics from backend.');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchEvaluation();
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-zinc-400">
        <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-3" />
        <p className="text-xs">Computing chronological walk-forward metrics...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 shrink-0" />
        <span>{error || 'Unable to load model evaluation metrics.'}</span>
      </div>
    );
  }

  const nEvaluated = data.n_evaluated ?? data.overall?.n ?? 0;
  const brierScore = data.overall?.brier_score;
  const accuracyPct = data.overall?.accuracy_pct;
  const majorityBaseline = data.overall?.majority_class_accuracy_pct ?? 33.3;

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">
              Chronological Walk-Forward Model Evaluation
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Strictly leakage-free point-in-time scoring. Predictions are evaluated exclusively against earlier historical updates.
            </p>
          </div>
        </div>

        <button
          onClick={fetchEvaluation}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#20222a] text-zinc-300 hover:text-white border border-[#2e313d] transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Recompute Evaluation</span>
        </button>
      </div>

      {/* Statistical Rigor Warning */}
      {nEvaluated < 20 && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200/90 space-y-1">
          <div className="flex items-center gap-2 font-bold text-amber-400">
            <ShieldAlert className="w-4 h-4 shrink-0" />
            Small Evaluation Sample Warning (n = {nEvaluated})
          </div>
          <p className="text-[12px] leading-relaxed text-zinc-300">
            {data.note ||
              'Walk-forward evaluation requires at least 20 labeled release moments for meaningful statistical convergence. Directional accuracy must not be claimed as an empirical trading edge until larger sample size is reached.'}
          </p>
        </div>
      )}

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Brier Score */}
        <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-2">
          <div className="flex justify-between items-center text-xs text-zinc-400">
            <span className="font-semibold uppercase tracking-wider">Multi-Class Brier Score</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
              Lower is Better
            </span>
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">
            {brierScore !== null && brierScore !== undefined ? formatNumber(brierScore, 4) : '—'}
          </div>
          <div className="text-[11px] text-zinc-400">
            Random 3-class baseline is <code className="font-mono text-zinc-300">0.6667</code>. Perfect score is <code className="font-mono text-zinc-300">0.0000</code>.
          </div>
        </div>

        {/* Directional Accuracy */}
        <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-2">
          <div className="flex justify-between items-center text-xs text-zinc-400">
            <span className="font-semibold uppercase tracking-wider">Directional Accuracy</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
              5m Horizon
            </span>
          </div>
          <div className="text-2xl font-bold font-mono text-amber-300 mt-1">
            {accuracyPct !== null && accuracyPct !== undefined ? `${accuracyPct.toFixed(1)}%` : '—'}
          </div>
          <div className="text-[11px] text-zinc-400">
            Compared to Majority-Class benchmark of <code className="font-mono text-zinc-300">~{majorityBaseline.toFixed(1)}%</code>.
          </div>
        </div>

        {/* Labeled Evaluated Events */}
        <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-2">
          <div className="flex justify-between items-center text-xs text-zinc-400">
            <span className="font-semibold uppercase tracking-wider">Evaluated Events (n)</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#22242b] text-zinc-300 font-mono">
              Walk-Forward
            </span>
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">
            {nEvaluated}
          </div>
          <div className="text-[11px] text-zinc-400">
            Chronologically evaluated without future lookahead.
          </div>
        </div>
      </div>

      {/* Breakdown by Event Family */}
      <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-4">
        <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
          Evaluation by U.S. Economic Release Family
        </h3>

        {data.by_event_family && Object.keys(data.by_event_family).length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                <tr>
                  <th className="py-2.5 px-3">Event Family</th>
                  <th className="py-2.5 px-3">Evaluated Count (n)</th>
                  <th className="py-2.5 px-3">Brier Score</th>
                  <th className="py-2.5 px-3">Directional Accuracy</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#23252c] font-mono text-[11px]">
                {Object.entries(data.by_event_family).map(([fam, stat]) => (
                  <tr key={fam} className="hover:bg-[#1a1c22]">
                    <td className="py-3 px-3 font-sans font-semibold text-zinc-200 uppercase">
                      {fam}
                    </td>
                    <td className="py-3 px-3 text-zinc-300">{stat.n}</td>
                    <td className="py-3 px-3 text-zinc-300">
                      {stat.brier_score !== null ? formatNumber(stat.brier_score, 4) : '—'}
                    </td>
                    <td className="py-3 px-3 font-bold text-amber-300">
                      {stat.accuracy_pct !== null ? `${stat.accuracy_pct.toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 text-center text-xs text-zinc-500">
            Insufficient graded historical release moments to break down by family.
          </div>
        )}
      </div>

      {/* Evaluation Methodology Notes */}
      <div className="p-4 rounded-xl bg-[#181a20] border border-[#26282e] text-xs text-zinc-400 space-y-2">
        <div className="flex items-center gap-2 font-bold text-zinc-200">
          <Info className="w-4 h-4 text-blue-400 shrink-0" />
          Walk-Forward Protocol & Metric Explanations
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px] leading-relaxed pt-1">
          <div>
            <strong className="text-zinc-200">Brier Score:</strong> Measures mean squared error between forecast class probabilities and the one-hot observed label. Penalizes overconfident wrong predictions heavily. A well-calibrated probabilistic model scores significantly lower than random guessing (0.667).
          </div>
          <div>
            <strong className="text-zinc-200">No Random Train/Test Splitting:</strong> Macroeconomic data is strictly time-ordered. Random k-fold cross validation causes severe future-data leakage. Each release moment is evaluated against model weights trained exclusively on strictly earlier observations.
          </div>
        </div>
      </div>
    </div>
  );
};
