const MODULE_ID = "legends-gmtools-bridge";

function getSetting(key) {
  return game.settings.get(MODULE_ID, key);
}

function normalizeBaseUrl(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  return value.replace(/\/+$/, "");
}

function slugifySetting(raw) {
  const text = String(raw || "").trim().toLowerCase();
  if (!text) return "";
  return text.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
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
  const selectedSetting = String(
    getSetting("gmtoolsSettingId")
    || getSetting("syncSettingTag")
    || getSetting("defaultSettingTag")
    || ""
  ).trim();
  const fallbackWorld = slugifySetting(game.world?.id || game.world?.title || "");
  const syncSetting = String(getSetting("syncSettingTag") || "").trim();
  const legacySetting = String(getSetting("defaultSettingTag") || "").trim();
  return {
    setting: slugifySetting(selectedSetting || syncSetting || legacySetting) || fallbackWorld,
    area: String(getSetting("defaultAreaTag") || "").trim(),
    location: String(getSetting("defaultLocationTag") || "").trim(),
    foundry_origin: effectiveFoundryAssetBaseUrl(),
  };
}

async function fetchGmtoolsSettingOptions() {
  const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
  if (!baseUrl) {
    throw new Error("GMTools base URL is empty");
  }
  const data = await requestJson(`${baseUrl}/settings`, {
    method: "GET",
    headers: buildAuthHeaders(),
  });
  const rows = Array.isArray(data?.settings) ? data.settings : (Array.isArray(data?.worlds) ? data.worlds : []);
  const options = rows
    .map((row) => {
      if (!row || typeof row !== "object") return null;
      const id = slugifySetting(row.id || row.value || row.slug || "");
      if (!id) return null;
      const label = String(row.label || row.name || row.title || row.id || id).trim();
      return { id, label: label || id };
    })
    .filter(Boolean);
  const unique = [];
  const seen = new Set();
  for (const row of options) {
    if (seen.has(row.id)) continue;
    seen.add(row.id);
    unique.push(row);
  }
  return unique;
}

class GmtoolsSyncTargetForm extends FormApplication {
  static get defaultOptions() {
    return foundry.utils.mergeObject(super.defaultOptions, {
      id: `${MODULE_ID}-sync-target-form`,
      title: "GMTools Sync Target",
      template: `modules/${MODULE_ID}/templates/gmtools-sync-target.hbs`,
      width: 520,
      height: "auto",
      closeOnSubmit: false,
      submitOnChange: false,
      submitOnClose: false,
      resizable: true,
    });
  }

  async getData() {
    const selected = String(getSetting("gmtoolsSettingId") || getSetting("syncSettingTag") || getSetting("defaultSettingTag") || "").trim();
    const fallbackWorld = slugifySetting(game.world?.id || game.world?.title || "") || "unsorted";
    const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
    let options = [];
    let error = "";
    try {
      options = await fetchGmtoolsSettingOptions();
    } catch (err) {
      error = String(err?.message || err || "Failed to load settings from GMTools.");
    }
    options = options.map((row) => ({
      ...row,
      selected: String(selected || "") === String(row.id || ""),
    }));
    return {
      baseUrl,
      selected,
      fallbackWorld,
      effectiveSelected: slugifySetting(selected) || fallbackWorld,
      options,
      error,
    };
  }

  activateListeners(html) {
    super.activateListeners(html);
    const refreshBtn = html[0]?.querySelector?.('[data-action="refresh-settings"]');
    if (refreshBtn) {
      refreshBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        await this.render(true);
      });
    }
  }

  async _updateObject(_event, formData) {
    const chosen = slugifySetting(formData?.gmtools_setting_id || "");
    const manual = slugifySetting(formData?.manual_setting_id || "");
    const finalValue = chosen || manual;
    await game.settings.set(MODULE_ID, "gmtoolsSettingId", finalValue);
    await game.settings.set(MODULE_ID, "syncSettingTag", finalValue);
    await game.settings.set(MODULE_ID, "defaultSettingTag", finalValue);
    const label = finalValue || "(empty)";
    ui.notifications.info(`GMTools sync target set to: ${label}`);
    if (getSetting("debugLog")) console.log(`[${MODULE_ID}] sync target set`, { finalValue });
    await this.render(true);
  }
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

