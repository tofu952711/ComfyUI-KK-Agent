import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const source = await readFile(new URL("../web/lib/full_video_widgets.js", import.meta.url), "utf8");
const { migrateFullVideoWidgets, migrateFullVideoImageInputs, migrateFullVideoOutputs, resizeFullVideoInputs } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const prefix = ["test-key", "https://localhost/v1", "test-model", "用户输入", 900, 32768];
const rules = "系统规则\n按视频证据输出。";
const broken = [...prefix, rules, "openai-completions", "deepseek-messages"];
const repaired = migrateFullVideoWidgets(broken);
assert.deepEqual(repaired, [...prefix, "", "deepseek-messages", rules]);
assert.deepEqual(broken, [...prefix, rules, "openai-completions", "deepseek-messages"]);
assert.equal(migrateFullVideoWidgets(repaired), repaired);
for (const saved of [
  [...prefix, "", "openai-completions"],
  [...prefix, "", "openai-completions", rules],
  [...prefix, "models/custom-asr", "codez", rules],
  [...prefix, rules, "models/custom-asr", "codez"],
]) assert.equal(migrateFullVideoWidgets(saved), saved);
assert.deepEqual(migrateFullVideoWidgets([...prefix, "", "openai-completions", "deepseek-messages"]),
                 [...prefix, "", "deepseek-messages", ""]);
assert.deepEqual(migrateFullVideoWidgets([...broken, false]), [...repaired, false]);
console.log("FULL_VIDEO_WIDGET_MIGRATION_OK");

const oldPrefix = [...prefix, "models/custom-asr", "codez", rules, false, "B分段规定\n保留原文"];
for (const effort of ["high", "medium", "low", "auto"]) {
  for (const tail of [[effort], [effort, true], [effort, false]]) {
    const old = [...oldPrefix, ...tail];
    const snapshot = [...old];
    const next = migrateFullVideoWidgets(old);
    assert.deepEqual(next, [...oldPrefix, "", ...tail]);
    assert.deepEqual(old, snapshot);
    assert.equal(migrateFullVideoWidgets(next), next);
  }
}
for (const reverse of ["high", "", "B反推规定\n完整原文"]) {
  for (const tail of [["medium"], ["low", false]]) {
    const current = [...oldPrefix, reverse, ...tail];
    assert.equal(migrateFullVideoWidgets(current), current);
  }
}
assert.deepEqual(migrateFullVideoWidgets([...broken, false, "分段", "medium", false]),
                 [...repaired, false, "分段", "", "medium", false]);
console.log("CHAIN_B_REVERSE_FIELD_MIGRATION_IDEMPOTENT_OK");

// Exercise the ComfyUI hook too: configure may have assigned saved values
// already, so both the saved array and actual named widgets must be repaired.
const migrationURL = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const stageGraphSource = await readFile(new URL("../web/lib/video_stage_graph.js", import.meta.url), "utf8");
const stageGraphURL = `data:text/javascript;base64,${Buffer.from(stageGraphSource).toString("base64")}`;
const extensionSource = (await readFile(new URL("../web/dsh_video_inputs.js", import.meta.url), "utf8"))
  .replace('import { app } from "../../scripts/app.js";',
           'const app = { registerExtension(extension) { globalThis.testExtension = extension; } };')
  .replace('"./lib/full_video_widgets.js"', JSON.stringify(migrationURL))
  .replace('"./lib/video_stage_graph.js"', JSON.stringify(stageGraphURL));
await import(`data:text/javascript;base64,${Buffer.from(extensionSource).toString("base64")}`);
class TestNode {
  onConfigure(info) { this.originalCalled = true; return "original-result"; }
}
globalThis.testExtension.beforeRegisterNodeDef(TestNode, { name: "DSH_FullVideoAgent" });
const node = new TestNode();
node.widgets = [
  { name: "asr_model_dir", value: "openai-completions" },
  { name: "api_protocol", value: "deepseek-messages" },
  { name: "rules_text", value: rules },
];
const info = { widgets_values: [...broken] };
assert.equal(node.onConfigure(info), "original-result");
assert.equal(node.originalCalled, true);
assert.deepEqual(info.widgets_values, repaired);
assert.deepEqual(node.widgets.map((widget) => widget.value), ["", "deepseek-messages", rules]);
console.log("FULL_VIDEO_CONFIGURE_HOOK_OK");

const oldNode = new TestNode();
const oldInfo = { widgets_values: [...oldPrefix, "low", false] };
oldNode.widgets = ["asr_model_dir", "api_protocol", "rules_text", "segment_rules_text",
  "chain_b_reverse_rules_text", "reasoning_effort", "stream_usage"].map(name => ({ name, value: "misaligned" }));
oldNode.onConfigure(oldInfo);
assert.deepEqual(oldNode.widgets.map(widget => widget.value),
  ["models/custom-asr", "codez", rules, oldPrefix[10], "", "low", false]);
