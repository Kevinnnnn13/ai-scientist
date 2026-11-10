/* ============================================
   AI Scientist 2.0 — 多页面应用主脚本
   整合前端设计完成版布局 + 后端修改版全部功能
   ============================================ */

// ==================== 配置与常量 ====================
const EXAMPLES = [
  "What is the microscopic mechanism for high-temperature superconductivity?",
  "How did the universe begin and how will it end?",
  "How does consciousness arise from the physical brain?",
  "In a crossed Cannizzaro reaction between two aromatic aldehydes bearing different substituents, which aldehyde is oxidized - the one with an electron-withdrawing group or the one with an electron-donating group?"
];

const STAGE_NAMES = {
  "知识整合": "知识整合",
  "缺口分析": "缺口分析",
  "假设生成": "假设生成",
  "评审": "评审迭代",
  "可验证性验证": "可验证性验证",
  "完成": "完成"
};

const FIELD_COLORS = {
  "依据": "accent",
  "提出依据": "accent",
  "研究缺口": "accent",
  "背景": "accent",
  "预期结果": "good",
  "验证方法": "neon",
  "修改说明": "warn",
  "说明": "warn"
};

const FIELD_NUM_COLORS = {"①": "accent", "②": "neon", "③": "good", "④": "violet", "⑤": "warn"};

const PAPER_MAX = 3;

// ==================== LaTeX 转换表 ====================
const LATEX_SYMBOLS = {
  "alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε","varepsilon":"ε",
  "zeta":"ζ","eta":"η","theta":"θ","vartheta":"ϑ","iota":"ι","kappa":"κ","lambda":"λ",
  "mu":"μ","nu":"ν","xi":"ξ","omicron":"ο","pi":"π","varpi":"ϖ","rho":"ρ","sigma":"σ",
  "varsigma":"ς","tau":"τ","upsilon":"υ","phi":"φ","varphi":"φ","chi":"χ","psi":"ψ","omega":"ω",
  "Gamma":"Γ","Delta":"Δ","Theta":"Θ","Lambda":"Λ","Xi":"Ξ","Pi":"Π","Sigma":"Σ",
  "Upsilon":"Υ","Phi":"Φ","Psi":"Ψ","Omega":"Ω",
  "infty":"∞","partial":"∂","nabla":"∇","propto":"∝","hbar":"ℏ",
  "pm":"±","mp":"∓","times":"×","div":"÷","cdot":"·","ast":"∗",
  "leq":"≤","geq":"≥","le":"≤","ge":"≥","neq":"≠","ne":"≠","ll":"≪","gg":"≫",
  "approx":"≈","simeq":"≃","sim":"∼","equiv":"≡","cong":"≅",
  "in":"∈","notin":"∉","ni":"∋","subset":"⊂","supset":"⊃","subseteq":"⊆","supseteq":"⊇",
  "cup":"∪","cap":"∩","forall":"∀","exists":"∃","nexists":"∄","neg":"¬","land":"∧","lor":"∨",
  "emptyset":"∅","circ":"∘","dagger":"†","ddagger":"‡","bullet":"•","prime":"′","degree":"°","ell":"ℓ",
  "to":"→","rightarrow":"→","leftarrow":"←","mapsto":"↦","Rightarrow":"⇒","Leftarrow":"⇐",
  "leftrightarrow":"↔","uparrow":"↑","downarrow":"↓","longrightarrow":"→",
  "int":"∫","oint":"∮","iint":"∬","iiint":"∭","sum":"Σ","prod":"∏","bigcup":"⋃","bigcap":"⋂","lim":"lim",
  "dots":"…","ldots":"…","cdots":"…","vdots":"⋮","ddots":"⋱",
  "langle":"⟨","rangle":"⟩","lfloor":"⌊","rfloor":"⌋","lceil":"⌈","rceil":"⌉",
  "parallel":"∥","perp":"⊥"
};
const LATEX_SUB = {"0":"₀","1":"₁","2":"₂","3":"₃","4":"₄","5":"₅","6":"₆","7":"₇","8":"₈","9":"₉","+":"₊","-":"₋","=":"₌","(":"₍",")":"₎"};
const LATEX_SUB_L = {"a":"ₐ","e":"ₑ","h":"ₕ","i":"ᵢ","j":"ⱼ","k":"ₖ","l":"ₗ","m":"ₘ","n":"ₙ","o":"ₒ","p":"ₚ","r":"ᵣ","s":"ₛ","t":"ₜ","u":"ᵤ","v":"ᵥ","x":"ₓ"};
const LATEX_SUP = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹","+":"⁺","-":"⁻","=":"⁼","(":"⁽",")":"⁾"};
const LATEX_SUP_L = {"a":"ᵃ","b":"ᵇ","c":"ᶜ","d":"ᵈ","e":"ᵉ","f":"ᶠ","g":"ᵍ","h":"ʰ","i":"ⁱ","j":"ʲ","k":"ᵏ","l":"ˡ","m":"ᵐ","n":"ⁿ","o":"ᵒ","p":"ᵖ","r":"ʳ","s":"ˢ","t":"ᵗ","u":"ᵘ","v":"ᵛ","w":"ʷ","x":"ˣ","y":"ʸ","z":"ᶻ"};
const LATEX_TEXT_CMDS = ["text","mathrm","mathbf","boldsymbol","bm","mathit","operatorname","textrm","textbf","emph","it","sf","tt","mathcal","mathbb","mathfrak"];
const LATEX_SYM_RE = new RegExp("\\\\(?:" + Object.keys(LATEX_SYMBOLS).sort((a, b) => b.length - a.length).join("|") + ")(?![a-zA-Z])", "g");

// ==================== 全局状态 ====================
let currentRunId = null;
let pollTimer = null;
let fbVerdict = "通过";
let progressMax = 0;
let finishingWait = 0;
let translateTimer = null;
let originalText = null;
let translateSeq = 0;
let typewriterTimer = null;
let typewriterText = '';
let typewriterIndex = 0;
let pendingRun = null;
let currentUser = null;