async function fetchSyncBatchFromGmtools({
  includeNpcs = true,
  includeCreatures = true,
  includeCyphers = true,
  includeArtifacts = true,
} = {}) {
  const baseUrl = normalizeBaseUrl(getSetting("appBaseUrl"));
  if (!baseUrl) throw new Error("GMTools base URL is empty");
  const setting = String(buildFoundryImportPayload()?.setting || "").trim();
  const types = [];
  if (includeNpcs) types.push("npc");
  if (includeCreatures) types.push("creature");
  if (includeCyphers) types.push("cypher");
  if (includeArtifacts) types.push("artifact");
  if (!types.length) {
    return { count: 0, entries: [], setting, types: [] };
  }
  return requestJson(`${baseUrl}/plugins/foundryvtt/export/sync`, {
    method: "POST",
    headers: buildAuthHeaders(),
    body: JSON.stringify({ setting, types }),
  });
}

function parseTimestampMs(raw) {
  const text = String(raw || "").trim();
  if (!text) return 0;
  const ms = Date.parse(text);
  if (Number.isNaN(ms)) return 0;
  return ms;
}

function findExistingSyncedDocument(docType, filename) {
  const key = String(filename || "").trim();
  if (!key) return null;
  const collection = docType === "Actor" ? game.actors : game.items;
  if (!collection) return null;
  return Array.from(collection.contents || []).find((doc) => {
    const synced = doc?.getFlag?.(MODULE_ID, "gmtools");
    return String(synced?.filename || "").trim() === key;
  }) || null;
}

async function ensureFolderTree(docType, setting, leafFolder) {
  const folderType = docType === "Actor" ? "Actor" : "Item";
  const allFolders = Array.from(game.folders?.contents || []).filter((f) => String(f.type || "") === folderType);
  const findFolder = (name, parent) => {
    const parentId = parent?.id || null;
    return allFolders.find((folder) => String(folder.name || "") === name && String(folder.parent?.id || "") === String(parentId || ""));
  };
  const makeFolder = async (name, parent) => {
    const created = await Folder.create({
      name,
      type: folderType,
      parent: parent?.id || null,
    });
    allFolders.push(created);
    return created;
  };

  const rootName = "GMTools Sync";
  const settingName = String(setting || "unsorted").trim() || "unsorted";
  const leafName = String(leafFolder || "Imported").trim() || "Imported";

  const root = findFolder(rootName, null) || await makeFolder(rootName, null);
  const settingFolder = findFolder(settingName, root) || await makeFolder(settingName, root);
  const leaf = findFolder(leafName, settingFolder) || await makeFolder(leafName, settingFolder);
  return leaf;
}

async function upsertGmtoolsEntryInFoundry(entry) {
  const filename = String(entry?.filename || "").trim();
  const docType = String(entry?.foundry_doc_type || "").trim();
  const leafFolder = String(entry?.foundry_folder || "").trim();
  const setting = String(entry?.setting || buildFoundryImportPayload()?.setting || "unsorted").trim();
  const sourceSavedAt = String(entry?.saved_at || "").trim();
  const sourceSavedAtMs = parseTimestampMs(sourceSavedAt);
  const payload = foundry.utils.deepClone(entry?.foundry_data || {});

  if (!filename || !docType || !payload || typeof payload !== "object") {
    return { status: "skipped", reason: "invalid-entry", filename };
  }

  const targetFolder = await ensureFolderTree(docType, setting, leafFolder);
  payload.folder = targetFolder?.id || null;
  payload.flags = payload.flags || {};
  payload.flags[MODULE_ID] = payload.flags[MODULE_ID] || {};
  payload.flags[MODULE_ID].gmtools = {
    filename,
    saved_at: sourceSavedAt,
    saved_at_ms: sourceSavedAtMs,
    setting,
    type: String(entry?.type || "").trim().toLowerCase(),
    synced_at: new Date().toISOString(),
    source: "gmtools",
  };

  const existing = findExistingSyncedDocument(docType, filename);
  if (existing) {
    const existingInfo = existing.getFlag(MODULE_ID, "gmtools") || {};
    const existingMs = parseTimestampMs(existingInfo.saved_at) || Number(existingInfo.saved_at_ms || 0);
    if (existingMs && sourceSavedAtMs && existingMs > sourceSavedAtMs) {
      return { status: "skipped", reason: "existing-newer", filename };
    }
    await existing.update(payload);
    return { status: "updated", filename, id: existing.id };
  }

  if (docType === "Actor") {
    const created = await Actor.create(payload);
    return { status: "created", filename, id: created?.id || "" };
  }
  const created = await Item.create(payload);
  return { status: "created", filename, id: created?.id || "" };
}

