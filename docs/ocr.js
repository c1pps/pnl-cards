/* PnL Cards : lecture des PNL cards directement dans le navigateur (version web).
   Port JavaScript de extract_terminal.py / extract_other.py. Moteur : Tesseract (WebAssembly), servi depuis ./ocr/.
   Aucune image ne quitte le navigateur. */
(function(){
'use strict';
const BASE = new URL('ocr/', document.currentScript ? document.currentScript.src : location.href).href;
const W = 1980, H = 1320;
const Z = {
  ticker:[150,505,1130,668], pnl_sol:[160,680,1136,910], invested:[222,1040,545,1110], position:[617,1040,945,1110],
  pnl_pct:[955,1040,1330,1110], inv_usd:[150,1120,540,1190], pnl_usd:[945,1120,1300,1190]
};
const ZP = { pnl:[160,735,1136,975], bought:[160,1040,550,1180], sold:[555,1040,945,1180], pct:[945,1040,1300,1180] };
const MONTH = /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*20\d\d/i;
const MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December';
const SUF = {K:1e3, M:1e6, B:1e9};

/* ---------- images : {w,h,d:RGBA} (couleur) et {w,h,g:Uint8Array} (gris) ---------- */
function crop(im, z){
  const sx = im.w / W, sy = im.h / H;
  return sub(im, Math.floor(z[0]*sx), Math.floor(z[1]*sy), Math.floor(z[2]*sx), Math.floor(z[3]*sy));
}
function sub(im, x0, y0, x1, y1){
  x0 = Math.max(0, x0); y0 = Math.max(0, y0); x1 = Math.min(im.w, x1); y1 = Math.min(im.h, y1);
  const w = Math.max(0, x1-x0), h = Math.max(0, y1-y0), d = new Uint8ClampedArray(w*h*4);
  for(let y=0;y<h;y++){ const s=((y0+y)*im.w+x0)*4; d.set(im.d.subarray(s, s+w*4), y*w*4); }
  return {w, h, d};
}
function zone(im, b){ return sub(im, Math.floor(b[0]*im.w), Math.floor(b[1]*im.h), Math.floor(b[2]*im.w), Math.floor(b[3]*im.h)); }
function maskOf(im, f){
  const n = im.w*im.h, m = new Uint8Array(n), d = im.d;
  for(let i=0;i<n;i++){ const r=d[i*4], g=d[i*4+1], b=d[i*4+2]; m[i] = f(r,g,b) ? 1 : 0; }
  return m;
}

/* ---------- composantes connexes (8 voisins), étiquettes dans l'ordre de balayage ---------- */
function ccl(mask, w, h){
  const lab = new Int32Array(w*h), parent = [0]; let n = 0;
  const find = x => { while(parent[x] !== x){ parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    const i = y*w+x; if(!mask[i]) continue;
    const nb = [];
    if(x>0 && lab[i-1]) nb.push(lab[i-1]);
    if(y>0){ if(x>0 && lab[i-w-1]) nb.push(lab[i-w-1]); if(lab[i-w]) nb.push(lab[i-w]); if(x<w-1 && lab[i-w+1]) nb.push(lab[i-w+1]); }
    if(!nb.length){ n++; parent[n] = n; lab[i] = n; continue; }
    const roots = nb.map(find), m = Math.min(...roots); lab[i] = m;
    for(const r of roots) if(r !== m) parent[r] = m;
  }
  const map = new Int32Array(parent.length), st = [null]; let k = 0;
  for(let i=0;i<w*h;i++){
    if(!lab[i]) continue; const r = find(lab[i]);
    if(!map[r]){ k++; map[r] = k; st.push([w, h, -1, -1, 0]); }   // [l, t, r, b, area]
    const c = map[r], s = st[c], x = i % w, y = (i / w) | 0;
    if(x < s[0]) s[0] = x; if(y < s[1]) s[1] = y; if(x > s[2]) s[2] = x; if(y > s[3]) s[3] = y; s[4]++;
    lab[i] = c;
  }
  const stats = [null]; for(let c=1;c<=k;c++){ const s = st[c]; stats.push({l:s[0], t:s[1], w:s[2]-s[0]+1, h:s[3]-s[1]+1, a:s[4]}); }
  return {n:k, lab, st:stats};
}

/* ---------- redimensionnement Lanczos (comme PIL) sur une image grise ---------- */
function lanczos(x){ if(x === 0) return 1; if(x <= -3 || x >= 3) return 0; const p = Math.PI*x; return 3*Math.sin(p)*Math.sin(p/3)/(p*p); }
function resizeAxis(src, sw, sh, ow, oh){
  const out = new Float32Array(ow*oh);
  if(ow === sw){ for(let i=0;i<sw*sh;i++) out[i] = src[i]; return out; }
  const sc = sw/ow, fs = Math.max(sc, 1), sup = 3*fs;
  const ks = [];
  for(let i=0;i<ow;i++){
    const c = (i+0.5)*sc; let x0 = Math.floor(c - sup + 0.5), x1 = Math.floor(c + sup + 0.5);
    x0 = Math.max(x0, 0); x1 = Math.min(x1, sw);
    const wt = []; let tot = 0;
    for(let x=x0;x<x1;x++){ const v = lanczos((x - c + 0.5)/fs); wt.push(v); tot += v; }
    ks.push([x0, wt.map(v => v/tot)]);
  }
  for(let y=0;y<sh;y++) for(let i=0;i<ow;i++){
    const [x0, wt] = ks[i]; let s = 0; for(let k=0;k<wt.length;k++) s += src[y*sw+x0+k]*wt[k];
    out[y*ow+i] = s;
  }
  return out;
}
function transpose(a, w, h){ const o = new Float32Array(w*h); for(let y=0;y<h;y++) for(let x=0;x<w;x++) o[x*h+y] = a[y*w+x]; return o; }
function resizeGray(g, w, h, ow, oh){
  if(ow === w && oh === h) return g;
  const a = resizeAxis(g, w, h, ow, h);                          // horizontal
  const t = resizeAxis(transpose(a, ow, h), h, ow, oh, ow);      // vertical
  const o = new Uint8Array(ow*oh);
  for(let y=0;y<oh;y++) for(let x=0;x<ow;x++){ const v = Math.round(t[x*oh+y]); o[y*ow+x] = v < 0 ? 0 : v > 255 ? 255 : v; }
  return o;
}

/* ---------- nettoyage du masque (port de _clean / _finish) ---------- */
function clean(mask, w, h, minBig, dropSign, dropPct){
  const {n, lab, st} = ccl(mask, w, h);
  const out = new Uint8Array(w*h).fill(255);
  const touches = i => { const s = st[i]; return s.l <= 0 || s.t <= 0 || s.l + s.w >= w || s.t + s.h >= h; };
  let big = []; for(let i=1;i<=n;i++) if(st[i].h >= minBig && !touches(i)) big.push(i);
  if(!big.length) return out;
  const hs = big.map(i => st[i].h).sort((a,b) => a-b), ref = hs[(big.length/2) | 0];
  big = big.filter(i => 0.6*ref <= st[i].h && st[i].h <= 1.5*ref);
  if(!big.length) return out;
  big.sort((a,b) => st[a].l - st[b].l || a - b);
  const groups = []; let cur = [big[0]];
  for(let k=1;k<big.length;k++){
    const i = big[k], prev = cur[cur.length-1], gap = st[i].l - (st[prev].l + st[prev].w);
    if(gap > 1.1*ref){ groups.push(cur); cur = [i]; } else cur.push(i);
  }
  groups.push(cur);
  let bestG = groups[0], bw = -1;
  for(const g of groups){ const sw = g.reduce((s,i) => s + st[i].w, 0); if(sw > bw){ bw = sw; bestG = g; } }
  big = bestG;
  if(dropSign && big.length > 1){ const s = st[big[0]]; if(s.w/s.h > 0.85 && s.a/(s.w*s.h) < 0.55) big = big.slice(1); }
  if(dropPct && big.length > 1){ const s = st[big[big.length-1]]; if(s.w/s.h > 0.95) big = big.slice(0, -1); }
  const y0 = Math.min(...big.map(i => st[i].t)), y1 = Math.max(...big.map(i => st[i].t + st[i].h));
  const x0 = Math.min(...big.map(i => st[i].l)), x1 = Math.max(...big.map(i => st[i].l + st[i].w));
  const keep = new Set(big);
  for(let i=1;i<=n;i++){
    if(keep.has(i) || touches(i)) continue;
    const s = st[i], cy = s.t + s.h/2;
    if(s.a >= 6 && y0 <= cy && cy <= y1+6 && x0-4 <= s.l && s.l <= x1+4 && s.w <= 0.45*ref && s.h <= 0.45*ref) keep.add(i);
  }
  for(let p=0;p<w*h;p++) if(lab[p] && keep.has(lab[p])) out[p] = 0;
  return out;
}
function finish(out, w, h, pad, scale){
  let xmin = w, xmax = -1, ymin = h, ymax = -1;
  for(let y=0;y<h;y++) for(let x=0;x<w;x++) if(out[y*w+x] === 0){ if(x<xmin) xmin=x; if(x>xmax) xmax=x; if(y<ymin) ymin=y; if(y>ymax) ymax=y; }
  let cx0 = 0, cy0 = 0, cx1 = w, cy1 = h;
  if(xmax >= 0){ cx0 = Math.max(xmin-pad, 0); cy0 = Math.max(ymin-pad, 0); cx1 = Math.min(xmax+pad, w); cy1 = Math.min(ymax+pad, h); }
  const cw = cx1-cx0, ch = cy1-cy0, c = new Uint8Array(cw*ch);
  for(let y=0;y<ch;y++) for(let x=0;x<cw;x++) c[y*cw+x] = out[(cy0+y)*w+cx0+x];
  const ow = cw*scale, oh = ch*scale, r = resizeGray(c, cw, ch, ow, oh);
  const W2 = ow+40, H2 = oh+40, g = new Uint8Array(W2*H2).fill(255);
  for(let y=0;y<oh;y++) for(let x=0;x<ow;x++) g[(y+20)*W2+x+20] = r[y*ow+x];
  return {w:W2, h:H2, g};
}
const cleanFinish = (im, mask, minBig, o) => {
  o = o || {};
  return finish(clean(mask, im.w, im.h, minBig, !!o.dropSign, !!o.dropPct), im.w, im.h, o.pad == null ? 14 : o.pad, o.scale == null ? 2 : o.scale);
};

/* ---------- masques propres à chaque carte ---------- */
const brightText = (im, thr = 232) => cleanFinish(im, maskOf(im, (r,g,b) => Math.min(r,g,b) >= thr), 40);
const bannerDigits = im => cleanFinish(im, maskOf(im, (r,g,b) => Math.max(r,g,b) < 90), 40, {dropSign:true, pad:12, scale:1});
function smallValue(im, o){
  o = o || {}; const tone = o.tone, thr = 246; let f;
  if(tone === 'green') f = (r,g,b) => (g-r > 40) && (g-b > 20) && g > 120;
  else if(tone === 'red') f = (r,g,b) => r > 200 && g < 90 && b < 110;
  else f = (r,g,b) => Math.min(r,g,b) >= thr;
  return cleanFinish(im, maskOf(im, f), 24, {dropSign:o.dropSign, dropPct:o.dropPct});
}
function colorSign(im){
  let red = 0, green = 0; const d = im.d;
  for(let i=0;i<im.w*im.h;i++){ const r=d[i*4], g=d[i*4+1], b=d[i*4+2]; if(r>180 && g<110 && b<120) red++; if(g>150 && r<140) green++; }
  return red > green ? -1 : 1;
}
function maskText(im, kind){
  let f;
  if(kind === 'dark') f = (r,g,b) => Math.max(r,g,b) < 90;
  else if(kind === 'white') f = (r,g,b) => Math.min(r,g,b) >= 215;
  else if(kind === 'green') f = (r,g,b) => (g-r > 40) && (g-b > 15) && g > 130;
  else f = (r,g,b) => r > 200 && g < 110;
  return cleanFinish(im, maskOf(im, f), Math.max(14, Math.floor(im.h*0.25)), {pad:10, scale:2});
}

/* ---------- Tesseract ---------- */
let tessLoad = null;
function loadTesseract(){
  if(window.Tesseract) return Promise.resolve();
  if(!tessLoad) tessLoad = new Promise((ok, ko) => { const s = document.createElement('script'); s.src = BASE + 'tesseract.min.js'; s.onload = ok; s.onerror = () => ko(new Error('tesseract')); document.head.appendChild(s); });
  return tessLoad;
}
async function newWorker(){
  await loadTesseract();
  return Tesseract.createWorker('eng', 1, {workerPath:BASE+'worker.min.js', corePath:BASE, langPath:BASE, gzip:true, logger:()=>{}});
}
function toCanvas(g){
  const c = document.createElement('canvas'); c.width = g.w; c.height = g.h;
  const id = new ImageData(g.w, g.h), d = id.data;
  for(let i=0;i<g.w*g.h;i++){ const v = g.g[i]; d[i*4] = v; d[i*4+1] = v; d[i*4+2] = v; d[i*4+3] = 255; }
  c.getContext('2d').putImageData(id, 0, 0); return c;
}
function rgbToCanvas(im, scaleTo){
  const c0 = document.createElement('canvas'); c0.width = im.w; c0.height = im.h;
  c0.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(im.d), im.w, im.h), 0, 0);
  if(!scaleTo || scaleTo.w === im.w) return c0;
  const c = document.createElement('canvas'); c.width = scaleTo.w; c.height = scaleTo.h;
  const x = c.getContext('2d'); x.imageSmoothingQuality = 'high'; x.drawImage(c0, 0, 0, scaleTo.w, scaleTo.h); return c;
}
const invertCanvas = c => { const x = c.getContext('2d'), id = x.getImageData(0,0,c.width,c.height), d = id.data; for(let i=0;i<d.length;i+=4){ d[i]=255-d[i]; d[i+1]=255-d[i+1]; d[i+2]=255-d[i+2]; } x.putImageData(id,0,0); return c; };

/* ---------- lecture ---------- */
function reader(worker){
  const ocr = async (img, psm, wl) => {
    await worker.setParameters({tessedit_pageseg_mode:String(psm), tessedit_char_whitelist:wl || '', user_defined_dpi:'300'});
    const r = await worker.recognize(img.g ? toCanvas(img) : img);
    return (r.data.text || '').trim();
  };
  const D = '0123456789';
  const withDecimals = (d, dec) => { if(!d) return null; d = d.padStart(dec+1, '0'); return parseInt(d, 10) / Math.pow(10, dec); };
  const uniq = a => { const s = []; for(const v of a) if(v && !s.includes(v)) s.push(v); return s; };

  async function readGlyphs(img, dec){
    const {w, h} = img, mask = new Uint8Array(w*h); for(let i=0;i<w*h;i++) mask[i] = img.g[i] < 128 ? 1 : 0;
    const {n, st} = ccl(mask, w, h), boxes = []; for(let i=1;i<=n;i++) boxes.push(st[i]);
    if(!boxes.length) return [null, ''];
    const maxh = Math.max(...boxes.map(b => b.h)), maxb = Math.max(...boxes.map(b => b.t + b.h)), items = [];
    for(const b of boxes){
      if(b.h >= 0.55*maxh) items.push([b.l, 'd', b]);
      else if(b.h <= 0.3*maxh && b.w <= 0.3*maxh && (b.t + b.h) >= 0.8*maxb) items.push([b.l, '.', b]);
    }
    items.sort((a,b) => a[0] - b[0]);
    let out = '', seenDot = false, decCount = 0;
    for(const [, kind, b] of items){
      if(kind === '.'){ if(!seenDot && out){ out += '.'; seenDot = true; } continue; }
      if(!out && !seenDot && b.w/b.h > 0.85){
        let on = 0; for(let y=b.t;y<b.t+b.h;y++) for(let x=b.l;x<b.l+b.w;x++) if(mask[y*w+x]) on++;
        if(on/(b.w*b.h) < 0.55) continue;                         // signe '+'
      }
      if(seenDot && decCount >= dec) break;
      const pad = 10, x0 = Math.max(b.l-pad, 0), y0 = Math.max(b.t-pad, 0), x1 = Math.min(b.l+b.w+pad, w), y1 = Math.min(b.t+b.h+pad, h);
      const gw = x1-x0, gh = y1-y0, g = new Uint8Array(gw*gh);
      for(let y=0;y<gh;y++) for(let x=0;x<gw;x++) g[y*gw+x] = mask[(y0+y)*w+x0+x] ? 0 : 255;
      const big = {w:gw*2, h:gh*2, g:resizeGray(g, gw, gh, gw*2, gh*2)};
      let t = '';
      for(const [psm, wl] of [[10,D],[8,D],[13,D],[10,'']]){ t = (await ocr(big, psm, wl)).replace(/[^0-9]/g, ''); if(t) break; }
      if(!t) return [null, out];
      out += t[0]; if(seenDot) decCount++;
    }
    if(out.includes('.') && decCount === dec){ const v = parseFloat(out); if(isFinite(v)) return [v, out]; }
    return [null, out];
  }
  async function readFixed(img, dec, alt, glyphs){
    alt = alt || [];
    if(glyphs) for(const d of [dec, ...alt]){ const [gv, gt] = await readGlyphs(img, d); if(gv != null) return [gv, gt]; }
    const raw = await ocr(img, 7, D + '.');
    for(const d of [dec, ...alt]){ const m = new RegExp('(\\d+)\\.(\\d{' + d + '})').exec(raw); if(m) return [parseFloat(m[1] + '.' + m[2]), raw]; }
    const dd = raw.replace(/[^0-9]/g, '');
    return [dd ? withDecimals(dd, dec) : null, raw];
  }

  /* les montants en dollars sont lus avec plus d'erreurs : on les recoupe avec le % et le prix du SOL (investi / PnL en SOL) */
  async function repairUsd(im, tone, r, pv, iv, pnlAbs, flags){
    const ok = (ui, up) => ui > 0 && up > 0 && Math.abs(up/ui*100 - pv)/pv <= 0.004 && ui/iv >= 20 && ui/iv <= 2000 && Math.abs(up - pnlAbs*ui/iv)/up <= 0.03;
    if(r.inv_usd && r.pnl_usd && ok(r.inv_usd, Math.abs(r.pnl_usd))) return;
    const dv = raw => { const d = raw.replace(/[^0-9]/g, ''), o = []; for(const dd of [d, d.slice(1), d.slice(0, -1), '1' + d]) if(dd.length >= 3) o.push(withDecimals(dd, 2)); return o; };
    const iz = crop(im, Z.inv_usd), pz = crop(im, Z.pnl_usd);
    const imgsI = [smallValue(iz)], imgsP = [smallValue(pz, {tone}), smallValue(pz, {tone, dropSign:true}), smallValue(pz)];
    const gather = async imgs => {
      const c = [];
      for(const im2 of imgs){ const [v, raw] = await readFixed(im2, 2); c.push(v, ...dv(raw)); }
      for(const im2 of imgs){ const [v] = await readFixed(im2, 2, [], true); c.push(v); }
      return uniq(c);
    };
    const ci = uniq([r.inv_usd, ...(await gather(imgsI))]), cp = uniq([r.pnl_usd && Math.abs(r.pnl_usd), ...(await gather(imgsP))]);
    for(const ui of ci) for(const up of cp) if(ok(ui, up)){
      r.inv_usd = ui; r.pnl_usd = (r.pnl_usd != null && r.pnl_usd < 0) || tone === 'red' ? -up : up; return;
    }
  }
  async function extractTerminal(im){
    const r = {terminal:'terminal'}, flags = [];
    const t = await ocr(brightText(crop(im, Z.ticker)), 7);
    let tc = t.replace(/[^A-Za-z0-9\-_. ]/g, '').replace(/^[ .\-_]+|[ .\-_]+$/g, '');
    if(MONTH.test(tc)){
      r.card_type = 'period'; r.currency = 'USD'; r.period_label = tc;
      const pz = crop(im, ZP.pnl), sign = colorSign(pz);
      r.pnl_value = sign * ((await readFixed(bannerDigits(pz), 2))[0] || 0);
      for(const k of ['bought', 'sold']){
        const txt = await ocr(smallValue(crop(im, ZP[k])), 7, D + '.KMk$');
        const m = /([0-9.]+)\s*([KMk])?/.exec(txt);
        if(m){
          let num = m[1]; if(m[2] && !num.includes('.') && num.length >= 3) num = num.slice(0, -2) + '.' + num.slice(-2);   // "$2.70K" : le point est parfois perdu
          let v = (num.split('.').length - 1 <= 1) ? parseFloat(num) : null; if(v != null && isNaN(v)) v = null;
          r['total_' + k] = v == null ? null : v * ({K:1e3, k:1e3, M:1e6}[m[2] || ''] || 1);
        }
      }
      const cz = crop(im, ZP.pct), cs = colorSign(cz);
      r.pnl_percent = cs * ((await readFixed(smallValue(cz, {dropSign:true, dropPct:true, tone:cs < 0 ? 'red' : 'green'}), 2))[0] || 0);
      r.flags = flags.concat(['abbreviated_amounts']);
      return r;
    }
    if(/^[A-Zl]+$/.test(tc) && tc.includes('l')) tc = tc.replace(/l/g, 'I');
    r.card_type = 'trade'; r.currency = 'SOL'; r.token_symbol = tc || null;
    if(/[Il1]/.test(tc)) flags.push('ticker_ambiguous_I_l');
    const ban = crop(im, Z.pnl_sol), sign = colorSign(ban);
    const pnl = (await readFixed(bannerDigits(ban), 4))[0];
    r.pnl_value = pnl == null ? null : sign * pnl;
    const tone = sign < 0 ? 'red' : 'green', pcVariants = [];
    const zimg0 = crop(im, [955, Z.pnl_pct[1], Z.pnl_pct[2], Z.pnl_pct[3]]);
    for(const ds of [true, false]) pcVariants.push(await readFixed(smallValue(zimg0, {dropSign:ds, dropPct:true, tone}), 2));
    r.position = (await readFixed(smallValue(crop(im, Z.position)), 2))[0];
    r.inv_usd = (await readFixed(smallValue(crop(im, Z.inv_usd)), 2))[0];
    r.pnl_usd = (await readFixed(smallValue(crop(im, Z.pnl_usd), {tone}), 2))[0];
    if(r.pnl_usd != null && sign < 0) r.pnl_usd = -Math.abs(r.pnl_usd);
    const [invVal4, invRaw] = await readFixed(smallValue(crop(im, Z.invested)), 4, [2]);
    const dI = invRaw.replace(/[^0-9]/g, '');
    const invC = uniq([invVal4, withDecimals(dI, 4), withDecimals(dI, 2)]);
    let pcC = [];
    for(const [v, raw] of pcVariants){
      if(v) pcC.push(v);
      const dP = raw.replace(/[^0-9]/g, '');
      for(const dd of [dP, dP.slice(0, -1), dP.slice(1)]) if(dd.length >= 3) pcC.push(withDecimals(dd, 2));
    }
    pcC = uniq(pcC);
    let expUsd = null;
    if(r.inv_usd && r.pnl_usd) expUsd = Math.abs(r.pnl_usd) / r.inv_usd * 100;
    const pnlAbs = r.pnl_value != null ? Math.abs(r.pnl_value) : null;
    const score = (iv, pv) => {
      const eS = pnlAbs ? Math.abs(pnlAbs - iv*pv/100) / Math.max(pnlAbs, 1e-9) : 9.0;
      const eU = expUsd ? Math.abs(pv - expUsd) / expUsd : null;
      const okS = eS <= (iv >= 1 ? 0.025 : 0.012), okU = eU != null && eU <= 0.004;
      return {rank:(okS && okU) ? 0 : okS ? 1 : okU ? 2 : 3, eS};
    };
    const pickPair = () => {
      let b = null;
      for(const iv of invC) for(const pv of pcC){
        const sc = score(iv, pv);
        if(!b || sc.rank < b.sc.rank || (sc.rank === b.sc.rank && sc.eS < b.sc.eS)) b = {sc, iv, pv};
      }
      return b;
    };
    let best = (invC.length && pcC.length) ? pickPair() : null;
    if(!best || best.sc.rank > 0){                                  // repli lent : glyphe par glyphe
      for(const x0 of [955, 970]){
        const zi = crop(im, [x0, Z.pnl_pct[1], Z.pnl_pct[2], Z.pnl_pct[3]]);
        const gv = (await readFixed(smallValue(zi, {dropSign:true, dropPct:true, tone}), 2, [], true))[0];
        if(gv && !pcC.includes(gv)) pcC.push(gv);
      }
      const gi = (await readFixed(smallValue(crop(im, Z.invested)), 4, [2], true))[0];
      if(gi && !invC.includes(gi)) invC.push(gi);
      if(invC.length && pcC.length) best = pickPair();
    }
    if(best && best.sc.rank === 1 && pnlAbs) await repairUsd(im, tone, r, best.pv, best.iv, pnlAbs, flags);
    if(best){
      r.invested = best.iv; r.pnl_percent = sign < 0 ? -best.pv : best.pv;
      let rk = best.sc.rank;
      if(rk === 1 && r.inv_usd && r.pnl_usd && Math.abs(Math.abs(r.pnl_usd)/r.inv_usd*100 - best.pv)/best.pv <= 0.004) rk = 0;
      if(rk === 3) flags.push('amount_mismatch'); else if(rk === 2) flags.push('invested_unverified'); else if(rk === 1) flags.push('usd_unverified');
    } else { r.invested = invC[0] || null; r.pnl_percent = null; }
    r.position_meaning = 'remaining';
    if([r.token_symbol, r.pnl_value, r.invested, r.pnl_percent, r.position].some(v => v == null)) flags.push('low_confidence');
    r.flags = flags;
    return r;
  }

  const money = txt => {
    const m = /([0-9][0-9,]*\.?[0-9]*)\s*([KMBkmb])?/.exec(txt || ''); if(!m) return null;
    const v = parseFloat(m[1].replace(/,/g, '')); if(isNaN(v)) return null;
    return v * (SUF[(m[2] || '').toUpperCase()] || 1);
  };
  async function detectTerminal(im){
    const w = Math.min(im.w, 1400), h = Math.floor(im.h * w / im.w);
    const c = rgbToCanvas(im, {w, h});
    const a = (await ocr(c, 11)), b = (await ocr(invertCanvas(rgbToCanvas(im, {w, h})), 11));
    const t = (a + ' ' + b).toLowerCase();
    if(t.includes('axiom') || t.includes('axio')) return 'axiom';
    if(t.includes('gmgn')) return 'gmgn';
    return 'terminal';
  }
  const fullText = im => ocr(rgbToCanvas(im, {w:im.w*2, h:im.h*2}), 11);
  async function parseAxiom(im){
    const row = {terminal:'axiom', card_type:'trade', currency:'USD', flags:['gabarit_a_valider']};
    const txt = await fullText(im);
    let m = /PNL\s*([+\-−])?\s*(\d[\d,]*)\.?(\d{2})\s*%/.exec(txt), pct = null;
    if(m){ pct = parseFloat(m[2].replace(/,/g, '') + '.' + m[3]); if(m[1] === '-' || m[1] === '−') pct = -pct; }
    m = /Invested\s*\$?\s*([0-9.,]+\s*[KMBkmb]?)/.exec(txt); const inv = m ? money(m[1]) : null;
    m = /Position\s*\$?\s*([0-9.,]+\s*[KMBkmb]?)/.exec(txt); const pos = m ? money(m[1]) : null;
    const ban = zone(im, [0.04, 0.30, 0.50, 0.46]); let r1 = 0, g1 = 0, g2 = 0;
    for(let i=0;i<ban.w*ban.h;i++){ if(ban.d[i*4] > 200) r1++; if(ban.d[i*4+1] > 200) g1++; if(ban.d[i*4+1] < 110) g2++; }
    const neg = r1 > g1*1.5 && g2 > 200;
    let pnl = money(await ocr(maskText(ban, 'dark'), 7, D + '.KMB$+-'));
    if(pnl != null && neg) pnl = -pnl;
    const tk = await ocr(maskText(zone(im, [0.03, 0.19, 0.52, 0.31]), 'white'), 7);
    row.token_symbol = tk.replace(/[^A-Za-z0-9\-_.]/g, '').replace(/^[.\-_]+|[.\-_]+$/g, '') || null;
    Object.assign(row, {pnl_value:pnl, pnl_percent:pct, invested:inv, position:pos, position_meaning:'total_value'});
    if(pnl != null && inv && pct && Math.abs(Math.abs(pnl) - inv*Math.abs(pct)/100) / Math.abs(pnl) > 0.04) row.flags.push('amount_mismatch');
    if([row.token_symbol, pnl, inv, pct].some(v => v == null)) row.flags.push('low_confidence');
    return row;
  }
  async function parseGmgn(im){
    const row = {terminal:'gmgn', card_type:'period', currency:'USD', flags:['gabarit_a_valider', 'abbreviated_amounts']};
    const txt = await fullText(im);
    let m = new RegExp('(' + MONTHS + ')\\s*(20\\d\\d)', 'i').exec(txt);
    row.period_label = m ? m[1][0].toUpperCase() + m[1].slice(1).toLowerCase() + ' ' + m[2] : 'Période';
    const ban = zone(im, [0.03, 0.46, 0.45, 0.62]); let neg = false;
    let btxt = await ocr(maskText(ban, 'green'), 7, D + '.KMB$+-');
    if(money(btxt) == null || money(btxt) === 0){ btxt = await ocr(maskText(ban, 'red'), 7, D + '.KMB$+-'); neg = money(btxt) != null; }
    const v = money(btxt);
    row.pnl_value = v != null ? (neg ? -v : v) : null;
    m = /(\d+)\s*\/\s*(\d+)/.exec(txt); if(m) row.profit_days = m[1] + '/' + m[2];
    if(row.pnl_value == null) row.flags.push('low_confidence');
    return row;
  }
  async function readAny(im){
    const looksTerminal = im.w >= 1900 && im.w <= 2060 && Math.abs(im.w/im.h - 1.5) < 0.01;   // gabarit exact des cartes Terminal : pas besoin de lire tout le texte
    const term = looksTerminal ? 'terminal' : await detectTerminal(im);
    if(term === 'axiom') return parseAxiom(im);
    if(term === 'gmgn') return parseGmgn(im);
    return extractTerminal(im);
  }
  return {readAny, extractTerminal};
}

/* ---------- format commun avec le serveur local (app.py : to_card) ---------- */
const rid = () => Math.random().toString(36).slice(2, 12);
function toCard(row, mtime){
  const base = {id:rid(), file:row.file, terminal:row.terminal || 'terminal', flags:(row.flags || []).filter(f => f !== 'ticker_ambiguous_I_l'), dateMs:mtime || null, edited:false};
  if(row.card_type === 'period') Object.assign(base, {type:'period', currency:'USD', label:row.period_label, pnl:row.pnl_value, pct:row.pnl_percent, bought:row.total_bought, sold:row.total_sold, profitDays:row.profit_days});
  else Object.assign(base, {type:'trade', currency:row.currency || 'SOL', token:row.token_symbol, pnl:row.pnl_value, invested:row.invested, pct:row.pnl_percent, usdPnl:row.pnl_usd, usdInv:row.inv_usd, position:row.position, positionMeaning:row.position_meaning || 'remaining'});
  if(base.type === 'trade' && typeof base.pnl !== 'number') base.error = 'unreadable';
  return base;
}
async function decode(file){
  const bmp = await createImageBitmap(file), c = document.createElement('canvas'); c.width = bmp.width; c.height = bmp.height;
  const x = c.getContext('2d', {willReadFrequently:true}); x.drawImage(bmp, 0, 0);
  const id = x.getImageData(0, 0, c.width, c.height);
  const k = Math.min(1, 1000 / Math.max(c.width, c.height)), t = document.createElement('canvas'); t.width = Math.round(c.width*k); t.height = Math.round(c.height*k);
  const tx = t.getContext('2d'); tx.imageSmoothingQuality = 'high'; tx.drawImage(c, 0, 0, t.width, t.height);
  return {im:{w:c.width, h:c.height, d:id.data}, thumb:t.toDataURL('image/jpeg', 0.82)};
}

/* ---------- API : PNLOCR.extract(files, onProgress) -> cartes ---------- */
let workers = null;
async function extract(files, onProgress){
  const n = Math.max(1, Math.min(3, (navigator.hardwareConcurrency || 2) - 1, files.length));
  if(!workers) workers = [];
  while(workers.length < n) workers.push(newWorker());
  const rs = (await Promise.all(workers.slice(0, n))).map(reader);
  const out = new Array(files.length); let next = 0, done = 0;
  await Promise.all(rs.map(async rd => {
    while(next < files.length){
      const i = next++, f = files[i];
      try{
        const {im, thumb} = await decode(f);
        const row = await rd.readAny(im); row.file = f.name;
        const card = toCard(row, f.lastModified); card.img = thumb; out[i] = card;
      }catch(e){
        out[i] = {id:rid(), file:f.name, type:'trade', currency:'SOL', flags:['low_confidence'], error:'error', detail:String(e && e.message || e).slice(0, 200), dateMs:f.lastModified, token:null, pnl:null, edited:false};
      }
      done++; if(onProgress) onProgress(done, files.length);
    }
  }));
  return out;
}
window.PNLOCR = {extract, _t:{reader, newWorker, decode, crop, brightText, smallValue, bannerDigits, ccl, resizeGray}};
})();