// ==================== 工具函数 ====================
function escapeHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escJs(s) {
  return JSON.stringify(String(s == null ? "" : s))
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function progressPct(p) {
  const s = (p && p.stage) || "";
  const r = p.round || 0;
  if (s === "完成") return 100;
  if (s === "可验证性验证") return 90;
  if (s === "评审") return Math.min(40 + (r - 1) * 5, 85);
  if (s === "假设生成") return Math.min(35 + (r - 1) * 5, 80);
  if (s === "缺口分析") return 20;
  if (s === "知识整合") return 8;
  return 3;
}

function renderProgress(p) {
  const card = document.getElementById("progressCard");
  if (!card) return;
  if (!p) { card.style.display = "none"; return; }
  card.style.display = "";
  const pct = Math.max(progressPct(p), progressMax);
  progressMax = pct;
  const pfill = document.getElementById("pfill");
  const pStage = document.getElementById("pStage");
  const pDetail = document.getElementById("pDetail");
  const pPct = document.getElementById("pPct");
  if (pfill) pfill.style.width = pct + "%";
  if (pStage) pStage.textContent = STAGE_NAMES[p.stage] || p.stage || "启动中";
  if (pDetail) pDetail.textContent = p.detail || "";
  if (pPct) pPct.textContent = pct + "%";
}

function timeAgo(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return s + '秒前';
  if (s < 3600) return Math.floor(s / 60) + '分钟前';
  if (s < 86400) return Math.floor(s / 3600) + '小时前';
  return Math.floor(s / 86400) + '天前';
}

async function api(path, opts) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    throw new Error("无法连接后端服务（" + e.message + "）。请先启动服务：python src\\api_server.py，然后刷新本页重试");
  }
  if (!r.ok) {
    let msg = "HTTP " + r.status;
    try { const j = await r.json(); msg = j.error || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

// ==================== LaTeX 转换 ====================
function latexScript(content, kind) {
  if (!content) return "";
  const mapping = kind === "sub"
    ? Object.assign({}, LATEX_SUB, LATEX_SUB_L)
    : Object.assign({}, LATEX_SUP, LATEX_SUP_L);
  let ok = true;
  for (const ch of content) { if (!(ch in mapping)) { ok = false; break; } }
  if (ok) return Array.from(content).map(ch => mapping[ch]).join("");
  if (/^[A-Za-z0-9_.+\-]+$/.test(content)) return (kind === "sub" ? "_" : "^") + content;
  return (kind === "sub" ? "_" : "^") + "(" + content + ")";
}

function latexConvertFrag(s) {
  for (const cmd of LATEX_TEXT_CMDS) {
    s = s.replace(new RegExp("\\\\" + cmd + "\\s*\\{([^{}]*)\\}", "g"), "$1");
  }
  s = s.replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, (m, num, den) => {
    num = (num || "").trim(); den = (den || "").trim();
    const simple = t => /^[A-Za-z0-9_.+\-^()/]+$/.test(t);
    num = simple(num) ? num : "(" + num + ")";
    den = simple(den) ? den : "(" + den + ")";
    return num + "/" + den;
  });
  s = s.replace(/\\sqrt(?:\[([^\]]*)\])?\s*\{([^{}]*)\}/g, (m, n, x) => (n ? "√" + n : "√") + "(" + x + ")");
  s = s.replace(/\\overline\{([^{}]*)\}/g, (m, x) => x + "\u0305");
  s = s.replace(/\\bar\{([^{}]*)\}/g, (m, x) => x + "\u0304");
  s = s.replace(/\\hat\{([^{}]*)\}/g, (m, x) => x + "\u0302");
  s = s.replace(/\\tilde\{([^{}]*)\}/g, (m, x) => x + "\u0303");
  s = s.replace(/\\left|\\right|\\big[lr]?|\\Big[lr]?|\\bigg[lr]?|\\Bigg[lr]?/g, "");
  s = s.replace(LATEX_SYM_RE, m => LATEX_SYMBOLS[m.slice(1)]);
  s = s.replace(/\^\{([^{}]*)\}/g, (m, c) => latexScript(c, "sup"));
  s = s.replace(/_\{([^{}]*)\}/g, (m, c) => latexScript(c, "sub"));
  s = s.replace(/\^([0-9a-zA-Z])(?![0-9a-zA-Z])/g, (m, c) => latexScript(c, "sup"));
  s = s.replace(/_([0-9a-zA-Z])(?![0-9a-zA-Z])/g, (m, c) => latexScript(c, "sub"));
  s = s.replace(/''/g, "″").replace(/'/g, "′");
  s = s.replace(/\\[,;:!]|\\quad|\\qquad|\\;|\\:|\\ /g, " ");
  s = s.replace(/\\\\/g, " ");
  s = s.replace(/\\(?:displaystyle|textstyle|limits|nolimits|phantom)\b/g, "");
  s = s.replace(/\\[a-zA-Z]+\*?/g, "");
  s = s.replace(/\{/g, "(").replace(/\}/g, ")");
  s = s.replace(/~/g, " ");
  s = s.replace(/ {2,}/g, " ");
  return s.trim();
}

function latexToUnicode(text) {
  if (!text) return text;
  let s = String(text);
  s = s.replace(/\\\(\s*([\s\S]*?)\s*\\\)/g, (m, c) => latexConvertFrag(c));
  s = s.replace(/\\\[\s*([\s\S]*?)\s*\\\]/g, (m, c) => latexConvertFrag(c));
  s = s.replace(/\$\$([\s\S]*?)\$\$/g, (m, c) => latexConvertFrag(c));
  s = s.replace(/(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)/g, (m, c) => latexConvertFrag(c));
  s = latexConvertFrag(s);
  return s;
}

// ==================== 打字机效果 ====================
function setThinkingText(text) {
  const el = document.getElementById('thinkDetail');
  if (!el) return;
  clearInterval(typewriterTimer);
  typewriterText = text || '';
  typewriterIndex = 0;
  el.textContent = '';
  el.classList.add('type-cursor');
  typewriterTimer = setInterval(() => {
    if (typewriterIndex < typewriterText.length) {
      el.textContent += typewriterText.charAt(typewriterIndex);
      typewriterIndex++;
    } else {
      clearInterval(typewriterTimer);
    }
  }, 25);
}

function setThinkingStage(text) {
  const el = document.getElementById('thinkStage');
  if (el) el.textContent = text || 'AI 思考中…';
}

// ==================== 页面初始化路由 ====================
document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  initQualitySelector();
  initMobileMenu();
  const page = document.body.dataset.page;
  if (page === 'index') initIndex();
  else if (page === 'running') initRunning();
  else if (page === 'result') initResult();
});

// ==================== 侧边栏 ====================
async function initSidebar() {
  await refreshHistory();
  setupHistoryInteractions();
}

function initMobileMenu() {
  const btn = document.getElementById('menuBtn');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  if (!btn || !sidebar) return;
  btn.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('active');
  });
  if (overlay) {
    overlay.addEventListener('click', () => {
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
    });
  }
}

