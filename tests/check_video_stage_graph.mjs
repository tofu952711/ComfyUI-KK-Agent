import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const source = await readFile(new URL("../web/lib/video_stage_graph.js", import.meta.url), "utf8");
const { migrateVideoStageGraph } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const inputs = ["api-key-not-printed", "user-rule-texts-remain-unchanged"];
const graph = {
  last_node_id: 92, last_link_id: 5,
  nodes: [
    { id: 92, type: "DSH_FullVideoAgent", pos: [100,100], size: [530,1500], inputs: [], widgets_values: inputs,
      outputs: [0,1,2,3,4,5,6,7].map((i) => ({ name: i<3 ? `text${i}` : `video${i-2}`, links: i===0 ? [1] : i===3 ? [2] : [] })) },
    { id: 77, type: "SaveText", inputs: [{ name: "text", link: 1 }] },
    { id: 88, type: "SaveVideo", pos: [1000,100], size: [300,300], inputs: [{ name: "video", link: 2 }],
      outputs: [], widgets_values: ["custom-prefix", "webm", "auto"] },
  ],
  links: [[1,92,0,77,0,"STRING"],[2,92,3,88,0,"VIDEO"]],
};
assert.equal(migrateVideoStageGraph(graph), true);
const stage = graph.nodes.find(n => n.id===92);
const reverse = graph.nodes.find(n => n.type==="DSH_VideoReverse");
assert.equal(stage.type, "DSH_VideoSegments");
assert.equal(stage.widgets_values, inputs);
assert.deepEqual(graph.links.find(l=>l[0]===1).slice(1,3), [reverse.id,0]);
assert.deepEqual(graph.links.find(l=>l[0]===2).slice(1,3), [92,3]);
assert.ok(graph.links.some(l=>l[1]===92 && l[2]===8 && l[3]===reverse.id));
const savers=graph.nodes.filter(n=>n.type==="SaveVideo");
assert.equal(savers.length, 5);
assert.ok(savers.every(n=>JSON.stringify(n.widgets_values)===JSON.stringify(["custom-prefix","webm","auto"])));
assert.deepEqual(graph.links.filter(l=>l[5]==="VIDEO").map(l=>l[2]).sort(), [3,4,5,6,7]);
assert.equal(new Set(graph.nodes.map(n=>n.id)).size,graph.nodes.length);
assert.equal(new Set(graph.links.map(l=>l[0])).size,graph.links.length);
const once = structuredClone(graph);
assert.equal(migrateVideoStageGraph(graph), false);
assert.deepEqual(graph, once);
const simple = { nodes: [{ id: 1,type:"DSH_FullVideoAgent" }], links: [] };
assert.equal(migrateVideoStageGraph(simple), false);
console.log("SAVEVIDEO_AND_REVERSE_GRAPH_BRANCHES_PRESERVED_AND_IDEMPOTENT_OK");
