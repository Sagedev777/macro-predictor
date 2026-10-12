// frontend/src/pages/SourcesPage.tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import {
  Database,
  AlertTriangle,
  ShieldAlert,
  RefreshCw,
} from 'lucide-react';
import type { SourceItem } from '../types';
import { formatTimestamp } from '../utils/formatters';

interface SourcesPageProps {
  useUtc: boolean;
}

export const SourcesPage: React.FC<SourcesPageProps> = ({ useUtc }) => {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSources = () => {
    setLoading(true);
    setError(null);
    axios
      .get('/api/sources/status')
      .then((res) => {
        setSources(res.data.sources || []);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load data sources:', err);
        setError('Failed to fetch data sources status from backend.');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchSources();
  }, []);

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">
              Data Ingestion Providers & Feature Availability
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Live inspection of candle feeds, economic calendars, Treasury yields, COT positioning, and sentiment feeds.
            </p>
          </div>
        </div>

        <button
          onClick={fetchSources}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#20222a] text-zinc-300 hover:text-white border border-[#2e313d] transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Feeds</span>
        </button>
      </div>

      {/* Critical Transparency Notice */}
      <div className="p-4 rounded-xl bg-[#181a20] border border-amber-500/30 text-xs text-amber-200/90 space-y-1.5">
        <div className="flex items-center gap-2 font-bold text-amber-400">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          Data Integrity Policy: Zero Tolerance for Synthetic Data
        </div>
        <p className="text-[12px] leading-relaxed text-zinc-300">
          Missing data remains strictly <code className="text-amber-300 font-mono">null</code>. FedWatch rate probabilities and CME Gold Options Implied Volatility are marked <strong>Explicitly Withheld</strong> because direct providers are not yet integrated. Missing values are never zeroed or fabricated.
        </p>
      </div>

      {/* Data Sources Grid */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 text-zinc-400">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-xs">Checking provider health and observation latency...</p>
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {sources.map((src, idx) => (
            <div
              key={idx}
              className={`p-5 rounded-xl border flex flex-col justify-between transition-all ${
                src.is_integrated
                  ? 'bg-[#15171c] border-[#26282e]'
                  : 'bg-[#131418] border-[#252730] opacity-75'
              }`}
            >
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-white">{src.name}</h3>
                    <p className="text-xs text-zinc-400 mt-0.5">{src.type}</p>
                  </div>
                  <div>
                    {src.is_integrated ? (
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded font-semibold ${
                          src.status === 'configured'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                            : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                        }`}
                      >
                        {src.status === 'configured' ? 'ACTIVE' : src.status}
                      </span>
                    ) : (
                      <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono">
                        WITHHELD
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-4 space-y-2 text-xs">
                  <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830] space-y-1">
                    <div className="text-[11px] text-zinc-400">Coverage & Instruments</div>
                    <div className="font-mono text-zinc-200 text-[11px]">{src.coverage}</div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830]">
                      <div className="text-[10px] text-zinc-400">Last Successful Sync</div>
                      <div className="font-mono text-[11px] text-zinc-200 mt-0.5">
                        {formatTimestamp(src.last_fetch, useUtc)}
                      </div>
                    </div>
                    <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830]">
                      <div className="text-[10px] text-zinc-400">Update Latency</div>
                      <div className="font-mono text-[11px] text-zinc-200 mt-0.5">{src.latency}</div>
                    </div>
                  </div>

                  <div className="p-2.5 rounded bg-[#1a1c22] border border-[#252830] space-y-1">
                    <div className="text-[11px] text-zinc-400">Model Feature Usage</div>
                    <div className="text-[11px] text-zinc-300 leading-relaxed">{src.model_usage}</div>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-[#22242b] flex items-center justify-between text-[11px]">
                <span className="text-zinc-500">
                  {src.is_integrated ? 'Validated Ingestion Pipeline' : 'Deliberately Unintegrated'}
                </span>
                <span
                  className={`font-semibold ${
                    src.is_integrated ? 'text-emerald-400' : 'text-zinc-500'
                  }`}
                >
                  {src.is_integrated ? 'Usable by Model' : 'Null at Model Input'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