async function refreshHistory() {
  const h = document.getElementById("history");
  if (!h) return;
  try {
    const r = await api("/api/runs");
    if (!r.runs.length) { h.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:13px">（暂无运行记录）</div>'; return; }
    h.innerHTML = r.runs.map((x, i) => {
      const statusClass = x.status === "done" ? "done" : x.status === "running" ? "running" : "err";
      const timeText = x.started ? timeAgo(x.started) : "";
      return '<div class="history-item-row" data-run-id="' + escapeHtml(x.run_id) + '">' +
        '<div class="history-item-inner" data-run-id="' + escapeHtml(x.run_id) + '">' +
        '<div class="q">' + escapeHtml((x.question || "").slice(0, 60)) + '</div>' +
        '<div class="meta"><span class="status-dot ' + statusClass + '"></span>' + escapeHtml(x.status) + (timeText ? ' · ' + timeText : '') + '</div>' +
        '</div>' +
        '<button class="history-item-delete" data-run-id="' + escapeHtml(x.run_id) + '" title="删除这条记录">×</button>' +
        '</div>';
    }).join("");
  } catch (e) {
    h.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:13px">（加载失败）</div>';
  }
}

let _historyEventsBound = false;
function setupHistoryInteractions() {
  const container = document.getElementById('history');
  if (!container) return;
  if (_historyEventsBound) return;
  _historyEventsBound = true;
  container.addEventListener('click', (e) => {
    const delBtn = e.target.closest('.history-item-delete');
    if (delBtn) {
      e.preventDefault();
      e.stopPropagation();
      const runId = delBtn.dataset.runId;
      if (runId) deleteRun(runId);
      return;
    }
    const inner = e.target.closest('.history-item-inner');
    if (inner) {
      const runId = inner.dataset.runId;
      if (runId) location.href = 'result.html?run_id=' + encodeURIComponent(runId);
    }
  });
}

async function deleteRun(runId) {
  if (!runId) return;
  if (!confirm('确定要删除这条运行记录吗？')) return;
  try {
    const r = await api('/api/run/' + encodeURIComponent(runId) + '?user=' + encodeURIComponent(currentUser || 'guest'), { method: 'DELETE' });
    if (r && r.deleted) {
      await refreshHistory();
    } else {
      alert('删除失败：' + (r && r.error ? r.error : '未知错误'));
    }
  } catch (err) {
    alert('删除失败（后端接口可能未接入）：' + err.message);
  }
}

// ==================== 档位选择器 ====================
function initQualitySelector() {
  const container = document.getElementById('qualitySelector');
  if (!container) return;
  const options = container.querySelectorAll('.quality-option');
  options.forEach(opt => {
    opt.addEventListener('click', () => {
      options.forEach(o => o.classList.remove('active'));
      opt.classList.add('active');
      const input = document.getElementById('quality');
      if (input) input.value = opt.dataset.value;
      updateTopBadge(opt.dataset.value);
    });
  });
}

function updateTopBadge(val) {
  const badge = document.getElementById('topBadge');
  if (badge) badge.innerHTML = '<span style="display:inline-block;width:6px;height:6px;background:var(--accent);border-radius:50%;box-shadow:0 0 8px var(--accent);margin-right:6px"></span>' + escapeHtml(val || '超好');
}

// ==================== 输入框自动高度 ====================
function autoResize(el) {
  el.style.height = 'auto';
  const newHeight = Math.min(Math.max(el.scrollHeight, 56), 200);
  el.style.height = newHeight + 'px';
}

// ==================== Enter 键发送 ====================
function handleEnter(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    startRun();
  }
}

// ==================== 登录弹窗（切换账号） ====================
function toggleLoginModal() {
  const modal = document.getElementById('loginModal');
  const overlay = document.getElementById('loginModalOverlay');
  if (!modal || !overlay) return;
  const isOpen = modal.classList.contains('active');
  if (isOpen) {
    modal.classList.remove('active');
    overlay.classList.remove('active');
  } else {
    modal.classList.add('active');
    overlay.classList.add('active');
  }
}

function handleLogin() {
  const account = document.getElementById('loginAccount');
  const acc = account ? account.value.trim() : '';
  if (!acc) { alert('请输入用户名'); return; }
  doLogin(acc, true);
  toggleLoginModal();
}

// ==================== Index 页面逻辑 ====================
function initIndex() {
  updateTopBadge('超好');
  const q = document.getElementById('q');
  if (q) {
    const params = new URLSearchParams(location.search);
    const rq = params.get('question');
    if (rq) {
      q.value = rq;
      autoResize(q);
    }
  }
  initAuth();
  addPaperSlot();
}

function detectAndTranslate() {
  const row = document.getElementById("translateRow");
  const q = document.getElementById("q");
  if (!row || !q) return;
  const text = q.value.trim();
  if (!/[\u4e00-\u9fff]/.test(text)) { row.style.display = "none"; return; }
  clearTimeout(translateTimer);
  translateTimer = setTimeout(async () => {
    const q2 = document.getElementById("q").value.trim();
    if (!/[\u4e00-\u9fff]/.test(q2)) return;
    const seq = ++translateSeq;
    try {
      const r = await api("/api/translate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: q2 })
      });
      if (seq !== translateSeq) return;
      originalText = q2;
      const tEl = document.getElementById("translatedText");
      if (tEl) tEl.textContent = r.translated;
      row.style.display = "";
    } catch (e) {
      row.style.display = "";
      const tEl = document.getElementById("translatedText");
      if (tEl) tEl.textContent = "翻译服务暂不可用，建议直接使用英文提问";
    }
  }, 1200);
}

function useTranslation() {
  const t = document.getElementById("translatedText");
  const q = document.getElementById("q");
  if (t && q && t.textContent.trim()) {
    q.value = t.textContent.trim();
    autoResize(q);
  }
  const row = document.getElementById("translateRow");
  if (row) row.style.display = "none";
}

function restoreOriginal() {
  const q = document.getElementById("q");
  if (originalText && q) {
    q.value = originalText;
    autoResize(q);
  }
  const row = document.getElementById("translateRow");
  if (row) row.style.display = "none";
}

// ---- 论文输入模块 ----
function addPaperSlot() {
  if (document.querySelectorAll(".paper-slot").length >= PAPER_MAX) { alert("最多添加 " + PAPER_MAX + " 篇论文"); return; }
  const n = document.querySelectorAll(".paper-slot").length + 1;
  const wrap = document.createElement("div");
  wrap.className = "paper-slot";
  wrap.innerHTML =
    '<div class="row" style="margin-bottom:8px">' +
      '<span class="muted">论文 ' + n + '</span>' +
      '<label class="file-btn">上传 .md/.docx/.pdf' +
        '<input type="file" accept=".md,.markdown,.txt,.docx,.pdf" style="display:none" onchange="handlePaperFile(this)">' +
      '</label>' +
      '<button type="button" onclick="this.closest(\'.paper-slot\').remove()" style="margin-left:auto;padding:4px 10px;background:var(--panel2);color:var(--muted);border:1px solid var(--border);border-radius:6px;cursor:pointer">移除</button>' +
    '</div>' +
    '<textarea class="paper-txt" placeholder="粘贴论文全文（或标题+摘要）… 或将 .md/.docx/.pdf 拖入此框" style="min-height:90px"></textarea>' +
    '<div class="paper-msg"></div>';
  document.getElementById("paperSlots").appendChild(wrap);
  const ta = wrap.querySelector("textarea.paper-txt");
  ["dragenter", "dragover"].forEach(ev => ta.addEventListener(ev, e => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).indexOf("Files") >= 0) {
      e.preventDefault();
      ta.classList.add("dragover");
    }
  }));
  ["dragleave", "drop"].forEach(ev => ta.addEventListener(ev, e => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).indexOf("Files") >= 0) {
      e.preventDefault();
      ta.classList.remove("dragover");
      if (ev === "drop" && e.dataTransfer.files && e.dataTransfer.files[0]) {
        parsePaperFile(e.dataTransfer.files[0], wrap);
      }
    }
  }));
  ta.addEventListener("input", () => maybeAutoAddNextSlot(wrap));
}

