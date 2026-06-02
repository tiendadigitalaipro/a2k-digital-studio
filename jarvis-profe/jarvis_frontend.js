/**
 * ╔══════════════════════════════════════════════════════════════════════════╗
 * ║  jarvis_frontend.js — JARVIS MENTE MAESTRA v4.0                        ║
 * ║  Módulo de voz, chat y audio para Bodega Pro IA                        ║
 * ║  A2K Digital Studio                                                    ║
 * ╠══════════════════════════════════════════════════════════════════════════╣
 * ║  INTEGRACIÓN RÁPIDA:                                                   ║
 * ║    <div id="jarvis-chat"></div>                                         ║
 * ║    <script src="jarvis_frontend.js"></script>                           ║
 * ║                                                                         ║
 * ║  CON OPCIONES:                                                          ║
 * ║    JarvisChat.init("#mi-div", { host: "http://192.168.10.3:5000",      ║
 * ║                                  tipo: "tecnico_aires" })               ║
 * ╚══════════════════════════════════════════════════════════════════════════╝
 *
 * NOTA HTTPS:
 *   SpeechRecognition solo funciona en HTTPS o en localhost.
 *   Si accedes desde una tablet/celular en la red local (http://192.168.x.x),
 *   el micrófono usará el modo texto como fallback automático.
 */

