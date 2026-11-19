import { app } from "../../scripts/app.js";
import { migrateFullVideoWidgets, migrateFullVideoImageInputs, migrateFullVideoOutputs, resizeFullVideoInputs } from "./lib/full_video_widgets.js";
import { migrateVideoStageGraph } from "./lib/video_stage_graph.js";

app.registerExtension({
  name: "DSH.FullVideo.InputMigration",
  beforeConfigureGraph(graphData) {
    if (migrateVideoStageGraph(graphData)) {
      console.info("[DSH] 已拆分B分段与反推连线：标准SaveVideo和独立反推节点可同时执行，保存配置保持不变");
    }
    for (const node of graphData?.nodes || []) {
      if (node.type === "DSH_VideoSegments" && (!node.title ||
          ["DSH 视频分析／B分段（并行入口）", "DSH 视频分析／B分段（SaveVideo与反推分流）"].includes(node.title))) {
        node.title = "KK agent 视频反推";
      }
      if (["DSH_FullVideoAgent", "DSH_VideoSegments"].includes(node.type)) {
        migrateFullVideoImageInputs(node, graphData.links);
        migrateFullVideoOutputs(node);
      }
    }
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!["DSH_FullVideoAgent", "DSH_VideoSegments"].includes(nodeData.name)) return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created?.apply(this, arguments);
      resizeFullVideoInputs(this);
      return result;
    };
    const original = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (info) {
      const previous = info?.widgets_values;
      const migrated = migrateFullVideoWidgets(previous);
      if (migrated !== previous) info.widgets_values = migrated;
      const result = original?.apply(this, arguments);
      if (this.inputs?.some((input) => input.name === "person" || input.name === "product") ||
          (this.inputs && !this.inputs.some((input) => input.name === "image10"))) {
        migrateFullVideoImageInputs(this, this.graph?.links);
      }
      migrateFullVideoOutputs(this);
      const effortWidget = this.widgets?.find((item) => item.name === "reasoning_effort");
      const effortLinked = this.inputs?.some((input) => input.name === "reasoning_effort" && input.link != null);
      if (effortWidget && !effortLinked &&
          ((Array.isArray(migrated) && migrated.length <= 11) || effortWidget.value == null)) {
        effortWidget.value = "high";
      }
      if (migrated !== previous) {
        for (const [index, name] of [[6, "asr_model_dir"], [7, "api_protocol"], [8, "rules_text"],
            [10, "segment_rules_text"], [11, "chain_b_reverse_rules_text"],
            [12, "reasoning_effort"], [13, "stream_usage"]]) {
          if (index >= migrated.length) continue;
          if (name === "reasoning_effort" && effortLinked) continue;
          const widget = this.widgets?.find((item) => item.name === name);
          if (widget) widget.value = migrated[index];
        }
        console.info("[DSH] 已兼容旧节点字段顺序，保留规则文本及思考等级设置");
      }
      resizeFullVideoInputs(this);
      return result;
    };
  },
});
