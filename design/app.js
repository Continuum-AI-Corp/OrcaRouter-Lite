/* ==========================================================================
   OrcaRouter Lite — dashboard
   Vanilla JS, no build step. State -> render. Keyboard-first DX.
   ========================================================================== */

const KEY_STORAGE = "orca-lite-api-key";
const ONBOARDING_KEY = "orca-lite-getting-started-dismissed";
const LOCALE_KEY = "orca-lite-locale";
const SUPPORTED_LOCALES = ["en", "zh", "hi", "es", "pt", "ru", "ja", "de", "fr", "it", "ar", "ko"];
const LOCALE_LABELS = { en: "English", zh: "中文", hi: "हिन्दी", es: "Español", pt: "Português", ru: "Русский", ja: "日本語", de: "Deutsch", fr: "Français", it: "Italiano", ar: "العربية", ko: "한국어" };
const I18N = {
  en: { "auth.tagline":"Open Source. Single Tenant.","auth.welcome":"Welcome back","auth.subtitle":"Paste the sk-orca-* key printed in your server logs on first run. Stored only in this browser via localStorage.","auth.api_key":"API key","auth.continue":"Continue","nav.search":"Search","nav.overview":"Overview","nav.providers":"Providers","nav.routing":"Routing","nav.analytics":"Analytics","nav.api_keys":"API keys","nav.help_docs":"Help & docs","nav.sign_out":"Sign out","status.connected":"Connected","status.disconnected":"Disconnected","auth.checking":"Checking…","auth.welcome_aboard":"Welcome aboard.","auth.key_invalid":"That key didn't work. Double-check the prefix sk-orca-…","tab.overview.title":"Overview","tab.overview.sub":"Your single-tenant LLM router at a glance.","tab.providers.title":"Provider keys","tab.providers.sub":"BYOK — encrypted at rest, used to call upstream LLMs.","tab.routing.title":"Routing","tab.routing.sub":"How model='auto' picks the right model for each request.","tab.analytics.title":"Analytics","tab.analytics.sub":"Local-only spend, latency and request history.","tab.keys.title":"API keys","tab.keys.sub":"Tokens that authenticate clients against this Lite workspace.","nav.quality":"Quality","tab.quality.title":"Quality scores","tab.quality.sub":"Real benchmark scores for the quality routing strategy. Pulls from Artificial Analysis." },
  zh: { "auth.tagline":"开源。单租户。","auth.welcome":"欢迎回来","auth.subtitle":"粘贴首次运行时服务器日志中的 sk-orca-* 密钥。仅保存在此浏览器 localStorage。","auth.api_key":"API 密钥","auth.continue":"继续","nav.search":"搜索","nav.overview":"概览","nav.providers":"供应商","nav.routing":"路由","nav.analytics":"分析","nav.api_keys":"API 密钥","nav.help_docs":"帮助与文档","nav.sign_out":"退出登录","status.connected":"已连接","status.disconnected":"已断开","auth.checking":"正在检查…","auth.welcome_aboard":"欢迎使用。","auth.key_invalid":"该密钥无效，请检查前缀 sk-orca-…","tab.overview.title":"概览","tab.overview.sub":"一览你的单租户 LLM 路由器。","tab.providers.title":"供应商密钥","tab.providers.sub":"BYOK — 静态加密存储，用于调用上游 LLM。","tab.routing.title":"路由","tab.routing.sub":"model='auto' 如何为每个请求选择合适模型。","tab.analytics.title":"分析","tab.analytics.sub":"仅本地的花费、延迟和请求历史。","tab.keys.title":"API 密钥","tab.keys.sub":"用于在此 Lite 工作区中验证客户端的令牌。","nav.quality":"质量","tab.quality.title":"质量分数","tab.quality.sub":"真实 benchmark 分数驱动 quality 路由策略,数据来自 Artificial Analysis。" },
  hi: { "auth.tagline":"ओपन सोर्स। सिंगल टेनेंट।","auth.welcome":"वापसी पर स्वागत है","auth.subtitle":"पहले रन पर सर्वर लॉग में छपी sk-orca-* कुंजी पेस्ट करें। यह केवल इस ब्राउज़र के localStorage में रहेगी।","auth.api_key":"API कुंजी","auth.continue":"जारी रखें","nav.search":"खोज","nav.overview":"अवलोकन","nav.providers":"प्रदाता","nav.routing":"रूटिंग","nav.analytics":"एनालिटिक्स","nav.api_keys":"API कुंजियाँ","nav.help_docs":"सहायता और दस्तावेज़","nav.sign_out":"साइन आउट","status.connected":"कनेक्टेड","status.disconnected":"डिस्कनेक्टेड","auth.checking":"जाँच हो रही है…","auth.welcome_aboard":"स्वागत है।","auth.key_invalid":"यह कुंजी काम नहीं कर रही। sk-orca- प्रीफिक्स जाँचें…","tab.overview.title":"ओवरव्यू","tab.overview.sub":"आपका सिंगल-टेनेंट LLM राउटर एक नज़र में।","tab.providers.title":"प्रोवाइडर कुंजियाँ","tab.providers.sub":"BYOK — स्टोरेज में एन्क्रिप्टेड, अपस्ट्रीम LLM कॉल के लिए उपयोग।","tab.routing.title":"रूटिंग","tab.routing.sub":"model='auto' हर अनुरोध के लिए सही मॉडल कैसे चुनता है।","tab.analytics.title":"एनालिटिक्स","tab.analytics.sub":"केवल स्थानीय खर्च, लेटेंसी और अनुरोध इतिहास।","tab.keys.title":"API कुंजियाँ","tab.keys.sub":"इस Lite वर्कस्पेस पर क्लाइंट प्रमाणित करने वाले टोकन।" },
  es: { "auth.tagline":"Código abierto. Inquilino único.","auth.welcome":"Bienvenido de nuevo","auth.subtitle":"Pega la clave sk-orca-* mostrada en los logs del servidor en el primer inicio. Solo se guarda en este navegador mediante localStorage.","auth.api_key":"Clave API","auth.continue":"Continuar","nav.search":"Buscar","nav.overview":"Resumen","nav.providers":"Proveedores","nav.routing":"Enrutamiento","nav.analytics":"Analíticas","nav.api_keys":"Claves API","nav.help_docs":"Ayuda y documentación","nav.sign_out":"Cerrar sesión","status.connected":"Conectado","status.disconnected":"Desconectado","auth.checking":"Verificando…","auth.welcome_aboard":"Bienvenido.","auth.key_invalid":"Esa clave no funcionó. Verifica el prefijo sk-orca-…","tab.overview.title":"Resumen","tab.overview.sub":"Tu enrutador LLM de inquilino único de un vistazo.","tab.providers.title":"Claves de proveedor","tab.providers.sub":"BYOK — cifradas en reposo, usadas para llamar a LLMs upstream.","tab.routing.title":"Enrutamiento","tab.routing.sub":"Cómo model='auto' elige el modelo adecuado para cada solicitud.","tab.analytics.title":"Analíticas","tab.analytics.sub":"Gasto, latencia e historial de solicitudes solo local.","tab.keys.title":"Claves API","tab.keys.sub":"Tokens que autentican clientes en este espacio Lite." },
  pt: { "auth.tagline":"Código aberto. Locatário único.","auth.welcome":"Bem-vindo de volta","auth.subtitle":"Cole a chave sk-orca-* exibida nos logs do servidor na primeira execução. Armazenada apenas neste navegador via localStorage.","auth.api_key":"Chave API","auth.continue":"Continuar","nav.search":"Pesquisar","nav.overview":"Visão geral","nav.providers":"Provedores","nav.routing":"Roteação","nav.analytics":"Análises","nav.api_keys":"Chaves API","nav.help_docs":"Ajuda e docs","nav.sign_out":"Sair","status.connected":"Conectado","status.disconnected":"Desconectado","auth.checking":"Verificando…","auth.welcome_aboard":"Boas-vindas.","auth.key_invalid":"Essa chave não funcionou. Verifique o prefixo sk-orca-…","tab.overview.title":"Visão geral","tab.overview.sub":"Seu roteador LLM single-tenant em um relance.","tab.providers.title":"Chaves de provedor","tab.providers.sub":"BYOK — criptografadas em repouso, usadas para chamar LLMs upstream.","tab.routing.title":"Roteamento","tab.routing.sub":"Como model='auto' escolhe o modelo certo para cada solicitação.","tab.analytics.title":"Análises","tab.analytics.sub":"Gasto, latência e histórico de solicitações apenas locais.","tab.keys.title":"Chaves API","tab.keys.sub":"Tokens que autenticam clientes neste workspace Lite." },
  ru: { "auth.tagline":"Открытый исходный код. Один арендатор.","auth.welcome":"С возвращением","auth.subtitle":"Вставьте ключ sk-orca-*, показанный в логах сервера при первом запуске. Он хранится только в localStorage этого браузера.","auth.api_key":"API-ключ","auth.continue":"Продолжить","nav.search":"Поиск","nav.overview":"Обзор","nav.providers":"Провайдеры","nav.routing":"Маршрутизация ИИ","nav.analytics":"Аналитика","nav.api_keys":"API-ключи","nav.help_docs":"Помощь и документация","nav.sign_out":"Выйти","status.connected":"Подключено","status.disconnected":"Отключено","auth.checking":"Проверка…","auth.welcome_aboard":"Добро пожаловать.","auth.key_invalid":"Ключ не подошел. Проверьте префикс sk-orca-…","tab.overview.title":"Обзор","tab.overview.sub":"Ваш single-tenant маршрутизатор LLM в одном экране.","tab.providers.title":"Ключи провайдеров","tab.providers.sub":"BYOK — шифруются при хранении, используются для вызова внешних LLM.","tab.routing.title":"Маршрутизация","tab.routing.sub":"Как model='auto' выбирает подходящую модель для каждого запроса.","tab.analytics.title":"Аналитика","tab.analytics.sub":"Локальные расходы, задержка и история запросов.","tab.keys.title":"API-ключи","tab.keys.sub":"Токены для аутентификации клиентов в этом Lite workspace." },
  ja: { "auth.tagline":"オープンソース。シングルテナント。","auth.welcome":"おかえりなさい","auth.subtitle":"初回起動時にサーバーログへ表示された sk-orca-* キーを貼り付けてください。localStorage にのみ保存されます。","auth.api_key":"APIキー","auth.continue":"続行","nav.search":"検索","nav.overview":"概要","nav.providers":"プロバイダー","nav.routing":"経路制御","nav.analytics":"分析","nav.api_keys":"APIキー","nav.help_docs":"ヘルプとドキュメント","nav.sign_out":"サインアウト","status.connected":"接続済み","status.disconnected":"未接続","auth.checking":"確認中…","auth.welcome_aboard":"ようこそ。","auth.key_invalid":"キーが無効です。接頭辞 sk-orca- を確認してください…","tab.overview.title":"概要","tab.overview.sub":"シングルテナント LLM ルーターの概要。","tab.providers.title":"プロバイダーキー","tab.providers.sub":"BYOK — 保存時に暗号化され、上流 LLM 呼び出しに使用。","tab.routing.title":"ルーティング","tab.routing.sub":"model='auto' が各リクエストに最適なモデルを選択する方法。","tab.analytics.title":"分析","tab.analytics.sub":"ローカル限定のコスト・遅延・リクエスト履歴。","tab.keys.title":"APIキー","tab.keys.sub":"この Lite ワークスペースでクライアント認証に使うトークン。" },
  de: { "auth.tagline":"Open Source. Einzelmandant.","auth.welcome":"Willkommen zurück","auth.subtitle":"Fügen Sie den beim ersten Start in den Server-Logs ausgegebenen sk-orca-* Schlüssel ein. Er wird nur in diesem Browser per localStorage gespeichert.","auth.api_key":"API-Schlüssel","auth.continue":"Weiter","nav.search":"Suchen","nav.overview":"Übersicht","nav.providers":"Anbieter","nav.routing":"Weiterleitung","nav.analytics":"Analysen","nav.api_keys":"API-Schlüssel","nav.help_docs":"Hilfe & Doku","nav.sign_out":"Abmelden","status.connected":"Verbunden","status.disconnected":"Getrennt","auth.checking":"Prüfe…","auth.welcome_aboard":"Willkommen an Bord.","auth.key_invalid":"Dieser Schlüssel funktioniert nicht. Prüfen Sie das Präfix sk-orca-…","tab.overview.title":"Übersicht","tab.overview.sub":"Ihr Single-Tenant-LLM-Router auf einen Blick.","tab.providers.title":"Anbieterschlüssel","tab.providers.sub":"BYOK — im Ruhezustand verschlüsselt, für Upstream-LLM-Aufrufe genutzt.","tab.routing.title":"Routing","tab.routing.sub":"Wie model='auto' für jede Anfrage das richtige Modell auswählt.","tab.analytics.title":"Analysen","tab.analytics.sub":"Nur lokale Ausgaben, Latenz und Anfrageverlauf.","tab.keys.title":"API-Schlüssel","tab.keys.sub":"Token zur Authentifizierung von Clients in diesem Lite-Workspace." },
  fr: { "auth.tagline":"Open source. Locataire unique.","auth.welcome":"Bon retour","auth.subtitle":"Collez la clé sk-orca-* affichée dans les logs serveur au premier démarrage. Elle est stockée uniquement dans ce navigateur via localStorage.","auth.api_key":"Clé API","auth.continue":"Continuer","nav.search":"Rechercher","nav.overview":"Vue d'ensemble","nav.providers":"Fournisseurs","nav.routing":"Routage IA","nav.analytics":"Analytique","nav.api_keys":"Clés API","nav.help_docs":"Aide et docs","nav.sign_out":"Se déconnecter","status.connected":"Connecté","status.disconnected":"Déconnecté","auth.checking":"Vérification…","auth.welcome_aboard":"Bienvenue.","auth.key_invalid":"Cette clé n'a pas fonctionné. Vérifiez le préfixe sk-orca-…","tab.overview.title":"Vue d'ensemble","tab.overview.sub":"Votre routeur LLM mono-locataire en un coup d'œil.","tab.providers.title":"Clés fournisseur","tab.providers.sub":"BYOK — chiffrées au repos, utilisées pour appeler les LLM amont.","tab.routing.title":"Routage","tab.routing.sub":"Comment model='auto' choisit le bon modèle pour chaque requête.","tab.analytics.title":"Analytique","tab.analytics.sub":"Dépenses, latence et historique des requêtes en local uniquement.","tab.keys.title":"Clés API","tab.keys.sub":"Jetons qui authentifient les clients sur cet espace Lite." },
  it: { "auth.tagline":"Open source. Tenant singolo.","auth.welcome":"Bentornato","auth.subtitle":"Incolla la chiave sk-orca-* mostrata nei log del server al primo avvio. Viene salvata solo in questo browser tramite localStorage.","auth.api_key":"Chiave API","auth.continue":"Continua","nav.search":"Cerca","nav.overview":"Panoramica","nav.providers":"Provider","nav.routing":"Smistamento","nav.analytics":"Analitica","nav.api_keys":"Chiavi API","nav.help_docs":"Aiuto e documentazione","nav.sign_out":"Disconnetti","status.connected":"Connesso","status.disconnected":"Disconnesso","auth.checking":"Verifica…","auth.welcome_aboard":"Benvenuto.","auth.key_invalid":"La chiave non ha funzionato. Controlla il prefisso sk-orca-…","tab.overview.title":"Panoramica","tab.overview.sub":"Il tuo router LLM single-tenant a colpo d'occhio.","tab.providers.title":"Chiavi provider","tab.providers.sub":"BYOK — crittografate a riposo, usate per chiamare LLM upstream.","tab.routing.title":"Instradamento","tab.routing.sub":"Come model='auto' sceglie il modello giusto per ogni richiesta.","tab.analytics.title":"Analitica","tab.analytics.sub":"Spesa locale, latenza e cronologia richieste.","tab.keys.title":"Chiavi API","tab.keys.sub":"Token che autenticano i client in questo workspace Lite." },
  ar: { "auth.tagline":"مفتوح المصدر. مستأجر واحد.","auth.welcome":"مرحبًا بعودتك","auth.subtitle":"ألصق مفتاح sk-orca-* المطبوع في سجلات الخادم عند التشغيل الأول. يُخزَّن فقط في هذا المتصفح عبر localStorage.","auth.api_key":"مفتاح API","auth.continue":"متابعة","nav.search":"بحث","nav.overview":"نظرة عامة","nav.providers":"المزوّدون","nav.routing":"توجيه الطلبات","nav.analytics":"التحليلات","nav.api_keys":"مفاتيح API","nav.help_docs":"المساعدة والوثائق","nav.sign_out":"تسجيل الخروج","status.connected":"متصل","status.disconnected":"غير متصل","auth.checking":"جارٍ التحقق…","auth.welcome_aboard":"مرحبًا بك.","auth.key_invalid":"هذا المفتاح لم يعمل. تحقّق من البادئة sk-orca-…","tab.overview.title":"نظرة عامة","tab.overview.sub":"موجّه LLM أحادي المستأجر بنظرة سريعة.","tab.providers.title":"مفاتيح المزوّدين","tab.providers.sub":"BYOK — مشفّرة أثناء التخزين وتُستخدم لاستدعاء نماذج LLM الخارجية.","tab.routing.title":"التوجيه","tab.routing.sub":"كيف يختار model='auto' النموذج المناسب لكل طلب.","tab.analytics.title":"التحليلات","tab.analytics.sub":"الإنفاق والزمن والسجل المحلي للطلبات فقط.","tab.keys.title":"مفاتيح API","tab.keys.sub":"رموز مصادقة العملاء في مساحة Lite هذه." },
  ko: { "auth.tagline":"오픈 소스. 단일 테넌트.","auth.welcome":"다시 오신 것을 환영합니다","auth.subtitle":"첫 실행 시 서버 로그에 출력된 sk-orca-* 키를 붙여넣으세요. 이 브라우저의 localStorage에만 저장됩니다.","auth.api_key":"API 키","auth.continue":"계속","nav.search":"검색","nav.overview":"개요","nav.providers":"공급자","nav.routing":"경로 지정","nav.analytics":"분석","nav.api_keys":"API 키","nav.help_docs":"도움말 및 문서","nav.sign_out":"로그아웃","status.connected":"연결됨","status.disconnected":"연결 끊김","auth.checking":"확인 중…","auth.welcome_aboard":"환영합니다.","auth.key_invalid":"키가 올바르지 않습니다. sk-orca- 접두사를 확인하세요…","tab.overview.title":"개요","tab.overview.sub":"싱글 테넌트 LLM 라우터를 한눈에 확인하세요.","tab.providers.title":"공급자 키","tab.providers.sub":"BYOK — 저장 시 암호화되며 상위 LLM 호출에 사용됩니다.","tab.routing.title":"라우팅","tab.routing.sub":"model='auto'가 요청별로 적절한 모델을 고르는 방식입니다.","tab.analytics.title":"분석","tab.analytics.sub":"로컬 전용 비용, 지연 시간, 요청 기록.","tab.keys.title":"API 키","tab.keys.sub":"Lite 워크스페이스에서 클라이언트를 인증하는 토큰." },
};
const PROVIDERS_KNOWN = [
  { id: "openai",      label: "OpenAI"      },
  { id: "anthropic",   label: "Anthropic"   },
  { id: "google",      label: "Google"      },
  { id: "groq",        label: "Groq"        },
  { id: "together",    label: "Together"    },
  { id: "fireworks",   label: "Fireworks"   },
  { id: "orcarouter",  label: "OrcaRouter (hosted)" },
];
const TAB_META = {
  overview:  { title: "tab.overview.title",  sub: "tab.overview.sub" },
  providers: { title: "tab.providers.title", sub: "tab.providers.sub" },
  routing:   { title: "tab.routing.title",   sub: "tab.routing.sub" },
  analytics: { title: "tab.analytics.title", sub: "tab.analytics.sub" },
  keys:      { title: "tab.keys.title",      sub: "tab.keys.sub" },
  quality:   { title: "tab.quality.title",   sub: "tab.quality.sub" },
};