function maybeAutoAddNextSlot(slot) {
  const slots = document.querySelectorAll(".paper-slot");
  if (slots.length >= PAPER_MAX) return;
  if (!slot || slots[slots.length - 1] !== slot) return;
  const ta = slot.querySelector("textarea.paper-txt");
  if (!ta || !ta.value.trim()) return;
  addPaperSlot();
}

function paperTexts() {
  return Array.from(document.querySelectorAll(".paper-slot textarea.paper-txt"))
    .map(t => t.value.trim()).filter(Boolean);
}

function base64FromBuffer(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

async function parsePaperFile(f, slot) {
  if (!f || !slot) return;
  const msg = slot.querySelector(".paper-msg");
  const ta = slot.querySelector("textarea.paper-txt");
  const ext = (f.name.split(".").pop() || "").toLowerCase();
  msg.textContent = "正在解析 " + f.name + " …";
  try {
    if (ext === "md" || ext === "markdown" || ext === "txt") {
      ta.value = await f.text();
      msg.textContent = "已读取 " + f.name + "（" + ta.value.length + " 字）";
    } else if (ext === "docx" || ext === "pdf") {
      const buf = await f.arrayBuffer();
      msg.textContent = "正在解析 " + f.name + " …（PDF 走云端，首次约 1~2 分钟）";
      const r = await api("/api/parse_doc", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: f.name, data: base64FromBuffer(buf)})
      });
      ta.value = r.text || "";
      const srcTag = r.source === "mineru" ? "（云端解析）" : "";
      msg.textContent = "已提取" + srcTag + " " + f.name + "：" + r.chars + " 字" + (r.warning ? "（" + r.warning + "）" : "");
    } else {
      msg.textContent = "不支持的文件类型：" + ext + "（仅 .md / .docx / .pdf）";
    }
    maybeAutoAddNextSlot(slot);
  } catch (e) {
    msg.textContent = "解析失败：" + e;
  }
}

function handlePaperFile(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  const slot = input.closest(".paper-slot");
  parsePaperFile(f, slot);
}

// ---- 启动运行 ----
async function startRun() {
  let q = document.getElementById("q").value.trim();
  if (!q) { alert("请输入科学问题"); return; }
  let note = "";
  let qEn = "";   // 中文问题：保留原文，翻译放到 question_en（后端中英文文献池分别检索）
  const statusEl = document.getElementById("status");
  const startBtn = document.getElementById("start");

  if (/[\u4e00-\u9fff]/.test(q)) {
    const row = document.getElementById("translateRow");
    const t = document.getElementById("translatedText").textContent.trim();
    if (row && row.style.display !== "none" && t) {
      qEn = t;   // 翻译保留给英文文献池；q 仍是中文原文（中文文献池）
      note = "（已自动翻译为英文，中英文文献池分别检索）";
      if (statusEl) statusEl.textContent = "已自动翻译为英文，中英文文献池分别检索";
    } else {
      if (statusEl) statusEl.textContent = "提示：检测到中文提问，建议改用英文提升文献命中率（仍继续运行）";
    }
  }

  if (startBtn) startBtn.disabled = true;
  if (statusEl) statusEl.textContent = "启动中…";

  try {
    const papers = paperTexts();
    if (papers.length > PAPER_MAX) { alert("最多 " + PAPER_MAX + " 篇论文"); return; }
    const qualityVal = document.getElementById("quality") ? document.getElementById("quality").value : "超好";
    const body = {question: q, quality: qualityVal, username: currentUser};
    if (qEn) body.question_en = qEn;
    if (papers.length > 0) body.papers = papers;
    const r = await api("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
    if (r.blocked) {
      showBlocked(r);
      if (startBtn) startBtn.disabled = false;
      return;
    }
    if (r.need_clarify) {
      pendingRun = {question: q, quality: qualityVal, papers: papers, note: note};
      renderClarify(r.questions || [], r.reason || "");
      if (statusEl) statusEl.textContent = "需要补充细节（追问精修）";
      return;
    }
    currentRunId = r.run_id;
    window.location.href = 'running.html?run_id=' + encodeURIComponent(currentRunId);
  } catch (e) {
    if (statusEl) statusEl.textContent = "启动失败：" + e;
    if (startBtn) startBtn.disabled = false;
  }
}

// ---- 追问精修 ----
function renderClarify(questions, reason) {
  const box = document.getElementById("clarifyQuestions");
  if (!box) return;
  box.innerHTML = "";
  (questions || []).forEach((q, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "clarify-question-wrap";
    wrap.innerHTML =
      '<div class="q-label">追问 ' + (idx + 1) + '：' + escapeHtml(q) + '</div>' +
      '<textarea id="clarifyA' + idx + '" placeholder="请补充细节（中英文均可），越具体对假设质量帮助越大…" style="width:100%;min-height:60px;padding:10px 14px;background:var(--panel2);color:var(--text);border:1px solid var(--border);border-radius:10px;box-sizing:border-box"></textarea>';
    box.appendChild(wrap);
  });
  const noteEl = document.getElementById("clarifyNote");
  if (noteEl) noteEl.textContent = reason ? ("说明：" + reason) : "";
  const card = document.getElementById("clarifyCard");
  if (card) card.style.display = "";
}

async function submitClarify() {
  if (!pendingRun) return;
  const clarify = [];
  document.querySelectorAll("#clarifyQuestions textarea").forEach((ta) => {
    const label = ta.previousElementSibling ? ta.previousElementSibling.textContent || "" : "";
    const q = label.replace(/^追问\s*\d+：/, "").trim();
    const answer = ta.value.trim();
    if (answer) clarify.push({question: q, answer: answer});
  });
  if (!clarify.length) { alert("请至少回答一个追问，或点「跳过追问」直接运行"); return; }
  const startBtn = document.getElementById("start");
  const statusEl = document.getElementById("status");
  if (startBtn) startBtn.disabled = true;
  if (statusEl) statusEl.textContent = "正在结合补充信息启动…";
  try {
    const r = await api("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: pendingRun.question, quality: pendingRun.quality,
                            papers: pendingRun.papers, clarify: clarify, username: currentUser})
    });
    if (r.blocked) { showBlocked(r); return; }
    if (r.need_clarify) { renderClarify(r.questions || [], r.reason || ""); return; }
    const clarifyCard = document.getElementById("clarifyCard");
    if (clarifyCard) clarifyCard.style.display = "none";
    currentRunId = r.run_id;
    pendingRun = null;
    window.location.href = 'running.html?run_id=' + encodeURIComponent(currentRunId);
  } catch (e) {
    if (statusEl) statusEl.textContent = "启动失败：" + e;
    if (startBtn) startBtn.disabled = false;
  }
}

