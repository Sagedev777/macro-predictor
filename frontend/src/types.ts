// frontend/src/types.ts

export type PageId =
  | 'overview'
  | 'calendar'
  | 'gold_model'
  | 'insights'
  | 'history'
  | 'sources'
  | 'evaluation'
  | 'system';

export interface GoldFeatureInput {
  value: number | null;
  source: string;
  observed_at: string | null;
  published_at?: string | null;
  captured_at: string;
  available_at?: string | null;
  staleness_status?: string;
  revision_status?: string;
  status: string;
}

export interface GoldForecastItem {
  id?: number;
  release_moment_id?: string;
  release_time_utc: string;
  forecast_cutoff_utc?: string | null;
  status?: string;
  forecast_status?: string;
  confidence_status?: string;
  direction?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null;
  forecast_direction?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null;
  probabilities?: { bullish: number; bearish: number; neutral: number } | null;
  p_bullish?: number | null;
  p_bearish?: number | null;
  p_neutral?: number | null;
  event_family: string;
  event_codes?: string[];
  event_names?: string[];
  features?: Record<string, GoldFeatureInput>;
  model_features?: Record<string, number | null>;
  model_version?: string;
  horizon_minutes?: number;
  threshold_pct?: number | null;
  outcome_threshold_pct?: number | null;
  outcome_label?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null;
  outcome_status?: string;
  outcome_recorded_at?: string | null;
  actual_outcome?: {
    recorded_at?: string | null;
    status: string;
    horizon_minutes: number;
    price_at_release?: number | null;
    change_1m_pct?: number | null;
    change_5m_pct?: number | null;
    change_15m_pct?: number | null;
    change_30m_pct?: number | null;
    max_up_5m_pct?: number | null;
    max_down_5m_pct?: number | null;
    max_favorable_5m_pct?: number | null;
    max_adverse_5m_pct?: number | null;
    outcome_label?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null;
    threshold_pct?: number | null;
    data_quality?: Record<string, any>;
    raw_releases?: any[];
  } | null;
  gold_change_1m_pct?: number | null;
  gold_change_5m_pct?: number | null;
  gold_change_15m_pct?: number | null;
  gold_change_30m_pct?: number | null;
  max_up_5m_pct?: number | null;
  max_down_5m_pct?: number | null;
  max_favorable_5m_pct?: number | null;
  max_adverse_5m_pct?: number | null;
  n_trained?: number;
  training_ledger?: {
    is_trained: boolean;
    claimed_at: string | null;
    trained_at: string | null;
  };
  linked_usd_predictions?: Array<{
    id: number;
    event_code: string;
    event_display_name: string;
    lean_direction: string;
    forecast: number | null;
    previous: number | null;
    actual: number | null;
    surprise: number | null;
    was_correct: boolean | null;
    result_15m: string | null;
    usd_move_15m: number | null;
    confidence_pct: number;
  }>;
}

export interface CalEvent {
  event_code: string | null;
  event_name: string;
  display_name?: string;
  currency: string;
  release_time_utc: string;
  forecast: number | null;
  previous: number | null;
  actual: number | null;
  impact: 'HIGH' | 'MEDIUM' | 'LOW';
  is_simultaneous: boolean;
  prediction?: {
    lean_direction: string;
    event_label: string;
    confidence_pct: number;
    composite_score: number;
    explanation?: string;
    indicators?: Array<{ name: string; score: number; detail?: string }>;
  } | null;
  gold_forecast?: GoldForecastItem | null;
}

export interface ModelInsightsData {
  has_sufficient_data: boolean;
  sample_size: number;
  message?: string;
  disclaimer?: string;
  date_range?: {
    from: string;
    to: string;
  };
  return_distribution?: {
    min: number;
    p25: number;
    median: number;
    p75: number;
    max: number;
  };
  direction_frequencies?: {
    counts: { BULLISH: number; BEARISH: number; NEUTRAL: number };
    percentages: { BULLISH: number; BEARISH: number; NEUTRAL: number };
  };
  by_family?: Record<
    string,
    {
      count: number;
      median_return_5m_pct: number;
      avg_abs_move_pct: number;
      bullish_count: number;
      bearish_count: number;
      neutral_count: number;
    }
  >;
  by_surprise?: Record<
    string,
    {
      count: number;
      median_return_pct: number | null;
      avg_abs_move_pct: number | null;
    }
  >;
}

export interface ModelEvaluationData {
  n_evaluated: number;
  overall: {
    n: number;
    brier_score: number | null;
    accuracy_pct: number | null;
    majority_class_accuracy_pct?: number | null;
    log_loss?: number | null;
  };
  by_event_family: Record<
    string,
    {
      n: number;
      brier_score: number | null;
      accuracy_pct: number | null;
    }
  >;
  note: string;
}

export interface SourceItem {
  name: string;
  type: string;
  status: string;
  last_fetch: string | null;
  coverage: string;
  publication_time?: string;
  latency: string;
  is_integrated: boolean;
  model_usage: string;
}

export interface SystemStatusData {
  backend: {
    version: string;
    mode: string;
    uptime: string;
    utc_time: string;
  };
  database: {
    engine: string;
    file_path: string;
    size_kb: number;
    gold_forecasts: number;
    usd_predictions: number;
    gold_trained_moments: number;
  };
  scheduler: {
    is_running: boolean;
    jobs: Array<{
      name: string;
      cadence: string;
      purpose: string;
      last_run: string | null;
    }>;
  };
  recent_alerts: Array<{
    id: number;
    sent_at: string | null;
    event_code: string;
    release_time: string | null;
    alert_type: string;
  }>;
}

export interface ModelActivityItem {
  timestamp: string | null;
  type: 'forecast_created' | 'outcome_graded' | 'model_trained' | 'alert_sent';
  title: string;
  description: string;
  moment_id?: string;
  status?: string;
}

export interface GoldModelStatus {
  model_version: string;
  total_graded_gold_outcomes: number;
  unique_training_observations: number;
  eligible_observations: number;
  status: string;
  last_trained_utc: string | null;
  pending_outcomes_count?: number;
  completed_outcomes_count?: number;
  unavailable_outcomes_count?: number;
}
