"""
Live Server — AutoPack VLO-127S
=================================
LAN HTTP + WebSocket server for real-time monitor sync.

Uses only stdlib + `websockets` library (port 8000/8001).
Legacy HTTP server (port 8000) — read-only redirect page, backward compat.

Falls back silently if `websockets` is not installed so the
PyQt5 app stays fully functional offline.

Install extras:  pip install websockets
"""

import asyncio
import json
import logging
import queue
import socket
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

_log = logging.getLogger(__name__)

# ── Optional websockets ──────────────────────────────────────────────
try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve, ServerConnection
    _WS_OK = True
except ImportError:
    _WS_OK = False

# ── Shared legacy state ──────────────────────────────────────────────
_live_data: dict = {
    "invoice": "", "product": "", "order_qty": 0,
    "packed": 0, "reels": [], "boxes": {},
    "totals": {"target": 0, "actual": 0, "reject": 0, "diff": 0},
    "progress": "0 / 0", "updated_at": "",
}
_data_lock = threading.Lock()

# ── Submit queue: HTTP thread → Qt main thread ───────────────────────
_submit_queue: queue.Queue = queue.Queue()


def get_submit_queue() -> queue.Queue:
    """Return the queue MonitorPage should poll (100 ms QTimer)."""
    return _submit_queue


def update_live_data(data: dict) -> None:
    with _data_lock:
        _live_data.update(data)
        _live_data["updated_at"] = (
            datetime.now().replace(microsecond=0).time().isoformat())


def get_live_data() -> dict:
    with _data_lock:
        return dict(_live_data)


# ════════════════════════════════════════════════════════════════════
#  EMBEDDED WEB UI
# ════════════════════════════════════════════════════════════════════

_WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>AutoPack Monitor — Control Tower</title>
<style>
/* ═══════════════════════════════════════════════════════════════════
   AUTOPACK MONITOR — CONTROL TOWER
   Light mode · Material Design · 100% offline · Responsive
   ═══════════════════════════════════════════════════════════════════ */

/* Design tokens */
:root{
  --bg:           #F5F7FA;
  --surface:      #FFFFFF;
  --surface-2:    #F8FAFC;
  --border:       #E2E8F0;
  --border-2:     #CBD5E1;
  --text:         #0F172A;
  --text-2:       #475569;
  --text-3:       #94A3B8;

  --primary:      #1E40AF;
  --primary-2:    #2563EB;
  --primary-soft: #DBEAFE;
  --success:      #059669;
  --success-soft: #D1FAE5;
  --warn:         #D97706;
  --warn-soft:    #FEF3C7;
  --danger:       #DC2626;
  --danger-soft:  #FEE2E2;
  --violet:       #7C3AED;
  --violet-soft:  #EDE9FE;

  --shadow-sm:    0 1px 2px rgba(15,23,42,.06);
  --shadow:       0 1px 3px rgba(15,23,42,.08),0 1px 2px rgba(15,23,42,.06);
  --shadow-md:    0 4px 6px -1px rgba(15,23,42,.08),0 2px 4px -1px rgba(15,23,42,.04);
  --shadow-lg:    0 10px 15px -3px rgba(15,23,42,.08),0 4px 6px -2px rgba(15,23,42,.04);

  --r-sm: 6px; --r: 10px; --r-lg: 14px; --r-xl: 20px;
  --font: "Segoe UI","SF Pro Text",-apple-system,BlinkMacSystemFont,Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono: "SFMono-Regular","Consolas","Liberation Mono","Menlo",monospace;
}

*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{font-family:var(--font);background:var(--bg);color:var(--text);
  min-height:100vh;line-height:1.5;-webkit-font-smoothing:antialiased;
  padding-bottom:24px}

/* ═══ HEADER ═══════════════════════════════════════════════════════ */
#hdr{background:var(--surface);border-bottom:1px solid var(--border);
  padding:14px 20px;display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;box-shadow:var(--shadow-sm);gap:12px;flex-wrap:wrap}
.hdr-left{display:flex;align-items:center;gap:14px;min-width:0;flex:1}
.hdr-logo{width:42px;height:42px;border-radius:var(--r);
  background:linear-gradient(135deg,var(--primary) 0%,var(--primary-2) 100%);
  display:flex;align-items:center;justify-content:center;color:#fff;
  flex-shrink:0;box-shadow:var(--shadow-md)}
.hdr-logo svg{width:22px;height:22px}
.hdr-titles{min-width:0}
.hdr-title{font-size:17px;font-weight:700;letter-spacing:-0.2px;color:var(--text)}
.hdr-sub{font-size:12px;color:var(--text-2);margin-top:2px;display:flex;
  gap:6px;align-items:center;flex-wrap:wrap}
.hdr-sub .chip{background:var(--surface-2);border:1px solid var(--border);
  padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;color:var(--text-2)}
.hdr-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
#clock{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--text-2);
  background:var(--surface-2);padding:6px 10px;border-radius:var(--r-sm);
  border:1px solid var(--border);display:none}
@media(min-width:720px){#clock{display:block}}
#conn{font-size:12px;font-weight:700;padding:6px 12px;border-radius:20px;
  display:inline-flex;align-items:center;gap:6px;white-space:nowrap;
  transition:all .2s}
#conn .dot{width:8px;height:8px;border-radius:50%;display:inline-block}
#conn.ok{background:var(--success-soft);color:var(--success)}
#conn.ok .dot{background:var(--success);box-shadow:0 0 0 0 rgba(5,150,105,.6);
  animation:pulse 2s infinite}
#conn.bad{background:var(--danger-soft);color:var(--danger)}
#conn.bad .dot{background:var(--danger)}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(5,150,105,.6)}
  70%{box-shadow:0 0 0 8px rgba(5,150,105,0)}
  100%{box-shadow:0 0 0 0 rgba(5,150,105,0)}
}

/* ═══ LAYOUT ═══════════════════════════════════════════════════════ */
.wrap{max-width:1400px;margin:0 auto;padding:16px}
.grid{display:grid;gap:14px}
@media(min-width:980px){
  .grid-main{grid-template-columns:minmax(0,1fr) 340px}
}

/* ═══ HERO PROGRESS ════════════════════════════════════════════════ */
#hero{background:var(--surface);border-radius:var(--r-xl);padding:20px 22px;
  box-shadow:var(--shadow);border:1px solid var(--border);margin-bottom:14px}
.hero-row{display:flex;justify-content:space-between;align-items:baseline;
  gap:12px;flex-wrap:wrap}
.hero-label{font-size:11px;font-weight:700;color:var(--text-3);
  text-transform:uppercase;letter-spacing:1px}
.hero-pct{font-size:30px;font-weight:800;color:var(--primary);
  font-family:var(--font);letter-spacing:-0.5px;line-height:1}
.hero-pct small{font-size:15px;color:var(--text-2);font-weight:600;margin-left:4px}
.hero-eta{text-align:right}
.hero-eta .lbl{font-size:10px;color:var(--text-3);font-weight:700;
  text-transform:uppercase;letter-spacing:0.8px}
.hero-eta .val{font-size:18px;font-weight:700;color:var(--text);
  font-family:var(--mono);margin-top:2px}
.hero-eta .val.warn{color:var(--warn)}
.hero-bar{margin-top:14px;background:var(--surface-2);border-radius:999px;
  height:14px;overflow:hidden;position:relative;border:1px solid var(--border)}
.hero-bar-fill{height:100%;background:linear-gradient(90deg,var(--primary),var(--primary-2));
  border-radius:999px;transition:width .5s cubic-bezier(0.4,0,0.2,1);width:0%;
  position:relative;overflow:hidden}
.hero-bar-fill::after{content:"";position:absolute;top:0;left:0;right:0;bottom:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);
  animation:shimmer 2.2s infinite}
@keyframes shimmer{
  0%  {transform:translateX(-100%)}
  100%{transform:translateX(100%)}
}
.hero-foot{display:flex;justify-content:space-between;margin-top:8px;
  font-size:12px;color:var(--text-2);font-family:var(--mono)}

