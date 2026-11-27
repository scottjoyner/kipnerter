import test from "node:test";
import assert from "node:assert/strict";
import { completeFleetChat } from "../lib/lfm3-fleet.mjs";
import { runParallelLFM3Research } from "../lib/lfm3-parallel.mjs";
const model="lfm3-1.7b-research";
function node(name,host,role="interactive"){return {name,baseUrl:"http://"+host+":19176",model,adapter:"openai",maxInflight:1,role};}
const question="Q".repeat(450);
const short="short";
const long="L".repeat(200);
function transport(fail=[]){
 const calls=[];
 const fetchImpl=async(url,opts)=>{
  const host=new URL(url).hostname;
  calls.push({host,method:opts.method,prompt:opts.body?JSON.parse(opts.body).messages.at(-1).content:null});
  if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
  if(fail.includes(host))throw Error("synthetic worker failure");
  return Response.json({model,choices:[{message:{content:"bounded summary"},finish_reason:"stop"}]});
 };
 return {calls,fetchImpl};
}
test("context-aware assignment preserves the GPU for the longer perspective",async()=>{
 const gpu=node("fit-gpu","10.1.0.1"),cpu=node("fit-cpu","10.1.0.2","overflow");
 const {calls,fetchImpl}=transport();
 const r=await runParallelLFM3Research({authorized:true,question,subtasks:[short,long],nodes:[gpu,cpu],fetchImpl});
 assert.equal(r.status,200);
 assert.deepEqual(r.workerRuntimes,["fit-cpu","fit-gpu"]);
 assert.equal(calls.filter(c=>c.method==="POST").length,3);
});
test("impossible distinct context assignment spends no inference requests",async()=>{
 const gpu=node("impossible-gpu","10.2.0.1"),cpu=node("impossible-cpu","10.2.0.2","overflow");
 const {calls,fetchImpl}=transport();
 const r=await runParallelLFM3Research({authorized:true,question,subtasks:[long,"M".repeat(200)],nodes:[gpu,cpu],fetchImpl});
 assert.equal(r.status,413);assert.equal(calls.length,0);
});
test("failed perspectives are matched to fitting distinct spare workers",async()=>{
 const a=node("spare-fail-a","10.3.0.1"),b=node("spare-fail-b","10.3.0.2");
 const gpu=node("spare-fit-gpu","10.3.0.3"),cpu=node("spare-fit-cpu","10.3.0.4","overflow");
 const {calls,fetchImpl}=transport(["10.3.0.1","10.3.0.2"]);
 const r=await runParallelLFM3Research({authorized:true,question,subtasks:[short,long],nodes:[a,b,gpu,cpu],fetchImpl});
 assert.equal(r.status,200);assert.deepEqual(r.workerRuntimes,["spare-fit-cpu","spare-fit-gpu"]);
 assert.equal(calls.filter(c=>c.method==="POST").length,5);
});

test("busy synthesis-only GPU does not burn worker inference",async()=>{
 const gpu=node("busy-synthesis-gpu","10.4.0.1"),a=node("busy-synthesis-cpu-a","10.4.0.2","overflow"),b=node("busy-synthesis-cpu-b","10.4.0.3","overflow");
 let entered,release;
 const started=new Promise(r=>{entered=r}),held=new Promise(r=>{release=r});
 const occupying=completeFleetChat([{role:"user",content:"hold"}],{nodes:[gpu],fetchImpl:async(url)=>{
  if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
  entered();await held;
  return Response.json({model,choices:[{message:{content:"done"},finish_reason:"stop"}]});
 }});
 await started;
 try {
  const calls=[];
  const fetchImpl=async(url,opts)=>{
   calls.push({url,method:opts.method});
   if(url.endsWith("/v1/models"))return Response.json({data:[{id:model}]});
   return Response.json({model,choices:[{message:{content:"detailed perspective ".repeat(20)},finish_reason:"stop"}]});
  };
  const r=await runParallelLFM3Research({authorized:true,question:"Q".repeat(401),subtasks:["short","other"],nodes:[gpu,a,b],fetchImpl});
  assert.equal(r.status,503);
  assert.equal(calls.length,0,"no worker tokens before an eligible synthesis context exists");
 } finally {release();await occupying;}
});
