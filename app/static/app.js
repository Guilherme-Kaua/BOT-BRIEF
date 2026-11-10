let currentScan = null;
let currentFilter = "all";

const FOLCOLOR_HEX = {
  4: "#a855f7",
  6: "#f97316",
  9: "#3b82f6",
  8: "#10b981",
  15: "#64748b",
  2: "#eab308",
  13: "#38bdf8",
};

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(i > 1 ? 2 : 0)} ${units[i]}`;
}

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 4500);
}

async function fetchScan() {
  const res = await fetch("/api/scan");
  currentScan = await res.json();
  renderHeader();
  renderHealthCards();
  renderQueue();
  await fetchRules();
  await fetchHistory();
}

function renderHeader() {
  const s = currentScan.summary;
  const cFreeGb = formatBytes(s.c_free_bytes);
  const recGb = formatBytes(s.recoverable_bytes);
  document.getElementById("vida-root-label").textContent = currentScan.vida_root || "F:\\Vida";
  document.getElementById("disk-summary").innerHTML =
    `Disco C: <strong>${cFreeGb} livres</strong> · ` +
    `<strong>${s.total_disorganized}</strong> itens na fila · ` +
    `<strong>${recGb}</strong> recuperáveis em Downloads`;

  const watchBtn = document.getElementById("btn-toggle-watch");
  const watchDot = document.getElementById("watch-dot");
  if (currentScan.auto_watch_enabled) {
    watchBtn.textContent = "Vigia Ativo";
    watchBtn.classList.remove("paused");
    watchDot.classList.add("active");
  } else {
    watchBtn.textContent = "Vigia Pausado";
    watchBtn.classList.add("paused");
    watchDot.classList.remove("active");
  }

  const undoBtn = document.getElementById("btn-undo");
  if (currentScan.last_undoable_batch) {
    undoBtn.disabled = false;
    undoBtn.textContent = `↩ Desfazer: ${currentScan.last_undoable_batch.description}`;
  } else {
    undoBtn.disabled = true;
    undoBtn.textContent = "↩ Desfazer última ação";
  }

  const q = currentScan.queue || [];
  document.getElementById("count-all").textContent = q.length;
  document.getElementById("count-move").textContent = q.filter(i => i.category === "pronto_para_mover").length;
  document.getElementById("count-rec").textContent = q.filter(i => i.category === "espaco_recuperavel").length;
  document.getElementById("count-ren").textContent = q.filter(i => i.category === "renomear_sugerido").length;
  document.getElementById("count-ico").textContent = q.filter(i => i.category === "icone_pendente").length;
}

function renderHealthCards() {
  const grid = document.getElementById("health-grid");
  grid.innerHTML = "";
  for (const card of currentScan.folder_cards || []) {
    const div = document.createElement("div");
    div.className = `health-card ${card.status_level}`;
    div.title = "Clique para abrir esta pasta no Windows Explorer";
    div.innerHTML = `
      <div class="hc-top">
        <span>${card.name}</span>
        <span class="hc-badge">${card.badge}</span>
      </div>
      <div class="hc-headline">${card.headline}</div>
      <div class="hc-detail">${card.detail}</div>
    `;
    div.addEventListener("click", () => openInExplorer(card.path));
    grid.appendChild(div);
  }
}

function renderQueue() {
  const list = document.getElementById("queue-list");
  list.innerHTML = "";
  const allItems = currentScan.queue || [];
  const items = currentFilter === "all"
    ? allItems
    : allItems.filter(i => i.category === currentFilter);

  const recBar = document.getElementById("recoverable-bar");
  const hasRec = items.some(i => i.category === "espaco_recuperavel");
  if (hasRec && (currentFilter === "espaco_recuperavel" || currentFilter === "all")) {
    recBar.classList.remove("hidden");
  } else {
    recBar.classList.add("hidden");
  }

  if (items.length === 0) {
    list.innerHTML = `<div style="padding:28px;text-align:center;color:#94a3b8;">✨ Tudo limpo e organizado nesta categoria!</div>`;
    return;
  }

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "queue-item";
    const fileName = item.source_path.split(/[\\/]/).pop();
    const sizeLabel = item.size_bytes > 0 ? ` · ${formatBytes(item.size_bytes)}` : "";

    let actionButtons = "";
    if (item.category === "espaco_recuperavel") {
      actionButtons = `
        <button class="btn btn-small btn-amber" onclick="executeItem('${item.id}', true, 'archive')">📦 Arquivar</button>
        <button class="btn btn-small btn-danger" onclick="executeItem('${item.id}', true, 'trash')">🗑️ Lixeira</button>
      `;
    } else if (item.category === "icone_pendente") {
      actionButtons = `
        <button class="btn btn-small btn-purple" onclick="executeItem('${item.id}', false, 'archive')">🎨 Aplicar Cor</button>
      `;
    } else {
      actionButtons = `
        <button class="btn btn-small btn-primary" onclick="executeItem('${item.id}', false, 'archive')">⚡ Organizar</button>
      `;
    }

    row.innerHTML = `
      <div class="qi-info">
        <div class="qi-title" title="${item.source_path}">${fileName}${sizeLabel}</div>
        <div class="qi-sub">${item.reason} · <code>${item.source_path}</code></div>
      </div>
      <div class="qi-actions">
        <button class="btn btn-small btn-ghost btn-open-explorer" title="Ver no Explorer">📂</button>
        ${actionButtons}
      </div>
    `;
    row.querySelector(".btn-open-explorer").addEventListener("click", () => openInExplorer(item.source_path));
    list.appendChild(row);
  }
}

async function executeItem(itemId, includeTrash, recoverableMode) {
  const res = await fetch("/api/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      item_ids: [itemId],
      include_trash: includeTrash,
      recoverable_mode: recoverableMode,
    }),
  });
  const data = await res.json();
  showToast(`Executado: ${data.executed_count} item(ns) organizado(s).`);
  await fetchScan();
}

async function executeCategories(categories, includeTrash = false, recoverableMode = "archive") {
  const res = await fetch("/api/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      categories,
      include_trash: includeTrash,
      recoverable_mode: recoverableMode,
    }),
  });
  const data = await res.json();
  showToast(`Organização concluída: ${data.executed_count} item(ns) processado(s)!`);
  await fetchScan();
}

async function openInExplorer(pathStr) {
  await fetch("/api/open-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: pathStr }),
  });
}

async function fetchRules() {
  const res = await fetch("/api/rules");
  const rules = await res.json();
  const container = document.getElementById("rules-list");
  container.innerHTML = "";

  for (const r of rules) {
    const color = FOLCOLOR_HEX[r.folcolor_index] || "#3b82f6";
    const kwText = (r.keywords && r.keywords.length > 0)
      ? `nome contém <code>${r.keywords.slice(0, 6).join(", ")}${r.keywords.length > 6 ? "…" : ""}</code>`
      : "qualquer nome";
    const extText = (r.extensions && r.extensions.length > 0)
      ? `extensão <code>.${r.extensions.join(", .")}</code>`
      : "qualquer extensão";

    const card = document.createElement("div");
    card.className = "rule-card";
    card.style.borderLeftColor = color;
    card.innerHTML = `
      <div class="rule-top">
        <strong style="color:${color}">📁 ${r.name} (Folcolor #${r.folcolor_index})</strong>
        <div style="display:flex;gap:6px;align-items:center;">
          <span style="font-size:11px;color:${r.enabled ? '#4ade80' : '#94a3b8'}">${r.enabled ? "● Ativa" : "○ Inativa"}</span>
          <button class="btn btn-small btn-ghost" onclick="deleteRule(${r.id})" title="Remover regra">🗑</button>
        </div>
      </div>
      <div class="rule-body">
        <strong>SE</strong> ${kwText} (${extText})<br/>
        <strong>ENTÃO</strong> mover p/ <code>F:\\Vida\\${r.target_subpath.replace(/\//g, "\\")}</code>
      </div>
    `;
    container.appendChild(card);
  }
}

async function deleteRule(id) {
  await fetch(`/api/rules/${id}`, { method: "DELETE" });
  showToast("Regra removida.");
  await fetchScan();
}

async function fetchHistory() {
  const res = await fetch("/api/history");
  const batches = await res.json();
  const container = document.getElementById("history-list");
  container.innerHTML = "";

  if (!batches.length) {
    container.innerHTML = `<div style="color:#94a3b8;font-size:12px;">Nenhuma ação executada ainda.</div>`;
    return;
  }

  for (const b of batches.slice(0, 8)) {
    const div = document.createElement("div");
    div.className = "history-item";
    const statusHtml = b.undone
      ? `<span style="color:#94a3b8;font-size:11px;">Desfeita</span>`
      : `<button class="btn btn-small btn-secondary" onclick="undoSpecificBatch(${b.id})">↩ Desfazer</button>`;
    div.innerHTML = `
      <div>
        <strong>#${b.id} · ${b.description}</strong>
        <div style="color:#94a3b8;font-size:11px;">${new Date(b.created_at).toLocaleString("pt-BR")}</div>
      </div>
      ${statusHtml}
    `;
    container.appendChild(div);
  }
}

async function undoSpecificBatch(batchId) {
  const res = await fetch("/api/undo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_id: batchId }),
  });
  const data = await res.json();
  showToast(`Desfeito: ${data.undone_count} item(ns) restaurado(s) ao local original.`);
  await fetchScan();
}

// Event Listeners
document.getElementById("btn-refresh").addEventListener("click", fetchScan);

document.getElementById("btn-organize-all").addEventListener("click", () => {
  executeCategories(["pronto_para_mover", "renomear_sugerido", "icone_pendente"], false);
});

document.getElementById("btn-icons").addEventListener("click", () => {
  executeCategories(["icone_pendente"], false);
});

document.getElementById("btn-undo").addEventListener("click", () => {
  undoSpecificBatch(null);
});

document.getElementById("btn-archive-all-rec").addEventListener("click", () => {
  executeCategories(["espaco_recuperavel"], true, "archive");
});

document.getElementById("btn-trash-all-rec").addEventListener("click", () => {
  executeCategories(["espaco_recuperavel"], true, "trash");
});

document.getElementById("btn-toggle-watch").addEventListener("click", async () => {
  await fetch("/api/toggle-watch", { method: "POST" });
  await fetchScan();
});

document.querySelectorAll("#queue-tabs .tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#queue-tabs .tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    renderQueue();
  });
});

// Modal logic
const modal = document.getElementById("rule-modal");
document.getElementById("btn-new-rule").addEventListener("click", () => {
  document.getElementById("rule-form").reset();
  modal.classList.remove("hidden");
});
document.getElementById("btn-close-modal").addEventListener("click", () => modal.classList.add("hidden"));
document.getElementById("btn-cancel-modal").addEventListener("click", () => modal.classList.add("hidden"));

document.getElementById("rule-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const catSelect = document.getElementById("rule-category");
  const selectedOpt = catSelect.options[catSelect.selectedIndex];
  const folcolorIndex = parseInt(selectedOpt.dataset.icon || "13", 10);

  const kwRaw = document.getElementById("rule-keywords").value;
  const extRaw = document.getElementById("rule-extensions").value;

  const payload = {
    name: document.getElementById("rule-name").value.trim(),
    priority: parseInt(document.getElementById("rule-priority").value || "50", 10),
    category_folder: catSelect.value,
    target_subpath: document.getElementById("rule-subpath").value.trim().replace(/\\/g, "/"),
    folcolor_index: folcolorIndex,
    keywords: kwRaw ? kwRaw.split(",").map(s => s.trim()).filter(Boolean) : [],
    extensions: extRaw ? extRaw.split(",").map(s => s.trim().replace(/^\./, "")).filter(Boolean) : [],
    source_scopes: ["*"],
    min_age_days: parseInt(document.getElementById("rule-min-age").value || "0", 10),
    enabled: 1,
  };

  await fetch("/api/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  modal.classList.add("hidden");
  showToast("Nova regra visual salva!");
  await fetchScan();
});

fetchScan();