const state = {
  apiKey: localStorage.getItem(KEY_STORAGE) || "",
  tab: "overview",
  providers: [],
  routing: { strategy: "balanced", preferred_models: [] },
  recent: [],
  spend: { total_microcents: 0, by_model: [] },
  latency: { by_provider: [] },
  savings: { saved_microcents: 0, savings_percent: 0, hosted_auto: null },
  models: [],
  hosted: { configured: false, source: null, signup_url: "https://www.orcarouter.ai/register", provider_name: "orcarouter" },
  unreachable: { hosted_configured: false, unreachable: [] },
  // Quality scoring (Artificial Analysis Intelligence Index + manual overrides)
  quality: { aa_index: { configured: false, source: "missing-key", matched_count: 0 }, models: [], override_count: 0 },
  qualityPreview: null,
  windowDays: 7,
  lang: "python",
  locale: "en",
};
const t = (k) => I18N[state.locale]?.[k] || I18N.en[k] || k;
function detectLocale() {
  const saved = localStorage.getItem(LOCALE_KEY);
  if (saved && SUPPORTED_LOCALES.includes(saved)) return saved;
  const browser = (navigator.languages?.[0] || navigator.language || "en").toLowerCase();
  const base = browser.split("-")[0];
  return SUPPORTED_LOCALES.includes(base) ? base : "en";
}
function applyI18n() {
  document.documentElement.lang = state.locale;
  document.documentElement.dir = state.locale === "ar" ? "rtl" : "ltr";
  $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  if (TAB_META[state.tab]) {
    $("#page-title").textContent = t(TAB_META[state.tab].title);
    $("#page-sub").textContent = t(TAB_META[state.tab].sub);
  }
}
function bindLocalePicker() {
  const sel = $("#language-select");
  if (!sel) return;
  sel.innerHTML = SUPPORTED_LOCALES.map((lc) => `<option value="${lc}">${LOCALE_LABELS[lc]}</option>`).join("");
  sel.value = state.locale;
  sel.addEventListener("change", () => {
    state.locale = sel.value;
    localStorage.setItem(LOCALE_KEY, state.locale);
    applyI18n();
  });
}

