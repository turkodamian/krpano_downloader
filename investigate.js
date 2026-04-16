const WebSocket = require('ws');
const http = require('http');

let cmdId = 1;
function cdpSend(ws, method, params) {
  params = params || {};
  return new Promise(function(resolve, reject) {
    var id = cmdId++;
    ws.send(JSON.stringify({ id: id, method: method, params: params }));
    var handler = function(data) {
      var parsed = JSON.parse(data.toString());
      if (parsed.id === id) {
        ws.removeListener('message', handler);
        resolve(parsed);
      }
    };
    ws.on('message', handler);
    setTimeout(function() { ws.removeListener('message', handler); reject(new Error('timeout ' + method)); }, 30000);
  });
}

function evalJS(ws, code) {
  return cdpSend(ws, 'Runtime.evaluate', { expression: code, awaitPromise: true, returnByValue: true })
    .then(function(r) { return r.result && r.result.value != null ? r.result.value : (r.result && r.result.description ? r.result.description : JSON.stringify(r)); });
}

function getTargets() {
  return new Promise(function(resolve, reject) {
    http.get('http://localhost:9222/json', function(res) {
      var d = '';
      res.on('data', function(c) { d += c; });
      res.on('end', function() { resolve(JSON.parse(d)); });
    }).on('error', reject);
  });
}

