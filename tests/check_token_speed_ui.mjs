import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

let extension, handler, interval, removed = false;
globalThis.document = {createElement: () => ({style:{},textContent:''})};
globalThis.setInterval = fn => {interval=fn;};
let root, widget;
class Node {
  id = 92; type='DSH_FullVideoAgent'; size=[400,600];
  addDOMWidget(name, _type, element, options) {root=element; return widget={name,options};}
  computeSize() {return [400,800];}
  setSize(value) {this.size=value;}
  onRemoved() {removed=true;}
}
const node = new Node();
globalThis.speedTest = {
  app: {registerExtension: value => {extension=value;},graph:{getNodeById: id => String(id)==='92' ? node : null}},
  api: {addEventListener: (name, fn) => {assert.equal(name,'dsh_token_speed');handler=fn;},
    fetchApi: async () => ({ok:true,json: async () => ({result:null})})},
};
let source = await readFile(new URL('../web/dsh_token_speed.js',import.meta.url),'utf8');
const formatter = await readFile(new URL('../web/lib/token_speed_format.js',import.meta.url),'utf8');
source = source.replace("import { app } from '../../scripts/app.js';",'const {app}=globalThis.speedTest;')
  .replace("import { api } from '../../scripts/api.js';",'const {api}=globalThis.speedTest;')
  .replace("import { FLAGS } from './_flags.js';",'const FLAGS={nodeUi:true};')
  .replace("'./lib/token_speed_format.js'",JSON.stringify(`data:text/javascript;base64,${Buffer.from(formatter).toString('base64')}`));
await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
extension.beforeRegisterNodeDef(Node,{name:'DSH_FullVideoAgent'});
extension.setup();
node.onNodeCreated();
assert.equal(widget.options.serialize,false);
assert.equal(widget.serialize,false);
assert.equal(node.size[1],800);
const data={node_id:'92',run_id:'a',model:'test',status:'running',updated_at:Date.now()/1000,task_seconds:1,requests:[],output_tokens:null};
handler({detail:data});
assert.ok(root.textContent.includes('运行中'));
interval();
handler({detail:{...data,status:'completed',output_tokens:50,average_tps:10,effective_tps:5,updated_at:data.updated_at+1}});
assert.ok(root.textContent.includes('10.00 tok/s'));
assert.ok(root.textContent.includes('已完成'));
handler({detail:data});
assert.ok(root.textContent.includes('已完成')); // Stale events cannot overwrite completed/newer state.
node.onConfigure();
await Promise.resolve();
node.onRemoved();
assert.ok(removed);
console.log('TOKEN_SPEED_NODE_WIDGET_LIFECYCLE_EVENTS_AND_STALE_UPDATES_OK');