/* ─────────────── tiny utils ─────────────── */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const fmtUsd = (mc) => {
  // Single-tenant dev workloads: a single chat completion can cost
  // ~$0.000006 (6 microcents). Default $0.00 rendering hides that
  // entirely until the operator has run hundreds of requests, which
  // makes the dashboard look broken on day 1. Lean precise on the
  // small end — a developer reading $0.000148 understands it; a
  // developer reading $0.00 thinks the meter is busted.
  const usd = (mc || 0) / 1_000_000;
  if (usd === 0) return "$0";
  if (usd < 0.001) return `$${usd.toFixed(6)}`;
  if (usd < 0.01)  return `$${usd.toFixed(5)}`;
  if (usd < 1)     return `$${usd.toFixed(3)}`;
  if (usd < 100)   return `$${usd.toFixed(2)}`;
  return `$${Math.round(usd).toLocaleString()}`;
};
const fmtNum = (n) => (n || 0).toLocaleString();
const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now - d;
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60)   return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

const escapeHtml = (s = "") =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[c]));

// Mirror of app/routes/analytics.py:_percentile — same nearest-rank
// algorithm, including Python's banker's rounding (round-half-to-even)
// for .5 ties so client-derived percentiles match the backend
// bit-for-bit on the same sample.
function bankersRound(x) {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}
function percentile(values, pct) {
  if (!values.length) return 0;
  const s = [...values].sort((a, b) => a - b);
  const idx = Math.max(0, Math.min(s.length - 1, bankersRound((s.length - 1) * pct)));
  return Math.round(s[idx]);
}

/* ─────────────── HTTP ─────────────── */
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.apiKey) headers["Authorization"] = `Bearer ${state.apiKey}`;
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 204) return null;
  let body = null;
  try { body = await r.json(); } catch { /* ignore */ }
  if (!r.ok) {
    const msg = body?.error?.message || body?.detail || r.statusText || "Request failed";
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return body;
}

