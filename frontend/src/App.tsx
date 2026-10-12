import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import './App.css';
import { Sidebar } from './components/Sidebar';
import { SystemBar } from './components/SystemBar';
import { EventDetailModal } from './components/EventDetailModal';
import { OverviewPage } from './pages/OverviewPage';
import { CalendarPage } from './pages/CalendarPage';
import { GoldModelPage } from './pages/GoldModelPage';
import { InsightsPage } from './pages/InsightsPage';
import { HistoryPage } from './pages/HistoryPage';
import { SourcesPage } from './pages/SourcesPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { SystemPage } from './pages/SystemPage';
import type {
  PageId,
  CalEvent,
  GoldForecastItem,
  GoldModelStatus,
  SystemStatusData,
  ModelActivityItem,
} from './types';

export default function App() {
  const [activePage, setActivePage] = useState<PageId>('overview');
  const [useUtc, setUseUtc] = useState<boolean>(true);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState<boolean>(false);
  const [detailModalReleaseId, setDetailModalReleaseId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // App-wide data caches
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [recentForecasts, setRecentForecasts] = useState<GoldForecastItem[]>([]);
  const [latestForecast, setLatestForecast] = useState<GoldForecastItem | null>(null);
  const [modelStatus, setModelStatus] = useState<GoldModelStatus | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatusData | null>(null);
  const [activityList, setActivityList] = useState<ModelActivityItem[]>([]);

  // Page titles and descriptions
  const pageMeta: Record<PageId, { title: string; subtitle: string }> = {
    overview: {
      title: 'MacroPredictor Overview',
      subtitle: 'USD Macroeconomic Releases & Probabilistic 5-Minute Gold Reaction Monitor',
    },
    calendar: {
      title: 'USD Economic Calendar',
      subtitle: 'Consensus Expectations, Live Releases & USD Macro Directional Leans',
    },
    gold_model: {
      title: 'Gold Reaction Model (XAU/USD)',
      subtitle: 'Online Adaptive Random Forest: Inputs, Evidence & Learning Progress',
    },
    insights: {
      title: 'Model Insights & Historical Evidence',
      subtitle: 'Empirical Findings Grouped by USD Event Family and Surprise Category',
    },
    history: {
      title: 'Forecast & Reaction History',
      subtitle: 'Searchable Audit Log with Immutable Feature Snapshots & Evaluated Outcomes',
    },
    sources: {
      title: 'Data Feeds & Provider Ingestion',
      subtitle: 'Live Ingestion Health: Twelve Data, Forex Factory, FRED, COT, and Sentiment',
    },
    evaluation: {
      title: 'Model Evaluation & Statistical Calibration',
      subtitle: 'Chronological Walk-Forward Multi-Class Brier Scores & Directional Accuracies',
    },
    system: {
      title: 'System Health & Dispatch Logs',
      subtitle: 'APScheduler Cadence, SQLite Storage Metrics & Telegram Alert Audits',
    },
  };

  const loadData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [
        eventsRes,
        forecastsRes,
        modelStatusRes,
        systemStatusRes,
        activityRes,
      ] = await Promise.allSettled([
        axios.get('/api/events'),
        axios.get('/api/gold/forecasts?limit=25'),
        axios.get('/api/gold/model-status'),
        axios.get('/api/system/status'),
        axios.get('/api/gold/activity?limit=30'),
      ]);

      if (eventsRes.status === 'fulfilled') {
        const evList = eventsRes.value.data.events || [];
        setEvents(evList);
      }

      if (forecastsRes.status === 'fulfilled') {
        const fList = forecastsRes.value.data.forecasts || [];
        setRecentForecasts(fList);
        if (fList.length > 0) {
          setLatestForecast(fList[0]);
        }
      }

      if (modelStatusRes.status === 'fulfilled') {
        setModelStatus(modelStatusRes.value.data);
      }

      if (systemStatusRes.status === 'fulfilled') {
        setSystemStatus(systemStatusRes.value.data);
      }

      if (activityRes.status === 'fulfilled') {
        setActivityList(activityRes.value.data.activity || []);
      }
    } catch (err) {
      console.error('Failed to load system data:', err);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  // Initial load and periodic polling (every 45s)
  useEffect(() => {
    loadData();
    // Warmup predictions for pending high impact releases in background
    axios.post('/api/predictions/warmup').catch(() => {});

    const interval = setInterval(loadData, 45000);
    return () => clearInterval(interval);
  }, [loadData]);

  const currentMeta = pageMeta[activePage];

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0d0e11] text-zinc-100 font-sans">
      {/* Persistent Sidebar */}
      <Sidebar
        activePage={activePage}
        onSelectPage={(page) => setActivePage(page)}
        isOpenMobile={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 lg:pl-64 overflow-hidden">
        {/* Global System Bar */}
        <SystemBar
          title={currentMeta.title}
          subtitle={currentMeta.subtitle}
          onOpenMobileSidebar={() => setMobileSidebarOpen(true)}
          onRefresh={loadData}
          isRefreshing={isRefreshing}
          useUtc={useUtc}
          onToggleTimezone={() => setUseUtc(!useUtc)}
          systemStatus={systemStatus}
        />

        {/* Page Container */}
        <main className="flex-1 overflow-y-auto px-4 lg:px-8 py-6">
          <div className="max-w-7xl mx-auto">
            {activePage === 'overview' && (
              <OverviewPage
                onNavigate={(page) => setActivePage(page)}
                onOpenEventDetail={(id) => setDetailModalReleaseId(id)}
                useUtc={useUtc}
                latestForecast={latestForecast}
                upcomingEvents={events}
                recentForecasts={recentForecasts}
                modelStatus={modelStatus}
                systemStatus={systemStatus}
                recentActivity={activityList}
              />
            )}

            {activePage === 'calendar' && (
              <CalendarPage
                events={events}
                onRefresh={loadData}
                isRefreshing={isRefreshing}
                onOpenEventDetail={(id) => setDetailModalReleaseId(id)}
                useUtc={useUtc}
              />
            )}

            {activePage === 'gold_model' && (
              <GoldModelPage
                latestForecast={latestForecast}
                recentForecasts={recentForecasts}
                modelStatus={modelStatus}
                activityList={activityList}
                onOpenEventDetail={(id) => setDetailModalReleaseId(id)}
                useUtc={useUtc}
              />
            )}

            {activePage === 'insights' && (
              <InsightsPage useUtc={useUtc} />
            )}

            {activePage === 'history' && (
              <HistoryPage
                onOpenEventDetail={(id) => setDetailModalReleaseId(id)}
                useUtc={useUtc}
              />
            )}

            {activePage === 'sources' && (
              <SourcesPage useUtc={useUtc} />
            )}

            {activePage === 'evaluation' && (
              <EvaluationPage useUtc={useUtc} />
            )}

            {activePage === 'system' && (
              <SystemPage
                systemStatus={systemStatus}
                onRefresh={loadData}
                isRefreshing={isRefreshing}
                useUtc={useUtc}
              />
            )}
          </div>
        </main>
      </div>

      {/* Complete Event Detail Modal */}
      {detailModalReleaseId && (
        <EventDetailModal
          releaseId={detailModalReleaseId}
          onClose={() => setDetailModalReleaseId(null)}
          useUtc={useUtc}
        />
      )}
    </div>
  );
}