assert.deepEqual(oldInfo.widgets_values, [...oldPrefix, "", "low", false]);
const editors = { widgets: ["requirement", "rules_text", "segment_rules_text", "chain_b_reverse_rules_text", "chain_b_review_rules_text"]
  .map(name => ({ name, type: "text" })) };
resizeFullVideoInputs(editors);
assert.deepEqual(editors.widgets.map(widget => widget.options.getMinHeight()), [120, 260, 140, 260, 260]);
assert.deepEqual(editors.widgets.map(widget => widget.computeSize(520)), [[520,120],[520,260],[520,140],[520,260],[520,260]]);
console.log("CHAIN_B_WIDGET_CONFIGURATION_AND_EDITOR_HEIGHT_OK");

const priorWorkflow = new TestNode();
priorWorkflow.widgets = [{ name: "reasoning_effort", value: "auto" }];
priorWorkflow.inputs = [];
priorWorkflow.onConfigure({ widgets_values: [...prefix, "", "openai-completions", rules, true, ""] });
assert.equal(priorWorkflow.widgets[0].value, "high");
for (const effort of ["high", "medium", "low", "auto"]) {
  priorWorkflow.widgets[0].value = effort;
  priorWorkflow.onConfigure({ widgets_values: [...prefix, "", "openai-completions", rules, true, "", effort] });
  assert.equal(priorWorkflow.widgets[0].value, effort);
}
priorWorkflow.inputs = [{ name: "reasoning_effort", link: 99 }];
priorWorkflow.widgets[0].value = "low";
priorWorkflow.onConfigure({ widgets_values: [...prefix, "", "openai-completions", rules, true, ""] });
assert.equal(priorWorkflow.widgets[0].value, "low");
console.log("OLD_WORKFLOW_DEFAULT_HIGH_AND_SAVED_EFFORT_PRESERVED_OK");

const saved = {
  id: 81, type: "DSH_FullVideoAgent",
  inputs: [{ name: "video", type: "VIDEO", link: 1 },
    { name: "person", type: "IMAGE", link: 2 },
    { name: "product", type: "IMAGE", link: 3 },
    { name: "rules_text", type: "STRING", link: 4, widget: { name: "rules_text" } }],
  outputs: [{ name: "提示词", type: "STRING", links: [5] },
    { name: "分析证据", type: "STRING", links: null }, { name: "状态", type: "STRING", links: null }],
};
const links = [[1, 78, 0, 81, 0, "VIDEO"], [2, 79, 0, 81, 1, "IMAGE"],
  [3, 80, 0, 81, 2, "IMAGE"], [4, 90, 0, 81, 3, "STRING"], [5, 81, 0, 91, 0, "STRING"]];
globalThis.testExtension.beforeConfigureGraph({ nodes: [saved], links });
assert.deepEqual(saved.inputs.map(input => input.name), ["video", ...Array.from({ length: 10 }, (_, i) => `image${i + 1}`), "rules_text"]);
assert.equal(links[3][4], 11);
assert.equal(saved.inputs[11].link, 4);
assert.equal(saved.outputs.length, 8);
assert.deepEqual(saved.outputs[0].links, [5]);
assert.deepEqual(saved.outputs.slice(3).map(output => output.type), Array(5).fill("VIDEO"));
const migratedNode = structuredClone(saved);
migrateFullVideoImageInputs(saved, links);
migrateFullVideoOutputs(saved);
assert.deepEqual(saved, migratedNode);
console.log("FULL_VIDEO_OLD_GRAPH_IMAGES_OUTPUTS_LINKS_OK");

// Older saved graphs inherit the visible default; explicit blanks and linked
// text are preserved instead of silently restoring the built-in instructions.
class ReviewNode {
  onConfigure(info) {
    this.widgets[0].value = info.widgets_values[14];
  }
}
const reviewDefault = "默认审核全文";
globalThis.testExtension.beforeRegisterNodeDef(ReviewNode, {
  name: "DSH_VideoSegments", input: { optional: { chain_b_review_rules_text: ["STRING", { default: reviewDefault }] } },
});
const reviewNode = new ReviewNode();
reviewNode.widgets = [{ name: "chain_b_review_rules_text", value: reviewDefault }];
const currentValues = [...oldPrefix, "B反推", "high", true];
reviewNode.onConfigure({ widgets_values: currentValues });
assert.equal(reviewNode.widgets[0].value, reviewDefault);
for (const custom of ["自定义审核\n完整规则", ""]) {
  reviewNode.onConfigure({ widgets_values: [...currentValues, custom] });
  assert.equal(reviewNode.widgets[0].value, custom);
}
reviewNode.inputs = [{ name: "chain_b_review_rules_text", link: 100 }];
reviewNode.onConfigure({ widgets_values: currentValues });
assert.equal(reviewNode.widgets[0].value, undefined);
console.log("EDITABLE_B_REVIEW_OLD_GRAPH_CUSTOM_BLANK_AND_LINKED_VALUES_OK");