/* ─────────────── toasts ─────────────── */
const TOAST_ICONS = {
  ok:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  err:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  info: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
};
function toast(msg, kind = "ok", ms = 2400) {
  const region = $("#toast-region");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<span class="ico">${TOAST_ICONS[kind] || TOAST_ICONS.info}</span><span>${escapeHtml(msg)}</span>`;
  region.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 220);
  }, ms);
}

/* ─────────────── clipboard ─────────────── */
async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      btn.classList.add("copied");
      setTimeout(() => btn.classList.remove("copied"), 1200);
    }
    toast("Copied to clipboard", "info", 1400);
    return true;
  } catch {
    toast("Could not copy — your browser blocked it", "err");
    return false;
  }
}

/* ==========================================================================
   AUTH
   ========================================================================== */
async function checkAuth() {
  if (!state.apiKey) return false;
  try {
    await api("/v1/keys");
    return true;
  } catch {
    return false;
  }
}

function showShell() {
  $("#auth-gate").hidden = true;
  $("#app-shell").hidden = false;
  pollHealth();
  // fire-and-forget — render once data arrives
  Promise.allSettled([
    loadProviders(),
    loadRouting(),
    loadAnalytics(),
    loadKeys(),
    loadModels(),
    loadHosted(),
    loadUnreachable(),
  ]).then(() => {
    renderProviders();
    renderRouting();
    renderAnalytics();
    renderKeys();
    renderOverview();
    renderQuickstart();
    renderHostedCard();
    renderUnreachable();
    syncOnboarding();
  });
}

function showGate() {
  $("#app-shell").hidden = true;
  $("#auth-gate").hidden = false;
  $("#api-key-input").focus();
}

/* ==========================================================================
   TABS / ROUTING
   ========================================================================== */
function setTab(tab) {
  if (!TAB_META[tab]) return;
  state.tab = tab;
  history.replaceState(null, "", `#${tab}`);
  $$("#tabs .nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".panel").forEach((p) => p.classList.remove("active"));
  $(`#panel-${tab}`).classList.add("active");
  $("#page-title").textContent = t(TAB_META[tab].title);
  $("#page-sub").textContent = t(TAB_META[tab].sub);
  // refresh the tab's data so it's fresh-on-view
  if (tab === "analytics") loadAnalytics().then(renderAnalytics);
  if (tab === "providers") {
    Promise.all([loadProviders(), loadHosted(), loadUnreachable()]).then(() => {
      renderProviders();
      renderHostedCard();
      renderUnreachable();
    });
  }
  if (tab === "keys")      loadKeys().then(renderKeys);
  if (tab === "overview")  {
    Promise.all([loadHosted(), loadUnreachable()]).then(() => {
      renderOverview();
      renderHostedCard();
      renderUnreachable();
    });
  }
  if (tab === "quality") {
    Promise.all([loadQuality(), loadQualityPreview()]).then(() => {
      renderQuality();
      renderQualityPreview();
    });
  }
}

function bindTabs() {
  $$("#tabs .nav-item").forEach((b) =>
    b.addEventListener("click", () => setTab(b.dataset.tab))
  );
  // Inline anchor "go to tab" links
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-go-tab]");
    if (t) {
      e.preventDefault();
      setTab(t.dataset.goTab);
    }
  });
  // Initial tab from hash
  const initial = (location.hash || "").replace("#", "");
  if (TAB_META[initial]) setTab(initial);
}

/* ==========================================================================
   PROVIDERS
   ========================================================================== */
async function loadProviders() {
  try {
    const data = await api("/v1/providers");
    state.providers = data.providers || [];
  } catch (e) {
    toast(`Couldn't load providers: ${e.message}`, "err");
  }
}

function renderProviders() {
  const tbody = $("#providers-table tbody");
  const empty = $("#providers-empty");
  tbody.innerHTML = "";
  if (!state.providers.length) {
    empty.classList.add("shown");
  } else {
    empty.classList.remove("shown");
    state.providers.forEach((p) => {
      const tr = document.createElement("tr");
      tr.className = "row-in";
      tr.innerHTML = `
        <td><strong>${escapeHtml(p.provider)}</strong></td>
        <td><code>${escapeHtml(p.key_prefix || "—")}</code></td>
        <td>${p.is_enabled
          ? '<span class="pill ok">Enabled</span>'
          : '<span class="pill muted">Disabled</span>'}</td>
        <td class="th-actions">
          <button class="btn btn-ghost btn-sm btn-danger del-prov" data-prov="${escapeHtml(p.provider)}">
            Remove
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    $$(".del-prov").forEach((b) =>
      b.addEventListener("click", async () => {
        const prov = b.dataset.prov;
        if (!confirm(`Remove the ${prov} key? Requests routed to ${prov} will start failing.`)) return;
        try {
          await api(`/v1/providers/${prov}`, { method: "DELETE" });
          toast(`Removed ${prov}`, "ok");
          await Promise.all([loadProviders(), loadHosted(), loadUnreachable()]);
          renderProviders();
          renderQuickAdd();
          renderHostedCard();
          renderUnreachable();
          renderOverview();
          syncOnboarding();
        } catch (e) {
          toast(e.message, "err");
        }
      })
    );
  }
  renderQuickAdd();
}

function renderQuickAdd() {
  const wrap = $("#provider-quickadd");
  if (!wrap) return;
  const configured = new Set(state.providers.map((p) => p.provider));
  wrap.innerHTML = `<span class="muted" style="font-size:12px;align-self:center;margin-right:4px">Quick-add:</span>` +
    PROVIDERS_KNOWN.map((p) => {
      const isSet = configured.has(p.id);
      return `<button class="chip ${isSet ? "configured" : ""}" data-prov-pick="${p.id}" ${isSet ? "disabled" : ""}>
        ${escapeHtml(p.label)}
      </button>`;
    }).join("");
  $$("[data-prov-pick]").forEach((b) =>
    b.addEventListener("click", () => {
      const sel = $("#provider-name");
      sel.value = b.dataset.provPick;
      $("#provider-key").focus();
    })
  );
}

function bindProviderForm() {
  $("#provider-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const provider = $("#provider-name").value;
    const apiKeyVal = $("#provider-key").value.trim();
    if (!apiKeyVal) {
      toast("API key cannot be empty", "err");
      return;
    }
    try {
      await api(`/v1/providers/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKeyVal }),
      });
      $("#provider-key").value = "";
      toast(`Saved ${provider} key`, "ok");
      await Promise.all([loadProviders(), loadHosted(), loadUnreachable()]);
      renderProviders();
      renderHostedCard();
      renderUnreachable();
      renderOverview();
      syncOnboarding();
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ==========================================================================
   ROUTING
   ========================================================================== */
async function loadRouting() {
  try {
    const r = await api("/v1/routing");
    state.routing = r;
  } catch (e) {
    toast(`Couldn't load routing: ${e.message}`, "err");
  }
}

function renderRouting() {
  $$(".strategy-card").forEach((c) => {
    const selected = c.dataset.value === state.routing.strategy;
    c.classList.toggle("selected", selected);
    const input = c.querySelector("input");
    if (input) input.checked = selected;
  });
}

function bindRouting() {
  $$(".strategy-card").forEach((c) => {
    c.addEventListener("click", async (e) => {
      e.preventDefault();
      const val = c.dataset.value;
      if (val === state.routing.strategy) return;
      const prev = state.routing.strategy;
      state.routing.strategy = val;
      renderRouting();
      try {
        await api("/v1/routing", { method: "PUT", body: JSON.stringify({ strategy: val }) });
        toast(`Routing strategy: ${val}`, "ok");
        // Refresh the Quality preview so the operator sees the new
        // strategy's primary pick immediately. The preview reads workspace
        // strategy server-side (NOT a query param — avoids a race where the
        // dashboard's local default `balanced` overrides the just-saved
        // value before loadRouting() finishes on initial load).
        try {
          await loadQualityPreview();
          renderQualityPreview();
        } catch (_) { /* preview is non-critical, never block strategy change */ }
        syncOnboarding();
      } catch (err) {
        state.routing.strategy = prev;
        renderRouting();
        toast(err.message, "err");
      }
    });
  });
}

/* ==========================================================================
   ANALYTICS
   ========================================================================== */
async function loadAnalytics() {
  const days = state.windowDays;
  try {
    const [recent, spend, latency, savings] = await Promise.all([
      api(`/v1/analytics/recent?limit=50`),
      api(`/v1/analytics/spend?days=${days}`),
      api(`/v1/analytics/latency?days=${days}`),
      api(`/v1/analytics/savings?days=${days}&baseline=gpt-4o`).catch(() => null),
    ]);
    state.recent = recent.items || [];
    state.spend = spend;
    state.latency = latency;
    if (savings) state.savings = savings;
  } catch (e) {
    toast(`Couldn't load analytics: ${e.message}`, "err");
  }
}

/* ==========================================================================
   HOSTED FALLBACK + UNREACHABLE MODELS
   ========================================================================== */
async function loadHosted() {
  try {
    state.hosted = await api(`/v1/hosted`);
  } catch {
    // Non-fatal — card just stays in unconfigured state.
  }
}

async function loadUnreachable() {
  try {
    state.unreachable = await api(`/v1/analytics/unreachable?limit=8`);
  } catch {
    state.unreachable = { hosted_configured: false, unreachable: [] };
  }
}

function fmtPerMtok(perToken) {
  // litellm prices are USD per token; show as $/1M tokens.
  const perMillion = (perToken || 0) * 1_000_000;
  if (perMillion === 0) return "—";
  if (perMillion < 1) return `$${perMillion.toFixed(2)}`;
  return `$${perMillion.toFixed(2)}`;
}