async function main() {
  var targets = await getTargets();
  var pt = targets.find(function(t) { return t.type === 'page' && t.url.indexOf('360cities') !== -1; });
  if (!pt) { console.log('No target found'); return; }
  console.log('Connected to: ' + pt.url);

  var ws = new WebSocket(pt.webSocketDebuggerUrl);
  await new Promise(function(r) { ws.on('open', r); });

  // Enable network
  await cdpSend(ws, 'Network.enable', {});

  // ======= 5. PAGE SOURCE ANALYSIS =======
  console.log('\n===== 5. PAGE SOURCE ANALYSIS =====');
  var code = `(function() {
    var results = {};
    results.initialState = typeof window.__INITIAL_STATE__ !== 'undefined' ? JSON.stringify(window.__INITIAL_STATE__).substring(0, 2000) : 'NOT FOUND';
    results.nextData = typeof window.__NEXT_DATA__ !== 'undefined' ? 'FOUND' : 'NOT FOUND';
    var videoVars = {};
    Object.keys(window).forEach(function(key) {
      var kl = key.toLowerCase();
      if (kl.indexOf('video') !== -1 || kl.indexOf('krpano') !== -1 || kl.indexOf('pano') !== -1 || kl.indexOf('config') !== -1) {
        try {
          var val = window[key];
          if (typeof val === 'object' && val !== null) videoVars[key] = JSON.stringify(val).substring(0, 500);
          else if (typeof val !== 'function') videoVars[key] = String(val);
          else videoVars[key] = '[function]';
        } catch(e) { videoVars[key] = '[error]'; }
      }
    });
    results.videoVars = videoVars;
    var containers = document.querySelectorAll('[data-video],[data-src],[data-url],[data-config],#pano,#krpano,.krpano,[id*=pano],[id*=video]');
    results.containers = Array.from(containers).map(function(el) {
      return { tag: el.tagName, id: el.id, className: el.className, dataset: JSON.stringify(el.dataset), attrs: Array.from(el.attributes).map(function(a) { return a.name + '=' + a.value.substring(0, 200); }) };
    });
    var scripts = document.querySelectorAll('script:not([src])');
    var keywords = ['video.360cities', 'original', 'download', '4096', '3840', 'full_res', 'high_quality', 'mp4', 'source_video', 'hd_video'];
    results.scriptMatches = [];
    scripts.forEach(function(s, i) {
      var text = s.textContent;
      keywords.forEach(function(kw) {
        var idx = text.indexOf(kw);
        if (idx !== -1) results.scriptMatches.push({ script: i, keyword: kw, context: text.substring(Math.max(0,idx-100), idx+200) });
      });
    });
    results.scriptSrcs = Array.from(document.querySelectorAll('script[src]')).map(function(s) { return s.src; });
    return JSON.stringify(results);
  })()`;
  var r = await evalJS(ws, code);
  console.log(r);

  // ======= KRPANO OBJECT INSPECTION =======
  console.log('\n===== KRPANO OBJECT INSPECTION =====');
  code = `(function() {
    var pano = document.getElementById('krpanoSWFObject');
    if (!pano) return 'krpanoSWFObject not found';
    var results = { id: pano.id, tag: pano.tagName };
    results.hasGet = typeof pano.get === 'function';
    results.hasCall = typeof pano.call === 'function';
    results.hasSet = typeof pano.set === 'function';
    if (results.hasGet) {
      var keys = ['xml.url','xml.content','plugin[video].url','plugin[video].source','plugin[video].videourl','plugin[video].posterurl','image.type','image.hfov','image.vfov'];
      results.values = {};
      keys.forEach(function(k) {
        try { var v = pano.get(k); results.values[k] = typeof v === 'string' ? v.substring(0, 2000) : String(v); }
        catch(e) { results.values[k] = 'ERR:' + e.message; }
      });
    }
    return JSON.stringify(results);
  })()`;
  r = await evalJS(ws, code);
  console.log(r);

  // ======= 6. VIDEO ELEMENTS =======
  console.log('\n===== 6. VIDEO ELEMENTS =====');
  code = `(function() {
    var videos = document.querySelectorAll('video');
    var results = Array.from(videos).map(function(v) {
      return { src: v.src, currentSrc: v.currentSrc, videoWidth: v.videoWidth, videoHeight: v.videoHeight, readyState: v.readyState };
    });
    return JSON.stringify({ count: videos.length, videos: results });
  })()`;
  r = await evalJS(ws, code);
  console.log(r);

  // ======= XML CONFIG =======
  console.log('\n===== XML CONFIG =====');
  code = `(function() {
    var pano = document.getElementById('krpanoSWFObject');
    if (pano && typeof pano.get === 'function') {
      try { return pano.get('xml.content'); } catch(e) { return 'ERR:' + e.message; }
    }
    return 'no krpano';
  })()`;
  r = await evalJS(ws, code);
  if (typeof r === 'string') console.log(r.substring(0, 5000));
  else console.log(r);

  // ======= 4. API ENDPOINT CHECKS =======
  console.log('\n===== 4. API ENDPOINT CHECKS =====');
  var endpoints = [
    '/api/v1/video/andean-amazon-rainforest',
    '/api/video/andean-amazon-rainforest',
    '/api/v1/videos/andean-amazon-rainforest',
    '/videos/andean-amazon-rainforest.json',
    '/video/andean-amazon-rainforest.json',
    '/panorama/andean-amazon-rainforest.json',
    '/api/panorama/andean-amazon-rainforest',
    '/api/v1/panorama/andean-amazon-rainforest'
  ];
  for (var i = 0; i < endpoints.length; i++) {
    var ep = endpoints[i];
    console.log('\n--- ' + ep + ' ---');
    code = "fetch('https://www.360cities.net" + ep + "', { credentials: 'include' }).then(function(r) { return r.text().then(function(t) { return JSON.stringify({status: r.status, statusText: r.statusText, body: t.substring(0, 3000)}); }); }).catch(function(e) { return JSON.stringify({error: e.message}); })";
    r = await evalJS(ws, code);
    console.log(r);
  }

  // ======= 9. EMBED ENDPOINTS =======
  console.log('\n===== 9. EMBED ENDPOINTS =====');
  var embedUrls = [
    'https://www.360cities.net/video/andean-amazon-rainforest/embed',
    'https://www.360cities.net/embed/andean-amazon-rainforest'
  ];
  for (var j = 0; j < embedUrls.length; j++) {
    console.log('\n--- ' + embedUrls[j] + ' ---');
    code = "fetch('" + embedUrls[j] + "', { credentials: 'include' }).then(function(r) { return r.text().then(function(t) { return JSON.stringify({status: r.status, url: r.url, bodyLen: t.length, snippet: t.substring(0, 1500)}); }); }).catch(function(e) { return JSON.stringify({error: e.message}); })";
    r = await evalJS(ws, code);
    console.log(r);
  }

  // ======= COOKIES =======
  console.log('\n===== COOKIES =====');
  var cookieResult = await cdpSend(ws, 'Network.getCookies', { urls: ['https://www.360cities.net', 'https://video.360cities.net'] });
  var cookies = (cookieResult.result && cookieResult.result.cookies) || [];
  console.log(JSON.stringify(cookies.map(function(c) { return { name: c.name, domain: c.domain, value: c.value.substring(0, 80) }; }), null, 2));

  // ======= 7. S3 BUCKET PROBING =======
  console.log('\n===== 7. S3 BUCKET PROBING =====');
  var s3Urls = [
    'https://video-360cities-net.s3.amazonaws.com/',
    'https://s3.amazonaws.com/video.360cities.net/',
    'https://video.360cities.net.s3.amazonaws.com/',
    'https://video.360cities.net/robots.txt'
  ];
  for (var k = 0; k < s3Urls.length; k++) {
    console.log('\n--- ' + s3Urls[k] + ' ---');
    code = "fetch('" + s3Urls[k] + "').then(function(r) { return r.text().then(function(t) { return JSON.stringify({status: r.status, body: t.substring(0, 500)}); }); }).catch(function(e) { return JSON.stringify({error: e.message}); })";
    r = await evalJS(ws, code);
    console.log(r);
  }

  ws.close();
}

main().catch(console.error);
