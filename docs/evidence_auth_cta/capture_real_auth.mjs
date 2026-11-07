import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(root, "apps/web/package.json"));
const { chromium } = require("playwright");
const outDir = path.join(root, "docs/evidence_auth_cta/screenshots_real");
mkdirSync(outDir, { recursive: true });
const API = process.env.CADIVOR_EVIDENCE_API || "http://127.0.0.1:8793";
const WEB = process.env.CADIVOR_EVIDENCE_WEB || "http://127.0.0.1:3007";
const shots=[];
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
async function shot(page,name){
  const file=path.join(outDir,`${name}.png`);
  await page.screenshot({path:file, fullPage:true});
  shots.push({name,file:path.relative(root,file)});
  console.log("captured", name);
}
async function label(page){
  await page.evaluate(()=>{
    if(document.querySelector('[data-testid="synthetic-sample-label"]')) return;
    const note=document.createElement("p");
    note.dataset.testid="synthetic-sample-label";
    note.setAttribute("role","note");
    note.style.cssText="margin:8px 12px;padding:8px 10px;border:1px solid #cbd5e1;background:#f8fafc;font:12px/1.4 system-ui";
    note.textContent="SYNTHETIC SAMPLE DATA — local sandbox auth evidence. Not production.";
    document.body.prepend(note);
  });
}
async function main(){
  await httpOk(`${API}/health`);
  await httpOk(WEB);
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});

  await page.goto(`${WEB}/login`,{waitUntil:"networkidle"});
  await label(page);
  await shot(page,"real_login_desktop");
  await page.setViewportSize({width:390,height:844});
  await wait(300);
  await shot(page,"real_login_mobile");

  await page.setViewportSize({width:1280,height:900});
  await page.goto(`${WEB}/signup`,{waitUntil:"networkidle"});
  await label(page);
  await shot(page,"real_signup_desktop");
  await page.setViewportSize({width:390,height:844});
  await wait(300);
  await shot(page,"real_signup_mobile");

  // Invitation registration: login with invite query if supported, else signup?invite=
  await page.setViewportSize({width:1280,height:900});
  await page.goto(`${WEB}/login?invite=synthetic-invite-token-evidence`,{waitUntil:"networkidle"});
  await label(page);
  await shot(page,"real_invitation_registration_desktop");
  await page.setViewportSize({width:390,height:844});
  await wait(300);
  await shot(page,"real_invitation_registration_mobile");

  writeFileSync(path.join(outDir,"real_route_manifest.json"), JSON.stringify({captured_at:new Date().toISOString(),api:API,web:WEB,synthetic:true,shots},null,2));
  console.log("done", shots.length);
  await browser.close();
}
main().catch(e=>{console.error(e);process.exit(1);});