/* ═══ KPI CARDS ════════════════════════════════════════════════════ */
#kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:14px}
@media(min-width:640px){#kpis{grid-template-columns:repeat(4,1fr)}}
.kpi{background:var(--surface);border-radius:var(--r-lg);padding:14px 16px;
  box-shadow:var(--shadow-sm);border:1px solid var(--border);
  display:flex;flex-direction:column;gap:4px;position:relative;overflow:hidden;
  transition:transform .15s,box-shadow .15s}
.kpi:hover{transform:translateY(-1px);box-shadow:var(--shadow-md)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
  background:var(--primary-2)}
.kpi.green::before{background:var(--success)}
.kpi.amber::before{background:var(--warn)}
.kpi.red::before  {background:var(--danger)}
.kpi-head{display:flex;justify-content:space-between;align-items:center}
.kpi-label{font-size:10px;font-weight:700;color:var(--text-3);
  text-transform:uppercase;letter-spacing:0.8px}
.kpi-icon{width:18px;height:18px;color:var(--text-3)}
.kpi-val{font-size:24px;font-weight:800;color:var(--text);font-family:var(--font);
  letter-spacing:-0.5px;line-height:1.1;margin-top:4px}
.kpi-val.green{color:var(--success)} .kpi-val.amber{color:var(--warn)}
.kpi-val.red{color:var(--danger)}    .kpi-val.blue{color:var(--primary)}
.kpi-sub{font-size:11px;color:var(--text-2);display:flex;align-items:center;
  gap:4px;font-weight:500;min-height:16px}
.kpi-sub .trend-up{color:var(--success)}
.kpi-sub .trend-down{color:var(--danger)}
.kpi-sub .trend-flat{color:var(--text-3)}
.spark{width:100%;height:20px;margin-top:2px}

/* ═══ SECTION CARD ═════════════════════════════════════════════════ */
.card{background:var(--surface);border-radius:var(--r-lg);border:1px solid var(--border);
  box-shadow:var(--shadow-sm);overflow:hidden;margin-bottom:14px}
.card-hdr{padding:14px 18px;border-bottom:1px solid var(--border);
  display:flex;justify-content:space-between;align-items:center;gap:10px;
  background:var(--surface-2)}
.card-title{font-size:13px;font-weight:700;color:var(--text);letter-spacing:0.3px;
  text-transform:uppercase;display:flex;align-items:center;gap:8px}
.card-title svg{width:16px;height:16px;color:var(--primary)}
.card-meta{font-size:11px;color:var(--text-2);font-family:var(--mono)}
.card-body{padding:16px 18px}

/* ═══ CURRENT REEL INPUT ═══════════════════════════════════════════ */
#input-card .card-hdr{background:linear-gradient(90deg,var(--primary-soft),var(--surface))}
.reel-title{font-size:17px;font-weight:700;color:var(--text);margin-bottom:4px}
.reel-meta{font-size:12px;color:var(--text-2);display:flex;gap:10px;
  flex-wrap:wrap;margin-bottom:14px}
.reel-meta .tag{background:var(--surface-2);border:1px solid var(--border);
  padding:3px 8px;border-radius:var(--r-sm);font-weight:500}
.reel-meta .tag strong{color:var(--text);font-weight:700;margin-left:4px;
  font-family:var(--mono)}
.inp-grp{margin-bottom:12px}
.inp-grp label{display:block;font-size:11px;font-weight:700;color:var(--text-2);
  text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px}
.num-row{display:flex;align-items:center;gap:6px}
.num-row input[type=number]{flex:1;min-width:0;background:var(--surface);
  border:2px solid var(--border-2);color:var(--text);border-radius:var(--r);
  padding:10px;font-size:22px;font-weight:700;text-align:center;
  font-family:var(--mono);-moz-appearance:textfield;transition:border-color .15s,box-shadow .15s}
.num-row input::-webkit-inner-spin-button,
.num-row input::-webkit-outer-spin-button{-webkit-appearance:none}
.num-row input:focus{outline:none;border-color:var(--primary-2);
  box-shadow:0 0 0 3px rgba(37,99,235,.15)}
.adj-btn{background:var(--surface);color:var(--primary);border:1.5px solid var(--border-2);
  border-radius:var(--r);font-size:14px;font-weight:700;cursor:pointer;
  min-width:46px;min-height:46px;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:all .15s;-webkit-user-select:none;user-select:none;
  font-family:var(--mono)}
.adj-btn:hover{background:var(--primary-soft);border-color:var(--primary-2)}
.adj-btn:active{background:var(--primary-2);color:#fff;transform:scale(0.97)}
.adj-btn.sm{min-width:40px;min-height:40px;font-size:12px}
#diff-hint{font-size:12px;margin-top:6px;text-align:center;min-height:18px;
  font-weight:600}
#submit-btn{display:flex;align-items:center;justify-content:center;gap:8px;
  width:100%;background:var(--success);color:#fff;border:none;
  border-radius:var(--r);font-size:15px;font-weight:700;padding:14px;cursor:pointer;
  margin-top:6px;transition:all .15s;letter-spacing:0.3px;
  box-shadow:0 2px 4px rgba(5,150,105,.2)}
#submit-btn:hover:not(:disabled){background:#047857;
  box-shadow:0 4px 8px rgba(5,150,105,.3);transform:translateY(-1px)}
#submit-btn:active:not(:disabled){transform:translateY(0)}
#submit-btn:disabled{background:#CBD5E1;color:#64748B;cursor:not-allowed;
  box-shadow:none}
#submit-btn svg{width:18px;height:18px}

/* ═══ BOX VISUALIZER ═══════════════════════════════════════════════ */
.boxes{display:grid;gap:8px}
.box-row{display:grid;grid-template-columns:80px minmax(0,1fr) 100px 90px;
  gap:12px;align-items:center;padding:10px 12px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:var(--r);font-size:13px;
  transition:background .15s}
.box-row:hover{background:var(--primary-soft)}
.box-row.active{background:var(--primary-soft);border-color:var(--primary-2)}
.box-row.done{background:var(--success-soft);border-color:#86EFAC}
.box-label{font-weight:700;color:var(--text);font-family:var(--font)}
.box-label .sub{display:block;font-size:10px;color:var(--text-3);font-weight:500;
  margin-top:2px;font-family:var(--mono)}
.box-bar-wrap{background:#E2E8F0;border-radius:999px;height:10px;overflow:hidden;
  position:relative}
.box-bar-fill{height:100%;border-radius:999px;transition:width .4s;
  background:var(--primary-2)}
.box-row.done .box-bar-fill{background:var(--success)}
.box-row.active .box-bar-fill{background:linear-gradient(90deg,var(--primary),var(--primary-2))}
.box-count{text-align:right;font-family:var(--mono);font-weight:700;color:var(--text);
  font-size:12px}
.box-count .sub{display:block;color:var(--text-3);font-size:10px;font-weight:500;
  margin-top:2px}
.box-status{text-align:right;font-size:11px;font-weight:700}
.box-status.done  {color:var(--success)}
.box-status.active{color:var(--primary)}
.box-status.pending{color:var(--text-3)}

/* ═══ LOT PROGRESS ═════════════════════════════════════════════════ */
.lots{display:grid;gap:10px}
.lot-row{padding:10px 12px;background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--r)}
.lot-head{display:flex;justify-content:space-between;align-items:center;
  margin-bottom:6px;font-size:12px}