async function pullSyncAllFromGmtools({
  includeNpcs = true,
  includeCreatures = true,
  includeCyphers = true,
  includeArtifacts = true,
} = {}) {
  const batch = await fetchSyncBatchFromGmtools({
    includeNpcs,
    includeCreatures,
    includeCyphers,
    includeArtifacts,
  });
  const entries = Array.isArray(batch?.entries) ? batch.entries : [];
  if (!entries.length) {
    ui.notifications.warn("GMTools pull sync found no matching records.");
    return { total: 0, created: 0, updated: 0, skipped: 0, failed: 0, failures: [] };
  }

  ui.notifications.info(`GMTools pull sync started for ${entries.length} record${entries.length === 1 ? "" : "s"}.`);
  let created = 0;
  let updated = 0;
  let skipped = 0;
  let failed = 0;
  const failures = [];
  for (const entry of entries) {
    try {
      const outcome = await upsertGmtoolsEntryInFoundry(entry);
      if (outcome.status === "created") created += 1;
      else if (outcome.status === "updated") updated += 1;
      else skipped += 1;
    } catch (err) {
      failed += 1;
      failures.push({
        filename: String(entry?.filename || ""),
        name: String(entry?.name || ""),
        message: String(err?.message || err || "unknown error"),
      });
      if (getSetting("debugLog")) console.error(`[${MODULE_ID}] pull sync error`, entry, err);
    }
  }

  if (failed) {
    ui.notifications.warn(`GMTools pull sync finished: ${created} created, ${updated} updated, ${skipped} skipped, ${failed} failed.`);
  } else {
    ui.notifications.info(`GMTools pull sync complete: ${created} created, ${updated} updated, ${skipped} skipped.`);
  }
  return {
    total: entries.length,
    created,
    updated,
    skipped,
    failed,
    failures,
  };
}

function openPullSyncAllDialog() {
  const settingTag = String(
    getSetting("gmtoolsSettingId")
    || getSetting("syncSettingTag")
    || getSetting("defaultSettingTag")
    || slugifySetting(game.world?.id || game.world?.title || "")
    || "unsorted"
  ).trim();
  new Dialog({
    title: "GMTools Pull Sync (Manual)",
    content: `
      <p>Pull records from GMTools into this Foundry world. No automatic syncing is performed.</p>
      <p><strong>Sync Setting:</strong> ${foundry.utils.escapeHTML(settingTag)}</p>
      <div class="form-group"><label><input type="checkbox" name="npcs" checked /> NPCs</label></div>
      <div class="form-group"><label><input type="checkbox" name="creatures" checked /> Creatures</label></div>
      <div class="form-group"><label><input type="checkbox" name="cyphers" checked /> Cyphers</label></div>
      <div class="form-group"><label><input type="checkbox" name="artifacts" checked /> Artifacts</label></div>
      <p class="notes">Newest wins on conflict using GMTools saved timestamp.</p>
    `,
    buttons: {
      sync: {
        label: "Pull Sync All",
        icon: '<i class="fas fa-cloud-download-alt"></i>',
        callback: async (html) => {
          const root = html?.[0] || html;
          const read = (name) => Boolean(root?.querySelector?.(`input[name="${name}"]`)?.checked);
          await pullSyncAllFromGmtools({
            includeNpcs: read("npcs"),
            includeCreatures: read("creatures"),
            includeCyphers: read("cyphers"),
            includeArtifacts: read("artifacts"),
          });
        },
      },
      cancel: { label: "Cancel" },
    },
    default: "sync",
  }).render(true);
}

function syncableActors() {
  return Array.from(game.actors?.contents || []).filter((actor) => {
    const actorType = String(actor?.type || "").trim().toLowerCase();
    return actorType === "pc" || actorType === "npc";
  });
}

