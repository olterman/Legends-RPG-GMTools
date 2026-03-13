const MODULE_ID = "legends-gmtools-bridge";

function getSetting(key) {
  return game.settings.get(MODULE_ID, key);
}

function normalizeBaseUrl(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  return value.replace(/\/+$/, "");
}

function effectiveFoundryAssetBaseUrl() {
  const override = normalizeBaseUrl(getSetting("assetBaseUrlOverride"));
  if (override) return override;
  return String(window.location?.origin || "").trim().replace(/\/+$/, "");
}

function absolutizeFoundryAssetPath(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  if (/^(https?:)?\/\//i.test(value) || value.startsWith("data:")) return value;
  const origin = effectiveFoundryAssetBaseUrl();
  if (!origin) return value;
  if (value.startsWith("/")) return `${origin}${value}`;
  if (/^(modules|systems|icons|assets)\//i.test(value)) return `${origin}/${value}`;
  return value;
}

function prepareActorForExport(actor) {
  const actorData = actor?.toObject ? actor.toObject() : actor;
  if (!actorData || typeof actorData !== "object") return actorData;
  const clone = foundry.utils.deepClone(actorData);
  clone.img = absolutizeFoundryAssetPath(clone.img);
  if (Array.isArray(clone.items)) {
    clone.items = clone.items.map((item) => {
      if (!item || typeof item !== "object") return item;
      const itemClone = foundry.utils.deepClone(item);
      itemClone.img = absolutizeFoundryAssetPath(itemClone.img);
      return itemClone;
    });
  }
  return clone;
}

function prepareItemForExport(item) {
  const itemData = item?.toObject ? item.toObject() : item;
  if (!itemData || typeof itemData !== "object") return itemData;
  const clone = foundry.utils.deepClone(itemData);
  clone.img = absolutizeFoundryAssetPath(clone.img);
  return clone;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data && data.error ? data.error : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return data;
}

function buildAuthHeaders() {
  const token = String(getSetting("apiToken") || "").trim();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function handshake() {
  const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
  if (!baseUrl) throw new Error("GMTools base URL is empty");

  const payload = {
    module_id: MODULE_ID,
    module_version: game.modules.get(MODULE_ID)?.version || "",
    foundry_version: game.version || game.release?.version || "",
    system_id: game.system?.id || "",
    system_version: game.system?.version || "",
    world_id: game.world?.id || "",
    user_id: game.user?.id || "",
  };

  return requestJson(`${baseUrl}/plugins/foundryvtt/handshake`, {
    method: "POST",
    headers: buildAuthHeaders(),
    body: JSON.stringify(payload),
  });
}

async function health() {
  const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
  if (!baseUrl) throw new Error("GMTools base URL is empty");
  return requestJson(`${baseUrl}/plugins/foundryvtt/health`);
}

function buildFoundryImportPayload() {
  const syncSetting = String(getSetting("syncSettingTag") || "").trim();
  const legacySetting = String(getSetting("defaultSettingTag") || "").trim();
  return {
    setting: syncSetting || legacySetting,
    area: String(getSetting("defaultAreaTag") || "").trim(),
    location: String(getSetting("defaultLocationTag") || "").trim(),
    foundry_origin: effectiveFoundryAssetBaseUrl(),
  };
}

async function sendActorToGmtools(actor) {
  const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
  if (!baseUrl) throw new Error("GMTools base URL is empty");
  if (!actor) throw new Error("No actor provided");

  const body = {
    actor: prepareActorForExport(actor),
    payload: buildFoundryImportPayload(),
  };

  return requestJson(`${baseUrl}/plugins/foundryvtt/import/actor`, {
    method: "POST",
    headers: buildAuthHeaders(),
    body: JSON.stringify(body),
  });
}

async function sendItemToGmtools(item) {
  const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
  if (!baseUrl) throw new Error("GMTools base URL is empty");
  if (!item) throw new Error("No item provided");

  const body = {
    item: prepareItemForExport(item),
    payload: buildFoundryImportPayload(),
  };

  return requestJson(`${baseUrl}/plugins/foundryvtt/import/item`, {
    method: "POST",
    headers: buildAuthHeaders(),
    body: JSON.stringify(body),
  });
}

function syncableActors() {
  return Array.from(game.actors?.contents || []).filter((actor) => {
    const actorType = String(actor?.type || "").trim().toLowerCase();
    return actorType === "pc" || actorType === "npc";
  });
}

async function bulkSyncActorsToGmtools({ includePcs = true, includeNpcs = true } = {}) {
  const actors = syncableActors().filter((actor) => {
    const actorType = String(actor?.type || "").trim().toLowerCase();
    if (actorType === "pc") return includePcs;
    if (actorType === "npc") return includeNpcs;
    return false;
  });

  if (!actors.length) {
    ui.notifications.warn("GMTools bulk sync found no matching actors.");
    return { total: 0, synced: 0, failed: 0, failures: [] };
  }

  ui.notifications.info(`GMTools bulk sync started for ${actors.length} actor${actors.length === 1 ? "" : "s"}.`);

  const failures = [];
  let synced = 0;

  for (const actor of actors) {
    try {
      const result = await sendActorToGmtools(actor);
      synced += 1;
      if (getSetting("debugLog")) console.log(`[${MODULE_ID}] bulk actor sync`, actor.name, result);
    } catch (err) {
      const message = String(err?.message || err || "unknown error");
      failures.push({ name: actor.name || "Unnamed Actor", message });
      if (getSetting("debugLog")) console.error(`[${MODULE_ID}] bulk actor sync error`, actor.name, err);
    }
  }

  const failed = failures.length;
  if (failed) {
    ui.notifications.warn(`GMTools bulk sync finished: ${synced} synced, ${failed} failed.`);
    console.warn(`[${MODULE_ID}] bulk sync failures`, failures);
  } else {
    ui.notifications.info(`GMTools bulk sync complete: ${synced} synced.`);
  }

  return {
    total: actors.length,
    synced,
    failed,
    failures,
  };
}

function openBulkSyncDialog() {
  const actors = syncableActors();
  const pcCount = actors.filter((actor) => String(actor?.type || "").trim().toLowerCase() === "pc").length;
  const npcCount = actors.length - pcCount;
  const settingTag = String(getSetting("syncSettingTag") || getSetting("defaultSettingTag") || "").trim() || "unsorted";

  new Dialog({
    title: "GMTools Bulk Sync",
    content: `
      <p>Sync your world actors into GMTools using the current Foundry settings bucket.</p>
      <p><strong>Sync Setting:</strong> ${foundry.utils.escapeHTML(settingTag)}</p>
      <p><strong>PCs:</strong> ${pcCount} · <strong>NPC/Creature actors:</strong> ${npcCount}</p>
      <p class="notes">Creatures imported through Foundry's actor system will be classified on the GMTools side during import.</p>
    `,
    buttons: {
      all: {
        label: "Sync All",
        icon: '<i class="fas fa-cloud-upload-alt"></i>',
        callback: () => bulkSyncActorsToGmtools({ includePcs: true, includeNpcs: true }),
      },
      pcs: {
        label: "Sync PCs",
        icon: '<i class="fas fa-user"></i>',
        callback: () => bulkSyncActorsToGmtools({ includePcs: true, includeNpcs: false }),
      },
      npcs: {
        label: "Sync NPCs/Creatures",
        icon: '<i class="fas fa-dragon"></i>',
        callback: () => bulkSyncActorsToGmtools({ includePcs: false, includeNpcs: true }),
      },
      cancel: {
        label: "Cancel",
      },
    },
    default: "all",
  }).render(true);
}

Hooks.once("init", () => {
  game.settings.register(MODULE_ID, "appBaseUrl", {
    name: "GMTools Base URL",
    hint: "Base URL for your Legends RPG GMTools app, e.g. http://127.0.0.1:5000",
    scope: "world",
    config: true,
    type: String,
    default: "http://127.0.0.1:5000",
  });

  game.settings.register(MODULE_ID, "apiToken", {
    name: "GMTools API Token",
    hint: "Optional token. Must match LOL_FOUNDRYVTT_API_TOKEN on the GMTools server.",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "assetBaseUrlOverride", {
    name: "Foundry Asset Base URL Override",
    hint: "Optional public base URL for image/assets sent to GMTools, e.g. https://foundry.olterman.eu . Use this when Foundry is accessed via localhost but GMTools must fetch images from a reachable host.",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "autoHandshake", {
    name: "Auto Handshake on Ready",
    hint: "If enabled, module will run handshake when Foundry is ready.",
    scope: "client",
    config: true,
    type: Boolean,
    default: false,
  });

  game.settings.register(MODULE_ID, "debugLog", {
    name: "Debug Logging",
    hint: "Enable extra logs in browser console.",
    scope: "client",
    config: true,
    type: Boolean,
    default: false,
  });

  game.settings.register(MODULE_ID, "lastHandshake", {
    name: "Last Handshake Result",
    scope: "client",
    config: false,
    type: Object,
    default: {},
  });

  game.keybindings.register(MODULE_ID, "runHandshake", {
    name: "Run GMTools Handshake",
    hint: "Run handshake with Legends RPG GMTools now.",
    editable: [{ key: "KeyH", modifiers: ["Control", "Shift"] }],
    onDown: () => {
      runHandshakeUi();
      return true;
    },
    restricted: true,
    precedence: CONST.KEYBINDING_PRECEDENCE.NORMAL,
  });

  game.settings.register(MODULE_ID, "syncSettingTag", {
    name: "Sync Setting Tag",
    hint: "Primary setting tag used for GMTools sync storage bucketing (e.g. lands_of_legends).",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "defaultSettingTag", {
    name: "Legacy Default Setting Tag",
    hint: "Backward-compat fallback if Sync Setting Tag is empty.",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "defaultAreaTag", {
    name: "Default Area Tag",
    hint: "Optional area tag passed to GMTools during actor import.",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "defaultLocationTag", {
    name: "Default Location Tag",
    hint: "Optional location tag passed to GMTools during actor import.",
    scope: "world",
    config: true,
    type: String,
    default: "",
  });

  game.legendsGmtoolsBridge = {
    handshake,
    health,
    runHandshakeUi,
    sendActorToGmtools,
    sendItemToGmtools,
    bulkSyncActorsToGmtools,
    openBulkSyncDialog,
  };
});

async function runHandshakeUi() {
  try {
    const data = await handshake();
    await game.settings.set(MODULE_ID, "lastHandshake", data);
    ui.notifications.info(`GMTools handshake ok (api ${data.api_version || "unknown"})`);
    if (getSetting("debugLog")) console.log(`[${MODULE_ID}] handshake`, data);
  } catch (err) {
    ui.notifications.error(`GMTools handshake failed: ${err.message || err}`);
    if (getSetting("debugLog")) console.error(`[${MODULE_ID}] handshake error`, err);
  }
}

Hooks.once("ready", async () => {
  if (!getSetting("autoHandshake")) return;
  await runHandshakeUi();
});

Hooks.on("getActorSheetHeaderButtons", (sheet, buttons) => {
  if (!game.user?.isGM) return;
  const actor = sheet?.actor;
  if (!actor) return;

  buttons.unshift({
    label: "GMTools",
    class: "legends-gmtools-send",
    icon: "fas fa-cloud-upload-alt",
    onclick: async () => {
      try {
        const result = await sendActorToGmtools(actor);
        const name = String(result?.name || actor.name || "actor");
        const file = String(result?.storage?.filename || "");
        const msg = file
          ? `Sent ${name} to GMTools (${file})`
          : `Sent ${name} to GMTools`;
        ui.notifications.info(msg);
        if (getSetting("debugLog")) console.log(`[${MODULE_ID}] actor import`, result);
      } catch (err) {
        ui.notifications.error(`GMTools actor import failed: ${err.message || err}`);
        if (getSetting("debugLog")) console.error(`[${MODULE_ID}] actor import error`, err);
      }
    },
  });
});

Hooks.on("getItemSheetHeaderButtons", (sheet, buttons) => {
  if (!game.user?.isGM) return;
  const item = sheet?.item;
  if (!item) return;

  buttons.unshift({
    label: "GMTools",
    class: "legends-gmtools-send-item",
    icon: "fas fa-cloud-upload-alt",
    onclick: async () => {
      try {
        const result = await sendItemToGmtools(item);
        const name = String(result?.name || item.name || "item");
        const file = String(result?.storage?.filename || "");
        const msg = file
          ? `Sent ${name} to GMTools (${file})`
          : `Sent ${name} to GMTools`;
        ui.notifications.info(msg);
        if (getSetting("debugLog")) console.log(`[${MODULE_ID}] item import`, result);
      } catch (err) {
        ui.notifications.error(`GMTools item import failed: ${err.message || err}`);
        if (getSetting("debugLog")) console.error(`[${MODULE_ID}] item import error`, err);
      }
    },
  });
});

Hooks.on("renderActorDirectory", (_app, html) => {
  if (!game.user?.isGM) return;
  const root = html?.[0] || html;
  if (!root || root.querySelector?.(".legends-gmtools-bulk-sync")) return;

  const header = root.querySelector(".directory-header");
  if (!header) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "legends-gmtools-bulk-sync";
  button.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> GMTools Sync';
  button.style.marginTop = "6px";
  button.style.width = "100%";
  button.addEventListener("click", () => openBulkSyncDialog());

  header.appendChild(button);
});