function renderHostedCard() {
  const card = $("#hosted-card");
  if (!card) return;
  card.hidden = false;

  const pill = $("#hosted-status-pill");
  const cta = $("#hosted-cta");
  const active = $("#hosted-active");
  const signupBtn = $("#hosted-signup-btn");
  const providersPill = $("#providers-hosted-pill");
  const providersSignup = $("#providers-hosted-signup");
  const providersCard = $("#providers-hosted-card");

  const url = state.hosted.signup_url || "https://www.orcarouter.ai/register";
  if (signupBtn) signupBtn.href = url;
  if (providersSignup) providersSignup.href = url;

  if (state.hosted.configured) {
    pill.textContent = "Active";
    pill.className = "pill ok";
    cta.hidden = true;
    active.hidden = false;
    if (providersPill) { providersPill.textContent = "Active"; providersPill.className = "pill ok"; }
    if (providersCard) providersCard.hidden = true;

    // Hosted-active state: source line + extra savings projection.
    // Three branches: no comparable history yet, additional savings
    // detected, or already optimal (history exists but routing matches
    // the cheapest hosted-auto pick on every comparable request).
    const isEnv = state.hosted.source === "env";
    const ha = state.savings.hosted_auto;
    let haText;
    if (!ha || ha.comparable_request_count === 0) {
      haText = `No comparable request history yet — once traffic flows, this card will show how much routing through hosted-auto would save.`;
    } else if (ha.saved_microcents > 0) {
      // savings_percent is computed against comparable spend only (rows
      // resolved to a catalog model), not total spend — keep the copy
      // honest so non-catalog traffic doesn't make the figure misleading.
      haText = `Up to <strong>${fmtUsd(ha.saved_microcents)}</strong> additional savings detected (${ha.savings_percent}% of comparable-traffic spend) by routing through hosted-auto on the cheapest catalog model per request.`;
    } else {
      haText = `Already optimal — your current routing matches the cheapest hosted-auto pick on every comparable request.`;
    }
    $("#hosted-active-meta").innerHTML = isEnv
      ? `Active via environment variable (<code>ORCAROUTER_API_KEY</code>). Every catalog model is reachable. To disable, unset the env var and restart.`
      : `Active via dashboard. Every catalog model is reachable.`;
    $("#hosted-savings").innerHTML = haText;
    // The Remove button DELETEs the DB row; with no DB row (env-only) it
    // would 404. Hide it and let the meta line explain how to disable.
    const removeBtn = $("#hosted-remove-btn");
    if (removeBtn) removeBtn.hidden = isEnv;
  } else {
    pill.textContent = "Not configured";
    pill.className = "pill muted";
    cta.hidden = false;
    active.hidden = true;
    if (providersPill) { providersPill.textContent = "Not configured"; providersPill.className = "pill muted"; }
    if (providersCard) providersCard.hidden = false;
  }
}

function renderUnreachable() {
  const wrap = $("#unreachable-list");
  const grid = $("#unreachable-grid");
  if (!wrap || !grid) return;
  const list = state.unreachable.unreachable || [];
  if (state.hosted.configured || list.length === 0) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  grid.innerHTML = list.map((m) => {
    const caps = [];
    if (m.supports_tools) caps.push("tools");
    if (m.supports_vision) caps.push("vision");
    if (m.supports_json_mode) caps.push("json");
    const capPills = caps.map((c) => `<span class="cap-pill">${c}</span>`).join("");
    return `
      <div class="unreachable-item" data-tooltip="Provider: ${escapeHtml(m.provider)} · ${fmtPerMtok(m.input_cost_per_token)}/$1M in · ${fmtPerMtok(m.output_cost_per_token)}/$1M out">
        <div class="unreachable-id"><code>${escapeHtml(m.id)}</code></div>
        <div class="unreachable-meta">
          <span class="unreachable-provider">${escapeHtml(m.provider)}</span>
          <span class="unreachable-price">${fmtPerMtok(m.input_cost_per_token)} / ${fmtPerMtok(m.output_cost_per_token)} per 1M</span>
        </div>
        <div class="unreachable-caps">${capPills}</div>
      </div>`;
  }).join("");
}

function bindHostedForm() {
  const form = $("#hosted-key-form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = $("#hosted-key-input").value.trim();
      if (!v) { toast("Paste your sk-orca-* key from orcarouter.ai", "err"); return; }
      try {
        await api(`/v1/providers/orcarouter`, {
          method: "PUT",
          body: JSON.stringify({ api_key: v }),
        });
        $("#hosted-key-input").value = "";
        toast("Hosted fallback activated — every model is now reachable", "ok");
        await Promise.all([loadHosted(), loadUnreachable(), loadProviders()]);
        renderHostedCard();
        renderUnreachable();
        renderProviders();
        renderOverview();
      } catch (err) {
        toast(err.message, "err");
      }
    });
  }
  const remove = $("#hosted-remove-btn");
  if (remove) {
    remove.addEventListener("click", async () => {
      if (!confirm("Disable hosted fallback? Requests for models without a local key will start failing.")) return;
      try {
        await api(`/v1/providers/orcarouter`, { method: "DELETE" });
        toast("Hosted fallback disabled", "info");
        await Promise.all([loadHosted(), loadUnreachable(), loadProviders()]);
        renderHostedCard();
        renderUnreachable();
        renderProviders();
        renderOverview();
      } catch (err) {
        toast(err.message, "err");
      }
    });
  }
}

function renderAnalytics() {
  // Spend summary
  const totalReq = state.spend.by_model.reduce((a, m) => a + m.request_count, 0);
  $("#spend-summary").innerHTML =
    `Last <strong>${state.spend.days || state.windowDays}d</strong> · ` +
    `<strong>${fmtUsd(state.spend.total_microcents)}</strong> across ` +
    `<strong>${fmtNum(totalReq)}</strong> requests`;

  // Bar chart
  const chart = $("#bar-chart");
  if (!state.spend.by_model.length) {
    chart.innerHTML = `<div class="empty-mini">
      <p>No spend data yet for this window.</p>
      <p class="muted">Send a request through <code>/v1/chat/completions</code> to see your costs here.</p>
    </div>`;
  } else {
    const max = Math.max(...state.spend.by_model.map((m) => m.cost_microcents)) || 1;
    chart.innerHTML = state.spend.by_model.slice(0, 10).map((m) => {
      const pct = Math.max(2, (m.cost_microcents / max) * 100);
      return `
        <div class="bar-row" data-tooltip="${fmtNum(m.request_count)} requests, ${fmtUsd(m.cost_microcents)}">
          <div class="bar-label">${escapeHtml(m.model || "—")}</div>
          <div class="bar-track"><div class="bar-fill" style="right:${100 - pct}%"></div></div>
          <div class="bar-value">${fmtUsd(m.cost_microcents)} <span class="reqs">${fmtNum(m.request_count)} req</span></div>
        </div>`;
    }).join("");
  }

  // Latency table
  const lt = $("#latency-table tbody");
  if (!state.latency.by_provider.length) {
    lt.innerHTML = `<tr><td colspan="4" class="muted" style="text-align:center;padding:24px">No data yet for this window.</td></tr>`;
  } else {
    lt.innerHTML = state.latency.by_provider.map((p) => `
      <tr class="row-in">
        <td><strong>${escapeHtml(p.provider)}</strong></td>
        <td>${fmtNum(p.request_count)}</td>
        <td>${fmtNum(p.p50_ms)} ms</td>
        <td>${fmtNum(p.p99_ms)} ms</td>
      </tr>
    `).join("");
  }

  // Recent table
  const rt = $("#recent-table tbody");
  const rEmpty = $("#recent-empty");
  if (!state.recent.length) {
    rt.innerHTML = "";
    rEmpty.hidden = false;
    rEmpty.classList.add("shown");
  } else {
    rEmpty.hidden = true;
    rEmpty.classList.remove("shown");
    rt.innerHTML = state.recent.map((it) => {
      const ok = (it.status_code || 0) < 400;
      const pillCls = ok ? "ok" : "err";
      const pillTxt = ok ? `${it.status_code} OK` : `${it.status_code} ${it.error_type || "error"}`;
      return `
        <tr class="row-in copy-row" data-trace="${escapeHtml(it.trace_id || "")}" data-tooltip="Click to copy trace ID">
          <td>${fmtTime(it.created_at)}</td>
          <td><code>${escapeHtml(it.model_resolved || it.model_requested || "—")}</code></td>
          <td>${escapeHtml(it.provider || "—")}</td>
          <td>${fmtNum(it.input_tokens)} / ${fmtNum(it.output_tokens)}</td>
          <td>${fmtNum(it.latency_ms)} ms</td>
          <td><span class="pill ${pillCls}">${escapeHtml(pillTxt)}</span></td>
        </tr>`;
    }).join("");
    $$(".copy-row").forEach((row) =>
      row.addEventListener("click", () => {
        const tid = row.dataset.trace;
        if (tid) copyToClipboard(tid);
      })
    );
  }
}

