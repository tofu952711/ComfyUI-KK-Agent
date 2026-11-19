// Exercise event ordering, stale revisions, DOM playback and transient widgets.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  querySelectorAll(tag) {
    return this.children.flatMap(child => [
      ...(child.tag === tag ? [child] : []), ...child.querySelectorAll(tag)]);
  }
  pause() { this.paused = true; }
  load() { this.loaded = true; }
  removeAttribute(key) { delete this[key]; }
}
globalThis.document = { createElement: tag => new Element(tag) };
let extension, handler, widget, root;
class Node {
  type = "DSH_FullVideoAgent";
  size = [400, 600];
  addDOMWidget(name, type, element, options) {
    root = element;
    widget = { name, type, options };
    return widget;
  }
  computeSize() { return this.size; }
  setSize(size) { this.size = size; }
  onRemoved() { this.removed = true; }
}
const node = new Node();
globalThis.previewTest = {
  app: { registerExtension(value) { extension = value; },
    graph: { getNodeById: id => id === "7" ? node : null, setDirtyCanvas() {} } },
  api: { addEventListener(name, callback) { assert.equal(name, "dsh_video_segments"); handler = callback; },
    apiURL: path => `/prefix${path}` },
};
let source = await readFile(new URL("../web/dsh_video_preview.js", import.meta.url), "utf8");
source = source.replace('import { app } from "../../scripts/app.js";', 'const { app } = globalThis.previewTest;')
  .replace('import { api } from "../../scripts/api.js";', 'const { api } = globalThis.previewTest;')
  .replace('import { FLAGS } from "./_flags.js";', 'const FLAGS = {nodeUi: true};');
await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
extension.beforeRegisterNodeDef(Node, { name: node.type });
extension.setup();
const emit = (kind, rest = {}) => handler({ detail: { node_id: "7", run_id: "run1", kind, ...rest } });
const clip = { index: 1, segment: {start: 0, end: 1}, seconds: .5,
  file: { filename: "r1-video1.mp4", type: "temp", subfolder: "dsh-preview-test" } };
emit("start");
assert.equal(widget.options.serialize, false);
emit("plan", {revision: 1, segments: [clip.segment]});
emit("clip", {revision: 1, ...clip});
const playing = root.querySelectorAll("video")[0];
assert.ok(playing.src.startsWith("/prefix/view?"));
assert.ok(playing.src.includes("type=temp"));
emit("plan", {revision: 2, segments: [clip.segment]});
assert.ok(playing.paused && playing.loaded && !playing.src);
emit("clip", {revision: 1, ...clip});
assert.equal(root.querySelectorAll("video").length, 0);
emit("clip", {revision: 2, ...clip});
assert.equal(root.querySelectorAll("video").length, 1);
emit("segments_ready", {revision: 2});
assert.ok(root.children[0].textContent.includes("裁切完成"));
emit("reverse_start", {revision: 2});
assert.ok(root.children[0].textContent.includes("第二个文本框"));
emit("start", {run_id: "run2"});
emit("clip", {revision: 2, ...clip});
assert.equal(root.querySelectorAll("video").length, 0); // Old run cannot populate a new run.
emit("clip", {run_id: "run2", revision: 1, ...clip});
emit("error", {run_id: "run2"});
assert.equal(root.querySelectorAll("video").length, 0);
emit("complete", {run_id: "run2", video_count: 0});
assert.ok(root.children[0].textContent.includes("不输出或保存视频"));
node.onRemoved();
assert.equal(node.removed, true);
console.log("EARLY_VIDEO_PREVIEW_EVENTS_AND_CLEANUP_OK");