function syncableItems() {
  const allowed = new Set([
    "cypher",
    "artifact",
    "equipment",
    "attack",
    "ability",
    "skill",
    "descriptor",
    "focus",
    "type",
    "flavor",
  ]);
  return Array.from(game.items?.contents || []).filter((item) => {
    const itemType = String(item?.type || "").trim().toLowerCase();
    return allowed.has(itemType);
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

function categoryForItemType(itemType) {
  const t = String(itemType || "").trim().toLowerCase();
  if (t === "cypher") return "cyphers";
  if (t === "artifact") return "artifacts";
  return "items";
}

async function bulkSyncItemsToGmtools({
  includeItems = true,
  includeCyphers = true,
  includeArtifacts = true,
} = {}) {
  const items = syncableItems().filter((item) => {
    const cat = categoryForItemType(item?.type);
    if (cat === "cyphers") return includeCyphers;
    if (cat === "artifacts") return includeArtifacts;
    return includeItems;
  });

  if (!items.length) {
    ui.notifications.warn("GMTools bulk sync found no matching items.");
    return { total: 0, synced: 0, failed: 0, failures: [] };
  }

  ui.notifications.info(`GMTools item sync started for ${items.length} item${items.length === 1 ? "" : "s"}.`);

  const failures = [];
  let synced = 0;
  for (const item of items) {
    try {
      const result = await sendItemToGmtools(item);
      synced += 1;
      if (getSetting("debugLog")) console.log(`[${MODULE_ID}] bulk item sync`, item.name, result);
    } catch (err) {
      const message = String(err?.message || err || "unknown error");
      failures.push({ name: item.name || "Unnamed Item", message });
      if (getSetting("debugLog")) console.error(`[${MODULE_ID}] bulk item sync error`, item.name, err);
    }
  }

  const failed = failures.length;
  if (failed) {
    ui.notifications.warn(`GMTools item sync finished: ${synced} synced, ${failed} failed.`);
    console.warn(`[${MODULE_ID}] bulk item sync failures`, failures);
  } else {
    ui.notifications.info(`GMTools item sync complete: ${synced} synced.`);
  }
  return {
    total: items.length,
    synced,
    failed,
    failures,
  };
}

async function bulkSyncAllToGmtools({
  includePcs = true,
  includeNpcs = true,
  includeItems = true,
  includeCyphers = true,
  includeArtifacts = true,
} = {}) {
  const actorResult = await bulkSyncActorsToGmtools({ includePcs, includeNpcs });
  const itemResult = await bulkSyncItemsToGmtools({ includeItems, includeCyphers, includeArtifacts });
  const total = Number(actorResult.total || 0) + Number(itemResult.total || 0);
  const synced = Number(actorResult.synced || 0) + Number(itemResult.synced || 0);
  const failed = Number(actorResult.failed || 0) + Number(itemResult.failed || 0);
  const failures = [...(actorResult.failures || []), ...(itemResult.failures || [])];
  if (failed) {
    ui.notifications.warn(`GMTools full sync finished: ${synced}/${total} synced, ${failed} failed.`);
  } else {
    ui.notifications.info(`GMTools full sync complete: ${synced}/${total} synced.`);
  }
  return { total, synced, failed, failures };
}

function openBulkSyncDialog() {
  const actors = syncableActors();
  const pcCount = actors.filter((actor) => String(actor?.type || "").trim().toLowerCase() === "pc").length;
  const npcCount = actors.length - pcCount;
  const settingTag = String(
    getSetting("gmtoolsSettingId")
    || getSetting("syncSettingTag")
    || getSetting("defaultSettingTag")
    || slugifySetting(game.world?.id || game.world?.title || "")
    || "unsorted"
  ).trim();

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

function openBulkSyncAllDialog() {
  const actors = syncableActors();
  const items = syncableItems();
  const pcCount = actors.filter((actor) => String(actor?.type || "").trim().toLowerCase() === "pc").length;
  const npcCount = actors.length - pcCount;
  const cypherCount = items.filter((item) => String(item?.type || "").trim().toLowerCase() === "cypher").length;
  const artifactCount = items.filter((item) => String(item?.type || "").trim().toLowerCase() === "artifact").length;
  const otherItemCount = Math.max(0, items.length - cypherCount - artifactCount);
  const settingTag = String(
    getSetting("gmtoolsSettingId")
    || getSetting("syncSettingTag")
    || getSetting("defaultSettingTag")
    || slugifySetting(game.world?.id || game.world?.title || "")
    || "unsorted"
  ).trim();

  new Dialog({
    title: "GMTools Sync All Content",
    content: `
      <p>Sync actors and items into GMTools in one run.</p>
      <p><strong>Sync Setting:</strong> ${foundry.utils.escapeHTML(settingTag)}</p>
      <div class="form-group"><label><input type="checkbox" name="pcs" checked /> PCs (${pcCount})</label></div>
      <div class="form-group"><label><input type="checkbox" name="npcs" checked /> NPC/Creature actors (${npcCount})</label></div>
      <div class="form-group"><label><input type="checkbox" name="cyphers" checked /> Cyphers (${cypherCount})</label></div>
      <div class="form-group"><label><input type="checkbox" name="artifacts" checked /> Artifacts (${artifactCount})</label></div>
      <div class="form-group"><label><input type="checkbox" name="items" checked /> Other items (${otherItemCount})</label></div>
      <p class="notes">Creatures are synced as Foundry NPC actors and classified on GMTools import.</p>
    `,
    buttons: {
      sync: {
        label: "Sync Selected",
        icon: '<i class="fas fa-cloud-upload-alt"></i>',
        callback: async (html) => {
          const root = html?.[0] || html;
          const read = (name) => Boolean(root?.querySelector?.(`input[name="${name}"]`)?.checked);
          await bulkSyncAllToGmtools({
            includePcs: read("pcs"),
            includeNpcs: read("npcs"),
            includeCyphers: read("cyphers"),
            includeArtifacts: read("artifacts"),
            includeItems: read("items"),
          });
        },
      },
      cancel: { label: "Cancel" },
    },
    default: "sync",
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

  game.settings.register(MODULE_ID, "gmtoolsSettingId", {
    name: "GMTools Setting ID",
    hint: "Active GMTools setting bucket used for Foundry sync imports.",
    scope: "world",
    config: false,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "syncSettingTag", {
    name: "Sync Setting Tag",
    hint: "Primary setting tag used for GMTools sync storage bucketing (e.g. lands_of_legends).",
    scope: "world",
    config: false,
    type: String,
    default: "",
  });

  game.settings.register(MODULE_ID, "defaultSettingTag", {
    name: "Legacy Default Setting Tag",
    hint: "Backward-compat fallback if Sync Setting Tag is empty.",
    scope: "world",
    config: false,
    type: String,
    default: "",
  });

  game.settings.registerMenu(MODULE_ID, "syncTargetMenu", {
    name: "GMTools Sync Target",
    label: "Configure Sync Target",
    hint: "Choose which GMTools setting bucket this Foundry world syncs into.",
    icon: "fas fa-map-signs",
    type: GmtoolsSyncTargetForm,
    restricted: true,
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
    bulkSyncItemsToGmtools,
    bulkSyncAllToGmtools,
    pullSyncAllFromGmtools,
    openBulkSyncDialog,
    openBulkSyncAllDialog,
    openPullSyncAllDialog,
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

  const fullButton = document.createElement("button");
  fullButton.type = "button";
  fullButton.className = "legends-gmtools-bulk-sync-all";
  fullButton.innerHTML = '<i class="fas fa-layer-group"></i> GMTools Sync All';
  fullButton.style.marginTop = "6px";
  fullButton.style.width = "100%";
  fullButton.addEventListener("click", () => openBulkSyncAllDialog());
  header.appendChild(fullButton);

  const pullButton = document.createElement("button");
  pullButton.type = "button";
  pullButton.className = "legends-gmtools-pull-sync-all";
  pullButton.innerHTML = '<i class="fas fa-cloud-download-alt"></i> GMTools Pull Sync';
  pullButton.style.marginTop = "6px";
  pullButton.style.width = "100%";
  pullButton.addEventListener("click", () => openPullSyncAllDialog());
  header.appendChild(pullButton);
});

Hooks.on("renderItemDirectory", (_app, html) => {
  if (!game.user?.isGM) return;
  const root = html?.[0] || html;
  if (!root || root.querySelector?.(".legends-gmtools-item-sync-all")) return;
  const header = root.querySelector(".directory-header");
  if (!header) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "legends-gmtools-item-sync-all";
  button.innerHTML = '<i class="fas fa-box-open"></i> GMTools Item Sync';
  button.style.marginTop = "6px";
  button.style.width = "100%";
  button.addEventListener("click", () => openBulkSyncAllDialog());
  header.appendChild(button);

  const pullButton = document.createElement("button");
  pullButton.type = "button";
  pullButton.className = "legends-gmtools-item-pull-sync-all";
  pullButton.innerHTML = '<i class="fas fa-cloud-download-alt"></i> GMTools Pull Sync';
  pullButton.style.marginTop = "6px";
  pullButton.style.width = "100%";
  pullButton.addEventListener("click", () => openPullSyncAllDialog());
  header.appendChild(pullButton);
});