function bindWindowSeg() {
  $$("#window-seg .seg-btn").forEach((b) =>
    b.addEventListener("click", async () => {
      $$("#window-seg .seg-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.windowDays = parseInt(b.dataset.days, 10);
      await loadAnalytics();
      renderAnalytics();
      renderOverview();
    })
  );
}

/* ==========================================================================
   KEYS
   ========================================================================== */
async function loadKeys() {
  try {
    const data = await api("/v1/keys");
    state.keys = data.keys || [];
  } catch (e) {
    toast(`Couldn't load keys: ${e.message}`, "err");
  }
}

function renderKeys() {
  const tbody = $("#keys-table tbody");
  tbody.innerHTML = "";
  if (!state.keys || !state.keys.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:24px">
      No keys yet. Create one above.
    </td></tr>`;
    return;
  }
  state.keys.forEach((k) => {
    const tr = document.createElement("tr");
    tr.className = "row-in";
    tr.innerHTML = `
      <td><strong>${escapeHtml(k.name)}</strong></td>
      <td><code>${escapeHtml(k.key_prefix)}</code></td>
      <td>${k.is_active ? '<span class="pill ok">Active</span>' : '<span class="pill muted">Revoked</span>'}</td>
      <td>${k.last_used_at ? fmtTime(k.last_used_at) : '<span class="muted">Never</span>'}</td>
      <td class="th-actions">
        ${k.is_active
          ? `<button class="btn btn-ghost btn-sm btn-danger rev-key" data-id="${escapeHtml(k.id)}" data-name="${escapeHtml(k.name)}">Revoke</button>`
          : ""}
      </td>
    `;
    tbody.appendChild(tr);
  });
  $$(".rev-key").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm(`Revoke "${b.dataset.name}"? Any client using it will start getting 401 immediately.`)) return;
      try {
        await api(`/v1/keys/${b.dataset.id}`, { method: "DELETE" });
        toast(`Revoked ${b.dataset.name}`, "ok");
        await loadKeys();
        renderKeys();
      } catch (e) {
        toast(e.message, "err");
      }
    })
  );
}

function bindKeyForm() {
  $("#key-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("#key-name").value.trim();
    if (!name) { toast("Give the key a name first", "err"); return; }
    try {
      const r = await api("/v1/keys", { method: "POST", body: JSON.stringify({ name }) });
      $("#key-name").value = "";
      const display = $("#new-key-display");
      $("#new-key-value").textContent = r.api_key;
      display.hidden = false;
      $("#new-key-copy").onclick = (ev) => copyToClipboard(r.api_key, ev.currentTarget);
      toast(`Created ${name}`, "ok");
      await loadKeys();
      renderKeys();
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ==========================================================================
   QUALITY (AA Intelligence Index + manual overrides)
   ========================================================================== */
async function loadQuality() {
  try {
    const data = await api("/v1/quality");
    state.quality = data;
  } catch (e) {
    toast(`Couldn't load quality scores: ${e.message}`, "err");
  }
}

async function loadQualityPreview() {
  try {
    state.qualityPreview = await api("/v1/quality/auto-preview");
  } catch (e) {
    state.qualityPreview = null;
  }
}

function renderQuality() {
  const aa = state.quality?.aa_index || {};
  const setupCard = $("#quality-setup-card");
  const statusCard = $("#quality-status-card");
  const tableCard = $("#quality-table-card");

  // Setup card is informational when no AA key — manual overrides still
  // work standalone, so the table card is always shown. Status card
  // (which surfaces AA freshness) is only meaningful when AA is wired up.
  const isConfigured = aa.source !== "missing-key";
  setupCard.hidden = isConfigured;
  statusCard.hidden = !isConfigured;
  tableCard.hidden = false;

  // Status line — only when AA is configured (the card itself is hidden
  // otherwise, but populating defensively avoids a blank flash on toggle).
  if (isConfigured) {
    const sourceLabel = {
      "live":         '<span class="pill ok">live</span>',
      "stale-cache":  '<span class="pill warn">stale (AA unreachable)</span>',
      "stale-db":     '<span class="pill warn">stale (DB snapshot)</span>',
      "error":        '<span class="pill err">error</span>',
      "missing-key":  '<span class="pill muted">no API key</span>',
    }[aa.source] || `<span class="pill">${escapeHtml(aa.source || "unknown")}</span>`;

    $("#quality-status-line").innerHTML = (
      `${sourceLabel} · matched <strong>${aa.matched_count || 0}</strong> of `
      + `${aa.raw_count || 0} AA models to your catalog · `
      + `<strong>${state.quality.override_count || 0}</strong> manual override`
      + `${state.quality.override_count === 1 ? "" : "s"}`
    );
  }

  renderQualityTable();
}

function renderQualityTable() {
  const tbody = $("#quality-table tbody");
  tbody.innerHTML = "";
  const rows = state.quality?.models || [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="muted" style="text-align:center;padding:24px">
      No models in catalog.
    </td></tr>`;
    return;
  }

  // Show top 60 by effective score; full table is 500+ entries which is
  // overwhelming. Add a search/filter later if needed.
  rows.slice(0, 60).forEach((m) => {
    const tr = document.createElement("tr");
    tr.className = "row-in";
    const aaCell = m.aa_score == null
      ? '<span class="muted">—</span>'
      : `<span title="Artificial Analysis Intelligence Index">${m.aa_score.toFixed(0)}</span>`;
    const manualCell = m.manual_score == null
      ? `<button class="btn btn-ghost btn-sm set-override" data-id="${escapeHtml(m.id)}" data-aa="${m.aa_score ?? ""}">Set</button>`
      : `<strong>${m.manual_score.toFixed(0)}</strong>`;
    const effectiveCell = m.effective_score == null
      ? '<span class="muted">unscored</span>'
      : `<strong>${m.effective_score.toFixed(0)}</strong>`;
    // TPS / TTFT come from AA latency benchmarks — null when AA hasn't
    // indexed this model on that axis. Used by the `fastest` strategy.
    const tpsCell = m.tps == null
      ? '<span class="muted">—</span>'
      : `<span title="Output tokens per second (AA median, max across reasoning variants)">${m.tps.toFixed(0)}</span>`;
    const ttftCell = m.ttft == null
      ? '<span class="muted">—</span>'
      : `<span title="Time to first token in seconds (AA median, min across variants — non-reasoning fast mode)">${m.ttft.toFixed(2)}s</span>`;
    const blendedPerM = (m.blended_cost * 1_000_000).toFixed(2);
    const statusCell = m.deployable
      ? '<span class="pill ok">deployable</span>'
      : '<span class="pill muted">no key</span>';
    const actions = m.manual_score != null
      ? `<button class="btn btn-ghost btn-sm reset-override" data-id="${escapeHtml(m.id)}" title="Revert to AA score">Reset</button>`
      : "";

    tr.innerHTML = `
      <td><code>${escapeHtml(m.id)}</code></td>
      <td>${escapeHtml(m.provider)}</td>
      <td class="num">${aaCell}</td>
      <td class="num">${manualCell}</td>
      <td class="num">${effectiveCell}</td>
      <td class="num">${tpsCell}</td>
      <td class="num">${ttftCell}</td>
      <td class="num">$${blendedPerM}</td>
      <td>${statusCell}</td>
      <td class="th-actions">${actions}</td>
    `;
    tbody.appendChild(tr);
  });

  $$(".set-override").forEach((b) =>
    b.addEventListener("click", () => promptOverride(b.dataset.id, b.dataset.aa))
  );
  $$(".reset-override").forEach((b) =>
    b.addEventListener("click", () => resetOverride(b.dataset.id))
  );
}

function renderQualityPreview() {
  const wrap = $("#quality-preview");
  const body = $("#quality-preview-body");
  if (!state.qualityPreview) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  const p = state.qualityPreview;
  if (!p.primary) {
    body.innerHTML = `<p class="muted">No deployable model satisfies the current capability requirements. Configure a provider key on the Providers page.</p>`;
    return;
  }
  // primary_score is already an int 0-100 from the server (cheapest = null
  // because raw token cost has no meaningful 0-100 mapping).
  const scoreText = p.primary_score != null
    ? `<span class="pill ok">score ${p.primary_score}</span>`
    : `<span class="pill muted">unscored</span>`;
  const fbList = p.fallbacks && p.fallbacks.length
    ? `<div class="small muted">→ falls back to: ${p.fallbacks.map((f) => `<code>${escapeHtml(f)}</code>`).join(", ")}</div>`
    : "";

  // Per-axis breakdown — surfaces the same numbers the ranker used to
  // decide. Without this, `fastest` looks opaque ("primary X, score 73"
  // tells you nothing about WHY it won). Renders as
  // "tps: raw=145.0 (78/100), ttft: raw=0.41s (88/100)" etc.
  const breakdown = p.primary_score_breakdown || {};
  const breakdownEntries = Object.entries(breakdown);
  const breakdownLine = breakdownEntries.length
    ? `<div class="small muted">${breakdownEntries.map(([axis, vals]) => {
        const raw = vals && vals.raw != null
          ? `${typeof vals.raw === "number" ? vals.raw.toLocaleString(undefined, {maximumFractionDigits: 2}) : escapeHtml(String(vals.raw))}`
          : "—";
        const norm = vals && vals.normalized != null
          ? ` (${(vals.normalized * 100).toFixed(0)}/100)`
          : "";
        return `<code>${escapeHtml(axis)}</code>: ${raw}${norm}`;
      }).join(" · ")}</div>`
    : "";

  body.innerHTML = `
    <div><code>${escapeHtml(p.primary)}</code> ${scoreText}</div>
    <div class="small muted">strategy: <code>${escapeHtml(p.strategy)}</code> · scoring: ${escapeHtml(p.scoring_source)}</div>
    ${breakdownLine}
    ${fbList}
  `;
}

async function promptOverride(modelId, aaHint) {
  const seed = aaHint && aaHint !== "" ? aaHint : "";
  const raw = prompt(
    `Set manual quality score for ${modelId} (0-100):`
    + (seed ? `\n\nAA score is currently: ${seed}` : ""),
    seed,
  );
  if (raw == null) return;
  const score = Number(raw);
  if (!Number.isFinite(score) || score < 0 || score > 100) {
    toast("Score must be a number between 0 and 100", "err");
    return;
  }
  const note = prompt("Optional note (why are you overriding?):", "") || null;
  try {
    await api(`/v1/quality/overrides/${encodeURIComponent(modelId)}`, {
      method: "PUT",
      body: JSON.stringify({ score, note }),
    });
    toast(`Override set for ${modelId}`, "ok");
    await Promise.all([loadQuality(), loadQualityPreview()]);
    renderQuality();
    renderQualityPreview();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function resetOverride(modelId) {
  if (!confirm(`Reset ${modelId} to its AA score?`)) return;
  try {
    await api(`/v1/quality/overrides/${encodeURIComponent(modelId)}`, { method: "DELETE" });
    toast(`Reset ${modelId}`, "ok");
    await Promise.all([loadQuality(), loadQualityPreview()]);
    renderQuality();
    renderQualityPreview();
  } catch (e) {
    toast(e.message, "err");
  }
}

function bindQualityRefresh() {
  const btn = $("#quality-refresh");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await api("/v1/quality/refresh", { method: "POST" });
      toast("Refreshed scores from Artificial Analysis", "ok");
      await Promise.all([loadQuality(), loadQualityPreview()]);
      renderQuality();
      renderQualityPreview();
    } catch (e) {
      toast(`Refresh failed: ${e.message}`, "err");
    } finally {
      btn.disabled = false;
    }
  });
}

/* ==========================================================================
   MODELS
   ========================================================================== */
async function loadModels() {
  try {
    const data = await api("/v1/models");
    state.models = data.data || [];
  } catch (e) {
    // Non-fatal — overview just shows "—".
    state.models = [];
  }
}

/* ==========================================================================
   OVERVIEW
   ========================================================================== */
function renderOverview() {
  // KPI cards
  const totalReq = (state.spend.by_model || []).reduce((a, m) => a + m.request_count, 0);
  $("#kpi-spend").textContent = fmtUsd(state.spend.total_microcents);
  $("#kpi-spend-sub").textContent = `across ${fmtNum(totalReq)} requests`;
  $("#kpi-saved").textContent = fmtUsd(state.savings.saved_microcents || 0);
  $("#kpi-saved-sub").textContent =
    state.savings.savings_percent
      ? `vs always-GPT-4o (${state.savings.savings_percent}% off)`
      : "vs always-GPT-4o baseline";

  // Second row: what hosted-auto could save on top of current routing.
  const hostedAuto = state.savings.hosted_auto;
  const haEl = $("#kpi-hosted-auto-value");
  if (haEl) {
    if (hostedAuto && hostedAuto.saved_microcents > 0) {
      haEl.textContent = `+${fmtUsd(hostedAuto.saved_microcents)} (${hostedAuto.savings_percent}%)`;
    } else if (hostedAuto && hostedAuto.comparable_request_count > 0) {
      haEl.textContent = "already optimal";
    } else {
      haEl.textContent = "—";
    }
  }

  // True p50/p99 across raw request samples — averaging per-provider
  // percentiles is the "median of medians" trap. The /v1/analytics/latency
  // endpoint only exposes pre-aggregated per-provider values, so we derive
  // global percentiles from the raw latency_ms in /v1/analytics/recent
  // (already loaded into state.recent), using the same algorithm as the
  // backend's _percentile() in app/routes/analytics.py.
  const rawLat = (state.recent || [])
    .map((r) => r.latency_ms)
    .filter((n) => Number.isFinite(n) && n >= 0);
  const p50 = percentile(rawLat, 0.5);
  const p99 = percentile(rawLat, 0.99);
  $("#kpi-p50").textContent = rawLat.length ? `${fmtNum(p50)} ms` : "— ms";
  $("#kpi-p99").textContent = rawLat.length ? `p99 ${fmtNum(p99)} ms` : "p99 — ms";

  $("#kpi-models").textContent = state.models.length ? fmtNum(state.models.length) : "—";
  $("#kpi-providers").textContent = `${state.providers.length} provider${state.providers.length === 1 ? "" : "s"} configured`;

  // Recent mini
  const mini = $("#overview-recent");
  if (!state.recent.length) {
    mini.innerHTML = `<div class="empty-mini">
      <p>No requests yet.</p>
      <p class="muted">Once you send your first <code>chat.completions</code> call, it'll show up here.</p>
    </div>`;
  } else {
    mini.innerHTML = state.recent.slice(0, 5).map((it) => {
      const ok = (it.status_code || 0) < 400;
      return `
        <div class="recent-row">
          <span class="recent-when">${fmtTime(it.created_at)}</span>
          <span class="recent-model">${escapeHtml(it.model_resolved || "—")}</span>
          <span class="recent-latency">${fmtNum(it.latency_ms)} ms</span>
          <span class="pill ${ok ? "ok" : "err"}">${ok ? "OK" : it.status_code}</span>
        </div>`;
    }).join("");
  }
}

/* ─────────────── quickstart snippet ─────────────── */
function snippetFor(lang, baseUrl, key) {
  const k = key && key.startsWith("sk-orca-") ? key : "sk-orca-...";
  if (lang === "node") {
    return `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${baseUrl}",
  apiKey:  "${k}",
});

const r = await client.chat.completions.create({
  model: "auto",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(r.choices[0].message.content);`;
  }
  if (lang === "curl") {
    return `curl ${baseUrl}/chat/completions \\
  -H "Authorization: Bearer ${k}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "auto",
    "messages": [{"role":"user","content":"Hello!"}]
  }'`;
  }
  return `from openai import OpenAI

client = OpenAI(
    base_url="${baseUrl}",
    api_key="${k}",
)

r = client.chat.completions.create(
    model="auto",  # or "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "Hello!"}],
)
print(r.choices[0].message.content)`;
}

