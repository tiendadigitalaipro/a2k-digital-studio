// ═══════════════════════════════════════════════════════════════════════
//  cart.js — A2K Digital Studio Shopping Cart v1.0
//  Inyectar como último <script> dentro de </body>
//  Sin dependencias externas. No toca el código existente del sitio.
// ═══════════════════════════════════════════════════════════════════════
(function (window, document) {
  'use strict';

  // ─── CONFIGURACIÓN ────────────────────────────────────────────────────
  const CONFIG = {
    PROXY_URL:   'https://cart-proxy.a2kdigitalstudio.online/pagar',
    SITE_URL:    'https://a2kdigitalstudio.online',
    STORAGE_KEY: 'a2k_cart_v1',
  };

  // ─── CATÁLOGO DE PRODUCTOS ────────────────────────────────────────────
  const PRODUCTS_CATALOG = {
    'bodega-pro': {
      id: 'bodega-pro', name: 'Bodega Pro',
      subtitle: 'Sistema POS · Bodega / Minimarket',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '🏪',
    },
    'mercado-logic-pro': {
      id: 'mercado-logic-pro', name: 'Mercado Logic Pro',
      subtitle: 'Sistema POS · Supermercado',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '🛒',
    },
    'fruteria-pro': {
      id: 'fruteria-pro', name: 'Frutería Pro',
      subtitle: 'Sistema POS · Frutería',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '🍎',
    },
    'nexo-pos': {
      id: 'nexo-pos', name: 'Nexo POS',
      subtitle: 'Sistema POS · Bodega Enterprise',
      price: 35.00, tax: 0.00, currency: 'USD', icon: '🔷',
    },
    'zync-electronics': {
      id: 'zync-electronics', name: 'ZYNC Electronics',
      subtitle: 'Sistema POS · Electrónica & Tecnología',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '⚡',
    },
    'barberia-pro': {
      id: 'barberia-pro', name: 'Barbería Pro',
      subtitle: 'Sistema POS · Barbería',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '💈',
    },
    'nail-studio-pro': {
      id: 'nail-studio-pro', name: 'Nail Studio Pro',
      subtitle: 'Sistema POS · Nail Studio',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '💅',
    },
    'ferreteria-pro': {
      id: 'ferreteria-pro', name: 'Ferretería A2K Pro',
      subtitle: 'Sistema POS · Ferretería',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '🔧',
    },
    'repuestos-motos-pro': {
      id: 'repuestos-motos-pro', name: 'Repuestos Motos Pro',
      subtitle: 'Sistema POS · Motocicletas',
      price: 25.00, tax: 0.00, currency: 'USD', icon: '🏍️',
    },
    'nexo-jarvis': {
      id: 'nexo-jarvis', name: 'Nexo Jarvis',
      subtitle: 'Asistente de escritorio con IA y voz',
      price: 35.00, tax: 0.00, currency: 'USD', icon: '🧠',
    },
  };

  // ─── ESTADO ───────────────────────────────────────────────────────────
  let cart = [];
  let isOpen = false;
  let payState = 'idle'; // idle | processing | success | error
  let originalBodyOverflow = '';

  // ─── PERSISTENCIA ─────────────────────────────────────────────────────
  function loadCart() {
    try { cart = JSON.parse(localStorage.getItem(CONFIG.STORAGE_KEY) || '[]'); }
    catch { cart = []; }
  }

  function saveCart() {
    try { localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(cart)); }
    catch {}
  }

  // ─── OPERACIONES DEL CARRITO ──────────────────────────────────────────
  function addItem(productId) {
    const product = PRODUCTS_CATALOG[productId];
    if (!product) return;
    const existing = cart.find(i => i.id === productId);
    if (existing) { existing.qty += 1; }
    else { cart.push({ id: productId, name: product.name, price: product.price, tax: product.tax, qty: 1 }); }
    saveCart();
    renderBadge();
    animateBadge();
    updateAddButtons();
    showToast(`${product.icon} ${product.name} agregado al carrito`);
  }

  function removeItem(productId) {
    cart = cart.filter(i => i.id !== productId);
    saveCart();
    renderBadge();
    renderCartItems();
    renderSummary();
    updateAddButtons();
  }

  function clearCart() {
    cart = [];
    saveCart();
    renderBadge();
    renderCartItems();
    renderSummary();
    updateAddButtons();
  }

  function getTotal()     { return cart.reduce((s, i) => s + i.price * i.qty, 0); }
  function getTotalTax()  { return cart.reduce((s, i) => s + i.tax   * i.qty, 0); }
  function getItemCount() { return cart.reduce((s, i) => s + i.qty, 0); }

  // ─── VALIDACIONES ─────────────────────────────────────────────────────
  function luhn(number) {
    const d = number.replace(/\D/g, '');
    if (d.length < 13 || d.length > 19) return false;
    let sum = 0, odd = true;
    for (let i = d.length - 1; i >= 0; i--) {
      let n = parseInt(d[i], 10);
      if (!odd) { n *= 2; if (n > 9) n -= 9; }
      sum += n; odd = !odd;
    }
    return sum % 10 === 0;
  }

  function cardType(number) {
    const n = number.replace(/\D/g, '');
    if (/^4/.test(n)) return 'Visa';
    if (/^5[1-5]/.test(n) || /^2[2-7]/.test(n)) return 'Mastercard';
    if (/^3[47]/.test(n)) return 'Amex';
    return '';
  }

  function validateForm(f) {
    const errors = [];
    if (!f.cardName || f.cardName.trim().length < 3)
      errors.push('Nombre del titular: mínimo 3 caracteres');
    if (!luhn(f.cardNumber))
      errors.push('Número de tarjeta inválido (verifica los dígitos)');
    if (!/^\d{2}\/\d{2}$/.test(f.expiry)) {
      errors.push('Fecha de vencimiento inválida (formato MM/YY)');
    } else {
      const [mm, yy] = f.expiry.split('/').map(Number);
      const exp = new Date(2000 + yy, mm - 1, 1);
      const now = new Date(); now.setDate(1); now.setHours(0, 0, 0, 0);
      if (mm < 1 || mm > 12 || exp < now) errors.push('Tarjeta vencida o fecha incorrecta');
    }
    if (!f.cvv || !/^\d{3,4}$/.test(f.cvv))
      errors.push('CVV inválido (debe tener 3 o 4 dígitos)');
    if (!f.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email))
      errors.push('Email inválido');
    if (!f.phone || f.phone.replace(/\D/g, '').length < 7)
      errors.push('Teléfono inválido (mínimo 7 dígitos)');
    if (cart.length === 0)
      errors.push('El carrito está vacío');
    return errors;
  }

  // ─── PAGO ─────────────────────────────────────────────────────────────
  async function processPayment(f) {
    payState = 'processing';
    renderPayState();

    const total   = (getTotal() + getTotalTax()).toFixed(2);
    const tax     = getTotalTax().toFixed(2);
    const concept = cart.map(i => `${i.name} ×${i.qty}`).join(', ');

    const payload = {
      amount:          total,
      taxAmount:       tax,
      phone:           f.phone.replace(/\D/g, ''),
      email:           f.email.trim(),
      concept:         `A2K Digital Studio — ${concept}`,
      description:     `Licencia software: ${concept}`,
      lang:            'ES',
      returnUrl:       `${CONFIG.SITE_URL}/pago-exitoso`,
      notificationUrl: `${CONFIG.SITE_URL}/api/notificacion-pago`,
      cardHolder:      f.cardName.trim(),
      cardNumber:      f.cardNumber.replace(/\D/g, ''),
      expiryMonth:     f.expiry.split('/')[0],
      expiryYear:      '20' + f.expiry.split('/')[1],
      cvv:             f.cvv,
    };

    try {
      const resp = await fetch(CONFIG.PROXY_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      const d = data.data || data;
      const approved = d.codError === '00' || d.codError === '000' || d.success === true || !!d.reference;
      if (approved) {
        payState = 'success';
        renderPaySuccess(d.reference || d.authorization || ('REF-' + Date.now()));
        clearCart();
      } else {
        payState = 'error';
        renderPayError(d.description || d.message || 'Pago rechazado por el banco emisor.');
      }
    } catch {
      payState = 'error';
      renderPayError('Error de conexión. Verifica tu internet e intenta de nuevo.');
    }
  }

  // ─── CSS INLINE ───────────────────────────────────────────────────────
  function injectCSS() {
    const css = `
#a2k-cart-root*{box-sizing:border-box;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}

/* Overlay */
#a2k-cart-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9998;
  backdrop-filter:blur(3px);transition:opacity .25s}
#a2k-cart-overlay.a2k-on{display:block;opacity:1}

/* Floating cart button — desktop: top-right, no colisiona con WA (bottom-right) */
#a2k-cart-btn{position:fixed;top:18px;right:20px;z-index:1001;width:50px;height:50px;
  border-radius:50%;border:2px solid #00d4ff;background:rgba(5,5,16,.95);color:#00d4ff;
  cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;
  box-shadow:0 0 20px rgba(0,212,255,.35),0 4px 20px rgba(0,0,0,.5);
  transition:transform .2s,box-shadow .2s;backdrop-filter:blur(12px)}
#a2k-cart-btn:hover{transform:scale(1.1);box-shadow:0 0 32px rgba(0,212,255,.6),0 4px 20px rgba(0,0,0,.5)}
#a2k-cart-btn:active{transform:scale(.95)}

/* Badge */
#a2k-cart-badge{position:absolute;top:-6px;right:-6px;background:#7B2FFF;color:#fff;
  border-radius:50%;width:20px;height:20px;font-size:10px;font-weight:700;
  display:none;align-items:center;justify-content:center;border:2px solid #050510}
#a2k-cart-badge.a2k-show{display:flex}
@keyframes a2k-pop{0%,100%{transform:scale(1)}50%{transform:scale(1.6)}}
#a2k-cart-badge.a2k-bounce{animation:a2k-pop .3s cubic-bezier(.68,-.55,.265,1.55)}

/* Drawer */
#a2k-cart-drawer{position:fixed;top:0;right:0;bottom:0;width:400px;max-width:100vw;
  background:#0a0a1f;border-left:1px solid rgba(0,212,255,.2);z-index:9999;
  display:flex;flex-direction:column;
  transform:translateX(100%);transition:transform .3s cubic-bezier(.4,0,.2,1);
  box-shadow:-12px 0 50px rgba(0,0,0,.7)}
#a2k-cart-drawer.a2k-open{transform:translateX(0)}

/* Header */
.a2k-dh{display:flex;align-items:center;justify-content:space-between;
  padding:16px 20px;border-bottom:1px solid rgba(0,212,255,.15);
  background:rgba(5,5,16,.98);flex-shrink:0}
.a2k-dh h2{margin:0;font-size:17px;color:#00d4ff;font-weight:700;
  display:flex;align-items:center;gap:8px;font-family:'Orbitron',monospace}
#a2k-close{background:none;border:1px solid rgba(0,212,255,.25);color:#6a6a8a;
  width:32px;height:32px;border-radius:6px;cursor:pointer;font-size:15px;
  display:flex;align-items:center;justify-content:center;transition:all .2s}
#a2k-close:hover{border-color:#00d4ff;color:#00d4ff;background:rgba(0,212,255,.1)}

/* Scrollable content */
.a2k-dc{flex:1;overflow-y:auto;padding:20px;
  scrollbar-width:thin;scrollbar-color:rgba(0,212,255,.2) transparent}
.a2k-dc::-webkit-scrollbar{width:4px}
.a2k-dc::-webkit-scrollbar-thumb{background:rgba(0,212,255,.2);border-radius:2px}

/* Section labels */
.a2k-sl{margin:0 0 14px;font-size:11px;font-weight:700;color:#6a6a8a;
  text-transform:uppercase;letter-spacing:.07em}

/* Form */
.a2k-fg{margin-bottom:12px}
.a2k-fg label{display:block;font-size:12px;color:#b0b0d0;margin-bottom:5px;font-weight:500}
.a2k-fg input{width:100%;padding:10px 12px;background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.08);border-radius:8px;color:#fff;font-size:14px;
  outline:none;transition:border-color .2s,box-shadow .2s;-webkit-appearance:none;
  font-family:inherit}
.a2k-fg input:focus{border-color:#00d4ff;box-shadow:0 0 0 3px rgba(0,212,255,.1)}
.a2k-fg input::placeholder{color:rgba(176,176,208,.35)}
.a2k-2col{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.a2k-ct{float:right;font-size:10px;color:#7B2FFF;font-weight:700;
  background:rgba(123,47,255,.15);padding:2px 7px;border-radius:4px}

/* Error list */
#a2k-ferr{display:none;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);
  border-radius:8px;padding:10px 12px;margin-top:8px}
#a2k-ferr.a2k-on{display:block}
#a2k-ferr ul{margin:0;padding-left:16px;color:#fca5a5;font-size:12px;line-height:1.7}

/* Divider */
.a2k-div{height:1px;background:rgba(255,255,255,.06);margin:20px 0}

/* Items header */
.a2k-ih{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.a2k-lnk{background:none;border:none;color:#ef4444;font-size:11px;cursor:pointer;
  padding:0;text-decoration:underline;transition:opacity .2s}
.a2k-lnk:hover{opacity:.7}

/* Cart item */
.a2k-item{display:flex;align-items:center;gap:12px;padding:12px;
  background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
  border-radius:10px;margin-bottom:8px;transition:border-color .2s}
.a2k-item:hover{border-color:rgba(0,212,255,.2)}
.a2k-ii{font-size:22px;width:36px;text-align:center;flex-shrink:0}
.a2k-in{flex:1;min-width:0}
.a2k-in p{margin:0}
.a2k-in .n{color:#fff;font-size:13px;font-weight:600;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.a2k-in .s{color:#6a6a8a;font-size:11px;margin-top:2px}
.a2k-ip{color:#00ff9d;font-weight:700;font-size:14px;flex-shrink:0;
  font-family:'Orbitron',monospace}
.a2k-rm{background:none;border:none;color:#3a3a5a;cursor:pointer;font-size:16px;
  width:26px;height:26px;display:flex;align-items:center;justify-content:center;
  border-radius:5px;transition:all .2s;flex-shrink:0;padding:0}
.a2k-rm:hover{color:#ef4444;background:rgba(239,68,68,.1)}

/* Empty state */
.a2k-empty{text-align:center;padding:24px 0;color:#3a3a5a}
.a2k-empty .ei{font-size:40px;margin-bottom:8px}
.a2k-empty p{margin:0;font-size:13px}

/* Drawer footer */
#a2k-foot{padding:16px 20px;border-top:1px solid rgba(255,255,255,.07);
  background:rgba(5,5,16,.98);flex-shrink:0}
.a2k-sr{display:flex;justify-content:space-between;align-items:center;
  color:#6a6a8a;font-size:13px;padding:3px 0}
.a2k-st{color:#fff;font-size:16px;padding-top:9px;
  border-top:1px solid rgba(255,255,255,.07);margin-top:5px}
.a2k-st strong{font-family:'Orbitron',monospace;color:#00ff9d}

/* Buttons */
.a2k-btn{display:block;width:100%;padding:13px;border-radius:10px;
  font-size:14px;font-weight:700;cursor:pointer;border:none;transition:all .2s;
  text-align:center;font-family:inherit}
.a2k-pay{background:linear-gradient(135deg,#7B2FFF,#5b21b6);color:#fff;
  box-shadow:0 4px 20px rgba(123,47,255,.45);margin-top:12px}
.a2k-pay:hover:not(:disabled){transform:translateY(-1px);
  box-shadow:0 6px 24px rgba(123,47,255,.6)}
.a2k-pay:active:not(:disabled){transform:translateY(0)}
.a2k-pay:disabled{opacity:.3;cursor:not-allowed}
.a2k-outline{background:transparent;border:1px solid rgba(0,212,255,.4);
  color:#00d4ff;margin-top:12px}
.a2k-outline:hover{background:rgba(0,212,255,.08)}
.a2k-sec{text-align:center;font-size:10px;color:#3a3a5a;margin:8px 0 0}

/* Payment state boxes */
.a2k-sb{text-align:center;padding:28px 16px}
.a2k-sb p{color:#6a6a8a;font-size:14px;margin:8px 0 0}
.a2k-sb h3{color:#fff;font-size:18px;margin:10px 0 0}
.a2k-si{width:56px;height:56px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:24px;font-weight:700;margin:0 auto}
.a2k-ok .a2k-si{background:rgba(0,255,157,.1);color:#00ff9d;border:2px solid #00ff9d}
.a2k-ko .a2k-si{background:rgba(239,68,68,.1);color:#ef4444;border:2px solid #ef4444}
.a2k-spin{width:42px;height:42px;border:3px solid rgba(0,212,255,.15);
  border-top-color:#00d4ff;border-radius:50%;margin:0 auto 14px;
  animation:a2k-r .75s linear infinite}
@keyframes a2k-r{to{transform:rotate(360deg)}}

/* Toast */
#a2k-toast{position:fixed;bottom:90px;left:50%;
  transform:translateX(-50%) translateY(60px);opacity:0;
  background:#0f0f2a;color:#e2e8f0;border:1px solid rgba(0,212,255,.3);
  border-radius:10px;padding:10px 20px;font-size:13px;z-index:10001;
  transition:transform .3s cubic-bezier(.4,0,.2,1),opacity .3s;
  white-space:nowrap;box-shadow:0 8px 32px rgba(0,0,0,.5);pointer-events:none}
#a2k-toast.a2k-on{transform:translateX(-50%) translateY(0);opacity:1}

/* "Agregar al carrito" — se inyecta debajo de .app-footer en .app-card-body */
.a2k-add{display:flex;align-items:center;justify-content:center;gap:7px;
  width:100%;padding:9px 16px;margin-top:10px;
  background:linear-gradient(135deg,rgba(0,212,255,.08),rgba(123,47,255,.08));
  border:1px solid rgba(0,212,255,.3);border-radius:8px;
  color:#00d4ff;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;
  font-family:'Inter',-apple-system,sans-serif}
.a2k-add:hover{background:linear-gradient(135deg,rgba(0,212,255,.18),rgba(123,47,255,.18));
  border-color:#00d4ff;transform:translateY(-1px);box-shadow:0 4px 14px rgba(0,212,255,.15)}
.a2k-add:active{transform:translateY(0)}
.a2k-add.in{border-color:rgba(0,255,157,.4);color:#00ff9d;background:rgba(0,255,157,.07)}

/* Mobile — carrito en bottom-left del WA button (bottom:24px right:90px) */
@media(max-width:768px){
  #a2k-cart-btn{top:auto;bottom:24px;right:90px}
  #a2k-cart-drawer{width:100vw}
  #a2k-toast{white-space:normal;max-width:calc(100vw - 48px);text-align:center;bottom:100px}
  .a2k-2col{grid-template-columns:1fr}
}`;
    const s = document.createElement('style');
    s.id = 'a2k-cart-css';
    s.textContent = css;
    document.head.appendChild(s);
  }

  // ─── HTML DEL CARRITO ─────────────────────────────────────────────────
  function injectHTML() {
    const root = document.createElement('div');
    root.id = 'a2k-cart-root';
    root.innerHTML = `
<div id="a2k-cart-overlay" aria-hidden="true"></div>

<button id="a2k-cart-btn" aria-label="Abrir carrito de compras" title="Carrito de compras">
  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
       fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/>
    <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
  </svg>
  <span id="a2k-cart-badge" aria-label="0 items en carrito"></span>
</button>

<div id="a2k-cart-drawer" role="dialog" aria-modal="true"
     aria-label="Carrito de compras" aria-hidden="true">

  <div class="a2k-dh">
    <h2>
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/>
        <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
      </svg>
      Carrito
    </h2>
    <button id="a2k-close" aria-label="Cerrar carrito">✕</button>
  </div>

  <div class="a2k-dc">

    <!-- ── SECCIÓN 1: Formulario PagueloFácil (siempre arriba) ── -->
    <div id="a2k-pay-idle">
      <p class="a2k-sl">💳 Datos de pago</p>
      <form id="a2k-form" novalidate autocomplete="on">

        <div class="a2k-fg">
          <label for="a2k-name">Nombre del titular</label>
          <input type="text" id="a2k-name" placeholder="Como aparece en la tarjeta"
            autocomplete="cc-name" maxlength="50" required />
        </div>

        <div class="a2k-fg">
          <label for="a2k-num">
            Número de tarjeta
            <span id="a2k-ctype" class="a2k-ct"></span>
          </label>
          <input type="text" id="a2k-num" placeholder="1234 5678 9012 3456"
            inputmode="numeric" autocomplete="cc-number" maxlength="19" required />
        </div>

        <div class="a2k-2col">
          <div class="a2k-fg">
            <label for="a2k-exp">Vencimiento</label>
            <input type="text" id="a2k-exp" placeholder="MM/YY"
              inputmode="numeric" autocomplete="cc-exp" maxlength="5" required />
          </div>
          <div class="a2k-fg">
            <label for="a2k-cvv">CVV</label>
            <input type="text" id="a2k-cvv" placeholder="123"
              inputmode="numeric" autocomplete="cc-csc" maxlength="4" required />
          </div>
        </div>

        <div class="a2k-fg">
          <label for="a2k-email">Email</label>
          <input type="email" id="a2k-email" placeholder="tu@correo.com"
            autocomplete="email" required />
        </div>

        <div class="a2k-fg">
          <label for="a2k-phone">Teléfono</label>
          <input type="tel" id="a2k-phone" placeholder="+58 412 000 0000"
            autocomplete="tel" required />
        </div>

        <div id="a2k-ferr" role="alert" aria-live="polite"></div>
      </form>
    </div>

    <div id="a2k-pay-processing" style="display:none" aria-live="polite">
      <div class="a2k-sb">
        <div class="a2k-spin"></div>
        <p>Procesando pago…</p>
        <p style="font-size:11px;color:#3a3a5a;margin-top:6px">No cierres esta ventana</p>
      </div>
    </div>

    <div id="a2k-pay-success" style="display:none" aria-live="polite">
      <div class="a2k-sb a2k-ok">
        <div class="a2k-si">✓</div>
        <h3>¡Pago exitoso!</h3>
        <p>Referencia: <strong id="a2k-ref" style="color:#00ff9d">—</strong></p>
        <p style="font-size:11px">Recibirás un email de confirmación.</p>
        <button class="a2k-btn a2k-outline" id="a2k-new">Nueva compra</button>
      </div>
    </div>

    <div id="a2k-pay-error" style="display:none" aria-live="polite">
      <div class="a2k-sb a2k-ko">
        <div class="a2k-si">✕</div>
        <h3>Pago rechazado</h3>
        <p id="a2k-errmsg">Error procesando el pago.</p>
        <button class="a2k-btn a2k-outline" id="a2k-retry">Intentar de nuevo</button>
      </div>
    </div>

    <div class="a2k-div"></div>

    <!-- ── SECCIÓN 2: Lista de productos ── -->
    <div class="a2k-ih">
      <p class="a2k-sl" style="margin:0">🛒 Productos seleccionados</p>
      <button id="a2k-clr" class="a2k-lnk" aria-label="Vaciar carrito">Vaciar todo</button>
    </div>
    <div id="a2k-items"></div>

  </div>

  <!-- Footer con total y botón pagar -->
  <div id="a2k-foot">
    <div>
      <div class="a2k-sr"><span>Subtotal</span><span id="a2k-sub">$0.00</span></div>
      <div class="a2k-sr a2k-st">
        <strong>Total a pagar</strong>
        <strong id="a2k-tot">$0.00</strong>
      </div>
    </div>
    <button id="a2k-paybtn" class="a2k-btn a2k-pay" disabled>🔒 Pagar ahora</button>
    <p class="a2k-sec">Pago seguro · PagueloFácil · Visa · Mastercard · Amex</p>
  </div>

</div>

<div id="a2k-toast" role="status" aria-live="polite"></div>`;
    document.body.appendChild(root);
  }

  // ─── RENDER ───────────────────────────────────────────────────────────
  function renderBadge() {
    const b = document.getElementById('a2k-cart-badge');
    if (!b) return;
    const c = getItemCount();
    b.textContent = c;
    b.setAttribute('aria-label', `${c} items en el carrito`);
    b.classList.toggle('a2k-show', c > 0);
  }

  function animateBadge() {
    const b = document.getElementById('a2k-cart-badge');
    if (!b) return;
    b.classList.remove('a2k-bounce');
    void b.offsetWidth;
    b.classList.add('a2k-bounce');
  }

  function renderCartItems() {
    const el = document.getElementById('a2k-items');
    if (!el) return;
    if (cart.length === 0) {
      el.innerHTML = `<div class="a2k-empty">
        <div class="ei">🛒</div>
        <p>Tu carrito está vacío</p>
        <p style="margin-top:5px;font-size:11px">Agrega productos desde el catálogo</p>
      </div>`;
      return;
    }
    el.innerHTML = cart.map(item => {
      const p = PRODUCTS_CATALOG[item.id] || {};
      return `<div class="a2k-item">
        <div class="a2k-ii">${p.icon || '📦'}</div>
        <div class="a2k-in">
          <p class="n">${esc(item.name)}</p>
          <p class="s">Licencia × ${item.qty} — $${item.price.toFixed(2)} c/u</p>
        </div>
        <div class="a2k-ip">$${(item.price * item.qty).toFixed(2)}</div>
        <button class="a2k-rm" data-id="${esc(item.id)}" aria-label="Eliminar ${esc(item.name)}">✕</button>
      </div>`;
    }).join('');
    el.querySelectorAll('[data-id]').forEach(btn => {
      btn.addEventListener('click', () => removeItem(btn.dataset.id));
    });
  }

  function renderSummary() {
    const sub    = getTotal();
    const tax    = getTotalTax();
    const tot    = sub + tax;
    const subEl  = document.getElementById('a2k-sub');
    const totEl  = document.getElementById('a2k-tot');
    const payBtn = document.getElementById('a2k-paybtn');
    if (subEl)  subEl.textContent  = `$${sub.toFixed(2)}`;
    if (totEl)  totEl.textContent  = `$${tot.toFixed(2)}`;
    if (payBtn) payBtn.disabled = cart.length === 0 || payState !== 'idle';
  }

  function renderPayState() {
    ['idle', 'processing', 'success', 'error'].forEach(s => {
      const el = document.getElementById(`a2k-pay-${s}`);
      if (el) el.style.display = s === payState ? 'block' : 'none';
    });
    renderSummary();
  }

  function renderPaySuccess(ref) {
    const r = document.getElementById('a2k-ref');
    if (r) r.textContent = ref;
    renderPayState();
  }

  function renderPayError(msg) {
    const m = document.getElementById('a2k-errmsg');
    if (m) m.textContent = msg;
    renderPayState();
  }

  function updateAddButtons() {
    document.querySelectorAll('.a2k-add').forEach(btn => {
      const id = btn.dataset.pid;
      const inCart = cart.some(i => i.id === id);
      btn.classList.toggle('in', inCart);
      btn.textContent = inCart ? '✓ En carrito' : '🛒 Agregar al carrito';
    });
  }

  // ─── OPEN / CLOSE ─────────────────────────────────────────────────────
  function openCart() {
    if (isOpen) return;
    isOpen = true;
    originalBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const d = document.getElementById('a2k-cart-drawer');
    const o = document.getElementById('a2k-cart-overlay');
    d?.classList.add('a2k-open');
    d?.setAttribute('aria-hidden', 'false');
    o?.classList.add('a2k-on');
    renderCartItems();
    renderSummary();
    renderPayState();
    setTimeout(() => document.getElementById('a2k-name')?.focus(), 310);
  }

  function closeCart() {
    if (!isOpen) return;
    isOpen = false;
    document.body.style.overflow = originalBodyOverflow;
    const d = document.getElementById('a2k-cart-drawer');
    const o = document.getElementById('a2k-cart-overlay');
    d?.classList.remove('a2k-open');
    d?.setAttribute('aria-hidden', 'true');
    o?.classList.remove('a2k-on');
    document.getElementById('a2k-cart-btn')?.focus();
  }

  // ─── TOAST ────────────────────────────────────────────────────────────
  let toastTimer;
  function showToast(msg) {
    const t = document.getElementById('a2k-toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('a2k-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('a2k-on'), 2600);
  }

  // ─── INPUT MASKS ──────────────────────────────────────────────────────
  function setupMasks() {
    const numInput = document.getElementById('a2k-num');
    const expInput = document.getElementById('a2k-exp');
    const ctSpan   = document.getElementById('a2k-ctype');

    numInput?.addEventListener('input', function () {
      const raw = this.value.replace(/\D/g, '').slice(0, 16);
      this.value = raw.replace(/(\d{4})(?=\d)/g, '$1 ');
      if (ctSpan) ctSpan.textContent = raw.length >= 4 ? cardType(raw) : '';
    });

    expInput?.addEventListener('input', function () {
      const raw = this.value.replace(/\D/g, '').slice(0, 4);
      this.value = raw.length >= 3 ? raw.slice(0, 2) + '/' + raw.slice(2) : raw;
    });
  }

  // ─── INYECCIÓN DE BOTONES "AGREGAR AL CARRITO" ───────────────────────
  // Busca [data-product-id], inyecta el botón dentro de .app-card-body
  // (después del .app-footer existente) para no romper el flex del footer.
  // En bot-card y otros contenedores, lo agrega al final.
  function injectAddButtons() {
    document.querySelectorAll('[data-product-id]').forEach(el => {
      const id = el.getAttribute('data-product-id');
      if (!PRODUCTS_CATALOG[id] || el.querySelector('.a2k-add')) return;
      const body = el.querySelector('.app-card-body');
      if (body) {
        body.appendChild(makeAddBtn(id));
      } else {
        el.appendChild(makeAddBtn(id));
      }
    });
  }

  function makeAddBtn(pid) {
    const p   = PRODUCTS_CATALOG[pid];
    const btn = document.createElement('button');
    btn.className = 'a2k-add';
    btn.dataset.pid = pid;
    btn.setAttribute('type', 'button');
    btn.setAttribute('aria-label', `Agregar ${p.name} al carrito`);
    btn.textContent = '🛒 Agregar al carrito';
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      addItem(pid);
      if (isOpen) renderCartItems();
    });
    return btn;
  }

  // ─── UTILIDADES ───────────────────────────────────────────────────────
  function esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }

  function formValues() {
    return {
      cardName:   document.getElementById('a2k-name')?.value  || '',
      cardNumber: document.getElementById('a2k-num')?.value   || '',
      expiry:     document.getElementById('a2k-exp')?.value   || '',
      cvv:        document.getElementById('a2k-cvv')?.value   || '',
      email:      document.getElementById('a2k-email')?.value || '',
      phone:      document.getElementById('a2k-phone')?.value || '',
    };
  }

  function showErrors(errors) {
    const el = document.getElementById('a2k-ferr');
    if (!el) return;
    if (!errors.length) { el.classList.remove('a2k-on'); el.innerHTML = ''; return; }
    el.classList.add('a2k-on');
    el.innerHTML = `<ul>${errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`;
  }

  // ─── EVENT LISTENERS ──────────────────────────────────────────────────
  function bindEvents() {
    document.getElementById('a2k-cart-btn')?.addEventListener('click', openCart);
    document.getElementById('a2k-close')?.addEventListener('click', closeCart);
    document.getElementById('a2k-cart-overlay')?.addEventListener('click', closeCart);

    document.getElementById('a2k-clr')?.addEventListener('click', () => {
      if (!cart.length) return;
      if (confirm('¿Vaciar el carrito?')) clearCart();
    });

    document.getElementById('a2k-paybtn')?.addEventListener('click', async () => {
      if (payState !== 'idle') return;
      const f = formValues();
      const errors = validateForm(f);
      showErrors(errors);
      if (errors.length) return;
      showErrors([]);
      await processPayment(f);
    });

    document.getElementById('a2k-retry')?.addEventListener('click', () => {
      payState = 'idle'; renderPayState();
    });

    document.getElementById('a2k-new')?.addEventListener('click', () => {
      payState = 'idle'; renderPayState(); closeCart();
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && isOpen) closeCart();
    });

    setupMasks();
  }

  // ─── INIT ─────────────────────────────────────────────────────────────
  function init() {
    loadCart();
    injectCSS();
    injectHTML();
    bindEvents();
    renderBadge();
    updateAddButtons();
    setTimeout(injectAddButtons, 200);

    window.A2KCart = {
      add:     addItem,
      open:    openCart,
      close:   closeCart,
      items:   () => [...cart],
      catalog: PRODUCTS_CATALOG,
    };

    console.info('[A2K Cart] v1.0 listo ✓');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

}(window, document));