.lot-name{font-weight:700;color:var(--text)}
.lot-pct{font-family:var(--mono);font-weight:700;color:var(--primary-2);font-size:13px}
.lot-bar{background:#E2E8F0;height:6px;border-radius:999px;overflow:hidden}
.lot-bar-fill{height:100%;background:linear-gradient(90deg,var(--primary),var(--primary-2));
  border-radius:999px;transition:width .4s}
.lot-row.complete .lot-bar-fill{background:var(--success)}
.lot-row.complete .lot-pct{color:var(--success)}
.lot-foot{display:flex;justify-content:space-between;margin-top:4px;
  font-size:11px;color:var(--text-3);font-family:var(--mono)}

/* ═══ ALERT BANNER ═════════════════════════════════════════════════ */
.alert{padding:10px 14px;border-radius:var(--r);margin-bottom:14px;
  display:flex;align-items:flex-start;gap:10px;font-size:13px;
  border:1px solid;animation:slide-in .3s ease-out}
@keyframes slide-in{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
.alert svg{width:18px;height:18px;flex-shrink:0;margin-top:1px}
.alert.warn {background:var(--warn-soft);border-color:#FCD34D;color:#92400E}
.alert.danger{background:var(--danger-soft);border-color:#FCA5A5;color:#991B1B}
.alert.info {background:var(--primary-soft);border-color:#93C5FD;color:#1E3A8A}
.alert-title{font-weight:700;margin-bottom:2px}
.alert-body{font-size:12px;opacity:.9;line-height:1.4}

/* ═══ PLAN TABLE ═══════════════════════════════════════════════════ */
#tbl-card .card-body{padding:0}
.tbl-wrap{overflow-x:auto;max-height:500px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:680px}
thead{position:sticky;top:0;background:var(--surface-2);z-index:5}
th{font-weight:700;color:var(--text-2);padding:10px 12px;text-align:left;
  border-bottom:1px solid var(--border);font-size:11px;
  text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap}
th:first-child{padding-left:18px}
th:last-child{padding-right:18px}
td{padding:10px 12px;border-bottom:1px solid var(--border);
  font-family:var(--mono);font-size:13px;color:var(--text)}
td:first-child{padding-left:18px;font-family:var(--font);font-weight:600}
td:last-child {padding-right:18px;font-family:var(--font)}
tbody tr{transition:background .15s}
tbody tr:hover{background:var(--surface-2)}
tr.done-row    td{color:var(--text-2)}
tr.done-row    td:first-child{color:var(--success)}
tr.cur-row     td{background:var(--primary-soft);font-weight:700}
tr.cur-row     td:first-child{border-left:3px solid var(--primary-2);padding-left:15px}
tr.wait-row    td{color:var(--warn);background:var(--warn-soft);font-style:italic}
tr.rem-row     td{color:var(--violet);background:var(--violet-soft)}
tr.sep-row     td{height:4px;background:var(--bg);padding:0;border:none}

.status-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;
  border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap;
  font-family:var(--font)}
.status-done {background:var(--success-soft);color:var(--success)}
.status-cur  {background:var(--primary-soft);color:var(--primary)}
.status-wait {background:var(--warn-soft);   color:var(--warn)}
.status-pend {background:var(--surface-2);   color:var(--text-3);
  border:1px solid var(--border)}

.diff-cell{display:inline-flex;align-items:center;gap:2px;font-weight:700}
.diff-cell.pos{color:var(--warn)}.diff-cell.neg{color:var(--danger)}
.diff-cell.zero{color:var(--success)}

/* ═══ EMPTY STATE ══════════════════════════════════════════════════ */
.empty{padding:40px 20px;text-align:center;color:var(--text-3)}
.empty svg{width:48px;height:48px;opacity:.4;margin-bottom:8px}
.empty .t{font-size:15px;font-weight:600;color:var(--text-2);margin-bottom:4px}
.empty .s{font-size:12px}

/* ═══ MOBILE ═══════════════════════════════════════════════════════ */
@media(max-width:640px){
  .wrap{padding:10px}
  #hero{padding:16px}
  .hero-pct{font-size:26px}
  .box-row{grid-template-columns:60px minmax(0,1fr) 80px}
  .box-row .box-status{display:none}
  .card-body{padding:12px 14px}
  th,td{padding:8px 10px;font-size:12px}
  th:first-child,td:first-child{padding-left:14px}
}
</style>
</head>
<body>

<!-- ════════════════ HEADER ════════════════ -->
<div id="hdr">
  <div class="hdr-left">
    <div class="hdr-logo">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
        <polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>
      </svg>
    </div>
    <div class="hdr-titles">
      <div class="hdr-title">AutoPack Monitor</div>
      <div class="hdr-sub" id="hdr-sub">
        <span class="chip" id="chip-invoice">Connecting…</span>
      </div>
    </div>
  </div>
  <div class="hdr-right">
    <div id="clock">--:--:--</div>
    <div id="conn" class="bad"><span class="dot"></span><span id="conn-txt">Disconnected</span></div>
  </div>
</div>

<div class="wrap">

  <!-- ════════════════ ALERTS ════════════════ -->
  <div id="alerts"></div>

  <!-- ════════════════ HERO PROGRESS ════════════════ -->
  <div id="hero">
    <div class="hero-row">
      <div>
        <div class="hero-label">Overall Progress</div>
        <div class="hero-pct" id="hero-pct">0<small>%</small></div>
      </div>
      <div class="hero-eta">
        <div class="lbl">Estimated Finish</div>
        <div class="val" id="hero-eta">—</div>
      </div>
    </div>
    <div class="hero-bar"><div class="hero-bar-fill" id="hero-fill"></div></div>
    <div class="hero-foot">
      <span id="hero-left"><strong id="hero-packed">0</strong> / <span id="hero-target">0</span> pcs</span>
      <span id="hero-rate">— pcs/min</span>
    </div>
  </div>

  <!-- ════════════════ KPI CARDS ════════════════ -->
  <div id="kpis">
    <div class="kpi green">
      <div class="kpi-head">
        <span class="kpi-label">Packed</span>
        <svg class="kpi-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 7L9 18l-5-5"/></svg>
      </div>
      <div class="kpi-val green" id="k-packed">0</div>
      <div class="kpi-sub" id="k-packed-sub">—</div>
      <svg class="spark" id="k-spark" viewBox="0 0 120 20" preserveAspectRatio="none"></svg>
    </div>
    <div class="kpi">
      <div class="kpi-head">
        <span class="kpi-label">Target</span>
        <svg class="kpi-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
      </div>
      <div class="kpi-val blue" id="k-target">0</div>
      <div class="kpi-sub">Order quantity</div>
    </div>
    <div class="kpi amber">
      <div class="kpi-head">
        <span class="kpi-label">Remaining</span>
        <svg class="kpi-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      </div>
      <div class="kpi-val amber" id="k-remain">0</div>
      <div class="kpi-sub" id="k-remain-sub">—</div>
    </div>
    <div class="kpi red">
      <div class="kpi-head">
        <span class="kpi-label">Reject</span>
        <svg class="kpi-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
      </div>
      <div class="kpi-val red" id="k-reject">0</div>
      <div class="kpi-sub" id="k-reject-sub">0.00%</div>
    </div>
  </div>

  <!-- ════════════════ MAIN GRID ════════════════ -->
  <div class="grid grid-main">

    <!-- LEFT COLUMN -->
    <div>

      <!-- Current Reel Input Card -->
      <div class="card" id="input-card">
        <div class="card-hdr">
          <div class="card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            Current Reel
          </div>
          <div class="card-meta" id="reel-meta-lot">—</div>
        </div>
        <div class="card-body">
          <div id="reel-info-wrap">
            <div id="reel-title" class="reel-title">No active plan</div>
            <div id="reel-meta" class="reel-meta"></div>
          </div>
          <div class="inp-grp">
            <label>Actual (pcs)</label>
            <div class="num-row">
              <button class="adj-btn sm" onclick="adj('actual',-100)">−100</button>
              <button class="adj-btn sm" onclick="adj('actual',-10)">−10</button>
              <button class="adj-btn" onclick="adj('actual',-1)">−</button>
              <input type="number" id="actual-in" min="0" max="9999999" value="0" oninput="onInputChange()">
              <button class="adj-btn" onclick="adj('actual',1)">+</button>
              <button class="adj-btn sm" onclick="adj('actual',10)">+10</button>
              <button class="adj-btn sm" onclick="adj('actual',100)">+100</button>
            </div>
          </div>
          <div class="inp-grp">
            <label>Reject (pcs)</label>
            <div class="num-row">
              <button class="adj-btn" onclick="adj('reject',-1)">−</button>
              <input type="number" id="reject-in" min="0" max="9999999" value="0" oninput="onInputChange()">
              <button class="adj-btn" onclick="adj('reject',1)">+</button>
              <button class="adj-btn sm" onclick="adj('reject',10)">+10</button>
            </div>
          </div>
          <div id="diff-hint"></div>
          <button id="submit-btn" onclick="doConfirm()" disabled>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            Submit Reel
          </button>
        </div>
      </div>

      <!-- Box Overview -->
      <div class="card">
        <div class="card-hdr">
          <div class="card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/></svg>
            Box Overview
          </div>
          <div class="card-meta" id="box-meta">— boxes</div>
        </div>
        <div class="card-body">
          <div class="boxes" id="boxes-wrap">
            <div class="empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>
              <div class="t">No boxes yet</div>
              <div class="s">Start a plan to see box breakdown</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Detailed Plan Table -->
      <div class="card" id="tbl-card">
        <div class="card-hdr">
          <div class="card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            Plan Details
          </div>
          <div class="card-meta" id="plan-meta">— reels</div>
        </div>
        <div class="card-body">
          <div class="tbl-wrap">
            <table>
              <thead><tr>
                <th>Box</th><th>Reel</th><th>Lot</th><th>Target</th>
                <th>Actual</th><th>Reject</th><th>Diff</th><th>Status</th>
              </tr></thead>
              <tbody id="tbody"></tbody>
            </table>
          </div>
        </div>
      </div>

    </div><!-- /LEFT -->

    <!-- RIGHT COLUMN -->
    <div>

      <!-- Lot Progress -->
      <div class="card">
        <div class="card-hdr">
          <div class="card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            Lot Progress
          </div>
          <div class="card-meta" id="lot-meta">— lots</div>
        </div>
        <div class="card-body">
          <div class="lots" id="lots-wrap">
            <div class="empty">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
              <div class="t">No lot data</div>
              <div class="s">Lot progress appears here</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Order Info -->
      <div class="card">
        <div class="card-hdr">
          <div class="card-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            Order Info
          </div>
        </div>
        <div class="card-body">
          <div id="order-info" style="display:grid;gap:10px;font-size:13px">
            <div style="display:flex;justify-content:space-between;padding-bottom:8px;border-bottom:1px solid var(--border)">
              <span style="color:var(--text-2);font-weight:500">Invoice</span>
              <span id="oi-invoice" style="font-family:var(--mono);font-weight:700">—</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding-bottom:8px;border-bottom:1px solid var(--border)">
              <span style="color:var(--text-2);font-weight:500">Destination</span>
              <span id="oi-dest" style="font-weight:700">—</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding-bottom:8px;border-bottom:1px solid var(--border)">
              <span style="color:var(--text-2);font-weight:500">Ship Date</span>
              <span id="oi-date" style="font-family:var(--mono);font-weight:700">—</span>
            </div>
            <div style="display:flex;justify-content:space-between">
              <span style="color:var(--text-2);font-weight:500">Last Update</span>
              <span id="oi-updated" style="font-family:var(--mono);font-weight:700;color:var(--text-2)">—</span>
            </div>
          </div>
        </div>
      </div>

    </div><!-- /RIGHT -->

  </div><!-- /grid-main -->
</div><!-- /wrap -->

<script>
/* ═══════════════════════════════════════════════════════════════════
   APP STATE + WEBSOCKET
   ═══════════════════════════════════════════════════════════════════ */
var WS_PORT  = __WS_PORT__;
var API_PORT = __API_PORT__;
var ws = null, state = {}, curReel = null, curTarget = 0;
var reconnDelay = 1500, reconnTimer = null;
var packHistory = [];   // [{t, packed}] — rolling window for rate/ETA
var packedSpark = [];   // sparkline values

function connect() {
  var url = 'ws://' + location.hostname + ':' + WS_PORT + '/ws';
  try { ws = new WebSocket(url); } catch(e){ setConn(false); return; }
  ws.onopen = function() {
    setConn(true); reconnDelay = 1500;
    clearTimeout(reconnTimer);
  };
  ws.onmessage = function(e) {
    try { var d = JSON.parse(e.data); if (d.type !== 'ping') update(d); } catch(x) {}
  };
  ws.onclose = ws.onerror = function() {
    setConn(false);
    reconnTimer = setTimeout(function() {
      reconnDelay = Math.min(reconnDelay * 1.5, 30000);
      connect();
    }, reconnDelay);
  };
}

function setConn(ok) {
  var el = document.getElementById('conn');
  var txt = document.getElementById('conn-txt');
  txt.textContent = ok ? 'LIVE' : 'Offline';
  el.className = ok ? 'ok' : 'bad';
}

function fmt(n)       { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtTime(iso) {
  if (!iso) return '—';
  try {
    var d = new Date(iso);
    return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  } catch(e) { return iso; }
}

/* ═══════════════════════════════════════════════════════════════════
   UPDATE — main render pipeline
   ═══════════════════════════════════════════════════════════════════ */
function update(d) {
  state = d;

  var packed   = d.total_packed  || 0;
  var orderQty = d.order_qty     || 0;
  var reject   = d.total_reject  || 0;
  var remain   = d.remaining != null ? d.remaining : Math.max(0, orderQty - packed);
  var pct      = orderQty > 0 ? Math.min(100, packed / orderQty * 100) : 0;

  /* ── Rolling pack history for rate/ETA ── */
  var now = Date.now();
  packHistory.push({t: now, packed: packed});
  // keep last 10 minutes
  while (packHistory.length > 1 && now - packHistory[0].t > 600000) packHistory.shift();
  // sparkline: last 24 values
  packedSpark.push(packed);
  if (packedSpark.length > 24) packedSpark.shift();

  /* ── HEADER ── */
  var inv  = d.invoice || '—';
  var dest = d.dest    || '';
  var sd   = d.ship_date || '';
  var sub  = document.getElementById('hdr-sub');
  sub.innerHTML =
    '<span class="chip" id="chip-invoice">' + inv + '</span>' +
    (dest ? '<span class="chip">📍 ' + dest + '</span>' : '') +
    (sd   ? '<span class="chip">🗓 ' + sd + '</span>' : '');

  /* ── HERO ── */
  document.getElementById('hero-pct').innerHTML =
    pct.toFixed(1) + '<small>%</small>';
  document.getElementById('hero-fill').style.width = pct + '%';
  document.getElementById('hero-packed').textContent = fmt(packed);
  document.getElementById('hero-target').textContent = fmt(orderQty);
  var rate = computeRate();      // pcs/min
  var eta  = computeETA(remain, rate);
  document.getElementById('hero-rate').textContent =
    rate > 0 ? (Math.round(rate).toLocaleString() + ' pcs/min') : '— pcs/min';
  var etaEl = document.getElementById('hero-eta');
  etaEl.textContent = eta.text;
  etaEl.className = 'val' + (eta.warn ? ' warn' : '');

  /* ── KPIs ── */
  document.getElementById('k-packed').textContent = fmt(packed);
  document.getElementById('k-target').textContent = fmt(orderQty);
  document.getElementById('k-remain').textContent = fmt(remain);
  document.getElementById('k-reject').textContent = fmt(reject);

  var rejPct = orderQty > 0 ? (reject/orderQty*100) : 0;
  document.getElementById('k-reject-sub').textContent = rejPct.toFixed(2) + '%';
  var remReels = (d.plan||[]).filter(function(r){ return r.status !== 'done' && r.note !== 'Wait next lot'; }).length;
  document.getElementById('k-remain-sub').textContent =
    remReels > 0 ? (remReels + ' reels left') : 'Done';

  // trend
  var packedSub = document.getElementById('k-packed-sub');
  if (packHistory.length > 1) {
    var delta = packHistory[packHistory.length-1].packed - packHistory[0].packed;
    if (delta > 0) packedSub.innerHTML = '<span class="trend-up">▲ +' + fmt(delta) + '</span> in ' + Math.round((now - packHistory[0].t)/60000) + 'm';
    else           packedSub.innerHTML = '<span class="trend-flat">→ steady</span>';
  } else {
    packedSub.textContent = 'Tracking…';
  }

  // Reject alert banner
  renderAlerts(rejPct, d);

  // Sparkline
  renderSpark(packedSpark);

  /* ── ORDER INFO ── */
  document.getElementById('oi-invoice').textContent = inv;
  document.getElementById('oi-dest').textContent    = dest || '—';
  document.getElementById('oi-date').textContent    = sd || '—';
  document.getElementById('oi-updated').textContent =
    d.timestamp ? fmtTime(d.timestamp) : '—';

  /* ── BOXES / LOTS / PLAN ── */
  renderBoxes(d.plan || []);
  renderLots(d);
  renderPlan(d.plan || []);

  /* ── Current reel input ── */
  var cur = (d.plan || []).find(function(r) { return r.status === 'current'; });
  if (cur) {
    curReel   = cur.reel;
    curTarget = cur.target;
    showInputCard(cur);
    document.getElementById('submit-btn').disabled = false;
  } else {
    curReel = null; curTarget = 0;
    var isAllDone = d.current_reel === null && (d.plan||[]).length > 0;
    document.getElementById('reel-title').textContent = isAllDone
      ? '✅ All reels complete'
      : ((d.plan||[]).length === 0 ? 'No active plan' : 'Awaiting next reel');
    document.getElementById('reel-meta').innerHTML = isAllDone
      ? '<span class="tag">Press <strong>Finish</strong> in the desktop app to close order</span>' : '';
    document.getElementById('diff-hint').textContent = '';
    document.getElementById('submit-btn').disabled = true;
  }
}

/* ═══════════════════════════════════════════════════════════════════
   ALERTS — reject threshold, overflow, etc.
   ═══════════════════════════════════════════════════════════════════ */
function renderAlerts(rejPct, d) {
  var wrap = document.getElementById('alerts');
  var html = '';
  if (rejPct >= 5) {
    html += '<div class="alert danger">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
      '<div><div class="alert-title">High Reject Rate</div>' +
      '<div class="alert-body">Reject rate is ' + rejPct.toFixed(2) + '% — exceeds 5% threshold. Inspect machine.</div></div></div>';
  } else if (rejPct >= 2) {
    html += '<div class="alert warn">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
      '<div><div class="alert-title">Elevated Reject Rate</div>' +
      '<div class="alert-body">Reject rate is ' + rejPct.toFixed(2) + '% — above 2% normal range.</div></div></div>';
  }
  wrap.innerHTML = html;
}

/* ═══════════════════════════════════════════════════════════════════
   SPARKLINE — tiny inline SVG chart
   ═══════════════════════════════════════════════════════════════════ */
function renderSpark(data) {
  var svg = document.getElementById('k-spark');
  if (data.length < 2) { svg.innerHTML = ''; return; }
  var w = 120, h = 20, pad = 1;
  var min = Math.min.apply(null, data), max = Math.max.apply(null, data);
  var range = max - min || 1;
  var pts = data.map(function(v, i) {
    var x = pad + (i / (data.length-1)) * (w - pad*2);
    var y = h - pad - ((v - min) / range) * (h - pad*2);
    return x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  var lastX = pad + (w - pad*2), lastY = h - pad - ((data[data.length-1] - min) / range) * (h - pad*2);
  svg.innerHTML =
    '<polyline points="' + pts + '" fill="none" stroke="var(--success)" stroke-width="1.5" stroke-linejoin="round"/>' +
    '<circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="2" fill="var(--success)"/>';
}

/* ═══════════════════════════════════════════════════════════════════
   RATE & ETA
   ═══════════════════════════════════════════════════════════════════ */
function computeRate() {
  if (packHistory.length < 2) return 0;
  var first = packHistory[0], last = packHistory[packHistory.length-1];
  var dt = (last.t - first.t) / 60000;
  if (dt <= 0) return 0;
  var dp = last.packed - first.packed;
  return dp / dt;
}
function computeETA(remain, rate) {
  if (remain <= 0) return {text: 'Complete', warn: false};
  if (rate <= 0)   return {text: '—', warn: false};
  var mins = remain / rate;
  var hrs  = Math.floor(mins / 60);
  var m    = Math.round(mins % 60);
  var text;
  if (hrs >= 24) text = '>24 h';
  else if (hrs >= 1) text = hrs + 'h ' + m + 'm';
  else text = m + ' min';
  // Project finish clock time
  var finish = new Date(Date.now() + mins * 60000);
  var clock  = finish.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  return {text: text + '  · ' + clock, warn: hrs >= 4};
}

/* ═══════════════════════════════════════════════════════════════════
   BOX VISUALIZER
   ═══════════════════════════════════════════════════════════════════ */
function renderBoxes(plan) {
  var wrap = document.getElementById('boxes-wrap');
  if (!plan.length) { return; }  // keep empty state
  // Group by box
  var map = {};
  plan.forEach(function(r) {
    if (r.note === 'Wait next lot') return;
    var b = r.box;
    if (!map[b]) map[b] = {reels:[], actual:0, target:0, lots:{}};
    map[b].reels.push(r);
    map[b].target += r.target || 0;
    if (r.actual != null) map[b].actual += r.actual;
    if (r.lot) map[b].lots[r.lot] = true;
  });
  var keys = Object.keys(map).map(Number).sort(function(a,b){return a-b});
  var html = '';
  keys.forEach(function(k) {
    var b = map[k];
    var pct = b.target > 0 ? Math.min(100, b.actual/b.target*100) : 0;
    var allDone = b.reels.every(function(r){ return r.status === 'done'; });
    var hasCur  = b.reels.some(function(r){ return r.status === 'current'; });
    var status  = allDone ? 'done' : hasCur ? 'active' : 'pending';
    var sLbl    = allDone ? '✓ Done' : hasCur ? '▶ Active' : '⏳ Pending';
    var lbl     = k === 0 ? '📋 Rem' : 'Box ' + k;
    var lots    = Object.keys(b.lots).join(', ') || '—';
    html += '<div class="box-row ' + status + '">' +
      '<div class="box-label">' + lbl + '<span class="sub">Lot ' + lots + '</span></div>' +
      '<div class="box-bar-wrap"><div class="box-bar-fill" style="width:' + pct + '%"></div></div>' +
      '<div class="box-count">' + fmt(b.actual) + '<span class="sub">/ ' + fmt(b.target) + '</span></div>' +
      '<div class="box-status ' + status + '">' + sLbl + '</div>' +
      '</div>';
  });
  wrap.innerHTML = html;
  document.getElementById('box-meta').textContent = keys.length + ' boxes';
}

/* ═══════════════════════════════════════════════════════════════════
   LOT PROGRESS
   ═══════════════════════════════════════════════════════════════════ */
function renderLots(d) {
  var wrap = document.getElementById('lots-wrap');
  var lots = d.lot_history || [];

  // Also compute CURRENT lot from plan (not yet in lot_history)
  var plan = d.plan || [];
  var curLotGroups = {};
  plan.forEach(function(r){
    if (!r.lot || r.note === 'Wait next lot') return;
    if (!curLotGroups[r.lot]) curLotGroups[r.lot] = {target:0, actual:0, reels:0};
    curLotGroups[r.lot].target += r.target || 0;
    if (r.actual != null) curLotGroups[r.lot].actual += r.actual;
    curLotGroups[r.lot].reels += 1;
  });

  // Build unified list
  var seen = {};
  var rows = [];
  lots.forEach(function(L){
    seen[L.lot] = true;
    rows.push({
      lot: L.lot, input: L.input || 0, packed: L.packed || 0,
      reject: L.reject || 0, complete: true
    });
  });
  Object.keys(curLotGroups).forEach(function(lot){
    if (seen[lot]) return;
    var g = curLotGroups[lot];
    rows.push({
      lot: lot, input: g.target, packed: g.actual, reject: 0, complete: false
    });
  });

  if (!rows.length) { return; }
  var html = '';
  rows.forEach(function(L){
    var pct = L.input > 0 ? Math.min(100, L.packed/L.input*100) : 0;
    var cls = L.complete ? 'complete' : '';
    html += '<div class="lot-row ' + cls + '">' +
      '<div class="lot-head">' +
        '<span class="lot-name">Lot ' + L.lot + (L.complete ? ' ✓' : '') + '</span>' +
        '<span class="lot-pct">' + pct.toFixed(0) + '%</span>' +
      '</div>' +
      '<div class="lot-bar"><div class="lot-bar-fill" style="width:' + pct + '%"></div></div>' +
      '<div class="lot-foot">' +
        '<span>' + fmt(L.packed) + ' / ' + fmt(L.input) + ' pcs</span>' +
        '<span>' + (L.reject > 0 ? 'Reject: ' + fmt(L.reject) : '') + '</span>' +
      '</div>' +
      '</div>';
  });
  wrap.innerHTML = html;
  document.getElementById('lot-meta').textContent = rows.length + ' lots';
}

/* ═══════════════════════════════════════════════════════════════════
   CURRENT REEL INPUT CARD
   ═══════════════════════════════════════════════════════════════════ */
function showInputCard(row) {
  var boxLbl = row.box === 0 ? '📋 Remainder' : 'Box ' + row.box;
  document.getElementById('reel-title').textContent = boxLbl + ' · Reel R' + row.reel;
  document.getElementById('reel-meta').innerHTML =
    '<span class="tag">Lot <strong>' + (row.lot || '—') + '</strong></span>' +
    '<span class="tag">Target <strong>' + fmt(row.target) + '</strong></span>';
  document.getElementById('reel-meta-lot').textContent = 'Lot ' + (row.lot || '—');

  var actualIn = document.getElementById('actual-in');
  if (actualIn.dataset.reel !== String(row.reel)) {
    actualIn.value = row.target;
    document.getElementById('reject-in').value = 0;
    actualIn.dataset.reel = String(row.reel);
  }
  onInputChange();
}

function onInputChange() {
  if (!curReel) return;
  var actual = parseInt(document.getElementById('actual-in').value) || 0;
  var reject = parseInt(document.getElementById('reject-in').value) || 0;
  var diff   = actual - curTarget;
  var hint   = document.getElementById('diff-hint');
  var total  = actual + reject;
  if (total > curTarget) {
    hint.innerHTML = '<span style="color:var(--danger)">⛔ Overflow: +' + (total-curTarget).toLocaleString() + ' pcs exceeds target</span>';
  } else if (diff === 0) {
    hint.innerHTML = '<span style="color:var(--success)">✓ Exact match</span>';
  } else if (diff > 0) {
    hint.innerHTML = '<span style="color:var(--warn)">▲ Over by ' + diff.toLocaleString() + '</span>';
  } else {
    hint.innerHTML = '<span style="color:var(--danger)">▼ Under by ' + Math.abs(diff).toLocaleString() + '</span>';
  }
}

function adj(field, delta) {
  var id = field === 'actual' ? 'actual-in' : 'reject-in';
  var el = document.getElementById(id);
  el.value = Math.max(0, (parseInt(el.value) || 0) + delta);
  onInputChange();
}

function doConfirm() {
  if (!curReel) return;
  var actual = parseInt(document.getElementById('actual-in').value) || 0;
  var reject = parseInt(document.getElementById('reject-in').value) || 0;
  var msg = 'Submit Reel R' + curReel + '?\n\n' +
            'Actual : ' + actual.toLocaleString() + ' pcs\n' +
            'Reject : ' + reject.toLocaleString() + ' pcs\n' +
            'Target : ' + fmt(curTarget) + ' pcs';
  if (!confirm(msg)) return;
  sendSubmit(curReel, actual, reject);
}

function sendSubmit(reelNo, actual, reject) {
  var btn = document.getElementById('submit-btn');
  btn.disabled = true;
  var orig = btn.innerHTML;
  btn.innerHTML = 'Submitting…';
  fetch('http://' + location.hostname + ':' + API_PORT + '/api/reel/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reel_no: reelNo, actual: actual, reject: reject})
  })
  .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
  .then(function(res) {
    if (!res.ok || res.data.error) alert('Error: ' + (res.data.error || 'Server error'));
  })
  .catch(function(e) { alert('Network error: ' + e.message); btn.disabled = false; })
  .finally(function() { btn.innerHTML = orig; });
}

/* ═══════════════════════════════════════════════════════════════════
   PLAN TABLE
   ═══════════════════════════════════════════════════════════════════ */
function renderPlan(plan) {
  var html = '', prevBox = null;
  for (var i = 0; i < plan.length; i++) {
    var r = plan[i];
    if (prevBox !== null && r.box !== prevBox)
      html += '<tr class="sep-row"><td colspan="8"></td></tr>';
    prevBox = r.box;

    var cls = r.status === 'done'    ? 'done-row'
            : r.status === 'current' ? 'cur-row'
            : r.note === 'Wait next lot' ? 'wait-row'
            : r.box === 0 ? 'rem-row' : '';
    var boxLbl = r.box === 0 ? '📋 Rem' : 'Box ' + r.box;
    var act    = r.actual != null ? fmt(r.actual) : '—';
    var rej    = r.reject != null
               ? (r.reject > 0 ? '<span style="color:var(--danger);font-weight:700">' + fmt(r.reject) + '</span>' : '0')
               : '—';
    var diff = '—', dCls = 'zero';
    if (r.actual != null) {
      var dv = r.actual - r.target;
      if (dv === 0)      { diff = '0';                       dCls = 'zero'; }
      else if (dv > 0)   { diff = '+' + dv.toLocaleString(); dCls = 'pos';  }
      else               { diff = dv.toLocaleString();       dCls = 'neg';  }
    }
    var stTxt  = r.status === 'done'    ? '<span class="status-badge status-done">✓ Done</span>'
               : r.status === 'current' ? '<span class="status-badge status-cur">▶ Active</span>'
               : r.note   === 'Wait next lot' ? '<span class="status-badge status-wait">⏳ Wait</span>'
               : '<span class="status-badge status-pend">Pending</span>';
    var idAttr = r.status === 'current' ? 'id="cur-tr"' : '';
    html += '<tr class="' + cls + '" ' + idAttr + '>' +
      '<td>' + boxLbl + '</td>' +
      '<td>R' + r.reel + '</td>' +
      '<td>' + (r.lot || '—') + '</td>' +
      '<td>' + fmt(r.target) + '</td>' +
      '<td>' + act + '</td>' +
      '<td>' + rej + '</td>' +
      '<td><span class="diff-cell ' + dCls + '">' + diff + '</span></td>' +
      '<td>' + stTxt + '</td>' +
      '</tr>';
  }
  document.getElementById('tbody').innerHTML = html;
  document.getElementById('plan-meta').textContent = plan.length + ' reels';
  var curTr = document.getElementById('cur-tr');
  if (curTr) curTr.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

/* ═══════════════════════════════════════════════════════════════════
   CLOCK
   ═══════════════════════════════════════════════════════════════════ */
function tickClock() {
  var d = new Date();
  var hh = String(d.getHours()).padStart(2,'0');
  var mm = String(d.getMinutes()).padStart(2,'0');
  var ss = String(d.getSeconds()).padStart(2,'0');
  document.getElementById('clock').textContent = hh + ':' + mm + ':' + ss;
}
setInterval(tickClock, 1000); tickClock();

/* ═══ BOOTSTRAP ═══════════════════════════════════════════════════ */
connect();
</script>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════
#  HTTP HANDLER  (stdlib, no FastAPI)
# ════════════════════════════════════════════════════════════════════

class _HttpHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for REST API and HTML serving."""

    live_srv = None  # set by LiveServer after creation

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            srv = _HttpHandler.live_srv
            if self.path in ("/", "/index.html"):
                self._send_html(srv._html if srv else "")
                return
            if self.path == "/health":
                # Lightweight probe — no lock contention, no state required
                has_plan = bool(
                    srv and srv._monitor_page
                    and getattr(srv._monitor_page, "_has_plan", False)
                ) if srv else False
                client_count = len(srv._manager._clients) if srv else 0
                self._send_json({
                    "ok":           True,
                    "service":      "AutoPack LiveServer",
                    "status":       "running",
                    "has_plan":     has_plan,
                    "ws_clients":   client_count,
                    "http_port":    srv._http_port if srv else None,
                    "ws_port":      srv._ws_port   if srv else None,
                    "timestamp":    datetime.now().isoformat(),
                })
                return
            if self.path == "/api/urls":
                # Tell the client all addresses this server accepts
                if srv:
                    self._send_json(srv.get_urls())
                else:
                    self._send_json({"error": "server not initialized"}, 503)
                return
            if self.path == "/api/state":
                mp = srv._monitor_page if srv else None
                if mp and getattr(mp, "_has_plan", False):
                    self._send_json(mp.get_web_state())
                else:
                    self._send_json(get_live_data())
                return
            if self.path == "/api/plan":
                mp = srv._monitor_page if srv else None
                if mp and getattr(mp, "_has_plan", False):
                    self._send_json({"plan": mp.get_web_state().get("plan", [])})
                else:
                    self._send_json({"plan": []})
                return
            self.send_response(404)
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            _log.debug("HTTP GET error: %s", e)

    def do_POST(self):
        try:
            srv = _HttpHandler.live_srv
            if self.path == "/api/reel/submit":
                length = int(self.headers.get("Content-Length", 0))
                if length > 4096:
                    self._send_json({"error": "Payload too large"}, 413)
                    return
                raw = self.rfile.read(length)
                body = json.loads(raw)
                reel_no = int(body.get("reel_no", 0))
                actual  = int(body.get("actual",  0))
                reject  = int(body.get("reject",  0))
                if reel_no <= 0 or actual < 0 or reject < 0:
                    self._send_json({"error": "Invalid values: reel_no must be >0, actual/reject must be >=0"}, 400)
                    return
                if actual > 9_999_999 or reject > 9_999_999:
                    self._send_json({"error": "Values out of range (max 9,999,999)"}, 400)
                    return
                mp = srv._monitor_page if srv else None
                if not (mp and getattr(mp, "_has_plan", False)):
                    self._send_json({"error": "No active plan"}, 400)
                    return
                ev     = threading.Event()
                holder: dict = {}
                _submit_queue.put((reel_no, actual, reject, ev, holder))
                ok = ev.wait(timeout=15.0)
                if not ok:
                    self._send_json({"error": "Qt processing timeout"}, 504)
                    return
                if holder.get("success"):
                    self._send_json({"ok": True, "message": holder.get("message", "")})
                else:
                    self._send_json({"error": holder.get("error", "Failed")}, 400)
                return
            if self.path == "/api/replan":
                ev     = threading.Event()
                holder: dict = {}
                _submit_queue.put(("__replan__", 0, 0, ev, holder))
                ev.wait(timeout=8.0)
                self._send_json({"ok": holder.get("success", False)})
                return
            self.send_response(404)
            self.end_headers()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            _log.debug("HTTP POST error: %s", e)
            try:
                self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    def log_message(self, format, *args):  # noqa: A002
        pass


# ════════════════════════════════════════════════════════════════════
#  WEBSOCKET MANAGER
# ════════════════════════════════════════════════════════════════════

class _WsManager:
    def __init__(self):
        self._clients: set = set()
        self._lock = asyncio.Lock()

    async def register(self, ws):
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws):
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data, ensure_ascii=False, default=str)
        async with self._lock:
            dead = set()
            for client in list(self._clients):
                try:
                    await client.send(msg)
                except Exception:
                    dead.add(client)
            self._clients -= dead


# ════════════════════════════════════════════════════════════════════
#  LIVE SERVER
# ════════════════════════════════════════════════════════════════════

class LiveServer:
    """
    Interactive LAN monitor server.

    Usage (from main.py):
        server = LiveServer(monitor_page_ref, config, logger)
        server.start()
        # later:
        server.stop()

    MonitorPage calls:
        server.broadcast(state_dict)   # push state to all WS clients
    """

    _WS_PORT   = 8001   # WebSocket
    _HTTP_PORT = 8000   # HTTP (UI + REST)

    def __init__(self, monitor_page, config, logger, port: int = 8000):
        self._monitor_page = monitor_page
        self._config  = config
        self._logger  = logger
        self._http_port = port
        self._ws_port   = port + 1          # e.g. 8001 for port=8000
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager = _WsManager()
        self._http_server: HTTPServer | None = None
        self._ws_stop_event: asyncio.Event | None = None
        self._html = _WEB_HTML.replace("__WS_PORT__", str(self._ws_port)
                               ).replace("__API_PORT__", str(self._http_port))

    # ── Public API ────────────────────────────────────────────────

    def start(self):
        if not _WS_OK:
            msg = ("websockets package not installed — "
                   "LAN remote-monitor is DISABLED.  "
                   "Install with:  pip install websockets")
            if self._logger:
                self._logger.warning(msg)
            else:
                print(f"[LiveServer] {msg}")
            return False
        if self._running:
            if self._logger:
                self._logger.info("LiveServer already running — ignoring start()")
            return True

        self._running = True

        # Register self in HTTP handler
        _HttpHandler.live_srv = self

        # ── HTTP server ───────────────────────────────────────────
        try:
            self._http_server = HTTPServer(("0.0.0.0", self._http_port),
                                           _HttpHandler)
        except OSError as e:
            self._running = False
            err = (f"LiveServer HTTP bind failed on port {self._http_port}: "
                   f"{e.strerror or e}")
            if self._logger:
                self._logger.error(err)
                self._logger.error("  → Another app may already own this port.  "
                                   "Close it or change the port argument.")
            else:
                print(f"[LiveServer] {err}")
            return False

        threading.Thread(
            target=self._http_server.serve_forever,
            daemon=True, name="LiveServer-HTTP").start()

        # ── WebSocket server ──────────────────────────────────────
        self._loop = asyncio.new_event_loop()
        threading.Thread(
            target=self._run_ws_loop,
            daemon=True, name="LiveServer-WS").start()

        # ── User-facing diagnostics ───────────────────────────────
        urls = self.get_urls()
        banner = [
            "",
            "╔══════════════════════════════════════════════════════════╗",
            "║           AutoPack LAN Monitor — READY                  ║",
            "╠══════════════════════════════════════════════════════════╣",
            f"║  On this PC    :  {urls['localhost']:<40s}║",
            f"║  From LAN/WiFi :  {urls['lan']:<40s}║",
            f"║  WebSocket     :  {urls['ws']:<40s}║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
        ]
        if self._logger:
            for line in banner:
                self._logger.info(line)
            self._logger.info(
                f"LAN Monitor ready — {urls['lan']}  (also {urls['localhost']})")
        else:
            print("\n".join(banner))

        return True

    def stop(self):
        self._running = False
        if self._http_server:
            self._http_server.shutdown()
        if self._loop and self._ws_stop_event:
            self._loop.call_soon_threadsafe(self._ws_stop_event.set)

    def broadcast(self, state: dict):
        """Push state dict to all connected WebSocket clients. Thread-safe."""
        if not self._running:
            return
        if not self._loop:
            if self._logger:
                self._logger.warning("broadcast() called but event loop is not ready")
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._manager.broadcast(state), self._loop)
        except RuntimeError as e:
            # loop was closed between checks
            if self._logger:
                self._logger.warning(f"broadcast skipped (loop closed): {e}")
        except Exception as e:
            if self._logger:
                self._logger.error(f"broadcast error: {type(e).__name__}: {e}")

    def update_monitor_page(self, monitor_page):
        """Call after MonitorPage widget is rebuilt (lot/order complete)."""
        self._monitor_page = monitor_page

    # ── Internal ──────────────────────────────────────────────────

    def _host_ip(self) -> str:
        """Return the best LAN IP for this host.

        Tries (in order):
          1. UDP connect to public DNS  → routed iface
          2. UDP connect to LAN gateway → works when offline (no internet)
          3. Enumerate all interfaces, pick first private IP
          4. socket.gethostbyname(hostname)
          5. Fallback to 'localhost'
        """
        # Strategy 1 & 2: UDP connect trick (doesn't actually send)
        for target in (("8.8.8.8", 80), ("192.168.1.1", 80), ("192.168.0.1", 80),
                           ("10.0.0.1", 80), ("172.16.0.1", 80)):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                s.connect(target)
                ip = s.getsockname()[0]
                s.close()
                if ip and not ip.startswith("127."):
                    return ip
            except Exception:
                pass

        # Strategy 3: Enumerate all hostname-bound IPs, pick private ones
        try:
            hostname = socket.gethostname()
            _, _, ips = socket.gethostbyname_ex(hostname)
            # Prefer 192.168.*  →  10.*  →  172.16-31.*
            def _rank(ip: str) -> int:
                if ip.startswith("192.168."): return 0
                if ip.startswith("10."):      return 1
                if ip.startswith("172."):
                    try:
                        oct2 = int(ip.split(".")[1])
                        if 16 <= oct2 <= 31:  return 2
                    except (ValueError, IndexError):
                        pass
                if ip.startswith("127."):     return 99
                return 50
            private = sorted([ip for ip in ips if not ip.startswith("127.")],
                             key=_rank)
            if private:
                return private[0]
        except Exception:
            pass

        # Strategy 4 & 5
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "localhost"

    def get_host_ip(self) -> str:
        """Public accessor — cached on first call."""
        if not hasattr(self, "_cached_ip") or self._cached_ip is None:
            self._cached_ip = self._host_ip()
        return self._cached_ip

    def get_urls(self) -> dict:
        """Return all URLs clients can use to reach the monitor."""
        ip = self.get_host_ip()
        return {
            "lan":       f"http://{ip}:{self._http_port}",
            "localhost": f"http://localhost:{self._http_port}",
            "ws":        f"ws://{ip}:{self._ws_port}/ws",
            "ip":        ip,
            "http_port": self._http_port,
            "ws_port":   self._ws_port,
        }

    def _run_ws_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._ws_main())
        self._loop.close()

    async def _ws_main(self):
        self._ws_stop_event = asyncio.Event()
        manager = self._manager

        async def handler(ws):
            await manager.register(ws)
            try:
                mp = self._monitor_page
                if mp and getattr(mp, "_has_plan", False):
                    init_state = mp.get_web_state()
                else:
                    init_state = get_live_data()
                await ws.send(json.dumps(init_state, ensure_ascii=False, default=str))
                async for msg in ws:
                    if msg == "ping":
                        await ws.send("pong")
            except Exception:
                pass
            finally:
                await manager.unregister(ws)

        async def _keepalive():
            # Ping clients every 30s — prevents NAT/firewall from dropping idle connections
            while not self._ws_stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._ws_stop_event.wait()), timeout=30)
                except asyncio.TimeoutError:
                    await manager.broadcast({"type": "ping"})

        async with ws_serve(handler, "0.0.0.0", self._ws_port):
            await asyncio.gather(
                self._ws_stop_event.wait(),
                _keepalive(),
                return_exceptions=True,
            )


# ════════════════════════════════════════════════════════════════════
#  BACKWARD-COMPAT — legacy HTTP server (port 5050)
#  + AUTO-UPGRADE to new LiveServer (port 8765 + 8766)
# ════════════════════════════════════════════════════════════════════

_legacy_server_instance: HTTPServer | None = None
_auto_live_server: LiveServer | None = None


class _LegacyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == "/api/data":
                body = json.dumps(get_live_data(),
                                  ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            else:
                # Build a redirect page pointing to whatever LAN IP we have
                ip = "localhost"
                if _auto_live_server is not None:
                    try:
                        ip = _auto_live_server.get_host_ip()
                    except Exception:
                        pass
                live_port = 8000
                if _auto_live_server is not None:
                    try:
                        live_port = _auto_live_server._http_port
                    except Exception:
                        pass
                body = (
                    f"<html><body style='font-family:sans-serif;"
                    f"text-align:center;padding:60px;background:#0F172A;"
                    f"color:#F1F5F9'>"
                    f"<h2>AutoPack Live Monitor</h2>"
                    f"<p style='margin:16px 0;color:#94A3B8'>"
                    f"Interactive monitor is now on port {live_port}.</p>"
                    f"<a href='http://{ip}:{live_port}' "
                    f"style='font-size:18px;color:#3B82F6'>"
                    f"Open Monitor &rarr;</a><br><br>"
                    f"<small style='color:#64748B'>"
                    f"From another device on your LAN, use "
                    f"<code>http://{ip}:{live_port}</code></small>"
                    f"</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, format, *args):  # noqa: A002
        pass


def start_live_server(port: int = 5050,
                      monitor_page=None,
                      config=None,
                      logger=None,
                      live_port: int = 8000):
    """
    Start both the legacy redirect (:5050) and the new LiveServer (:8000 HTTP + :8001 WS).

    Call sites:
      • Old main.py  :  start_live_server()                    → legacy only (same as before)
      • New main.py  :  start_live_server(monitor_page=mp,
                                          config=cfg, logger=lg)
                        → legacy + full interactive LiveServer

    Returns the LiveServer instance (or None if not started).
    """
    global _legacy_server_instance, _auto_live_server

    # ── 1. Legacy redirect server (unchanged behavior) ───────────
    if _legacy_server_instance is None:
        try:
            _legacy_server_instance = HTTPServer(
                ("0.0.0.0", port), _LegacyHandler)
            threading.Thread(
                target=_legacy_server_instance.serve_forever,
                daemon=True, name="LegacyLiveServer").start()
            if logger:
                logger.info(f"Legacy dashboard: http://localhost:{port}  "
                            f"→  redirects to :{live_port}")
        except OSError as e:
            _legacy_server_instance = None
            if logger:
                logger.warning(f"Legacy server bind failed on :{port} — {e}")

    # ── 2. New interactive LiveServer ────────────────────────────
    if monitor_page is not None and _auto_live_server is None:
        try:
            _auto_live_server = LiveServer(
                monitor_page, config, logger, port=live_port)
            started = _auto_live_server.start()
            if started:
                # Link MonitorPage → server so broadcasts work
                try:
                    monitor_page.set_live_server(_auto_live_server)
                except AttributeError:
                    if logger:
                        logger.warning(
                            "monitor_page has no set_live_server() method — "
                            "broadcasts will not be forwarded")
            else:
                _auto_live_server = None
        except Exception as e:
            _auto_live_server = None
            if logger:
                logger.error(f"LiveServer failed to start: {type(e).__name__}: {e}")

    return _auto_live_server


def get_live_server() -> "LiveServer | None":
    """Return the auto-started LiveServer instance (or None)."""
    return _auto_live_server


def check_firewall_ports(http_port: int = 8000, ws_port: int = 8001) -> dict:
    """
    Test whether the LAN ports are reachable (can bind on 0.0.0.0).
    Returns dict with 'http_ok', 'ws_ok', 'error'.
    Call this from startup diagnostics — does NOT open firewall rules.
    """
    import socket as _sock
    result = {"http_ok": False, "ws_ok": False, "error": ""}
    for port, key in ((http_port, "http_ok"), (ws_port, "ws_ok")):
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.close()
            result[key] = True
        except OSError as e:
            result["error"] += f"Port {port}: {e.strerror}. "
    return result



def stop_live_server():
    global _legacy_server_instance, _auto_live_server
    if _legacy_server_instance:
        try:
            _legacy_server_instance.shutdown()
        except Exception:
            pass
        _legacy_server_instance = None
    if _auto_live_server:
        try:
            _auto_live_server.stop()
        except Exception:
            pass
        _auto_live_server = None