function renderQuickstart() {
  const baseUrl = `${location.origin}/v1`;
  $("#base-url-code").textContent = baseUrl;
  $("#help-base-url").textContent = baseUrl;
  $("#quickstart-code").textContent = snippetFor(state.lang, baseUrl, state.apiKey);
}

function bindQuickstart() {
  $$("#lang-seg .seg-btn").forEach((b) =>
    b.addEventListener("click", () => {
      $$("#lang-seg .seg-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.lang = b.dataset.lang;
      renderQuickstart();
    })
  );
  $("#copy-snippet").addEventListener("click", (e) => {
    copyToClipboard($("#quickstart-code").textContent, e.currentTarget);
  });
  $("#copy-base-url").addEventListener("click", () => {
    copyToClipboard(`${location.origin}/v1`);
  });
}

/* ─────────────── onboarding checklist ─────────────── */
function syncOnboarding() {
  const banner = $("#getting-started");
  if (!banner) return;
  if (localStorage.getItem(ONBOARDING_KEY) === "1") {
    banner.classList.add("dismissed");
    return;
  }
  const step1 = state.providers.length > 0;
  const step2 = !!state.routing.strategy;
  const step3 = state.recent.length > 0;
  $("#step-1").classList.toggle("done", step1);
  $("#step-2").classList.toggle("done", step2);
  $("#step-3").classList.toggle("done", step3);
  if (step1 && step2 && step3) {
    setTimeout(() => {
      banner.classList.add("dismissed");
      localStorage.setItem(ONBOARDING_KEY, "1");
    }, 1800);
  }
}

function bindOnboarding() {
  $("#dismiss-getting-started").addEventListener("click", () => {
    localStorage.setItem(ONBOARDING_KEY, "1");
    $("#getting-started").classList.add("dismissed");
  });
}

/* ==========================================================================
   HEALTH POLLING
   ========================================================================== */
async function pollHealth() {
  const dot = $("#health-dot");
  const txt = $("#health-text");
  async function tick() {
    try {
      await api("/health");
      dot.classList.remove("err"); dot.classList.add("ok");
      txt.textContent = t("status.connected");
    } catch {
      dot.classList.remove("ok"); dot.classList.add("err");
      txt.textContent = t("status.disconnected");
    }
  }
  await tick();
  setInterval(tick, 15_000);
}

/* ==========================================================================
   HELP DRAWER
   ========================================================================== */
function openHelp() {
  $("#help-drawer").hidden = false;
  $("#scrim").hidden = false;
}
function closeHelp() {
  const d = $("#help-drawer");
  d.hidden = true;
  $("#scrim").hidden = true;
}
function bindHelp() {
  $("#open-help").addEventListener("click", openHelp);
  $("#close-help").addEventListener("click", closeHelp);
  $("#scrim").addEventListener("click", () => {
    closeHelp();
  });
}

/* ==========================================================================
   COMMAND PALETTE
   ========================================================================== */
function paletteCommands() {
  return [
    { id: "go-overview",  title: "Go to Overview",       meta: "Tab",  hint: "1",  do: () => setTab("overview")  },
    { id: "go-providers", title: "Go to Providers",      meta: "Tab",  hint: "2",  do: () => setTab("providers") },
    { id: "go-routing",   title: "Go to Routing",        meta: "Tab",  hint: "3",  do: () => setTab("routing")   },
    { id: "go-analytics", title: "Go to Analytics",      meta: "Tab",  hint: "4",  do: () => setTab("analytics") },
    { id: "go-keys",      title: "Go to API keys",       meta: "Tab",  hint: "5",  do: () => setTab("keys")      },
    { id: "copy-base",    title: "Copy base URL",        meta: "Action", hint: "", do: () => copyToClipboard(`${location.origin}/v1`) },
    { id: "copy-snip",    title: "Copy quickstart snippet", meta: "Action", hint: "", do: () => copyToClipboard($("#quickstart-code").textContent) },
    { id: "open-help",    title: "Open help & docs",     meta: "Help", hint: "?",  do: () => openHelp() },
    { id: "open-docs",    title: "Open docs.orcarouter.ai", meta: "Link", hint: "↗", do: () => window.open("https://docs.orcarouter.ai/introduction", "_blank") },
    { id: "open-site",    title: "Open orcarouter.ai",   meta: "Link", hint: "↗",  do: () => window.open("https://www.orcarouter.ai", "_blank") },
    { id: "logout",       title: "Sign out (forget API key)", meta: "Action", hint: "", do: () => logout() },
  ];
}

let paletteFocus = 0;

function openPalette() {
  $("#palette").hidden = false;
  $("#palette-input").value = "";
  paletteFocus = 0;
  renderPalette("");
  setTimeout(() => $("#palette-input").focus(), 10);
}
function closePalette() { $("#palette").hidden = true; }

function renderPalette(query) {
  const q = query.trim().toLowerCase();
  const all = paletteCommands();
  const items = q ? all.filter((c) => c.title.toLowerCase().includes(q)) : all;
  const list = $("#palette-list");
  if (!items.length) {
    list.innerHTML = `<li class="palette-empty">No matches</li>`;
    return;
  }
  list.innerHTML = items.map((c, i) => `
    <li class="palette-item ${i === paletteFocus ? "focused" : ""}" data-id="${c.id}">
      <span>${escapeHtml(c.title)}</span>
      <span class="meta">${escapeHtml(c.hint || c.meta)}</span>
    </li>
  `).join("");
  $$("#palette-list .palette-item").forEach((el) =>
    el.addEventListener("click", () => {
      const cmd = items.find((c) => c.id === el.dataset.id);
      if (cmd) { closePalette(); cmd.do(); }
    })
  );
}

function bindPalette() {
  $("#open-palette").addEventListener("click", openPalette);
  $("#palette-close").addEventListener("click", closePalette);
  const input = $("#palette-input");
  input.addEventListener("input", () => { paletteFocus = 0; renderPalette(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
      return;
    }
    const visible = $$("#palette-list .palette-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      paletteFocus = Math.min(visible.length - 1, paletteFocus + 1);
      renderPalette(input.value);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      paletteFocus = Math.max(0, paletteFocus - 1);
      renderPalette(input.value);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const focused = visible[paletteFocus];
      if (focused) {
        const all = paletteCommands();
        const q = input.value.trim().toLowerCase();
        const items = q ? all.filter((c) => c.title.toLowerCase().includes(q)) : all;
        const cmd = items.find((c) => c.id === focused.dataset.id);
        if (cmd) { closePalette(); cmd.do(); }
      }
    }
  });
  // click on the backdrop (anywhere outside the card) closes
  $("#palette").addEventListener("click", (e) => {
    if (!e.target.closest(".palette-card")) closePalette();
  });
}

/* ==========================================================================
   LOGOUT
   ========================================================================== */
function logout() {
  localStorage.removeItem(KEY_STORAGE);
  state.apiKey = "";
  showGate();
  toast("Signed out — your key is forgotten on this device", "info");
}

/* ==========================================================================
   GLOBAL KEYBOARD SHORTCUTS
   ========================================================================== */
function bindKeyboard() {
  document.addEventListener("keydown", (e) => {
    const inField = e.target.matches("input, textarea, [contenteditable=true]");
    const cmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";

    if (cmdK) {
      e.preventDefault();
      if ($("#palette").hidden) openPalette(); else closePalette();
      return;
    }
    if (e.key === "Escape") {
      if (!$("#palette").hidden) closePalette();
      else if (!$("#help-drawer").hidden) closeHelp();
      return;
    }
    if (inField) return;
    if ($("#auth-gate").hidden === false) return;

    if (e.key === "?") { e.preventDefault(); $("#help-drawer").hidden ? openHelp() : closeHelp(); }
    if (e.key >= "1" && e.key <= "5") {
      const order = ["overview", "providers", "routing", "analytics", "keys"];
      const idx = parseInt(e.key, 10) - 1;
      if (order[idx]) setTab(order[idx]);
    }
  });
}

/* ==========================================================================
   AUTH FORM BIND
   ========================================================================== */
function bindAuth() {
  const form = $("#auth-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = $("#api-key-input").value.trim();
    if (!v) return;
    state.apiKey = v;
    localStorage.setItem(KEY_STORAGE, v);
    const status = $("#auth-status");
    status.textContent = t("auth.checking");
    status.classList.remove("ok");
    const ok = await checkAuth();
    if (ok) {
      status.textContent = t("auth.welcome_aboard");
      status.classList.add("ok");
      setTimeout(showShell, 350);
    } else {
      status.textContent = t("auth.key_invalid");
      localStorage.removeItem(KEY_STORAGE);
      state.apiKey = "";
    }
  });

  $("#api-key-toggle").addEventListener("click", () => {
    const i = $("#api-key-input");
    i.type = i.type === "password" ? "text" : "password";
  });

  $("#logout-btn").addEventListener("click", logout);
}

/* ==========================================================================
   BOOT
   ========================================================================== */
document.addEventListener("DOMContentLoaded", async () => {
  state.locale = detectLocale();
  applyI18n();
  bindLocalePicker();
  bindAuth();
  bindTabs();
  bindProviderForm();
  bindRouting();
  bindWindowSeg();
  bindKeyForm();
  bindQualityRefresh();
  bindHelp();
  bindPalette();
  bindKeyboard();
  bindQuickstart();
  bindOnboarding();
  bindHostedForm();

  // Probe existing key
  const ok = await checkAuth();
  if (ok) showShell();
  else showGate();
});

window.addEventListener("hashchange", () => {
  const t = (location.hash || "").replace("#", "");
  if (TAB_META[t]) setTab(t);
});