async function skipClarify() {
  if (!pendingRun) return;
  const startBtn = document.getElementById("start");
  const statusEl = document.getElementById("status");
  if (startBtn) startBtn.disabled = true;
  if (statusEl) statusEl.textContent = "跳过追问，正在启动…";
  try {
    const r = await api("/api/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: pendingRun.question, quality: pendingRun.quality,
                            papers: pendingRun.papers, skip_clarify: true, username: currentUser})
    });
    if (r.blocked) { showBlocked(r); return; }
    const clarifyCard = document.getElementById("clarifyCard");
    if (clarifyCard) clarifyCard.style.display = "none";
    currentRunId = r.run_id;
    pendingRun = null;
    window.location.href = 'running.html?run_id=' + encodeURIComponent(currentRunId);
  } catch (e) {
    if (statusEl) statusEl.textContent = "启动失败：" + e;
    if (startBtn) startBtn.disabled = false;
  }
}

function showBlocked(r) {
  const g = r.guard || {};
  const cats = (g.categories || []).join("、");
  const el = document.getElementById("guardAlert");
  if (!el) return;
  el.innerHTML =
    "🛡️ <b>已拦截违规提问</b>：系统判定该输入属于"
    + (cats || "违规内容")
    + "类风险（风险等级：" + (g.risk || "high") + "）。<br>"
    + "说明：" + escapeHtml(g.reason || "") + "<br>"
    + '<span class="muted">本系统用于科研假设生成，不接受获取危害性内容的具体方法。如属正常科研提问，请换一种表述后重试。</span>';
  el.style.display = "";
  const startBtn = document.getElementById("start");
  if (startBtn) startBtn.disabled = false;
  const statusEl = document.getElementById("status");
  if (statusEl) statusEl.textContent = "已拦截违规提问";
}

// ==================== 用户登录系统 ====================
async function doLogin(name, remember) {
  const loginMsg = document.getElementById("loginMsg");
  if (loginMsg) loginMsg.textContent = "登录中…";
  try {
    const r = await api("/api/login", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username: name})
    });
    currentUser = r.username;
    if (remember) localStorage.setItem("ais_user", r.username);
    const overlay = document.getElementById("loginOverlay");
    if (overlay) overlay.classList.add("hidden");
    const userBar = document.getElementById("userBar");
    if (userBar) userBar.style.display = "";
    const userBadge = document.getElementById("userBadge");
    if (userBadge) userBadge.textContent = "👤 " + r.username;
    const loginLabel = document.getElementById("loginLabel");
    if (loginLabel) loginLabel.textContent = r.username;
    const myHistoryCard = document.getElementById("myHistoryCard");
    if (myHistoryCard) myHistoryCard.style.display = "";
    const myHistoryUser = document.getElementById("myHistoryUser");
    if (myHistoryUser) myHistoryUser.textContent = r.username;
    loadMyHistory();
    refreshHistory();
    loadProfile();
  } catch (e) {
    if (loginMsg) loginMsg.textContent = "登录失败：" + e;
  }
}

async function login() {
  const n = document.getElementById("loginName").value.trim();
  if (!n) { const m = document.getElementById("loginMsg"); if (m) m.textContent = "请输入用户名"; return; }
  await doLogin(n, true);
}

async function loginGuest() {
  await doLogin("guest", true);
}

function logout() {
  currentUser = null;
  localStorage.removeItem("ais_user");
  const overlay = document.getElementById("loginOverlay");
  if (overlay) {
    overlay.classList.remove("hidden");
    overlay.style.display = "flex";
  }
  const userBar = document.getElementById("userBar");
  if (userBar) userBar.style.display = "none";
  const loginLabel = document.getElementById("loginLabel");
  if (loginLabel) loginLabel.textContent = "登录";
  const myHistoryCard = document.getElementById("myHistoryCard");
  if (myHistoryCard) myHistoryCard.style.display = "none";
  const profileCard = document.getElementById("profileCard");
  if (profileCard) profileCard.style.display = "none";
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
}

function initAuth() {
  const saved = localStorage.getItem("ais_user");
  if (saved) {
    doLogin(saved, false);
  } else {
    const overlay = document.getElementById("loginOverlay");
    if (overlay) overlay.style.display = "flex";
  }
}

// ==================== 画像 ====================
function profileChips(arr, label) {
  if (!arr || !arr.length) return "";
  return '<div style="margin-top:2px"><span class="muted">' + label + "：</span>"
    + arr.map(x => '<span class="tree-gap-chip" style="color:var(--neon);border-color:rgba(var(--accent-rgb),.35);background:rgba(var(--accent-rgb),.08)">' + escapeHtml(x) + "</span>").join("")
    + "</div>";
}

function renderProfile(p, updatedAt) {
  if (!p || !p.disciplines || !p.disciplines.length) return '<div class="muted">（暂无画像数据）</div>';
  const conf = p.confidence != null ? Math.round(Number(p.confidence) * 100) : "-";
  let html = '<div style="margin-bottom:10px"><b>画像：</b>' + escapeHtml(p.summary || "")
    + '　<span class="tree-badge ok">置信度 ' + conf + "%</span>"
    + (updatedAt ? '<span class="muted" style="margin-left:8px">更新于 ' + escapeHtml(updatedAt) + "</span>" : "") + "</div>";
  html += '<div style="display:flex;flex-direction:column;gap:8px">';
  (p.disciplines || []).forEach(d => {
    const w = d.weight != null ? Math.min(100, Math.max(0, Math.round(Number(d.weight) * 100))) : 0;
    html += '<div class="profile-discipline">'
      + '<div class="discipline-header"><b>' + escapeHtml(d.discipline || "") + '</b><span class="muted">' + w + "%</span></div>"
      + '<div class="discipline-bar"><div class="fill" style="width:' + w + '%"></div></div>'
      + '<div class="muted" style="font-size:12px;margin-top:4px">'
      + profileChips(d.subfields, "子领域") + profileChips(d.topics, "主题") + profileChips(d.methods, "方法")
      + "</div></div>";
  });
  html += "</div>";
  if (p.evidence && p.evidence.length) {
    html += '<div style="margin-top:10px"><b>推断依据：</b></div><ul style="margin:4px 0 0 18px;font-size:13px">'
      + p.evidence.map(e => "<li>" + escapeHtml(e) + "</li>").join("") + "</ul>";
  }
  return html;
}

async function loadProfile(force) {
  if (!currentUser) return;
  const pc = document.getElementById("profileCard");
  try {
    const r = await api("/api/profile?user=" + encodeURIComponent(currentUser));
    const profileMeta = document.getElementById("profileMeta");
    if (profileMeta) profileMeta.textContent = "";
    if (!r.ready) {
      const profileBox = document.getElementById("profileBox");
      if (profileBox) profileBox.innerHTML = '<div class="muted">'
        + (r.reason || "样本不足") + "：累计 <b>" + (r.samples || 0) + "</b> 次有效提问，还差 <b>"
        + (r.need || 0) + "</b> 次即可生成画像。</div>";
      if (pc) pc.style.display = force ? "" : "none";
      return;
    }
    const profileBox = document.getElementById("profileBox");
    if (profileBox) profileBox.innerHTML = renderProfile(r.profile, r.updated_at);
    if (pc) pc.style.display = "";
  } catch (e) {
    const profileBox = document.getElementById("profileBox");
    if (profileBox) profileBox.textContent = "画像加载失败：" + e;
    if (pc) pc.style.display = force ? "" : "none";
  }
}

