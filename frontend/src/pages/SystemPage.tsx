// frontend/src/pages/SystemPage.tsx
import React, { useState } from 'react';
import axios from 'axios';
import {
  Terminal,
  Server,
  Database,
  Activity,
  CheckCircle2,
  Play,
  RefreshCw,
  Send,
  Zap,
} from 'lucide-react';
import type { SystemStatusData } from '../types';
import { formatTimestamp } from '../utils/formatters';

interface SystemPageProps {
  systemStatus: SystemStatusData | null;
  onRefresh: () => void;
  isRefreshing: boolean;
  useUtc: boolean;
}

export const SystemPage: React.FC<SystemPageProps> = ({
  systemStatus,
  onRefresh,
  isRefreshing,
  useUtc,
}) => {
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);

  const handleTriggerCheck = async () => {
    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await axios.post('/api/scheduler/check-now');
      setActionMessage(res.data.message || 'Alert check triggered successfully.');
      onRefresh();
    } catch (err: any) {
      setActionMessage('Failed to trigger alert check: ' + (err.response?.data?.detail || err.message));
    } finally {
      setActionLoading(false);
    }
  };

  const handleWarmup = async () => {
    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await axios.post('/api/predictions/warmup');
      setActionMessage(`Warmup started. Triggered: ${res.data.triggered?.join(', ') || 'none'}`);
      onRefresh();
    } catch (err: any) {
      setActionMessage('Failed to run warmup: ' + (err.response?.data?.detail || err.message));
    } finally {
      setActionLoading(false);
    }
  };

  const handleTestTelegram = async () => {
    setActionLoading(true);
    setActionMessage(null);
    try {
      const res = await axios.post('/api/telegram/test');
      setActionMessage(res.data.success ? 'Test telegram alert sent successfully.' : 'Telegram test failed (check bot token/chat ID).');
    } catch (err: any) {
      setActionMessage('Failed to test telegram: ' + (err.response?.data?.detail || err.message));
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6 pb-12 animate-fadeIn">
      {/* Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Terminal className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white tracking-wide">
              System Operations, Background Jobs & Audit Logs
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Authoritative diagnostic telemetry for FastAPI server, SQLite engine, APScheduler, and dispatch logs.
            </p>
          </div>
        </div>

        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#20222a] text-zinc-300 hover:text-white border border-[#2e313d] transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          <span>Refresh Telemetry</span>
        </button>
      </div>

      {/* Manual Actions Banner */}
      <div className="p-4 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
        <div className="text-xs font-bold text-zinc-300 uppercase tracking-wider">
          Manual Operational Triggers
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleTriggerCheck}
            disabled={actionLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-amber-500/15 border border-amber-500/30 text-amber-300 hover:bg-amber-500/25 transition-colors disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            <span>Trigger Scheduler Alert Sweep</span>
          </button>

          <button
            onClick={handleWarmup}
            disabled={actionLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-blue-500/15 border border-blue-500/30 text-blue-300 hover:bg-blue-500/25 transition-colors disabled:opacity-50"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Warmup Pre-Release Predictions</span>
          </button>

          <button
            onClick={handleTestTelegram}
            disabled={actionLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-purple-500/15 border border-purple-500/30 text-purple-300 hover:bg-purple-500/25 transition-colors disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Send Test Telegram Alert</span>
          </button>
        </div>

        {actionMessage && (
          <div className="p-2.5 rounded bg-[#1a1c22] border border-[#262830] text-xs text-amber-300 font-mono">
            {actionMessage}
          </div>
        )}
      </div>

      {/* Status Overview Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Backend & Process */}
        <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
          <div className="flex items-center gap-2 text-xs font-bold text-zinc-300 uppercase tracking-wider">
            <Server className="w-4 h-4 text-emerald-400" />
            <span>Backend Runtime</span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Server Engine:</span>
              <span className="font-mono text-zinc-200">FastAPI (Uvicorn)</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Version:</span>
              <span className="font-mono text-zinc-200">{systemStatus?.backend?.version || '4.0.0'}</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Operating Mode:</span>
              <span className="font-mono text-amber-400 font-semibold">{systemStatus?.backend?.mode || 'USD & XAU/USD Only'}</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Server UTC Time:</span>
              <span className="font-mono text-zinc-300 text-[11px]">
                {formatTimestamp(systemStatus?.backend?.utc_time, useUtc, true)}
              </span>
            </div>
          </div>
        </div>

        {/* Database Health & Sizes */}
        <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
          <div className="flex items-center gap-2 text-xs font-bold text-zinc-300 uppercase tracking-wider">
            <Database className="w-4 h-4 text-blue-400" />
            <span>Database Storage</span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Engine / Storage:</span>
              <span className="font-mono text-zinc-200">{systemStatus?.database?.engine || 'SQLite 3'}</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Database Size:</span>
              <span className="font-mono text-zinc-200">{systemStatus?.database?.size_kb ?? 0} KB</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Gold Forecast Rows:</span>
              <span className="font-mono text-emerald-400 font-semibold">{systemStatus?.database?.gold_forecasts ?? 0}</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">USD Prediction Rows:</span>
              <span className="font-mono text-zinc-300">{systemStatus?.database?.usd_predictions ?? 0}</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Trained Release Moments:</span>
              <span className="font-mono text-purple-400 font-semibold">{systemStatus?.database?.gold_trained_moments ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Scheduler Status */}
        <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-3">
          <div className="flex items-center gap-2 text-xs font-bold text-zinc-300 uppercase tracking-wider">
            <Activity className="w-4 h-4 text-amber-400" />
            <span>Scheduler Engine</span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Background Engine:</span>
              <span className="font-mono text-zinc-200">APScheduler (Background)</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Execution Status:</span>
              <span className="text-emerald-400 font-semibold flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Running
              </span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Active Cadence:</span>
              <span className="font-mono text-zinc-300">1-Minute Tick</span>
            </div>
            <div className="flex justify-between p-2 rounded bg-[#1a1c22]">
              <span className="text-zinc-400">Post-Release Grace:</span>
              <span className="font-mono text-zinc-300">35 Minutes Threshold</span>
            </div>
          </div>
        </div>
      </div>

      {/* Scheduled Periodic Jobs */}
      <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-4">
        <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
          Configured Background Jobs & Last Execution Time
        </h3>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
              <tr>
                <th className="py-2.5 px-3">Job Identifier</th>
                <th className="py-2.5 px-3">Cadence</th>
                <th className="py-2.5 px-3">Functional Purpose</th>
                <th className="py-2.5 px-3">Last Recorded Execution</th>
                <th className="py-2.5 px-3 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#23252c]">
              {(systemStatus?.scheduler?.jobs || []).map((job, idx) => (
                <tr key={idx} className="hover:bg-[#1a1c22]">
                  <td className="py-3 px-3 font-mono font-bold text-zinc-200">{job.name}</td>
                  <td className="py-3 px-3 font-mono text-zinc-400">{job.cadence}</td>
                  <td className="py-3 px-3 text-zinc-300">{job.purpose}</td>
                  <td className="py-3 px-3 font-mono text-zinc-400">
                    {formatTimestamp(job.last_run, useUtc, true)}
                  </td>
                  <td className="py-3 px-3 text-right">
                    <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold">
                      ACTIVE
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Alerts Dispatch Log */}
      <div className="p-5 rounded-xl bg-[#15171c] border border-[#26282e] space-y-4">
        <h3 className="text-xs font-bold text-zinc-200 uppercase tracking-wider">
          Telegram Alerts Dispatch Ledger (AlertLog Table)
        </h3>

        {systemStatus?.recent_alerts && systemStatus.recent_alerts.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#121316] text-zinc-400 uppercase text-[10px] tracking-wider border-b border-[#26282e]">
                <tr>
                  <th className="py-2.5 px-3">Log ID</th>
                  <th className="py-2.5 px-3">Sent Timestamp</th>
                  <th className="py-2.5 px-3">Event Code</th>
                  <th className="py-2.5 px-3">Release Time</th>
                  <th className="py-2.5 px-3">Alert Type</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#23252c] font-mono text-[11px]">
                {systemStatus.recent_alerts.map((al) => (
                  <tr key={al.id} className="hover:bg-[#1a1c22]">
                    <td className="py-2.5 px-3 text-zinc-500">#{al.id}</td>
                    <td className="py-2.5 px-3 text-zinc-300">
                      {formatTimestamp(al.sent_at, useUtc, true)}
                    </td>
                    <td className="py-2.5 px-3 font-sans font-bold text-white">{al.event_code}</td>
                    <td className="py-2.5 px-3 text-zinc-400">{al.release_time || '—'}</td>
                    <td className="py-2.5 px-3">
                      <span className="px-2 py-0.5 rounded bg-[#252832] text-zinc-200 text-[10px]">
                        {al.alert_type}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-8 text-center text-xs text-zinc-500">
            No dispatch alerts recorded in database yet.
          </div>
        )}
      </div>
    </div>
  );
};
