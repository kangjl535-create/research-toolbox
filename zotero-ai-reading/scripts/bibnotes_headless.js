// Run the user's installed BibNotes Formatter (Obsidian plugin "bibnotes") outside Obsidian, so a note is exactly
// what "Create/Update Literature Note" would write, without touching the real vault or the plugin settings.
//
// usage: node bibnotes_headless.js --plugin-dir <vault>/.obsidian/plugins/bibnotes --bbt-json <export.json>
//          --vault <temp dir> --citekey <key> [--existing <note.md>] [--storage <dir with KEY/image.png>]
//          [--add-note <annotation-note html>] [--keep-user-notes] [--settings <json of settings to try>]
// Writes <temp vault>/out/<exportTitle>.md and prints JSON {output, notices}. With --existing, that note is copied
// there first, so BibNotes merges into it as "Update Current Note" would (the user's save mode from data.json).
// Reads, never writes, main.js and data.json. Settings are changed in memory only (export folder, storage path).
const Module = require("module");
const fs = require("fs");
const path = require("path");

const args = {};
process.argv.slice(2).forEach((a, i, arr) => {
  if (a.startsWith("--")) args[a.slice(2)] = arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true;
});
for (const k of ["plugin-dir", "bbt-json", "vault", "citekey"]) if (!args[k]) { console.error("missing --" + k); process.exit(2); }
const PLUGIN = path.resolve(args["plugin-dir"]);
const vault = path.resolve(args.vault);

global.window = {}; // lets the bundled HTML parser skip browser-only code at load time
const notices = [];
const stub = {
  Plugin: class {
    constructor(app, manifest) { this.app = app; this.manifest = manifest; }
    addCommand() {} addSettingTab() {} registerEvent() {}
    loadData() { return Promise.resolve(JSON.parse(fs.readFileSync(path.join(PLUGIN, "data.json"), "utf8"))); }
    saveData() { return Promise.resolve(); } // never write the real data.json
  },
  Notice: class { constructor(m) { notices.push(String(m)); } },
  Modal: class {}, FuzzySuggestModal: class {}, PluginSettingTab: class {}, Setting: class {},
  Scope: class {}, TFolder: class {}, Platform: {},
  normalizePath: (p) => p.replace(/\\/g, "/").replace(/\/+/g, "/"),
};
const origLoad = Module._load;
Module._load = function (req) { return req === "obsidian" ? stub : origLoad.apply(this, arguments); };

(async () => {
  const app = { vault: { adapter: { getBasePath: () => vault } }, workspace: {} };
  global.app = app; // createNoteTitle() reads app at module scope
  const Plugin = require(path.join(PLUGIN, "main.js")).default;
  const plugin = new Plugin(app, {});
  await plugin.loadSettings();
  if (args.settings) Object.assign(plugin.settings, JSON.parse(fs.readFileSync(args.settings, "utf8"))); // trial set-up
  plugin.settings.exportPath = "out";
  plugin.settings.debugMode = false;
  if (args.storage) plugin.settings.zoteroStoragePathManual = path.resolve(args.storage) + path.sep;
  fs.mkdirSync(path.join(vault, "out"), { recursive: true });
  fs.mkdirSync(path.join(vault, plugin.settings.imagesPath || "."), { recursive: true });

  const data = JSON.parse(fs.readFileSync(args["bbt-json"], "utf8"));
  const entry = data.items.find((i) => i.citationKey === args.citekey);
  if (!entry) throw new Error("citekey not in the Better BibTeX export: " + args.citekey);
  // Non-annotation child notes need a browser DOM to convert; the user's template has no {{UserNotes}}.
  const isAnnotationNote = (n) => unescape(n.note).includes("<span class=") || unescape(n.note).includes('<a href="zotero://open-pdf/library/');
  if (!args["keep-user-notes"]) entry.notes = entry.notes.filter(isAnnotationNote);
  if (args["add-note"]) {
    const now = new Date().toISOString().replace(/\.\d+Z$/, "Z");
    entry.notes = entry.notes.concat([{ key: "UNSAVED1", itemType: "note", note: fs.readFileSync(args["add-note"], "utf8"),
      tags: [], relations: {}, dateAdded: now, dateModified: now }]);
  }
  const title = plugin.settings.exportTitle.replace(/\{\{citeKey\}\}/gi, args.citekey);
  const target = path.join(vault, "out", title + ".md");
  if (args.existing) fs.copyFileSync(args.existing, target);
  else if (fs.existsSync(target)) fs.unlinkSync(target);

  plugin.createNote(entry, data);
  for (let i = 0; i < 50 && !fs.existsSync(target); i++) await new Promise((r) => setTimeout(r, 100));
  await new Promise((r) => setTimeout(r, 1000)); // writeFile/copyFile are callback-based
  console.log(JSON.stringify({ output: target, notices }));
})().catch((e) => { console.error("ERROR", (e && e.stack) || e); process.exit(1); });