// ==================== 我的历史 ====================
async function loadMyHistory() {
  if (!currentUser) return;
  try {
    const r = await api("/api/history?user=" + encodeURIComponent(currentUser));
    const h = document.getElementById("myHistory");
    const list = r.history || [];
    if (!h) return;
    if (!list.length) { h.innerHTML = '<div class="muted">（暂无历史，跑一题就有了）</div>'; return; }
    h.innerHTML = list.map(x =>
      '<div class="hist-item">'
      + '<span class="q" title="' + escapeHtml(x.question || "") + '">' + escapeHtml((x.question || "").slice(0, 60)) + "</span>"
      + '<span class="pill ' + (x.status === "done" ? "done" : x.status === "running" ? "running" : "err") + '">' + (x.status || "") + "</span>"
      + (x.best_score != null ? '<span class="muted">假设分 ' + x.best_score + "</span>" : "")
      + '<button class="btn-secondary" onclick="location.href=\'result.html?run_id=' + encodeURIComponent(x.run_id) + '\'">详情</button>'
      + '<button class="btn-secondary" onclick="exportMyRun(' + escJs(x.run_id) + ', \'html\')">导出</button>'
      + '<button class="btn-secondary" onclick="rerunMyRun(' + escJs(x.question) + ')">重跑</button>'
      + "</div>").join("");
  } catch (e) {}
}

async function viewMyRun(runId) {
  if (!currentUser || !runId) return;
  location.href = 'result.html?run_id=' + encodeURIComponent(runId);
}

async function exportMyRun(runId, fmt) {
  if (!currentUser || !runId) return;
  try {
    const r = await fetch("/api/history/" + runId + "/export?user=" + encodeURIComponent(currentUser) + "&fmt=" + fmt);
    if (!r.ok) { let msg = "HTTP " + r.status; try { const j = await r.json(); msg = j.error || msg; } catch (e) {} throw new Error(msg); }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "结果报告_" + runId + "." + (fmt === "md" ? "md" : "html");
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) {
    alert("导出失败：" + e.message);
  }
}

function rerunMyRun(question) {
  if (!question) return;
  location.href = 'index.html?question=' + encodeURIComponent(question);
}

