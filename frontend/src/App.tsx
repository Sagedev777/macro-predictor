import './App.css'
import axios from 'axios'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const API = '/api'
const LS_CCY   = 'mp_ccy_filter'
const LS_PAIRS = 'mp_pair_filter'

// ── Types ─────────────────────────────────────────────────────────────────────
interface CalEvent {
  event_code: string | null
  event_name: string
  currency: string
  release_time_utc: string
  forecast: number | null
  previous: number | null
  actual: number | null
  impact: 'HIGH' | 'MEDIUM'
  display_name?: string
  is_simultaneous: boolean
  prediction?: PredSummary | null
}
interface PredSummary {
  lean_direction: string
  event_label: string
  confidence_pct: number
  composite_score: number
  pair_signals: PairSignal[]
  order_suggestions: OrderSug[]
  indicators: Indicator[]
}
interface PairSignal { pair: string; direction: string; bias: number; confidence_pct: number }
interface OrderSug {
  pair: string; bias: string; current_price: number | null; atr_14: number | null
  suggested_entry: number | null; suggested_sl: number | null; suggested_tp: number | null
  confidence_pct: number
}
interface Indicator { description: string; z_score: number | null; signal: number; weight: number }

interface StoredPred {
  id: number; event_code: string; display_name: string; currency: string
  lean_direction: string; event_label: string; confidence_pct: number; composite_score: number
  pair_signals: PairSignal[]; order_suggestions: OrderSug[]; indicators: Indicator[]
  trade_signals: string[]
  created_at: string; was_correct: boolean | null; forecast: number | null; actual: number | null
}

interface CcyStrength {
  currency: string; strength_score: number; confidence_pct: number; n_trained: number
  indicator_score: number | null; rate_diff_score: number | null
  cot_score: number | null; sentiment_score: number | null; recorded_at: string | null
}
interface PairBias {
  pair: string; bias: number; direction: string; confidence_pct: number
  base_strength: number; quote_strength: number
}
interface ModelStatus {
  currency: string; n_trained: number; n_real: number
  live_accuracy: number | null; feature_weights: Record<string, number>
  last_updated: string | null; status: 'learning' | 'seeded_only' | 'untrained'
}
interface AccTrendWindow {
  window_start: number; window_end: number; predictions: number
  wins: number; hit_rate_pct: number; date_from: string | null; date_to: string | null
}
interface AccTrendCcy {
  currency: string; total_graded: number; windows: AccTrendWindow[]; improving: boolean
}

interface HistItem {
  id: number; event_code: string; display_name: string; currency: string
  lean_direction: string; confidence_pct: number; forecast: number | null
  actual: number | null; surprise: number | null; was_correct: boolean; date: string | null
}
interface AccStats {
  total_predictions: number; wins: number; losses: number; overall_hit_rate: number
  confidence_stats: { bucket: string; total: number; wins: number; hit_rate_pct: number }[]
}

type Tab = 'calendar' | 'signals' | 'strength' | 'results'

// ── Statics ───────────────────────────────────────────────────────────────────
const FLAG: Record<string,string> = {
  USD:'🇺🇸',EUR:'🇪🇺',GBP:'🇬🇧',JPY:'🇯🇵',AUD:'🇦🇺',CHF:'🇨🇭',CAD:'🇨🇦',NZD:'🇳🇿',
}
const ALL_CCYS  = ['USD','EUR','GBP','JPY','AUD','CHF','CAD','NZD']
const ALL_PAIRS = [
  // USD majors
  'EURUSD','GBPUSD','USDJPY','USDCHF','AUDUSD','USDCAD','NZDUSD','XAUUSD',
  // EUR crosses
  'EURGBP','EURJPY','EURCHF','EURAUD','EURCAD','EURNZD',
  // GBP crosses
  'GBPJPY','GBPCHF','GBPAUD','GBPCAD','GBPNZD',
  // JPY crosses
  'AUDJPY','CADJPY','CHFJPY','NZDJPY',
  // AUD crosses
  'AUDCAD','AUDCHF','AUDNZD',
  // CAD crosses
  'CADCHF','NZDCAD',
  // CHF/NZD
  'NZDCHF',
]
const FW_LABELS: Record<string,string> = {
  indicator_score:'Indicator',rate_diff_score:'Rate Diff',cot_score:'COT',sentiment_score:'Sentiment'
}
const FW_COLS = ['#6366f1','#06b6d4','#f59e0b','#10b981']

