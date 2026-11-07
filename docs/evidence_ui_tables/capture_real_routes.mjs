import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(root, "apps/web/package.json"));
const { chromium } = require("playwright");
const outDir = path.join(root, "docs/evidence_ui_tables/screenshots_real");
mkdirSync(outDir, { recursive: true });
const API = process.env.CADIVOR_EVIDENCE_API || "http://127.0.0.1:8792";
const WEB = process.env.CADIVOR_EVIDENCE_WEB || "http://127.0.0.1:3006";
const EMAIL = "sandbox-a@cadivor.test";
const PASSWORD = "CadivorSandbox!a";
const widths = [
  { name: "desktop", width: 1440, height: 960 },
  { name: "tablet_696", width: 696, height: 900 },
  { name: "mobile_390", width: 390, height: 844 },
];
const routes = [
  { id: "settings", path: "/settings" },
  { id: "design_impact", path: "/design-impact" },
  { id: "portfolio", path: "/portfolio-intelligence" },
];
const shots = [];
const overflow = [];

function wait(ms){return new Promise(r=>setTimeout(r,ms));}
function httpOk(url, timeoutMs=90000){
  const start=Date.now();
  return new Promise((resolve,reject)=>{
    const tick=()=>{
      const req=http.get(url,res=>{res.resume(); if(res.statusCode&&res.statusCode<500) return resolve(true);
        if(Date.now()-start>timeoutMs) return reject(new Error("timeout "+url)); setTimeout(tick,500);});
      req.on("error",()=>{ if(Date.now()-start>timeoutMs) return reject(new Error("timeout "+url)); setTimeout(tick,500);});
    }; tick();
  });
}

async function main(){
  await httpOk(`${API}/health`);
  await httpOk(WEB);
  const login = await fetch(`${API}/auth/login`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({email:EMAIL,password:PASSWORD})});
  const session = await login.json();
  if(!login.ok) throw new Error("login failed "+JSON.stringify(session));
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage();
  await page.addInitScript((sess)=>{
    localStorage.setItem("cadivor_next_session", JSON.stringify({
      access_token: sess.access_token,
      email: sess.email || EMAIL,
      workspace: sess.workspace || "Sandbox Workspace A",
      workspace_id: sess.workspace_id || "ws-sandbox-a",
      user_id: sess.user_id || "sandbox-a",
      plan: sess.plan || "Trial",
      mode: sess.mode || "sandbox-jwt",
    }));
  }, session);

  for (const route of routes){
    for (const vp of widths){
      await page.setViewportSize({width:vp.width,height:vp.height});
      await page.goto(`${WEB}${route.path}`,{waitUntil:"networkidle"});
      await wait(700);
      // Label synthetic evidence
      // Measure overflow before injecting the synthetic label banner.
      const metrics = await page.evaluate(()=>({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
      }));
      const overflowPx = Math.max(0, metrics.scrollWidth - metrics.clientWidth, metrics.bodyScrollWidth - metrics.clientWidth);
      overflow.push({route:route.id, viewport:vp.name, width:vp.width, ...metrics, overflowPx, ok: overflowPx <= 1});
      await page.evaluate(()=>{
        if(document.querySelector('[data-testid="synthetic-sample-label"]')) return;
        const note=document.createElement("p");
        note.dataset.testid="synthetic-sample-label";
        note.setAttribute("role","note");
        note.style.cssText="margin:8px 12px;padding:8px 10px;border:1px solid #cbd5e1;background:#f8fafc;font:12px/1.4 system-ui;max-width:calc(100% - 24px);box-sizing:border-box;overflow-wrap:anywhere";
        note.textContent="SYNTHETIC SAMPLE DATA — signed-in sandbox evidence capture. Not production.";
        (document.querySelector("main")||document.body).prepend(note);
      });
      const file = path.join(outDir, `real_${route.id}_${vp.name}.png`);
      await page.screenshot({path:file, fullPage:true});
      shots.push({route:route.id, viewport:vp.name, file: path.relative(root,file), overflowPx});
      console.log("captured", route.id, vp.name, "overflow", overflowPx);
    }
  }
  writeFileSync(path.join(outDir,"real_route_manifest.json"), JSON.stringify({captured_at:new Date().toISOString(), api:API, web:WEB, synthetic:true, shots, overflow}, null, 2));
  const bad = overflow.filter(o=>!o.ok);
  if(bad.length){
    console.error("OVERFLOW", bad);
    process.exitCode = 2;
  } else {
    console.log("done", shots.length, "no overflow");
  }
  await browser.close();
}
main().catch(err=>{console.error(err); process.exit(1);});