// ==================== 假设渲染 ====================
function parseHypothesis(text) {
  const segRe = /(?:^|\n)\s*(?:#{1,6}\s*|\*{1,2}\s*)*假设\s*[0-9一二三四五六七八九十]+\s*[（(:：]?[^\n]*/g;
  const sm = [];
  let m;
  while ((m = segRe.exec(text)) !== null) sm.push({ idx: m.index, len: m[0].length, title: m[0].trim() });
  const segs = [];
  if (!sm.length) {
    segs.push({ title: "", body: text });
  } else {
    for (let i = 0; i < sm.length; i++) {
      const start = sm[i].idx + sm[i].len;
      const end = i + 1 < sm.length ? sm[i + 1].idx : text.length;
      segs.push({ title: sm[i].title, body: text.slice(start, end) });
    }
  }
  const secRe = /(?:^|\n)\s*(?:#{1,6}\s*)?\*{0,2}\s*([①-⑩])\s*\*{0,2}\s*([^：:\n]{1,60}?)\s*(?:[:：]|\n|$)\s*\*{0,2}/g;
  return segs.map(seg => {
    let body = seg.body;
    let notes = "";
    const ni = body.indexOf("【修改说明】");
    if (ni >= 0) { notes = body.slice(ni).trim(); body = body.slice(0, ni); }
    const fields = [];
    const fm = [];
    let mm;
    while ((mm = secRe.exec(body)) !== null) fm.push({ idx: mm.index, len: mm[0].length, num: mm[1], label: mm[2] });
    if (!fm.length) return { title: seg.title, body: body.trim(), notes };
    for (let i = 0; i < fm.length; i++) {
      const start = fm[i].idx + fm[i].len;
      const end = i + 1 < fm.length ? fm[i + 1].idx : body.length;
      const b = body.slice(start, end).trim();
      if (b) fields.push({ num: fm[i].num, label: fm[i].label, body: b });
    }
    return { title: seg.title, fields, notes };
  });
}

function extractStatement(body) {
  const s = String(body || "").trim();
  if (!s) return "";
  const idx = s.indexOf("。");
  if (idx > 0) return s.slice(0, idx + 1);
  return s.length > 160 ? s.slice(0, 160) + "…" : s;
}

function renderHypothesis(text) {
  if (!text || !text.trim()) return '<div class="muted" style="color:var(--muted);padding:20px 0;text-align:center">（暂无假设输出）</div>';
  text = latexToUnicode(text);
  const segs = parseHypothesis(text);
  return segs.map((seg, idx) => {
    let html = '<div class="hyp-block" style="animation-delay:' + (idx * 0.1) + 's">';
    const title = (seg.title || "").replace(/^[#>*\s]+/, "").replace(/[*\s]+$/, "").trim();
    if (title) html += '<div class="hyp-title">' + escapeHtml(title) + '</div>';
    const fields = seg.fields && seg.fields.length ? seg.fields
      : (seg.body ? [{ num: "", label: "", body: seg.body }] : []);
    const claim = fields.find(f => f.label === "明确主张");
    const stmt = claim ? extractStatement(claim.body) : "";
    if (stmt) {
      html += '<div class="hyp-statement"><span class="hyp-statement-label">假设内容 · Hypothesis</span>'
        + escapeHtml(stmt)
        + (claim && stmt.length < claim.body.trim().length ? ' <span class="muted">（完整论证见②明确主张）</span>' : "")
        + '</div>';
    }
    fields.forEach(f => {
      html += '<div class="hyp-field">';
      const label = ((f.num ? f.num + " " : "") + f.label).trim();
      if (label) {
        const cls = FIELD_NUM_COLORS[f.num] || FIELD_COLORS[f.label] || "accent";
        html += '<div class="hyp-label ' + cls + '">' + escapeHtml(label) + '</div>';
      }
      html += '<div class="hyp-body">' + escapeHtml(f.body) + '</div></div>';
    });
    if (seg.notes) {
      html += '<details class="hyp-notes"><summary>【修改说明】</summary>'
        + '<div class="hyp-body muted">' + escapeHtml(seg.notes) + '</div></details>';
    }
    html += '</div>';
    return html;
  }).join("");
}

// ==================== 知识树 ====================
function treeCoverageBadge(sp) {
  const cov = String(sp.coverage || "").toLowerCase();
  let tag = cov === "covered" ? '<span class="tree-badge ok">✓已覆盖</span>'
    : cov === "partial" ? '<span class="tree-badge part">△部分覆盖</span>'
    : '<span class="tree-badge gap">✗缺口</span>';
  const deb = sp.open_debate ? '<span class="tree-badge deb">◇争议</span>' : "";
  return (tag + " " + deb).trim();
}

function renderKnowledgeTree(tree, gaps) {
  const card = document.getElementById("treeCard");
  const root = document.getElementById("treeRoot");
  const gapsBox = document.getElementById("treeGaps");
  if (!tree || !tree.sub_problems || !tree.sub_problems.length) { if (card) card.style.display = "none"; return; }
  let html = '<div class="tree-q">' + escapeHtml(tree.root_question || "（根问题）") + "</div>";
  if (tree.analysis) html += '<div class="tree-analysis">' + escapeHtml(tree.analysis) + "</div>";
  html += '<div class="tree-children">';
  (tree.sub_problems || []).forEach(sp => {
    const papers = sp.papers || [];
    html += '<div class="tree-node">';
    html += '<div class="tree-node-head" onclick="toggleTreeNode(this)">';
    html += '<span class="tree-caret">▶</span>';
    html += '<span class="tree-name">' + escapeHtml(sp.name || ("子问题 " + (sp.id != null ? sp.id : ""))) + "</span>";
    html += treeCoverageBadge(sp);
    html += '<span class="tree-meta">' + papers.length + " 篇文献</span>";
    html += "</div>";
    html += '<div class="tree-detail" style="display:none">';
    if (sp.concepts && sp.concepts.length) html += "<div><b>概念：</b>" + escapeHtml(sp.concepts.join("、")) + "</div>";
    if (sp.verifiable_angles && sp.verifiable_angles.length) {
      html += "<div><b>可检验角度：</b></div><ul>" + sp.verifiable_angles.map(a => "<li>" + escapeHtml(a) + "</li>").join("") + "</ul>";
    }
    if (papers.length) {
      html += "<div><b>文献：</b></div><ul>";
      papers.forEach(p => {
        const t = p["标题"] || "(无标题)";
        const link = p["链接"] || "";
        html += "<li>" + (link ? '<a href="' + escapeHtml(link) + '" target="_blank" rel="noopener">' + escapeHtml(t) + "</a>" : escapeHtml(t)) + "</li>";
      });
      html += "</ul>";
    } else {
      html += '<div class="tree-no-papers">（暂无直接文献 —— 知识缺口，作为假设生长点）</div>';
    }
    html += "</div></div>";
  });
  html += "</div>";
  if (root) root.innerHTML = html;
  if (gaps && gaps.length) {
    if (gapsBox) {
      gapsBox.style.display = "";
      gapsBox.innerHTML = "<b>知识缺口（" + gaps.length + " 个）：</b>" + gaps.map(g => '<span class="tree-gap-chip">' + escapeHtml(g) + "</span>").join("");
    }
  } else {
    if (gapsBox) gapsBox.style.display = "none";
  }
  if (card) card.style.display = "";
}

function toggleTreeNode(head) {
  const detail = head.nextElementSibling;
  const caret = head.querySelector(".tree-caret");
  if (!detail) return;
  const open = detail.style.display !== "none";
  detail.style.display = open ? "none" : "";
  if (caret) caret.textContent = open ? "▶" : "▼";
}

// ==================== Running 页面逻辑 ====================
function initRunning() {
  const params = new URLSearchParams(location.search);
  currentRunId = params.get('run_id');
  const statusEl = document.getElementById('status');
  const runMeta = document.getElementById('runMeta');

  if (!currentRunId) {
    if (statusEl) statusEl.textContent = '错误：未提供 run_id';
    return;
  }

  if (runMeta) runMeta.textContent = 'RUN ID  ' + currentRunId;
  progressMax = 0;
  finishingWait = 0;
  setThinkingStage('启动中');
  setThinkingText('正在初始化研究环境…');
  initAuth();
  pollRunning();
}

async function pollRunning() {
  if (!currentRunId) return;
  const statusEl = document.getElementById('status');

  try {
    const r = await api('/api/run/' + currentRunId);

    if (r.status === 'running' && r.started) {
      const el = Math.max(0, Math.floor(Date.now() / 1000 - r.started));
      if (statusEl) statusEl.textContent = '已运行 ' + Math.floor(el / 60) + '分' + (el % 60) + '秒';
    } else {
      if (statusEl) statusEl.textContent = r.status === 'done' ? '运行完成' : '状态：' + r.status;
    }

    renderProgress(r.progress || null);

    if (r.progress) {
      const stageText = STAGE_NAMES[r.progress.stage] || r.progress.stage || 'AI 思考中…';
      setThinkingStage(stageText);
      setThinkingText(r.progress.detail || '正在处理…');
    }

    const sHyp = document.getElementById('sHyp');
    const sData = document.getElementById('sData');
    const sRounds = document.getElementById('sRounds');
    const sStatus = document.getElementById('sStatus');
    if (sHyp) sHyp.textContent = r.best_score ?? '-';
    if (sData) sData.textContent = r.best_data_score ?? '-';
    if (sRounds) sRounds.textContent = r.rounds ?? (r.progress && r.progress.round) ?? '-';
    if (sStatus) sStatus.textContent = r.status === 'running' ? '运行中' : (r.status === 'done' ? '完成' : r.status);

    // 成本
    const costLine = document.getElementById('costLine');
    if (costLine) {
      const liveCost = r.progress ? r.progress.cost_cny : null;
      const finalCost = r.cost_cny;
      const cost = (finalCost != null) ? finalCost : liveCost;
      if (cost != null) {
        costLine.style.display = "";
        document.getElementById("costVal").textContent = (typeof cost === "number")
          ? (cost >= 0.01 ? cost.toFixed(4) : cost.toFixed(6)) : cost;
        let tok = "-";
        if (r.api_usage && r.api_usage.prompt_tokens != null) tok = (r.api_usage.prompt_tokens + r.api_usage.completion_tokens).toLocaleString();
        else if (r.progress && r.progress.tokens != null) tok = r.progress.tokens.toLocaleString();
        document.getElementById("tokVal").textContent = tok;
      } else {
        costLine.style.display = "none";
      }
    }

    // 数据分低提示
    const dataNote = document.getElementById('dataNote');
    if (dataNote) {
      if (r.best_data_score != null && Number(r.best_data_score) <= 65) {
        dataNote.style.display = "";
        dataNote.innerHTML = "⚠️ <b>数据分较低（" + r.best_data_score + " 分）</b>：多为该问题领域冷门、可直接引用的文献/数据稀少所致，不代表假设本身错误（详见导出报告中的「关于数据分较低的说明」）。";
      } else {
        dataNote.style.display = "none";
      }
    }

    if (r.status !== 'running' && r.best_score != null) {
      const pfill = document.getElementById('pfill');
      const pStage = document.getElementById('pStage');
      const pPct = document.getElementById('pPct');
      if (pfill) pfill.style.width = '100%';
      if (pStage) pStage.textContent = '完成';
      if (pPct) pPct.textContent = '100%';
      setThinkingStage('研究完成');
      setThinkingText('所有阶段已结束，正在生成最终报告…');
    }

    if (r.status === 'running') {
      pollTimer = setTimeout(pollRunning, 5000);
    } else if (r.status === 'finishing') {
      finishingWait = (finishingWait || 0) + 1;
      if (finishingWait <= 4) {
        if (statusEl) statusEl.textContent = '收尾中…';
        setThinkingStage('收尾中');
        setThinkingText('正在整理最终结果…');
        pollTimer = setTimeout(pollRunning, 5000);
      } else {
        if (statusEl) statusEl.textContent = '运行异常：进程已退出但未生成结果';
        setThinkingStage('异常');
        setThinkingText('进程异常退出，请查看日志');
      }
    } else if (r.status === 'error' || r.status === 'done_no_state') {
      if (statusEl) statusEl.textContent = '运行失败：' + (r.error_msg || '未生成结果');
      setThinkingStage('运行失败');
      setThinkingText(r.error_msg || '未生成结果，请查看日志');
    } else {
      // done - 自动跳转到结果页
      const nav = document.getElementById('navLinks');
      const toResult = document.getElementById('toResult');
      if (nav) nav.style.display = '';
      if (toResult) toResult.href = 'result.html?run_id=' + encodeURIComponent(currentRunId);
      setThinkingStage('完成');
      setThinkingText('研究假设已生成完毕');
      // 延迟2秒后自动跳转
      setTimeout(() => {
        location.href = 'result.html?run_id=' + encodeURIComponent(currentRunId);
      }, 2000);
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = '查询失败：' + e;
    setThinkingStage('连接异常');
    setThinkingText('无法连接到服务器，请检查网络');
  }
}

// ==================== Result 页面逻辑 ====================
function initResult() {
  const params = new URLSearchParams(location.search);
  currentRunId = params.get('run_id');
  const runMeta = document.getElementById('runMeta');
  const hypText = document.getElementById('hypText');

  if (!currentRunId) {
    if (hypText) hypText.innerHTML = '<div style="color:var(--muted);text-align:center;padding:40px 0">错误：未提供 run_id</div>';
    return;
  }

  if (runMeta) runMeta.textContent = 'RUN ID  ' + currentRunId;
  progressMax = 0;
  finishingWait = 0;
  initAuth();
  pollResult();
}

async function pollResult() {
  if (!currentRunId) return;
  const statusEl = document.getElementById('status');

  try {
    const r = await api('/api/run/' + currentRunId);

    if (r.status === 'running' && r.started) {
      const el = Math.max(0, Math.floor(Date.now() / 1000 - r.started));
      if (statusEl) statusEl.textContent = '运行中 · 已运行 ' + Math.floor(el / 60) + '分' + (el % 60) + '秒';
    } else {
      if (statusEl) statusEl.textContent = r.status === 'done' ? '运行完成' : '状态：' + r.status;
    }

    if (r.status === 'running') {
      renderProgress(r.progress || null);
    } else {
      const progressCard = document.getElementById('progressCard');
      if (progressCard) progressCard.style.display = 'none';
    }

    // 成本
    const costLine = document.getElementById('costLine');
    if (costLine) {
      const liveCost = r.progress ? r.progress.cost_cny : null;
      const finalCost = r.cost_cny;
      const cost = (finalCost != null) ? finalCost : liveCost;
      if (cost != null) {
        costLine.style.display = "";
        document.getElementById("costVal").textContent = (typeof cost === "number")
          ? (cost >= 0.01 ? cost.toFixed(4) : cost.toFixed(6)) : cost;
        let tok = "-";
        if (r.api_usage && r.api_usage.prompt_tokens != null) tok = (r.api_usage.prompt_tokens + r.api_usage.completion_tokens).toLocaleString();
        else if (r.progress && r.progress.tokens != null) tok = r.progress.tokens.toLocaleString();
        document.getElementById("tokVal").textContent = tok;
      } else {
        costLine.style.display = "none";
      }
    }

    // 数据分低提示
    const dataNote = document.getElementById('dataNote');
    if (dataNote) {
      if (r.best_data_score != null && Number(r.best_data_score) <= 65) {
        dataNote.style.display = "";
        dataNote.innerHTML = "⚠️ <b>数据分较低（" + r.best_data_score + " 分）</b>：多为该问题领域冷门、可直接引用的文献/数据稀少所致，不代表假设本身错误（详见导出报告中的「关于数据分较低的说明」）。";
      } else {
        dataNote.style.display = "none";
      }
    }

    // 分数
    const sHyp = document.getElementById('sHyp');
    const sData = document.getElementById('sData');
    const sRounds = document.getElementById('sRounds');
    const sStatus = document.getElementById('sStatus');
    if (sHyp) sHyp.textContent = r.best_score ?? '-';
    if (sData) sData.textContent = r.best_data_score ?? '-';
    if (sRounds) sRounds.textContent = r.rounds ?? (r.progress && r.progress.round) ?? '-';
    if (sStatus) sStatus.textContent = r.status === 'running' ? '运行中' : (r.status === 'done' ? '完成' : r.status);

    // 假设
    if (r.hypothesis) {
      const hypText = document.getElementById('hypText');
      const fbArea = document.getElementById('fbArea');
      if (hypText) hypText.innerHTML = renderHypothesis(r.hypothesis);
      if (fbArea) fbArea.style.display = '';
    }

    // 知识树
    renderKnowledgeTree(r.knowledge_tree, r.knowledge_gaps);

    // 导出按钮
    if (r.status === 'done' && r.best_score != null) {
      const exportRow = document.getElementById('exportRow');
      if (exportRow) exportRow.style.display = '';
      const nextRow = document.getElementById('nextRow');
      if (nextRow) nextRow.style.display = '';
    }

    if (r.status === 'running') {
      pollTimer = setTimeout(pollResult, 5000);
    } else if (r.status === 'finishing') {
      finishingWait = (finishingWait || 0) + 1;
      if (finishingWait <= 4) {
        pollTimer = setTimeout(pollResult, 5000);
      } else {
        if (statusEl) statusEl.textContent = '运行异常：进程已退出但未生成结果';
      }
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = '查询失败：' + e;
  }
}

function setVerdict(v, btn) {
  fbVerdict = v;
  document.querySelectorAll(".fb-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
}

async function sendFeedback() {
  if (!currentRunId) return;
  const qsEl = document.getElementById('fbQs');
  const qs = qsEl ? qsEl.value.split("\n").map(s => s.trim()).filter(Boolean) : [];
  const body = { verdict: fbVerdict, questions: qs, suggestions: [] };
  try {
    const r = await api('/api/run/' + currentRunId + '/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    alert('反馈已保存：' + r.saved);
  } catch (e) {
    alert('反馈保存失败：' + e);
  }
}

async function exportReport(fmt) {
  if (!currentRunId) return;
  const btn = document.getElementById('exportBtn');
  const old = btn ? btn.textContent : '导出';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '生成中…';
  }
  try {
    const r = await fetch('/api/run/' + currentRunId + '/export?fmt=' + fmt);
    if (!r.ok) {
      let msg = 'HTTP ' + r.status;
      try { msg = (await r.json()).error || msg; } catch (e) {}
      throw new Error(msg);
    }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '结果报告_' + currentRunId + '.' + (fmt === 'md' ? 'md' : 'html');
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) {
    alert('导出失败：' + e.message);
  } finally {
    if (btn) {
      btn.textContent = old;
      btn.disabled = false;
    }
  }
}