(function (global) {
  "use strict";

  /* ══════════════════════════════════════════════════════════════════════════
     CONFIGURACIÓN — edita JARVIS_HOST con la IP de tu servidor
  ══════════════════════════════════════════════════════════════════════════ */
   const CFG = {
     host:         window.location.origin,  // ← Origen actual (local o producción)
     tipo:         "bodega",                     // "bodega" | "tecnico_aires"
     idioma:       "es-VE",                      // idioma SpeechRecognition
     timeoutFetch: 20000,                        // ms máximos esperando al servidor
     timeoutAudio: 8000,                         // ms máximos para el endpoint /voz
     pingInterval: 30000,                        // ms entre pings de heartbeat
   };

  const EP = {
    bodega:  () => `${CFG.host}/bodega`,
    tecnico: () => `${CFG.host}/tecnico`,
    voz:     () => `${CFG.host}/voz`,
    ping:    () => `${CFG.host}/ping`,
  };

  /* ══════════════════════════════════════════════════════════════════════════
     ESTADO GLOBAL
  ══════════════════════════════════════════════════════════════════════════ */
   const S = {
     listening:  false,
     processing: false,
     speaking:   false,
     online:     false,
     moneda:     "VES",
     cart:       [],     // Carrito de compras: [{id, name, price, quantity}]
     rec:        null,   // SpeechRecognition instance
     audio:      null,   // HTMLAudioElement en curso
     pingTimer:  null,
   };

  /* ══════════════════════════════════════════════════════════════════════════
     CSS INYECTADO — sin hoja externa, listo para embeber
  ══════════════════════════════════════════════════════════════════════════ */
  const STYLES = `
    :root {
      --jv-bg:      #07090f;
      --jv-bg2:     #0d1117;
      --jv-cyan:    #00ffcc;
      --jv-cyan-d:  #005c55;
      --jv-green:   #00c853;
      --jv-amber:   #ffab00;
      --jv-red:     #ff5252;
      --jv-blue:    #40c4ff;
      --jv-gray:    #334155;
      --jv-text:    #cfd8e3;
      --jv-radius:  14px;
      --jv-font:    'Segoe UI', system-ui, sans-serif;
    }

    /* ── Panel raíz ──────────────────────────────────────────────────────── */
    #jv-root {
      display: flex;
      flex-direction: column;
      width: 100%;
      max-width: 480px;
      height: 680px;
      background: var(--jv-bg);
      border: 1px solid var(--jv-cyan-d);
      border-radius: var(--jv-radius);
      overflow: hidden;
      font-family: var(--jv-font);
      box-shadow: 0 0 40px rgba(0,255,204,0.08);
    }

    /* ── Card de Analítica BI ────────────────────────────────────────────── */
    #jv-analytics-card {
      display: none;                   /* visible solo cuando hay datos */
      align-items: center;
      gap: 14px;
      padding: 10px 14px;
      background: var(--jv-bg2);
      border-bottom: 1px solid rgba(0,255,204,0.09);
      flex-shrink: 0;
    }
    #jv-analytics-card.visible { display: flex; }
    #jv-analytics-canvas { width:72px; height:72px; flex-shrink:0; }

    .jv-bi-stats { display:flex; flex-direction:column; gap:5px; flex:1; min-width:0; }
    .jv-bi-stat  {
      display: flex; align-items: center; gap: 6px;
      font-size: 11px; color: var(--jv-text);
    }
    .jv-bi-dot  { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
    .jv-bi-pct  { font-weight:700; font-size:12px; }
    .jv-bi-lbl  { color:var(--jv-gray); font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .jv-bi-alert {
      font-size:10px; font-weight:700; color: var(--jv-amber);
      background: rgba(245,158,11,.12); border: 1px solid rgba(245,158,11,.3);
      border-radius: 5px; padding: 2px 7px; white-space:nowrap;
    }
    .jv-bi-stock { font-size:10px; color:var(--jv-red); font-weight:600; }
    #jv-bi-refresh {
      background:none; border:none; color:var(--jv-gray);
      cursor:pointer; font-size:14px; padding:0 2px; flex-shrink:0;
      transition: color .2s;
    }
    #jv-bi-refresh:hover { color:var(--jv-cyan); }

    /* ── Pestañas Chat / Fiado ───────────────────────────────────────────── */
    #jv-tabs { display:flex; flex-shrink:0; background:var(--jv-bg2);
               border-bottom:1px solid rgba(0,255,204,.08); }
    .jv-tab  { flex:1; padding:8px 4px; background:none; border:none;
               border-bottom:2px solid transparent; color:var(--jv-gray);
               font-size:11px; font-weight:600; cursor:pointer; letter-spacing:.3px;
               transition:color .2s, border-color .2s; font-family:var(--jv-font); }
    .jv-tab.active          { color:var(--jv-cyan); border-bottom-color:var(--jv-cyan); }
    .jv-tab:hover:not(.active){ color:var(--jv-text); }

    /* ── Panel de clientes (Fiado) ───────────────────────────────────────── */
    #jv-clientes-panel { flex:1; overflow-y:auto; padding:10px 12px;
                         display:none; flex-direction:column; gap:8px; }
    #jv-clientes-panel.visible { display:flex; }
    #jv-clientes-panel::-webkit-scrollbar { width:4px; }
    #jv-clientes-panel::-webkit-scrollbar-thumb { background:var(--jv-gray); border-radius:4px; }

    .jv-cliente-card {
      background:var(--jv-bg2); border:1px solid rgba(0,255,204,.08);
      border-radius:12px; padding:10px 13px;
      display:flex; align-items:center; gap:10px; cursor:pointer;
      transition:border-color .2s, background .2s;
    }
    .jv-cliente-card:hover    { border-color:rgba(0,255,204,.22); }
    .jv-cliente-card.bloqueado{ border-color:rgba(239,68,68,.3);  background:rgba(239,68,68,.04); }
    .jv-cliente-card.mora     { border-color:rgba(245,158,11,.3); background:rgba(245,158,11,.03); }

    .jv-cli-avatar {
      width:36px; height:36px; border-radius:50%; flex-shrink:0;
      display:flex; align-items:center; justify-content:center;
      font-size:14px; font-weight:700;
      background:rgba(0,255,204,.10); color:var(--jv-cyan);
    }
    .jv-cliente-card.bloqueado .jv-cli-avatar { background:rgba(239,68,68,.12); color:#ef4444; }
    .jv-cliente-card.mora      .jv-cli-avatar { background:rgba(245,158,11,.12); color:#f59e0b; }

    .jv-cli-info    { flex:1; min-width:0; }
    .jv-cli-nombre  { font-size:13px; font-weight:600; color:var(--jv-text);
                      overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .jv-cli-saldo   { font-size:11px; color:var(--jv-gray); margin-top:2px; }

    .jv-cli-badge   { font-size:9px; font-weight:700; padding:3px 8px;
                      border-radius:12px; flex-shrink:0; letter-spacing:.4px; }
    .jv-badge-bloqueado { background:rgba(239,68,68,.15); color:#ef4444; border:1px solid rgba(239,68,68,.3); }
    .jv-badge-mora      { background:rgba(245,158,11,.15); color:#f59e0b; border:1px solid rgba(245,158,11,.3); }
    .jv-badge-ok        { background:rgba(6,214,160,.10);  color:#06d6a0; border:1px solid rgba(6,214,160,.25); }

    #jv-clientes-empty   { text-align:center; color:var(--jv-gray); font-size:12px;
                           padding:30px 0; display:none; }
    #jv-clientes-reload  { align-self:flex-end; background:none; font-family:var(--jv-font);
                           border:1px solid var(--jv-gray); border-radius:8px;
                           color:var(--jv-gray); font-size:11px; padding:4px 10px;
                           cursor:pointer; margin-bottom:4px; transition:color .2s, border-color .2s; }
    #jv-clientes-reload:hover { color:var(--jv-cyan); border-color:var(--jv-cyan); }

    /* ── Barra superior ──────────────────────────────────────────────────── */
    #jv-topbar {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      background: var(--jv-bg2);
      border-bottom: 1px solid var(--jv-cyan-d);
      flex-shrink: 0;
    }
    #jv-logo {
      font-size: 14px;
      font-weight: 700;
      color: var(--jv-cyan);
      letter-spacing: 1px;
      margin-right: auto;
    }
    #jv-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--jv-gray);
      transition: background .4s;
      flex-shrink: 0;
    }
    #jv-dot.online  { background: var(--jv-green); box-shadow: 0 0 6px var(--jv-green); }
    #jv-dot.offline { background: var(--jv-red);   box-shadow: 0 0 6px var(--jv-red); }

    #jv-moneda-badge {
      font-size: 10px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 20px;
      background: var(--jv-cyan-d);
      color: var(--jv-cyan);
      letter-spacing: .5px;
      transition: background .3s, color .3s;
    }
    #jv-moneda-badge.usd { background: #1a3a2a; color: var(--jv-green); }

    #jv-tipo-sel {
      font-size: 11px;
      background: var(--jv-bg);
      color: var(--jv-text);
      border: 1px solid var(--jv-gray);
      border-radius: 8px;
      padding: 3px 6px;
      cursor: pointer;
      outline: none;
    }

    /* ── Área de chat ─────────────────────────────────────────────────────── */
    #jv-chat {
      flex: 1;
      overflow-y: auto;
      padding: 14px 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      scroll-behavior: smooth;
    }
    #jv-chat::-webkit-scrollbar { width: 4px; }
    #jv-chat::-webkit-scrollbar-track { background: transparent; }
    #jv-chat::-webkit-scrollbar-thumb { background: var(--jv-gray); border-radius: 4px; }

    /* ── Burbujas ─────────────────────────────────────────────────────────── */
    .jv-row {
      display: flex;
      flex-direction: column;
      max-width: 86%;
    }
    .jv-row.user    { align-self: flex-end;  align-items: flex-end; }
    .jv-row.jarvis  { align-self: flex-start; align-items: flex-start; }

    .jv-bubble {
      padding: 9px 13px;
      border-radius: var(--jv-radius);
      font-size: 13.5px;
      line-height: 1.55;
      word-break: break-word;
    }
    .jv-row.user   .jv-bubble {
      background: #0e3a33;
      color: #d0fff5;
      border-bottom-right-radius: 4px;
    }
    .jv-row.jarvis .jv-bubble {
      background: var(--jv-bg2);
      color: var(--jv-text);
      border: 1px solid #1e2a3a;
      border-bottom-left-radius: 4px;
    }
    .jv-bubble strong { color: var(--jv-cyan); font-weight: 600; }

    .jv-time {
      font-size: 10px;
      color: var(--jv-gray);
      margin-top: 3px;
      padding: 0 4px;
    }

    /* Badge moneda por burbuja */
    .jv-tag {
      display: inline-block;
      font-size: 9px;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 4px;
      margin-left: 6px;
      vertical-align: middle;
    }
    .jv-tag.ves { background: #1a2a3a; color: var(--jv-blue); }
    .jv-tag.usd { background: #1a3a2a; color: var(--jv-green); }

    /* Burbuja de "escribiendo" */
    .jv-typing .jv-dot-anim {
      display: inline-flex;
      gap: 4px;
      align-items: center;
      height: 18px;
    }
    .jv-typing .jv-dot-anim span {
      display: block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--jv-cyan);
      animation: jv-bounce .9s infinite ease-in-out;
    }
    .jv-typing .jv-dot-anim span:nth-child(2) { animation-delay: .15s; }
    .jv-typing .jv-dot-anim span:nth-child(3) { animation-delay: .30s; }
    @keyframes jv-bounce {
      0%, 80%, 100% { transform: scale(.6); opacity: .4; }
      40%            { transform: scale(1);  opacity: 1; }
    }

    /* ── Barra de estado ──────────────────────────────────────────────────── */
    #jv-status {
      font-size: 11px;
      text-align: center;
      padding: 5px 12px;
      min-height: 22px;
      color: var(--jv-gray);
      transition: color .3s;
      flex-shrink: 0;
    }
    #jv-status.listening { color: var(--jv-red);   animation: jv-pulse 1.2s infinite; }
    #jv-status.processing{ color: var(--jv-amber); }
    #jv-status.speaking  { color: var(--jv-cyan);  }
    #jv-status.error     { color: var(--jv-red);   }
    @keyframes jv-pulse  { 0%,100%{opacity:1} 50%{opacity:.45} }

    /* ── Controles inferiores ─────────────────────────────────────────────── */
    #jv-controls {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: var(--jv-bg2);
      border-top: 1px solid var(--jv-cyan-d);
      flex-shrink: 0;
    }

    #jv-mic {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      border: 2px solid var(--jv-cyan-d);
      background: var(--jv-bg);
      color: var(--jv-cyan);
      font-size: 18px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: border-color .2s, background .2s, box-shadow .2s;
    }
    #jv-mic:hover  { border-color: var(--jv-cyan); box-shadow: 0 0 10px rgba(0,255,204,.3); }
    #jv-mic.active { background: #1a0a0a; border-color: var(--jv-red);
                     box-shadow: 0 0 14px rgba(255,82,82,.5);
                     animation: jv-pulse 1s infinite; }
    #jv-mic:disabled { opacity: .4; cursor: not-allowed; }

    #jv-input {
      flex: 1;
      background: var(--jv-bg);
      border: 1px solid var(--jv-gray);
      border-radius: 10px;
      color: var(--jv-text);
      font-size: 13.5px;
      padding: 9px 12px;
      outline: none;
      transition: border-color .2s;
    }
    #jv-input:focus   { border-color: var(--jv-cyan-d); }
    #jv-input::placeholder { color: #3a4a5a; }

    #jv-send {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      border: none;
      background: var(--jv-cyan-d);
      color: var(--jv-cyan);
      font-size: 16px;
      cursor: pointer;
      flex-shrink: 0;
      transition: background .2s;
    }
    #jv-send:hover    { background: #007a70; }
    #jv-send:disabled { opacity: .4; cursor: not-allowed; }

    /* ── Divisas P2P ──────────────────────────────────────────────────────── */
    #jv-divisas-panel {
      flex:1; overflow-y:auto; padding:12px;
      display:none; flex-direction:column; gap:10px;
    }
    #jv-divisas-panel.visible { display:flex; }
    #jv-divisas-panel::-webkit-scrollbar { width:4px; }
    #jv-divisas-panel::-webkit-scrollbar-thumb { background:var(--jv-gray); border-radius:4px; }

    .jv-rate-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .jv-rate-card {
      background:var(--jv-bg2); border:1px solid rgba(0,255,204,.1);
      border-radius:12px; padding:14px 12px;
      display:flex; flex-direction:column; gap:4px;
    }
    .jv-rate-card.spread-ok   { border-color:rgba(0,200,83,.25);  background:rgba(0,200,83,.03); }
    .jv-rate-card.spread-warn { border-color:rgba(255,170,0,.3);  background:rgba(255,170,0,.04); }
    .jv-rate-card.spread-hi   { border-color:rgba(255,82,82,.35); background:rgba(255,82,82,.05); }
    .jv-rate-lbl {
      font-size:9px; font-weight:700; letter-spacing:.5px;
      text-transform:uppercase; color:var(--jv-gray);
    }
    .jv-rate-val {
      font-size:22px; font-weight:700; color:var(--jv-cyan);
      font-variant-numeric:tabular-nums; line-height:1;
    }
    .jv-rate-sub { font-size:10px; color:var(--jv-gray); margin-top:2px; }
    .jv-rate-card.spread-ok   .jv-rate-val { color:var(--jv-green); }
    .jv-rate-card.spread-warn .jv-rate-val { color:var(--jv-amber); }
    .jv-rate-card.spread-hi   .jv-rate-val { color:var(--jv-red);   }

    .jv-mes-card {
      background:var(--jv-bg2); border:1px solid rgba(0,255,204,.07);
      border-radius:12px; padding:12px;
    }
    .jv-mes-title {
      font-size:10px; font-weight:700; color:var(--jv-gray);
      letter-spacing:.4px; text-transform:uppercase; margin-bottom:10px;
    }
    .jv-mes-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; }
    .jv-mes-stat { display:flex; flex-direction:column; align-items:center; gap:2px; }
    .jv-mes-val  { font-size:14px; font-weight:700; color:var(--jv-green); }
    .jv-mes-lbl  { font-size:9px; color:var(--jv-gray); text-align:center; }

    .jv-panel-reload {
      align-self:flex-end; background:none; font-family:var(--jv-font);
      border:1px solid var(--jv-gray); border-radius:8px;
      color:var(--jv-gray); font-size:11px; padding:4px 10px;
      cursor:pointer; transition:color .2s, border-color .2s;
    }
    .jv-panel-reload:hover { color:var(--jv-cyan); border-color:var(--jv-cyan); }

    #jv-divisas-empty {
      text-align:center; color:var(--jv-gray); font-size:12px;
      padding:30px 0; display:none;
    }

    /* ── Importaciones ────────────────────────────────────────────────────── */
    #jv-importaciones-panel {
      flex:1; overflow-y:auto; padding:10px 12px;
      display:none; flex-direction:column; gap:8px;
    }
    #jv-importaciones-panel.visible { display:flex; }
    #jv-importaciones-panel::-webkit-scrollbar { width:4px; }
    #jv-importaciones-panel::-webkit-scrollbar-thumb { background:var(--jv-gray); border-radius:4px; }

    .jv-ped-card {
      background:var(--jv-bg2); border:1px solid rgba(0,255,204,.08);
      border-radius:12px; padding:12px;
      display:flex; flex-direction:column; gap:8px;
      transition:border-color .2s;
    }
    .jv-ped-card:hover   { border-color:rgba(0,255,204,.2); }
    .jv-ped-card.recibido    { border-left:3px solid var(--jv-green); }
    .jv-ped-card.en_transito { border-left:3px solid var(--jv-blue); }
    .jv-ped-card.en_aduana   { border-left:3px solid var(--jv-amber); }
    .jv-ped-card.cotizando   { border-left:3px solid var(--jv-gray); }
    .jv-ped-card.pagado      { border-left:3px solid var(--jv-cyan); }

    .jv-ped-header { display:flex; align-items:center; gap:8px; }
    .jv-ped-id {
      font-size:11px; font-weight:700; color:var(--jv-cyan);
      font-family:'Consolas', monospace; flex:1;
    }
    .jv-ped-badge {
      font-size:9px; font-weight:700; padding:2px 7px;
      border-radius:10px; letter-spacing:.3px;
    }
    .jv-badge-recibido  { background:rgba(0,200,83,.12); color:#00c853; border:1px solid rgba(0,200,83,.3); }
    .jv-badge-transito  { background:rgba(64,196,255,.12); color:#40c4ff; border:1px solid rgba(64,196,255,.3); }
    .jv-badge-aduana    { background:rgba(255,170,0,.12); color:#ffaa00; border:1px solid rgba(255,170,0,.3); }
    .jv-badge-cotizando { background:rgba(68,68,68,.3); color:#888; border:1px solid rgba(88,88,88,.4); }
    .jv-badge-pagado    { background:rgba(0,255,204,.1); color:var(--jv-cyan); border:1px solid rgba(0,255,204,.25); }

    .jv-ped-supplier { font-size:11px; color:var(--jv-gray); }

    .jv-ped-metrics { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; }
    .jv-ped-metric  {
      display:flex; flex-direction:column; gap:2px;
      background:rgba(255,255,255,.02); border-radius:8px; padding:6px 8px;
    }
    .jv-ped-mlbl { font-size:9px; color:var(--jv-gray); letter-spacing:.2px; }
    .jv-ped-mval { font-size:12px; font-weight:700; color:var(--jv-text); }

    .jv-ped-hero {
      display:grid; grid-template-columns:1fr 1fr; gap:8px;
      padding:10px; background:rgba(0,255,204,.03);
      border:1px solid rgba(0,255,204,.1); border-radius:10px;
    }
    .jv-ped-hero-item { display:flex; flex-direction:column; gap:3px; }
    .jv-ped-hero-lbl  {
      font-size:9px; color:var(--jv-gray);
      text-transform:uppercase; letter-spacing:.4px;
    }
    .jv-ped-hero-val       { font-size:18px; font-weight:700; color:var(--jv-cyan); font-variant-numeric:tabular-nums; }
    .jv-ped-hero-val.green { color:var(--jv-green); }
    .jv-ped-hero-val.muted { font-size:14px; color:var(--jv-text); }
    .jv-ped-hero-val.roi   { font-size:16px; }

    #jv-pedidos-empty {
      text-align:center; color:var(--jv-gray); font-size:12px;
      padding:30px 0; display:none;
    }
  `;

  /* ══════════════════════════════════════════════════════════════════════════
     HTML DEL PANEL
  ══════════════════════════════════════════════════════════════════════════ */
  const PANEL_HTML = `
    <div id="jv-topbar">
      <span id="jv-logo">&#9672; JARVIS</span>
      <div id="jv-dot" title="Estado del servidor Jarvis"></div>
      <span id="jv-moneda-badge">VES</span>
      <select id="jv-tipo-sel" title="Contexto de Jarvis">
        <option value="bodega">Bodega / Ferreteria</option>
        <option value="tecnico_aires">Servicio Tecnico</option>
      </select>
    </div>
    <div id="jv-analytics-card">
      <canvas id="jv-analytics-canvas"></canvas>
      <div class="jv-bi-stats">
        <div class="jv-bi-stat">
          <span class="jv-bi-dot" style="background:#10b981"></span>
          <span class="jv-bi-pct" id="jv-bi-pct-usd">0%</span>
          <span class="jv-bi-lbl">USD — Zinli / Wally</span>
        </div>
        <div class="jv-bi-stat">
          <span class="jv-bi-dot" style="background:#06d6a0"></span>
          <span class="jv-bi-pct" id="jv-bi-pct-ves">0%</span>
          <span class="jv-bi-lbl">VES — Bancos nacionales</span>
        </div>
        <div id="jv-bi-alert" style="display:none" class="jv-bi-alert">⚠ TASA DESVIADA</div>
        <div id="jv-bi-stock" style="display:none" class="jv-bi-stock"></div>
      </div>
      <button id="jv-bi-refresh" title="Actualizar analítica">&#8635;</button>
    </div>
    <div id="jv-tabs">
      <button class="jv-tab active" data-tab="chat">&#128172; Chat</button>
      <button class="jv-tab"        data-tab="fiado">&#128221; Fiado</button>
      <button class="jv-tab"        data-tab="divisas">&#128177; P2P</button>
      <button class="jv-tab"        data-tab="importaciones">&#128230; Import</button>
    </div>
    <div id="jv-chat"></div>
    <div id="jv-clientes-panel">
      <button id="jv-clientes-reload" class="jv-panel-reload">&#8635; Actualizar</button>
      <div id="jv-clientes-list"></div>
      <div id="jv-clientes-empty">Sin deudores activos</div>
    </div>
    <div id="jv-divisas-panel">
      <button id="jv-divisas-reload" class="jv-panel-reload">&#8635; Actualizar</button>
      <div class="jv-rate-grid" id="jv-rate-grid"></div>
      <div class="jv-mes-card" id="jv-mes-card" style="display:none">
        <div class="jv-mes-title">&#128197; Resumen del Mes</div>
        <div class="jv-mes-grid" id="jv-mes-grid"></div>
      </div>
      <div id="jv-divisas-empty">Sin datos. Escribe "tasa bcv 41.50" en Jarvis.</div>
    </div>
    <div id="jv-importaciones-panel">
      <button id="jv-pedidos-reload" class="jv-panel-reload">&#8635; Actualizar</button>
      <div id="jv-pedidos-list"></div>
      <div id="jv-pedidos-empty">Sin pedidos registrados aún.</div>
    </div>
    <div id="jv-status"></div>
    <div id="jv-controls">
      <button id="jv-mic" title="Hablar con Jarvis">&#127908;</button>
      <input  id="jv-input" type="text"
              placeholder="Escribe o usa el microfono..."
              autocomplete="off" spellcheck="true" />
      <button id="jv-send" title="Enviar">&#9654;</button>
    </div>
  `;

  /* ══════════════════════════════════════════════════════════════════════════
     FORMATEO DE TEXTO — *negrita* y saltos de línea
  ══════════════════════════════════════════════════════════════════════════ */
  /**
   * Convierte el formato WhatsApp de Jarvis a HTML seguro para el navegador.
   * - *texto* → <strong>texto</strong>  (montos, refs, horarios)
   * - \n      → <br>
   * Escapa HTML primero para evitar XSS.
   */
  function formatMsg(raw) {
    const escaped = raw
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return escaped
      .replace(/\*(.*?)\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  /* ══════════════════════════════════════════════════════════════════════════
     CHAT UI
  ══════════════════════════════════════════════════════════════════════════ */
  function appendBubble(text, role, monedaTag) {
    const chat = document.getElementById("jv-chat");
    const row   = document.createElement("div");
    row.className = `jv-row ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "jv-bubble" + (role === "jarvis" && !text ? " jv-typing" : "");

    if (!text && role === "jarvis") {
      // Indicador de "escribiendo" con 3 puntos animados
      bubble.innerHTML = `<div class="jv-dot-anim">
        <span></span><span></span><span></span>
      </div>`;
    } else if (role === "jarvis") {
      bubble.innerHTML = formatMsg(text);
      if (monedaTag) {
        const tag = document.createElement("span");
        tag.className = `jv-tag ${monedaTag.toLowerCase()}`;
        tag.textContent = monedaTag;
        bubble.appendChild(tag);
      }
    } else {
      bubble.textContent = text;
    }

    const ts = document.createElement("span");
    ts.className = "jv-time";
    ts.textContent = new Date().toLocaleTimeString("es-VE", {
      hour: "2-digit", minute: "2-digit",
    });

    row.appendChild(bubble);
    row.appendChild(ts);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return bubble;
  }

  function removeTypingIndicator() {
    document.querySelectorAll(".jv-typing").forEach(el => el.closest(".jv-row")?.remove());
  }

  /* ══════════════════════════════════════════════════════════════════════════
     BARRA DE ESTADO
  ══════════════════════════════════════════════════════════════════════════ */
  function setStatus(msg, type) {
    const el = document.getElementById("jv-status");
    if (!el) return;
    el.textContent = msg || "";
    el.className   = type ? `jv-status ${type}` : "jv-status";
  }

  /* ══════════════════════════════════════════════════════════════════════════
     EFECTO TYPEWRITER — revela el texto carácter a carácter
  ══════════════════════════════════════════════════════════════════════════ */
  async function typewriter(el, html, delayMs) {
    // Extraer texto plano para el efecto
    const tmp  = document.createElement("div");
    tmp.innerHTML = html;
    const plain = tmp.textContent;

    // Fase 1: texto plano char a char
    for (let i = 0; i <= plain.length; i++) {
      el.textContent = plain.slice(0, i);
      document.getElementById("jv-chat").scrollTop = 99999;
      if (i < plain.length) await sleep(delayMs);
    }
    // Fase 2: reemplazar con HTML formateado (<strong>, etc.)
    el.innerHTML = html;
    document.getElementById("jv-chat").scrollTop = 99999;
  }

  /* ══════════════════════════════════════════════════════════════════════════
     CAPTURA DE VOZ — Web SpeechRecognition
  ══════════════════════════════════════════════════════════════════════════ */
  function initRecognition() {
    const SR = global.SpeechRecognition || global.webkitSpeechRecognition;
    if (!SR) return null;

    const r = new SR();
    r.lang            = CFG.idioma;
    r.continuous      = false;
    r.interimResults  = true;
    r.maxAlternatives = 1;

    r.onstart = () => {
      S.listening = true;
      setStatus("Jarvis escuchando...", "listening");
      document.getElementById("jv-mic")?.classList.add("active");
    };

    r.onresult = (evt) => {
      const last       = evt.results[evt.results.length - 1];
      const transcript = last[0].transcript.trim();
      const inp        = document.getElementById("jv-input");
      if (inp) inp.value = transcript;

      if (last.isFinal && transcript) {
        stopListening();
        sendToJarvis(transcript);
      }
    };

    r.onerror = (evt) => {
      stopListening();
      const msgs = {
        "not-allowed": "Permiso de microfono denegado. Habilítalo en el navegador.",
        "no-speech":   "No se detectó voz. Intenta de nuevo.",
        "network":     "Error de red en reconocimiento de voz.",
        "aborted":     "",   // cancelado manualmente, sin aviso
      };
      const m = msgs[evt.error];
      if (m !== "") setStatus(m || `Error de voz: ${evt.error}`, "error");
    };

    r.onend = () => { if (S.listening) stopListening(); };

    return r;
  }

  function startListening() {
    if (S.processing || S.speaking) return;
    if (!S.rec) S.rec = initRecognition();
    if (!S.rec) {
      setStatus("SpeechRecognition no disponible. Usa Chrome o escribe tu pregunta.", "error");
      return;
    }
    try {
      S.rec.start();
    } catch {
      // Ya estaba iniciado — resetear
      try { S.rec.stop(); } catch {}
      setTimeout(() => { try { S.rec.start(); } catch {} }, 350);
    }
  }

  function stopListening() {
    S.listening = false;
    try { S.rec?.stop(); } catch {}
    document.getElementById("jv-mic")?.classList.remove("active");
    if (!S.processing && !S.speaking) setStatus("", "");
  }

  /* ══════════════════════════════════════════════════════════════════════════
     ENVÍO AL SERVIDOR — POST /bodega o /tecnico
  ══════════════════════════════════════════════════════════════════════════ */
   async function sendToJarvis(texto) {
     texto = (texto || "").trim();
     if (!texto || S.processing) return;

     // Detectar comandos especiales de carrito
     if (texto.toLowerCase().startsWith("/agregar ")) {
       const parts = texto.substring(9).trim().split(" ");
       if (parts.length >= 2) {
         const productName = parts.slice(0, -1).join(" ");
         const price = parseFloat(parts[parts.length - 1]);
         if (!isNaN(price) && price > 0) {
           // Agregar producto al carrito
           addToCart({
             id: Date.now() + Math.random(), // ID temporal único
             name: productName,
             price: price
           });
           
           // Mostrar confirmación
           appendBubble(`Producto "${productName}" agregado al carrito por Bs ${price.toFixed(2)}`, "jarvis");
           setStatus("", "");
           document.getElementById("jv-input").value = "";
           return;
         }
       }
       // Si el formato es incorrecto, mostrar error pero continuar con el procesamiento normal
       appendBubble("Formato incorrecto. Usa: /agregar [nombre del producto] [precio]", "jarvis");
       setStatus("", "");
       document.getElementById("jv-input").value = "";
       return;
     }
     
     if (texto.toLowerCase().startsWith("/carrito")) {
       showCart();
       setStatus("", "");
       document.getElementById("jv-input").value = "";
       return;
     }
     
     if (texto.toLowerCase().startsWith("/vaciar")) {
       S.cart = [];
       updateCartUI();
       appendBubble("Carrito vaciado", "jarvis");
       setStatus("", "");
       document.getElementById("jv-input").value = "";
       return;
     }

     // Desactivar controles mientras procesa
     S.processing = true;
     _setControlsDisabled(true);
     document.getElementById("jv-input").value = "";

     // Mostrar burbuja del usuario + indicador typing
     appendBubble(texto, "user");
     appendBubble("", "jarvis");   // dots animados
     setStatus("Jarvis procesando...", "processing");

     const tipo     = document.getElementById("jv-tipo-sel")?.value || CFG.tipo;
     const endpoint = tipo === "tecnico_aires" ? EP.tecnico() : EP.bodega();

     try {
       const ctrl  = new AbortController();
       const timer = setTimeout(() => ctrl.abort(), CFG.timeoutFetch);

       const resp = await fetch(endpoint, {
         method:  "POST",
         headers: { "Content-Type": "application/json" },
         body:    JSON.stringify({ message: texto, tipo, moneda: S.moneda }),
         signal:  ctrl.signal,
       });
       clearTimeout(timer);

       if (!resp.ok) throw new Error(`HTTP ${resp.status} — ${resp.statusText}`);

       const data      = await resp.json();
       const respuesta = (data.response || data.text || "").trim() || "(sin respuesta)";
       const nuevaMoneda = (data.moneda || S.moneda).toUpperCase();

       // Actualizar moneda global y badge de topbar
       if (nuevaMoneda !== S.moneda) {
         S.moneda = nuevaMoneda;
         const badge = document.getElementById("jv-moneda-badge");
         if (badge) {
           badge.textContent = S.moneda;
           badge.className   = S.moneda === "USD" ? "usd" : "";
         }
       }

       // Reemplazar dots por respuesta con typewriter
       removeTypingIndicator();
       const bubble = appendBubble("", "jarvis", S.moneda);
       const delay  = respuesta.length > 300 ? 8 : 14;
       await typewriter(bubble, formatMsg(respuesta), delay);

       setStatus("", "");

       // Reproducir voz de Jarvis
       await playJarvisVoice(respuesta);

     } catch (err) {
       removeTypingIndicator();
       if (err.name === "AbortError") {
         appendBubble("El servidor tardo demasiado. Verifica que Jarvis este corriendo.", "jarvis");
         setStatus("Timeout — servidor no responde", "error");
       } else {
         appendBubble(`Error de conexion: ${err.message}`, "jarvis");
         setStatus("Sin conexion al servidor", "error");
       }
     } finally {
       S.processing = false;
       _setControlsDisabled(false);
     }
   }

  function _setControlsDisabled(disabled) {
    ["jv-mic", "jv-send", "jv-input"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = disabled;
    });
  }

  /* ══════════════════════════════════════════════════════════════════════════
     AUDIO — Google Cloud Neural2 vía backend, con fallback al navegador
  ══════════════════════════════════════════════════════════════════════════ */
  async function playJarvisVoice(texto) {
    if (!texto) return;
    S.speaking = true;
    setStatus("Jarvis hablando...", "speaking");
    try {
      const ok = await _playBackendAudio(texto);
      if (!ok) await _browserSpeak(texto);
    } finally {
      S.speaking = false;
      setStatus("", "");
    }
  }

  /**
   * Intenta obtener el audio WAV del endpoint /voz del servidor
   * (Google Cloud TTS Neural2 sintetizado en el backend).
   * Retorna true si el audio se reprodujo correctamente.
   */
  async function _playBackendAudio(texto) {
    try {
      const ctrl  = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), CFG.timeoutAudio);

      const resp = await fetch(EP.voz(), {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ texto: texto.slice(0, 480) }),
        signal:  ctrl.signal,
      });
      clearTimeout(timer);

      const ct = resp.headers.get("Content-Type") || "";
      if (!resp.ok || !ct.startsWith("audio/")) return false;

      const blob = await resp.blob();
      if (blob.size < 200) return false;  // respuesta vacía o error

      const blobUrl = URL.createObjectURL(blob);
      await _playAudioUrl(blobUrl);
      URL.revokeObjectURL(blobUrl);
      return true;

    } catch {
      return false;  // timeout, sin conexión, endpoint no existe → fallback
    }
  }

  /** Reproduce una URL de audio y espera a que termine. */
  function _playAudioUrl(src) {
    return new Promise((resolve) => {
      if (S.audio) {
        S.audio.pause();
        S.audio.src = "";
      }
      const audio = new Audio(src);
      S.audio = audio;
      audio.onended = resolve;
      audio.onerror = resolve;
      audio.play().catch(resolve);
    });
  }

  /**
   * Fallback: SpeechSynthesis del navegador cuando el backend no está disponible
   * o el endpoint /voz no está configurado.
   */
  function _browserSpeak(texto) {
    return new Promise((resolve) => {
      if (!global.speechSynthesis) return resolve();
      global.speechSynthesis.cancel();

      const utter   = new SpeechSynthesisUtterance(texto.slice(0, 500));
      utter.lang    = "es-VE";
      utter.rate    = 0.95;
      utter.pitch   = 1.0;
      utter.volume  = 1.0;

      // Preferir voz en español si el navegador la tiene disponible
      const loadVoices = () => {
        const voices  = global.speechSynthesis.getVoices();
        const esVoice = voices.find(v => v.lang.startsWith("es"));
        if (esVoice) utter.voice = esVoice;
        utter.onend  = resolve;
        utter.onerror = resolve;
        global.speechSynthesis.speak(utter);
      };

      // Chrome carga voces de forma asíncrona
      if (global.speechSynthesis.getVoices().length > 0) {
        loadVoices();
      } else {
        global.speechSynthesis.onvoiceschanged = loadVoices;
        // Safety timeout: hablar igual si las voces tardan
        setTimeout(loadVoices, 600);
      }
    });
  }

  /* ══════════════════════════════════════════════════════════════════════════
     ANALÍTICA BI — Chart.js + endpoint /analitica
  ══════════════════════════════════════════════════════════════════════════ */
  let _chartInstance = null;   // referencia al Chart activo (para destroy antes de redibujar)

  /**
   * Carga Chart.js dinámicamente si no está disponible en el contexto.
   * En bodega-auditoria.html ya viene cargado por CDN (line 8), por lo que
   * esta función solo actúa como guardián para uso standalone del JS.
   */
  function _ensureChartJs() {
    return new Promise((resolve) => {
      if (global.Chart) return resolve(true);
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js";
      s.onload  = () => resolve(true);
      s.onerror = () => resolve(false);
      document.head.appendChild(s);
    });
  }

  /**
   * Dibuja o actualiza la gráfica de dona con los datos de analítica.
   * Verde (#10b981)  = ventas en USD (Zinli, Wally, Facebank, etc.)
   * Cian  (#06d6a0)  = ventas en VES (bancos nacionales)
   */
  function _renderSalesChart(an) {
    const canvas = document.getElementById("jv-analytics-canvas");
    if (!canvas || !global.Chart) return;

    const vals   = an.grafica.valores;
    const total  = vals[0] + vals[1];
    if (total <= 0) return;

    const data = {
      labels:   an.grafica.labels,
      datasets: [{
        data:            vals,
        backgroundColor: an.grafica.colores,
        hoverBackgroundColor: an.grafica.colores_hover,
        borderWidth:     0,
        spacing:         2,
      }],
    };

    if (_chartInstance) {
      _chartInstance.data = data;
      _chartInstance.update("none");
      return;
    }

    _chartInstance = new global.Chart(canvas, {
      type: "doughnut",
      data,
      options: {
        cutout:    "70%",
        animation: { duration: 600, easing: "easeOutQuart" },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const pct = ((ctx.raw / total) * 100).toFixed(1);
                return ` Bs ${ctx.raw.toLocaleString("es-VE", {minimumFractionDigits:2})} (${pct}%)`;
              },
            },
            backgroundColor: "#0f0f1a",
            borderColor:     "#2a2a3a",
            borderWidth:     1,
            titleColor:      "#e8e8f0",
            bodyColor:       "#06d6a0",
          },
        },
        responsive:          true,
        maintainAspectRatio: true,
      },
    });
  }

  /**
   * Actualiza los elementos de texto del card (%, alerta, stock crítico).
   */
  function _updateAnalyticsCard(an) {
    const card = document.getElementById("jv-analytics-card");
    if (!card) return;

    const v = an.ventas;
    if (v.transacciones === 0) {
      card.classList.remove("visible");
      return;
    }

    card.classList.add("visible");

    const elUsd = document.getElementById("jv-bi-pct-usd");
    const elVes = document.getElementById("jv-bi-pct-ves");
    if (elUsd) elUsd.textContent = `${v.pct_usd}%`;
    if (elVes) elVes.textContent = `${v.pct_ves}%`;

    const elAlert = document.getElementById("jv-bi-alert");
    if (elAlert) {
      if (an.alerta_tasa.activa) {
        elAlert.style.display = "block";
        elAlert.title = an.alerta_tasa.mensaje;
      } else {
        elAlert.style.display = "none";
      }
    }

    const elStock = document.getElementById("jv-bi-stock");
    if (elStock) {
      const sc = an.stock_critico || [];
      const agotados = sc.filter(p => p.urgencia === "AGOTADO").length;
      const criticos = sc.filter(p => p.urgencia === "CRITICO").length;
      if (sc.length > 0) {
        elStock.style.display = "block";
        elStock.textContent   = agotados > 0
          ? `${agotados} AGOTADO(S) · ${criticos} critico(s)`
          : `${sc.length} prod. stock bajo`;
      } else {
        elStock.style.display = "none";
      }
    }
  }

  /**
   * Llama al endpoint GET /analitica y actualiza el card + gráfica.
   * Se ejecuta al abrir el panel y cada 60 s mientras está abierto.
   */
  async function _fetchAnalitica() {
    try {
      const ok = await _ensureChartJs();
      if (!ok) return;

      const resp = await fetch(`${CFG.host}/analitica`, {
        method: "GET",
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) return;

      const an = await resp.json();
      _updateAnalyticsCard(an);
      _renderSalesChart(an);
    } catch {
      /* Error silencioso — el card simplemente no aparece */
    }
  }

  /* ══════════════════════════════════════════════════════════════════════════
     PANEL FIADO — Cuentas por Cobrar (tarjetas con badges dinámicos)
  ══════════════════════════════════════════════════════════════════════════ */

  /* ══════════════════════════════════════════════════════════════════════════
     ZYNC SUITE — DIVISAS P2P · endpoint GET|POST /divisas
  ══════════════════════════════════════════════════════════════════════════ */

  /**
   * Obtiene tasas BCV, Binance P2P y resumen mensual del servidor.
   * Llama a _renderDivisasPanel() para pintar las tarjetas.
   */
  async function _fetchDivisas() {
    const emptyEl = document.getElementById("jv-divisas-empty");
    try {
      const resp = await fetch(`${CFG.host}/divisas`, {
        method: "GET",
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (emptyEl) emptyEl.style.display = "none";
      _renderDivisasPanel(data);
    } catch {
      if (emptyEl) emptyEl.style.display = "block";
    }
  }

  /**
   * Pinta las tarjetas de tasas + el resumen mensual.
   * Lógica de color por spread:
   *   < 5 %  → verde  (spread bajo)
   *   5–10 % → ámbar  (spread moderado)
   *   > 10 % → rojo   (oportunidad de cajero)
   */
  function _renderDivisasPanel(data) {
    const tasas   = data.tasas       || {};
    const mes     = data.resumen_mes || {};
    const grid    = document.getElementById("jv-rate-grid");
    const mesGrid = document.getElementById("jv-mes-grid");
    const mesCard = document.getElementById("jv-mes-card");
    if (!grid) return;

    const bcv     = parseFloat(tasas.bcv_usd_bs          || 0);
    const binance = parseFloat(tasas.binance_p2p_usdt_bs || 0);
    const spread  = parseFloat(tasas.spread_pct          || 0);
    const fmtBs   = (n) => n > 0
      ? `Bs ${n.toLocaleString("es-VE", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
      : "—";

    const spreadCls  = spread > 10 ? "spread-hi"
                     : spread > 5  ? "spread-warn" : "spread-ok";
    const spreadEmoji = spread > 10 ? "🔴 Oportunidad de cajero"
                      : spread > 5  ? "🟡 Spread moderado"
                      : spread > 0  ? "🟢 Spread bajo" : "Sin datos";

    grid.innerHTML = `
      <div class="jv-rate-card">
        <div class="jv-rate-lbl">Tasa BCV Oficial</div>
        <div class="jv-rate-val">${fmtBs(bcv)}</div>
        <div class="jv-rate-sub">USD · ${tasas.fuente_bcv || "manual"}</div>
        <div class="jv-rate-sub">${(tasas.ts_bcv || "").slice(0, 16) || "—"}</div>
      </div>
      <div class="jv-rate-card">
        <div class="jv-rate-lbl">Binance P2P</div>
        <div class="jv-rate-val">${fmtBs(binance)}</div>
        <div class="jv-rate-sub">USDT · ${tasas.fuente_binance || "manual"}</div>
        <div class="jv-rate-sub">${(tasas.ts_binance || "").slice(0, 16) || "—"}</div>
      </div>
      <div class="jv-rate-card ${spread > 0 ? spreadCls : ""}"
           style="grid-column:1/-1; flex-direction:row; align-items:center; gap:12px;">
        <div style="flex:1">
          <div class="jv-rate-lbl">Spread BCV vs P2P</div>
          <div class="jv-rate-val" style="font-size:30px">
            ${spread > 0 ? spread.toFixed(2) + "%" : "—"}
          </div>
          <div class="jv-rate-sub">${spreadEmoji}</div>
        </div>
        <button id="jv-spread-refresh"
                style="background:none; border:1px solid var(--jv-gray); border-radius:8px;
                       color:var(--jv-gray); font-size:20px; width:40px; height:40px;
                       cursor:pointer; flex-shrink:0; transition:color .2s, border-color .2s;"
                title="Refrescar tasas desde Binance / BCV">&#8635;</button>
      </div>
    `;

    // Bind botón de refresh inline
    document.getElementById("jv-spread-refresh")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.style.opacity = ".4";
      try {
        await fetch(`${CFG.host}/divisas`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ accion: "refrescar" }),
          signal:  AbortSignal.timeout(5000),
        });
        // Esperar a que el hilo daemon del backend termine (~2.5 s) y volver a leer
        await new Promise(r => setTimeout(r, 2600));
        await _fetchDivisas();
      } catch { /* silencioso */ }
      btn.disabled = false;
      btn.style.opacity = "1";
    });

    // ── Resumen del mes ────────────────────────────────────────────────────
    const ciclos   = parseInt(mes.ciclos_total            || 0);
    const volBs    = parseFloat(mes.volumen_bs            || 0);
    const volUsdt  = parseFloat(mes.volumen_usdt          || 0);
    const ganancia = parseFloat(mes.ganancia_neta_usd     || 0);
    const comis    = parseFloat(mes.comisiones_pagadas_usd|| 0);
    const periodo  = mes.periodo || "";

    if (!mesCard || !mesGrid) return;

    if (ciclos === 0) {
      mesCard.style.display = "none";
      return;
    }
    mesCard.style.display = "";

    const ganColor = ganancia > 0 ? "var(--jv-green)" : "var(--jv-red)";
    mesGrid.innerHTML = `
      <div class="jv-mes-stat">
        <span class="jv-mes-val">${ciclos}</span>
        <span class="jv-mes-lbl">Ciclos</span>
      </div>
      <div class="jv-mes-stat">
        <span class="jv-mes-val" style="font-size:11px;">
          Bs ${volBs.toLocaleString("es-VE", { maximumFractionDigits: 0 })}
        </span>
        <span class="jv-mes-lbl">Vol. Bolívares</span>
      </div>
      <div class="jv-mes-stat">
        <span class="jv-mes-val" style="font-size:11px;">${volUsdt.toFixed(2)}</span>
        <span class="jv-mes-lbl">Vol. USDT</span>
      </div>
      <div class="jv-mes-stat"
           style="grid-column:1/-1; margin-top:6px; padding-top:8px;
                  border-top:1px solid rgba(0,255,204,.08); align-items:center;">
        <span class="jv-mes-val" style="font-size:19px; color:${ganColor}">
          $${ganancia.toFixed(4)} USD
        </span>
        <span class="jv-mes-lbl">
          Ganancia Neta ${periodo ? "· " + periodo : ""}
          · Comisiones: $${comis.toFixed(4)}
        </span>
      </div>
    `;
  }

  /* ══════════════════════════════════════════════════════════════════════════
     ZYNC SUITE — IMPORTACIONES · endpoint GET /importaciones
  ══════════════════════════════════════════════════════════════════════════ */

  /**
   * Obtiene la lista de pedidos de importación China → Venezuela y
   * llama a _renderImportacionesCards() para pintarlos.
   */
  async function _fetchImportaciones() {
    const emptyEl = document.getElementById("jv-pedidos-empty");
    try {
      const resp = await fetch(`${CFG.host}/importaciones`, {
        method: "GET",
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      _renderImportacionesCards(data.pedidos || []);
    } catch {
      if (emptyEl) emptyEl.style.display = "block";
    }
  }

  /**
   * Renderiza tarjetas de pedido ordenadas por ID descendente.
   * Cada tarjeta expone las métricas críticas calculadas por el backend:
   *   • Unidades · Costo Fábrica · Logística (modalidad)
   *   • Costo Unitario de Desembarque  ← número rey
   *   • Precio de Venta Sugerido · Costo Total · ROI
   */
  function _renderImportacionesCards(pedidos) {
    const list    = document.getElementById("jv-pedidos-list");
    const emptyEl = document.getElementById("jv-pedidos-empty");
    if (!list) return;

    list.innerHTML = "";
    if (pedidos.length === 0) {
      if (emptyEl) emptyEl.style.display = "block";
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";

    // Ordenar por ID desc (más reciente primero)
    const sorted = [...pedidos].sort((a, b) => (b.id || "").localeCompare(a.id || ""));

    const BADGES = {
      recibido:    ["jv-badge-recibido",  "RECIBIDO"],
      en_transito: ["jv-badge-transito",  "EN TRÁNSITO"],
      en_aduana:   ["jv-badge-aduana",    "EN ADUANA"],
      pagado:      ["jv-badge-pagado",    "PAGADO"],
      cotizando:   ["jv-badge-cotizando", "COTIZANDO"],
    };

    const f  = (n, d = 2) => parseFloat(n || 0)
      .toLocaleString("es-VE", { minimumFractionDigits: d, maximumFractionDigits: d });
    const fu = (n, d = 2) => `$${f(n, d)}`;

    sorted.forEach(p => {
      const r   = p.resumen             || {};
      const log = p.costos_logisticos   || {};
      const prv = p.proveedor           || {};
      const est = (p.estado || "cotizando").toLowerCase();

      const [badgeCls, badgeTxt] = BADGES[est] || ["jv-badge-cotizando", est.toUpperCase()];
      const roi     = parseFloat(r.roi_pct                   || 0);
      const llegada = p.fecha_estimada_llegada ? `· Llegada: ${p.fecha_estimada_llegada}` : "";
      const unidades = parseInt(r.unidades_totales || 0);

      const card = document.createElement("div");
      card.className = `jv-ped-card ${est}`;
      card.innerHTML = `
        <div class="jv-ped-header">
          <span class="jv-ped-id">${p.id || "—"}</span>
          <span class="jv-ped-badge ${badgeCls}">${badgeTxt}</span>
        </div>
        <div class="jv-ped-supplier">
          ${prv.nombre || "Sin proveedor"} · ${prv.plataforma || "—"}
          · ${p.courier || "sin courier"} ${llegada}
        </div>
        <div class="jv-ped-metrics">
          <div class="jv-ped-metric">
            <span class="jv-ped-mlbl">Unidades</span>
            <span class="jv-ped-mval">${unidades.toLocaleString("es-VE")}</span>
          </div>
          <div class="jv-ped-metric">
            <span class="jv-ped-mlbl">Costo Fábrica</span>
            <span class="jv-ped-mval">${fu(r.costo_fabrica_usd)}</span>
          </div>
          <div class="jv-ped-metric">
            <span class="jv-ped-mlbl">Logística (${log.modalidad || "—"})</span>
            <span class="jv-ped-mval">${fu(r.costo_logistica_usd)}</span>
          </div>
        </div>
        <div class="jv-ped-hero">
          <div class="jv-ped-hero-item">
            <span class="jv-ped-hero-lbl">Costo Unit. Desembarque</span>
            <span class="jv-ped-hero-val">${fu(r.costo_unitario_desembarque, 4)}</span>
          </div>
          <div class="jv-ped-hero-item">
            <span class="jv-ped-hero-lbl">Precio Venta Sugerido</span>
            <span class="jv-ped-hero-val green">${fu(r.precio_venta_sugerido_usd, 4)}</span>
          </div>
          <div class="jv-ped-hero-item">
            <span class="jv-ped-hero-lbl">Costo Total</span>
            <span class="jv-ped-hero-val muted">${fu(r.costo_total_usd)}</span>
          </div>
          <div class="jv-ped-hero-item">
            <span class="jv-ped-hero-lbl">ROI · ${r.margen_aplicado_pct || 0}% margen</span>
            <span class="jv-ped-hero-val roi ${roi > 0 ? 'green' : ''}">${roi.toFixed(1)}%</span>
          </div>
        </div>
      `;
      list.appendChild(card);
    });
  }

  /* ══════════════════════════════════════════════════════════════════════════
     GESTIÓN DE PESTAÑAS (Chat · Fiado · Divisas · Importaciones)
  ══════════════════════════════════════════════════════════════════════════ */

  /**
   * Alterna entre las cuatro pestañas.
   * Cada pestaña tiene su panel propio; el panel Chat usa display en lugar de
   * clase .visible para no perder el scroll position del historial.
   */
  function _switchTab(tabName) {
    document.querySelectorAll(".jv-tab").forEach(b =>
      b.classList.toggle("active", b.dataset.tab === tabName)
    );

    // Mapa id-de-panel → nombre-de-pestaña
    const PANELS = {
      "jv-chat":                 "chat",
      "jv-clientes-panel":       "fiado",
      "jv-divisas-panel":        "divisas",
      "jv-importaciones-panel":  "importaciones",
    };

    Object.entries(PANELS).forEach(([id, name]) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (id === "jv-chat") {
        // Chat usa display para conservar el historial de scroll
        el.style.display = tabName === "chat" ? "" : "none";
      } else {
        el.classList.toggle("visible", name === tabName);
      }
    });

    // Cargar datos al abrir cada pestaña
    if (tabName === "fiado")         _fetchClientes();
    if (tabName === "divisas")       _fetchDivisas();
    if (tabName === "importaciones") _fetchImportaciones();
  }

  /**
   * Llama a GET /clientes y pasa la lista a _renderClientCards().
   * Silencioso en caso de error de red.
   */
  async function _fetchClientes() {
    try {
      const resp = await fetch(`${CFG.host}/clientes`, {
        method: "GET",
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      _renderClientCards(data.clientes || []);
    } catch {
      /* silencioso — el panel queda vacío o con el estado anterior */
    }
  }

  /**
   * Renderiza las tarjetas de deudores en #jv-clientes-list.
   * Badge rojo = crédito bloqueado (mora > 7 días o supera límite).
   * Badge amarillo = en mora pero no bloqueado.
   * Badge verde = al día.
   * Clic en tarjeta → abre el chat y envía la consulta de balance.
   */
  function _renderClientCards(clientes) {
    const list  = document.getElementById("jv-clientes-list");
    const empty = document.getElementById("jv-clientes-empty");
    if (!list) return;

    list.innerHTML = "";
    const deudores = clientes.filter(c =>
      parseFloat(c.deuda_bs || 0) > 0 || parseFloat(c.deuda_usd || 0) > 0
    );

    if (deudores.length === 0) {
      if (empty) empty.style.display = "block";
      return;
    }
    if (empty) empty.style.display = "none";

    deudores.forEach(c => {
      const est       = c.estado || {};
      const bloqueado = !!est.credito_bloqueado;
      const mora      = est.en_mora && !bloqueado;
      const d_usd     = parseFloat(c.deuda_usd || 0);
      const d_bs      = parseFloat(c.deuda_bs  || 0);
      const inicial   = (c.nombre || "?")[0].toUpperCase();

      const clsCard   = bloqueado ? "bloqueado" : (mora ? "mora" : "");
      let badgeCls, badgeTxt;
      if (bloqueado) { badgeCls = "jv-badge-bloqueado"; badgeTxt = "BLOQUEADO"; }
      else if (mora) { badgeCls = "jv-badge-mora";      badgeTxt = `${est.dias_mora}d MORA`; }
      else           { badgeCls = "jv-badge-ok";        badgeTxt = "Al dia"; }

      const saldoTxt = d_usd > 0
        ? `$ ${d_usd.toFixed(2)} USD · Bs ${d_bs.toLocaleString("es-VE", {minimumFractionDigits:2})}`
        : `Bs ${d_bs.toLocaleString("es-VE", {minimumFractionDigits:2})}`;

      const card = document.createElement("div");
      card.className = `jv-cliente-card ${clsCard}`;
      card.innerHTML = `
        <div class="jv-cli-avatar">${inicial}</div>
        <div class="jv-cli-info">
          <div class="jv-cli-nombre">${c.nombre || "—"}</div>
          <div class="jv-cli-saldo">${saldoTxt}</div>
        </div>
        <span class="jv-cli-badge ${badgeCls}">${badgeTxt}</span>
      `;
      // Clic → ir a Chat y consultar el balance
      card.addEventListener("click", () => {
        _switchTab("chat");
        sendToJarvis(`cuanto debe ${c.nombre}`);
      });
      list.appendChild(card);
    });
  }

  /* ══════════════════════════════════════════════════════════════════════════
     PING — monitor de conectividad con el servidor Jarvis
  ══════════════════════════════════════════════════════════════════════════ */
  async function pingServer() {
    try {
      const resp = await fetch(EP.ping(), { method: "GET", signal: AbortSignal.timeout(4000) });
      S.online = resp.ok;
    } catch {
      S.online = false;
    }
    const dot = document.getElementById("jv-dot");
    if (dot) {
      dot.className = S.online ? "online" : "offline";
      dot.title     = S.online
        ? `Jarvis online — ${CFG.host}`
        : `Sin conexion — ${CFG.host}`;
    }
  }

  /* ══════════════════════════════════════════════════════════════════════════
     CONSTRUCCIÓN DEL PANEL + EVENTOS
  ══════════════════════════════════════════════════════════════════════════ */
  function _injectStyles() {
    if (document.getElementById("jv-styles")) return;
    const style = document.createElement("style");
    style.id = "jv-styles";
    style.textContent = STYLES;
    document.head.appendChild(style);
  }

  function _buildPanel(selector) {
    let container = document.querySelector(selector);
    if (!container) {
      // Crear panel flotante si no hay contenedor
      container = document.createElement("div");
      container.id = "jv-float";
      container.style.cssText = [
        "position:fixed", "bottom:20px", "right:20px", "z-index:9999",
        "width:360px", "box-shadow:0 8px 40px rgba(0,0,0,.7)",
      ].join(";");
      document.body.appendChild(container);
    }

    const root = document.createElement("div");
    root.id = "jv-root";
    root.innerHTML = PANEL_HTML;
    container.appendChild(root);

    // Sincronizar selector de tipo con CFG
    const sel = document.getElementById("jv-tipo-sel");
    if (sel) sel.value = CFG.tipo;
  }

   function _bindEvents() {
     // Botón de micrófono
     document.getElementById("jv-mic")?.addEventListener("click", () => {
       if (S.listening) stopListening();
       else             startListening();
     });
     
     // Botón enviar
     document.getElementById("jv-send")?.addEventListener("click", () => {
       const val = document.getElementById("jv-input")?.value.trim();
       if (val) sendToJarvis(val);
     });
     
     // Enter en el campo de texto (sin Shift)
     document.getElementById("jv-input")?.addEventListener("keydown", (e) => {
       if (e.key === "Enter" && !e.shiftKey) {
         e.preventDefault();
         const val = e.target.value.trim();
         if (val) sendToJarvis(val);
       }
     });
     
     // Selector de tipo de contexto
     document.getElementById("jv-tipo-sel")?.addEventListener("change", (e) => {
       CFG.tipo = e.target.value;
     });
     
     // Event listeners para el carrito
     document.getElementById("close-cart")?.addEventListener("click", hideCart);
     document.getElementById("checkout-btn")?.addEventListener("click", processCheckout);
     document.getElementById("close-payment-modal")?.addEventListener("click", hidePaymentModal);
     
     // Cerrar modal al hacer clic fuera de él
     document.getElementById("payment-modal")?.addEventListener("click", (e) => {
       if (e.target === e.currentTarget) {
         hidePaymentModal();
       }
     });
   }

  /* ══════════════════════════════════════════════════════════════════════════
     UTILIDADES
  ══════════════════════════════════════════════════════════════════════════ */
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  /* ══════════════════════════════════════════════════════════════════════════
     API PÚBLICA — JarvisChat
  ══════════════════════════════════════════════════════════════════════════ */
  /**
   * init(selector, options)
   * @param {string}  selector  - Selector CSS del contenedor (default: "#jarvis-chat")
   * @param {object}  options   - Overrides de CFG: { host, tipo, idioma }
   *
   * Ejemplos:
   *   JarvisChat.init()                                  → panel flotante
   *   JarvisChat.init("#mi-div")                         → en ese div
   *   JarvisChat.init("#mi-div", { tipo: "tecnico_aires" })
   */
  function init(selector, options) {
    Object.assign(CFG, options || {});
    _injectStyles();
    _buildPanel(selector || "#jarvis-chat");
    S.rec = initRecognition();
    _bindEvents();

    // Bienvenida inicial
    appendBubble(
      "Hola. Soy *JARVIS*, tu asistente de " +
      (CFG.tipo === "tecnico_aires" ? "servicio tecnico de aires." : "bodega.") +
      " ¿En que te ayudo?",
      "jarvis"
    );

    // Ping al arrancar y luego cada N segundos
    pingServer();
    S.pingTimer = setInterval(pingServer, CFG.pingInterval);

    // Analítica BI: cargar al init y refrescar cada 60 s
    _fetchAnalitica();
    setInterval(_fetchAnalitica, 60_000);

    // Botón de refresh manual del card BI
    document.getElementById("jv-bi-refresh")?.addEventListener("click", () => {
      _fetchAnalitica();
    });

    // Pestañas Chat / Fiado
    document.querySelectorAll(".jv-tab").forEach(btn => {
      btn.addEventListener("click", () => _switchTab(btn.dataset.tab));
    });

    // Botón reload del panel fiado
    document.getElementById("jv-clientes-reload")?.addEventListener("click", () => {
      _fetchClientes();
    });

    // Botones reload de la Zync Suite — Divisas e Importaciones
    document.getElementById("jv-divisas-reload")?.addEventListener("click", () => {
      _fetchDivisas();
    });
    document.getElementById("jv-pedidos-reload")?.addEventListener("click", () => {
      _fetchImportaciones();
    });
  }

   // Exponer en window
   global.JarvisChat = {
     init,
     send:             sendToJarvis,
     startListening,
     stopListening,
     setHost:          (h) => { CFG.host = h; },
     setTipo:          (t) => { CFG.tipo = t; },
     setMoneda:        (m) => { S.moneda = m.toUpperCase(); },
     pingNow:          pingServer,
     refreshAnalytics:     _fetchAnalitica,       // _jv.refreshAnalytics()
     refreshClientes:      _fetchClientes,        // _jv.refreshClientes()
     refreshDivisas:       _fetchDivisas,         // _jv.refreshDivisas()
     refreshImportaciones: _fetchImportaciones,   // _jv.refreshImportaciones()
     switchTab:            _switchTab,            // _jv.switchTab("divisas") | "importaciones"
     // Carrito de compras
     addToCart:          addToCart,
     removeFromCart:     removeFromCart,
     getCart:            () => [...S.cart],
     getCartTotal:       calculateCartTotal,
     showCart:           showCart,
     hideCart:           hideCart
   };

  /* ══════════════════════════════════════════════════════════════════════════
     AUTO-INIT — si existe #jarvis-chat en el DOM al cargar la página
  ══════════════════════════════════════════════════════════════════════════ */
  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("jarvis-chat")) {
      global.JarvisChat.init("#jarvis-chat");
    }
  });

})(window);