// ── Helpers ───────────────────────────────────────────────────────────────────
function ls<T>(key:string, fb:T): T {
  try { const v=localStorage.getItem(key); return v?JSON.parse(v):fb } catch { return fb }
}
function saveLs(key:string, val:unknown) { try { localStorage.setItem(key,JSON.stringify(val)) } catch {} }

function cd(iso:string, now:number): string {
  const ms = new Date(iso).getTime()-now
  if (ms<=0) return 'Released'
  const s=Math.floor(ms/1000),h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sc=s%60
  if (h>48) return `${Math.floor(h/24)}d ${h%24}h`
  if (h>0)  return `${h}h ${m}m`
  if (m>0)  return `${m}m ${sc}s`
  return `${sc}s`
}
function utcT(iso:string) {
  try { return new Date(iso).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC' }
  catch { return iso }
}
function fmtD(iso:string) {
  try { return new Date(iso).toLocaleDateString('en-GB',{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}) }
  catch { return '' }
}
function fN(n:number|null,dp=3){ return n==null?'—':n.toFixed(dp) }
function dc(d:string): 'bull'|'bear'|'flat' {
  const u=d?.toUpperCase()
  if(u==='BEAT'||u==='BULLISH'||u==='BUY') return 'bull'
  if(u==='MISS'||u==='BEARISH'||u==='SELL') return 'bear'
  return 'flat'
}
function dl(d:string) {
  const u=d?.toUpperCase()
  if(u==='BEAT'||u==='BULLISH') return 'BULLISH'
  if(u==='MISS'||u==='BEARISH') return 'BEARISH'
  return 'INLINE'
}

// ── Micro-components ──────────────────────────────────────────────────────────
function Bar({pct,cls}:{pct:number;cls?:string}) {
  const a=pct>=70?'bar-bull':pct>=55?'bar-amb':'bar-flat'
  return <div className="bar-t"><div className={`bar-f ${cls??a}`} style={{width:`${Math.min(pct,100)}%`}}/></div>
}
function Dot({impact}:{impact:string}) {
  return <span className={`dot ${impact==='HIGH'?'dot-h':'dot-m'}`}/>
}
function DTag({d}:{d:string}) {
  return <span className={`tag tag-${dc(d)}`}>{dl(d)}</span>
}
// ── Filter chip rows ──────────────────────────────────────────────────────────
function CcyFilter({sel,toggle}:{sel:string[];toggle:(c:string)=>void}) {
  const allOn = sel.length===ALL_CCYS.length
  return (
    <div className="filter-row">
      <button className={`fchip${allOn?' fchip-on':''}`}
        onClick={()=>allOn?ALL_CCYS.forEach(c=>sel.includes(c)&&toggle(c)):ALL_CCYS.forEach(c=>!sel.includes(c)&&toggle(c))}>
        All
      </button>
      {ALL_CCYS.map(c=>(
        <button key={c} className={`fchip${sel.includes(c)?' fchip-on':''}`} onClick={()=>toggle(c)}>
          {FLAG[c]} {c}
        </button>
      ))}
    </div>
  )
}
function PairFilter({sel,toggle}:{sel:string[];toggle:(p:string)=>void}) {
  const allOn = sel.length===ALL_PAIRS.length
  return (
    <div className="filter-row">
      <button className={`fchip fchip-sm${allOn?' fchip-on':''}`}
        onClick={()=>allOn?ALL_PAIRS.forEach(p=>sel.includes(p)&&toggle(p)):ALL_PAIRS.forEach(p=>!sel.includes(p)&&toggle(p))}>
        All
      </button>
      {ALL_PAIRS.map(p=>(
        <button key={p} className={`fchip fchip-sm${sel.includes(p)?' fchip-on':''}`} onClick={()=>toggle(p)}>
          {p}
        </button>
      ))}
    </div>
  )
}

// ── Next-event banner ─────────────────────────────────────────────────────────
function Banner({events,now}:{events:CalEvent[];now:number}) {
  const sorted = [...events]
    .filter(e=>e.release_time_utc)
    .sort((a,b)=>new Date(a.release_time_utc).getTime()-new Date(b.release_time_utc).getTime())
  const next = sorted.find(e=>e.actual==null)??sorted[sorted.length-1]
  if(!next) return null
  const ms=new Date(next.release_time_utc).getTime()-now
  const released=ms<=0, imminent=!released&&ms<3600000
  return (
    <div className={`banner${imminent?' b-hot':released?' b-past':''}`}>
      <div className="b-l">
        <Dot impact={next.impact}/>
        <span className="b-flag">{FLAG[next.currency]??''}</span>
        <span className="b-name">{next.display_name??next.event_name}</span>
        {next.forecast!=null&&<span className="b-fc">Forecast {fN(next.forecast,1)}</span>}
        {next.prediction&&<DTag d={next.prediction.lean_direction}/>}
      </div>
      <div className="b-r">
        <span className="b-time">{utcT(next.release_time_utc)}</span>
        <span className={`b-cd${imminent?' b-cd-hot':released?' b-cd-past':''}`}>
          {cd(next.release_time_utc,now)}
        </span>
      </div>
    </div>
  )
}

// ── Calendar card ─────────────────────────────────────────────────────────────
function CalCard({ev,now,onPredict}:{ev:CalEvent;now:number;onPredict:(c:string)=>void}) {
  const [open,setOpen]=useState(false)
  const pred=ev.prediction, done=ev.actual!=null
  const hasPairs=(pred?.pair_signals?.length??0)>0
  const hasOrders=(pred?.order_suggestions?.filter(s=>s.suggested_entry).length??0)>0
  return (
    <div className={`cc${done?' cc-done':''}`}>
      <div className="cc-top">
        <div className="cc-tl">
          <Dot impact={ev.impact}/>
          <span className="cc-flag">{FLAG[ev.currency]??''}</span>
          <span className="cc-ccy">{ev.currency}</span>
          <span className="cc-name">{ev.display_name??ev.event_name}</span>
        </div>
        <div className="cc-tr">
          <span className="cc-time">{utcT(ev.release_time_utc)}</span>
          {!done&&<span className="cc-cd">{cd(ev.release_time_utc,now)}</span>}
          {done&&<span className="cc-rel">Released</span>}
        </div>
      </div>
      <div className="cc-data">
        {(['Forecast','Previous','Actual'] as const).map((lbl,i)=>{
          const val=[ev.forecast,ev.previous,ev.actual][i]
          return (
            <div key={lbl} className="cc-cell">
              <span className="cc-lbl">{lbl}</span>
              <span className={`cc-val${lbl==='Actual'&&val!=null?' cc-act':''}`}>
                {val!=null?String(val):'—'}
              </span>
            </div>
          )
        })}
      </div>
      {pred?(
        <div className={`pred-row pred-${dc(pred.lean_direction)}${hasPairs||hasOrders?' pred-click':''}`}
          onClick={()=>(hasPairs||hasOrders)&&setOpen(v=>!v)}>
          <span className="pred-lbl">{pred.event_label}</span>
          <div className="pred-bar"><Bar pct={pred.confidence_pct} cls={`bar-${dc(pred.lean_direction)}`}/></div>
          <span className="pred-pct">{pred.confidence_pct.toFixed(0)}%</span>
          {(hasPairs||hasOrders)&&<span className="pred-tog">{open?'▲':'▼'}</span>}
        </div>
      ):ev.event_code&&(
        <button className="run-btn" onClick={()=>onPredict(ev.event_code!)}>Run prediction</button>
      )}
      {open&&pred&&(
        <div className="pred-detail">
          {hasPairs&&(
            <div className="chip-row">
              {pred.pair_signals.slice(0,8).map(ps=>(
                <span key={ps.pair} className={`chip chip-${dc(ps.direction)}`}>
                  {ps.pair} <b>{ps.direction}</b> <em>{ps.confidence_pct.toFixed(0)}%</em>
                </span>
              ))}
            </div>
          )}
          {hasOrders&&pred.order_suggestions.filter(s=>s.suggested_entry).slice(0,2).map(s=>(
            <div key={s.pair} className="ord-row">
              <span className={`ord-p ord-${dc(s.bias)}`}>{s.pair} {s.bias}</span>
              <span className="ord-v">Entry <b>{fN(s.suggested_entry,5)}</b></span>
              <span className="ord-v">SL <span className="ord-sl">{fN(s.suggested_sl,5)}</span></span>
              <span className="ord-v">TP <span className="ord-tp">{fN(s.suggested_tp,5)}</span></span>
              <span className="ord-ref">reference only</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Signal card ───────────────────────────────────────────────────────────────
function SigCard({pred,onRefresh}:{pred:StoredPred;onRefresh:(c:string)=>void}) {
  const [open,setOpen]=useState(false)
  const hasPairs=(pred.pair_signals?.length??0)>0
  const hasOrders=pred.order_suggestions?.some(s=>s.suggested_entry)
  const hasIndicators=(pred.indicators?.length??0)>0

  // Build "Affected majors" line from trade_signals
  const affectedMajors = (pred.trade_signals ?? [])
    .filter(s => s && !s.toUpperCase().startsWith('WAIT'))
    .map(s => {
      const parts = s.trim().split(' ')
      const dir = parts[0] ?? ''
      const sym = parts[1] ?? ''
      // Insert slash for 6-char forex pairs (e.g. USDJPY → USD/JPY, XAUUSD → XAU/USD)
      const fmtSym = sym.length === 6 ? `${sym.slice(0,3)}/${sym.slice(3)}` : sym
      return `${dir} ${fmtSym}`
    })
    .join(' • ')

  // Outcome badge
  const outcomeBadge = pred.was_correct === true
    ? <span className="sc-outcome sc-outcome-ok">✓ Correct</span>
    : pred.was_correct === false
      ? <span className="sc-outcome sc-outcome-err">✗ Incorrect</span>
      : null

  const hasDetails = hasPairs || hasOrders || hasIndicators

  return (
    <div className={`sc sc-${dc(pred.lean_direction)}`}>
      <div className="sc-head">
        <div>
          <div className="sc-meta">
            <span>{FLAG[pred.currency]??''}</span>
            <span className="sc-ccy">{pred.currency}</span>
            <span className="sc-t">{new Date(pred.created_at).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}</span>
          </div>
          <div className="sc-name">{pred.display_name}</div>
        </div>
        <DTag d={pred.lean_direction}/>
      </div>
      <div className="sc-conf">
        <span className="sc-pct">{pred.confidence_pct.toFixed(1)}%</span>
        <div className="sc-bar"><Bar pct={pred.confidence_pct} cls={`bar-${dc(pred.lean_direction)}`}/></div>
      </div>
      {affectedMajors && (
        <div className="sc-majors">
          <span className="sc-majors-lbl">Affected majors:</span>
          <span className="sc-majors-val">{affectedMajors}</span>
        </div>
      )}
      {outcomeBadge}
      <div className="sc-actions">
        {hasDetails&&(
          <button className="ind-btn" onClick={()=>setOpen(v=>!v)}>
            {open?'Details ▲':'Details ▼'}
          </button>
        )}
        <button className="sc-ref" onClick={()=>onRefresh(pred.event_code)}>Refresh</button>
      </div>
      {open&&(
        <div className="sc-detail">
          {hasPairs&&(
            <div className="chip-row">
              {pred.pair_signals.map(ps=>(
                <span key={ps.pair} className={`chip chip-${dc(ps.direction)}`}>
                  {ps.pair} <b>{ps.direction}</b> <em>{ps.confidence_pct.toFixed(0)}%</em>
                </span>
              ))}
            </div>
          )}
          {hasOrders&&pred.order_suggestions.filter(s=>s.suggested_entry&&s.bias!=='NEUTRAL').slice(0,2).map(s=>(
            <div key={s.pair} className="ord-row">
              <span className={`ord-p ord-${dc(s.bias)}`}>{s.pair} {s.bias}</span>
              <span className="ord-v">Entry <b>{fN(s.suggested_entry,5)}</b></span>
              <span className="ord-v">SL <span className="ord-sl">{fN(s.suggested_sl,5)}</span></span>
              <span className="ord-v">TP <span className="ord-tp">{fN(s.suggested_tp,5)}</span></span>
              <span className="ord-ref">reference only</span>
            </div>
          ))}
          {hasIndicators&&(
            <div className="ind-list">
              {pred.indicators.map((ind,i)=>(
                <div key={i} className="ind-row">
                  <span className={`ind-dot ind-${ind.signal>0?'bull':ind.signal<0?'bear':'flat'}`}>
                    {ind.signal>0?'▲':ind.signal<0?'▼':'●'}
                  </span>
                  <span className="ind-desc">{ind.description}</span>
                  <span className="ind-z">{ind.z_score!=null?ind.z_score.toFixed(2):'—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Currency meter ────────────────────────────────────────────────────────────
function Meter({cs,ccy}:{cs:CcyStrength|null;ccy:string}) {
  const score=cs?.strength_score??null
  const pct=score!=null?Math.abs(score)*100:0
  const bull=(score??0)>=0
  const noData=score==null||(score===0&&(cs?.n_trained??0)===0)
  return (
    <div className={`meter${noData?' meter-empty':''}`}>
      <div className="m-head">
        <span className="m-flag">{FLAG[ccy]??''}</span>
        <span className="m-ccy">{ccy}</span>
        <span className={`m-score${noData?' m-none':` m-${dc(score!=null&&score>0.05?'BULLISH':score!=null&&score<-0.05?'BEARISH':'INLINE')}`}`}>
          {noData?'—':`${(score??0)>=0?'+':''}${((score??0)*100).toFixed(1)}`}
        </span>
      </div>
      <div className="m-track">
        <div className="m-ctr"/>
        {!noData&&<div className={`m-fill ${bull?'m-bull':'m-bear'}`} style={{width:`${pct/2}%`,left:bull?'50%':`${50-pct/2}%`}}/>}
      </div>
      <div className="m-foot">
        <span>{cs?`n=${cs.n_trained}`:'No data'}</span>
        {cs?.recorded_at&&<span>{new Date(cs.recorded_at).toLocaleDateString('en-GB',{month:'short',day:'numeric'})}</span>}
      </div>
    </div>
  )
}

// ── Pair bias row ─────────────────────────────────────────────────────────────
function PairRow({pb}:{pb:PairBias}) {
  const d=dc(pb.direction)
  return (
    <div className={`pair-row pair-${d}`}>
      <span className="pr-pair">{pb.pair}</span>
      <span className={`pr-dir pr-${d}`}>{pb.direction}</span>
      <span className={`pr-bias ${pb.bias>0?'pr-pos':pb.bias<0?'pr-neg':''}`}>
        {pb.bias>0?'+':''}{(pb.bias*100).toFixed(1)}
      </span>
      <div className="pr-bar"><Bar pct={pb.confidence_pct} cls={`bar-${d}`}/></div>
      <span className="pr-conf">{pb.confidence_pct.toFixed(0)}%</span>
    </div>
  )
}

// ── Model learning panel ──────────────────────────────────────────────────────
function ModelPanel({models,trend}:{models:ModelStatus[];trend:AccTrendCcy[]}) {
  const fwKeys = ['indicator_score','rate_diff_score','cot_score','sentiment_score']

  return (
    <div className="model-panel">
      <div className="mp-title">Model learning status</div>
      <div className="mp-grid">
        {models.map(m=>{
          const trendRow = trend.find(t=>t.currency===m.currency)
          const lastW = trendRow?.windows.slice(-1)[0]
          return (
            <div key={m.currency} className={`mp-card mp-${m.status}`}>
              <div className="mp-head">
                <span>{FLAG[m.currency]??''}</span>
                <span className="mp-ccy">{m.currency}</span>
                <span className={`mp-status mp-s-${m.status}`}>
                  {m.status==='learning'?'Learning':m.status==='seeded_only'?'Seeded':'Untrained'}
                </span>
              </div>
              <div className="mp-stats">
                <span className="mp-n">n={m.n_trained}</span>
                {m.n_real>0&&<span className="mp-real">+{m.n_real} real</span>}
                {m.live_accuracy!=null&&(
                  <span className="mp-acc">{(m.live_accuracy*100).toFixed(1)}% acc</span>
                )}
                {lastW&&<span className="mp-last">Last 10: {lastW.hit_rate_pct.toFixed(0)}%</span>}
                {trendRow?.improving&&<span className="mp-up">↑ improving</span>}
              </div>
              {/* Feature weight bar */}
              {Object.keys(m.feature_weights).length>0&&(
                <div className="mp-fw" title={fwKeys.map(k=>`${FW_LABELS[k]}: ${((m.feature_weights[k]??0)*100).toFixed(0)}%`).join(' | ')}>
                  {fwKeys.map((k,i)=>(
                    <div key={k} className="mp-fw-seg" style={{
                      width:`${((m.feature_weights[k]??0)*100).toFixed(1)}%`,
                      background:FW_COLS[i],
                    }}/>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
      {/* Legend */}
      <div className="mp-legend">
        {fwKeys.map((k,i)=>(
          <span key={k} className="mp-leg-item">
            <span className="mp-leg-dot" style={{background:FW_COLS[i]}}/>
            {FW_LABELS[k]}
          </span>
        ))}
        <span className="mp-leg-note">
          n=10 = seed only · n&gt;10 = real learn_one() calls fired
        </span>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// APP
// ══════════════════════════════════════════════════════════════════════════════
export default function App() {
  // ── Clock: ticks every second for live countdown ─────────────────────────
  const [now,setNow] = useState(Date.now())
  useEffect(()=>{ const id=setInterval(()=>setNow(Date.now()),1000); return()=>clearInterval(id) },[])

  const [tab,setTab]     = useState<Tab>('calendar')
  const [busy,setBusy]   = useState(false)
  const [toast,setToast] = useState<string|null>(null)

  // ── One-shot startup flags ────────────────────────────────────────────────
  const warmupDone   = useRef(false)
  const strengthDone = useRef(false)

  // ── Data ──────────────────────────────────────────────────────────────────
  const [calEvents,  setCal]  = useState<CalEvent[]>([])
  const [strengths,  setStr]  = useState<CcyStrength[]>([])
  const [pairBiases, setPB]   = useState<PairBias[]>([])
  const [preds,      setPred] = useState<StoredPred[]>([])
  const [history,    setHist] = useState<HistItem[]>([])
  const [accuracy,   setAcc]  = useState<AccStats|null>(null)
  const [models,     setModels]= useState<ModelStatus[]>([])
  const [trend,      setTrend]= useState<AccTrendCcy[]>([])

  // ── Filters — persisted ───────────────────────────────────────────────────
  const [ccySel,  setCcySel]  = useState<string[]>(()=>ls(LS_CCY,  ALL_CCYS))
  const [pairSel, setPairSel] = useState<string[]>(()=>ls(LS_PAIRS,ALL_PAIRS))

  const toggleCcy = (c:string) => setCcySel(prev=>{
    const next=prev.includes(c)?prev.filter(x=>x!==c):[...prev,c]
    saveLs(LS_CCY,next); return next
  })
  const togglePair = (p:string) => setPairSel(prev=>{
    const next=prev.includes(p)?prev.filter(x=>x!==p):[...prev,p]
    saveLs(LS_PAIRS,next); return next
  })

  const flash = (msg:string)=>{ setToast(msg); setTimeout(()=>setToast(null),3500) }

  // ── Fetchers ──────────────────────────────────────────────────────────────
  const loadCal = useCallback(async(force=false)=>{
    setBusy(true)
    try { const r=await axios.get(`${API}/events${force?'?force_refresh=true':''}`); setCal(r.data.events??[]) }
    catch(e:any){ flash(`Calendar: ${e.message}`) }
    finally{ setBusy(false) }
  },[])

  const loadStr = useCallback(async()=>{
    setBusy(true)
    try {
      const [sr,pbr]=await Promise.all([axios.get(`${API}/currency-strengths`),axios.get(`${API}/pair-biases`)])
      setStr(sr.data.currency_strengths??[])
      setPB(pbr.data.pair_biases??[])
    } catch(e:any){ flash(`Strength: ${e.message}`) }
    finally{ setBusy(false) }
  },[])

  const loadSig = useCallback(async()=>{
    setBusy(true)
    try { const r=await axios.get(`${API}/predictions?limit=40`); setPred(r.data.predictions??[]) }
    catch(e:any){ flash(`Signals: ${e.message}`) }
    finally{ setBusy(false) }
  },[])

  const loadRes = useCallback(async()=>{
    setBusy(true)
    try {
      const [h,a]=await Promise.all([axios.get(`${API}/history?limit=60`),axios.get(`${API}/accuracy`)])
      setHist(h.data.history??[]); setAcc(a.data)
    } catch(e:any){ flash(`Results: ${e.message}`) }
    finally{ setBusy(false) }
  },[])

  const loadModels = useCallback(async()=>{
    try {
      const [ms,at]=await Promise.all([axios.get(`${API}/model-status`),axios.get(`${API}/accuracy-trend`)])
      setModels(ms.data.currencies??[])
      setTrend(at.data.trend??[])
    } catch{ /* non-fatal */ }
  },[])

  // Load on tab switch
  useEffect(()=>{
    if(tab==='calendar') loadCal()
    if(tab==='strength'){ loadStr(); loadModels() }
    if(tab==='signals')  loadSig()
    if(tab==='results')  loadRes()
  },[tab]) // eslint-disable-line

  // Warmup: fire once after first calendar load
  useEffect(()=>{
    if(calEvents.length>0&&!warmupDone.current){
      warmupDone.current=true
      axios.post(`${API}/predictions/warmup`).catch(()=>{})
      setTimeout(async()=>{
        try {
          const [ev,sp]=await Promise.all([axios.get(`${API}/events`),axios.get(`${API}/predictions?limit=40`)])
          setCal(ev.data.events??[]); setPred(sp.data.predictions??[])
        } catch{}
      },15000)
    }
    if(calEvents.length>0&&!strengthDone.current){
      strengthDone.current=true
      axios.post(`${API}/run-full-cycle`).catch(()=>{})
      setTimeout(async()=>{
        try {
          const [sr,pbr]=await Promise.all([axios.get(`${API}/currency-strengths`),axios.get(`${API}/pair-biases`)])
          setStr(sr.data.currency_strengths??[]); setPB(pbr.data.pair_biases??[])
        } catch{}
      },35000)
    }
  },[calEvents.length]) // eslint-disable-line

  // ── Actions ───────────────────────────────────────────────────────────────
  const runPred = useCallback(async(code:string)=>{
    setBusy(true)
    try {
      await axios.get(`${API}/prediction/${code}`)
      flash(`${code}: done`)
      if(tab==='calendar') loadCal()
      if(tab==='signals')  loadSig()
    } catch(e:any){ flash(`${code}: ${e.message}`) }
    finally{ setBusy(false) }
  },[tab,loadCal,loadSig])

  const syncActuals = async()=>{
    setBusy(true)
    try {
      const r=await axios.post(`${API}/events/sync-actuals`)
      flash(`${r.data.newly_graded} graded`)
      loadCal(true); loadModels()
    } catch(e:any){ flash(`Sync: ${e.message}`) }
    finally{ setBusy(false) }
  }

  // ── Filtered data ─────────────────────────────────────────────────────────
  const filtCal  = useMemo(()=>calEvents.filter(e=>ccySel.includes(e.currency)),[calEvents,ccySel])
  const filtPred = useMemo(()=>preds.filter(p=>ccySel.includes(p.currency)),[preds,ccySel])
  const filtStr  = useMemo(()=>ALL_CCYS.filter(c=>ccySel.includes(c)),[ccySel])
  const filtPairs= useMemo(()=>pairBiases.filter(pb=>pairSel.includes(pb.pair)),[pairBiases,pairSel])

  const calByDate = useMemo(()=>{
    const r:Record<string,CalEvent[]>={}
    for(const ev of filtCal){ const k=fmtD(ev.release_time_utc)||'Unknown'; if(!r[k])r[k]=[]; r[k].push(ev) }
    return r
  },[filtCal])

  // ── RENDER ────────────────────────────────────────────────────────────────
  return (
    <div className="app">
      {toast&&<div className="toast">{toast}</div>}

      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <header className="topbar">
        <div className="tb-inner">
          {/* Logo */}
          <div className="brand"><span className="bdot"/><span className="bname">MacroPredictor</span></div>

          {/* Currency filter chips — always visible */}
          <div className="tb-chips">
            <CcyFilter sel={ccySel} toggle={toggleCcy}/>
          </div>

          {/* Tabs */}
          <nav className="tb-tabs">
            {(['calendar','signals','strength','results'] as Tab[]).map(t=>(
              <button key={t} className={`tab-btn${tab===t?' tab-on':''}`} onClick={()=>setTab(t)}>
                {t==='calendar'?'Calendar':t==='signals'?'Signals':t==='strength'?'Strength':'Results'}
              </button>
            ))}
          </nav>

          {/* Actions + spinner */}
          <div className="tb-right">
            {busy&&<span className="spin"/>}
            {tab==='calendar'&&<>
              <button className="btn" onClick={()=>loadCal(true)} disabled={busy}>Refresh</button>
              <button className="btn btn-p" onClick={syncActuals} disabled={busy}>Sync Actuals</button>
            </>}
            {tab==='strength'&&<button className="btn" onClick={()=>{loadStr();loadModels()}} disabled={busy}>Refresh</button>}
            {tab==='signals' &&<button className="btn" onClick={loadSig}  disabled={busy}>Refresh</button>}
            {tab==='results' &&<button className="btn" onClick={loadRes}  disabled={busy}>Refresh</button>}
          </div>
        </div>
      </header>

      {/* ── Next-event banner ─────────────────────────────────────────────── */}
      <Banner events={calEvents} now={now}/>

      {/* ── Pair filter — Strength tab only ──────────────────────────────── */}
      {tab==='strength'&&(
        <div className="filter-bar filter-bar-sub">
          <PairFilter sel={pairSel} toggle={togglePair}/>
        </div>
      )}

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="main">

        {/* CALENDAR ────────────────────────────────────────────────────── */}
        {tab==='calendar'&&(
          <div className="cal-wrap">
            {filtCal.length===0&&!busy&&(
              <div className="empty">
                <p>{calEvents.length===0?'No events loaded.':'No events match the selected currencies.'}</p>
                <p className="empty-s">{calEvents.length===0?'Click Refresh to pull this week\'s calendar.':'Toggle currencies in the top bar to show more events.'}</p>
              </div>
            )}
            {Object.entries(calByDate).map(([dk,evs])=>(
              <section key={dk} className="cal-sec">
                <div className="cal-dh">{dk}</div>
                {evs.map((ev,i)=>(
                  <CalCard key={`${ev.event_code}-${i}`} ev={ev} now={now} onPredict={runPred}/>
                ))}
              </section>
            ))}
          </div>
        )}

        {/* SIGNALS ─────────────────────────────────────────────────────── */}
        {tab==='signals'&&(
          <div className="sig-wrap">
            {filtPred.length===0&&!busy&&(
              <div className="empty">
                <p>{preds.length===0?'Predictions loading.':'No predictions match the selected currencies.'}</p>
                <p className="empty-s">{preds.length===0?'Generating for high-impact events — takes ~15 seconds on first load.':'Toggle currencies in the top bar.'}</p>
              </div>
            )}
            <div className="sig-grid">
              {filtPred.map(p=><SigCard key={p.id} pred={p} onRefresh={runPred}/>)}
            </div>
          </div>
        )}

        {/* STRENGTH ────────────────────────────────────────────────────── */}
        {tab==='strength'&&(
          <div className="str-wrap">
            {/* 8 currency meters */}
            <div className="str-grid">
              {filtStr.map(ccy=>{
                const cs=strengths.find(s=>s.currency===ccy)??null
                return <Meter key={ccy} cs={cs} ccy={ccy}/>
              })}
            </div>

            {/* Pair bias grid */}
            {filtPairs.length>0?(
              <div className="pb-sec">
                <div className="sec-lbl">Pair bias</div>
                <div className="pb-list">{filtPairs.map(pb=><PairRow key={pb.pair} pb={pb}/>)}</div>
              </div>
            ):pairBiases.length>0?(
              <div className="empty"><p>No pairs match current filter.</p><p className="empty-s">Toggle pairs in the filter bar above.</p></div>
            ):(
              <div className="empty"><p>Pair bias loading.</p><p className="empty-s">Strength cycle runs automatically on first load (~35s).</p></div>
            )}

            {/* Model learning panel */}
            {models.length>0&&<ModelPanel models={models} trend={trend}/>}
          </div>
        )}

        {/* RESULTS ─────────────────────────────────────────────────────── */}
        {tab==='results'&&(
          <div className="res-wrap">
            {history.length===0&&!busy&&(
              <div className="empty">
                <p>No graded predictions yet.</p>
                <p className="empty-s">Results appear after a release prints and is graded against the pre-release forecast. Use Sync Actuals on Calendar to trigger grading.</p>
              </div>
            )}
            {history.length>0&&accuracy&&<>
              <div className="kpi-row">
                {[
                  {v:accuracy.total_predictions,l:'Predictions',c:''},
                  {v:accuracy.wins,l:'Correct',c:'kv-bull'},
                  {v:accuracy.losses,l:'Incorrect',c:'kv-bear'},
                  {v:`${accuracy.overall_hit_rate.toFixed(1)}%`,l:'Hit Rate',c:accuracy.overall_hit_rate>=60?'kv-bull':'kv-amb'},
                ].map(({v,l,c})=>(
                  <div key={l} className="kpi"><div className={`kv ${c}`}>{v}</div><div className="kl">{l}</div></div>
                ))}
              </div>
              {accuracy.confidence_stats?.length>0&&(
                <div className="bkt-card">
                  <div className="sec-lbl">Accuracy by confidence band</div>
                  {accuracy.confidence_stats.map(b=>(
                    <div key={b.bucket} className="bkt-row">
                      <span className="bkt-n">{b.bucket}</span>
                      <div className="bkt-b"><Bar pct={b.hit_rate_pct} cls={b.hit_rate_pct>=60?'bar-bull':'bar-amb'}/></div>
                      <span className="bkt-p">{b.hit_rate_pct.toFixed(0)}%</span>
                      <span className="bkt-cnt">{b.wins}/{b.total}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="ledger">
                <div className="l-hd">
                  <span>Event</span><span>Lean</span><span>Forecast</span>
                  <span>Actual</span><span>Surprise</span><span>Conf</span><span>✓✗</span>
                </div>
                {history.map(h=>{
                  const s=h.surprise??0
                  return (
                    <div key={h.id} className="l-row">
                      <span className="l-name">{FLAG[h.currency]??''} {h.display_name}</span>
                      <span className={`l-lean l-${dc(h.lean_direction)}`}>{dl(h.lean_direction).slice(0,4)}</span>
                      <span className="l-num">{fN(h.forecast)}</span>
                      <span className="l-num l-act">{fN(h.actual)}</span>
                      <span className={`l-num ${s>0?'l-pos':s<0?'l-neg':''}`}>{h.surprise!=null?`${s>0?'+':''}${s.toFixed(3)}`:'—'}</span>
                      <span className="l-num">{h.confidence_pct?.toFixed(0)}%</span>
                      <span className={h.was_correct?'l-ok':'l-no'}>{h.was_correct?'✓':'✗'}</span>
                    </div>
                  )
                })}
              </div>
            </>}
          </div>
        )}

      </main>
    </div>
  )
}
