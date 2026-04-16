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

  var ws = new WebSocket(pt.webSocketDebuggerUrl);
  await new Promise(function(r) { ws.on('open', r); });

  // ======= FULL VIDEO XML CONFIG =======
  console.log('===== FULL VIDEO XML CONFIG =====');
  var r = await evalJS(ws, "fetch('https://www.360cities.net/video/andean-amazon-rainforest.xml', { credentials: 'include' }).then(function(r) { return r.text(); })");
  console.log(r);

  // ======= FULL VIDEOINTERFACE.XML =======
  console.log('\n\n===== FULL VIDEOINTERFACE.XML =====');
  r = await evalJS(ws, "fetch('https://www.360cities.net/krpano_templates/xml/skin/videointerface.xml?cache=202511', { credentials: 'include' }).then(function(r) { return r.text(); })");
  console.log(r);

  // ======= VIDEO_ASYNC.JS (first 20k chars) =======
  console.log('\n\n===== VIDEO_ASYNC.JS =====');
  r = await evalJS(ws, "fetch('https://www.360cities.net/assets/video_async-567bce58ffa6fffc0fe4ccecf04d0ccd8b9a0885a819ca323e87c7c6c42b4602.js', { credentials: 'include' }).then(function(r) { return r.text().then(function(t) { return t.substring(0, 30000); }); })");
  console.log(r);

  // ======= Check krpanoObject methods and XML content =======
  console.log('\n\n===== KRPANO OBJECT DEEP INSPECT =====');
  r = await evalJS(ws, `(function() {
    var pano = document.getElementById('krpanoObject');
    if (!pano) return 'krpanoObject not found by ID';
    var result = {};
    result.tag = pano.tagName;
    result.hasGet = typeof pano.get === 'function';
    result.hasCall = typeof pano.call === 'function';

    if (result.hasGet) {
      result.xmlContent = pano.get('xml.content');
      result.xmlUrl = pano.get('xml.url');

      // Get video plugin info
      var videoProps = ['video.url', 'video.videourl', 'video.source', 'video.posterurl',
                        'plugin[video].url', 'plugin[video].videourl', 'plugin[video].source'];
      result.videoProps = {};
      videoProps.forEach(function(p) {
        try { result.videoProps[p] = String(pano.get(p)); } catch(e) { result.videoProps[p] = 'ERR'; }
      });

      // Check action add_video_sources
      try { result.addVideoSources = String(pano.get('action[add_video_sources].content')); } catch(e) { result.addVideoSources = 'ERR: ' + e.message; }
      try { result.videointerface_play = String(pano.get('action[videointerface_play].content')); } catch(e) { result.videointerface_play = 'ERR: ' + e.message; }
      try { result.videointerface_selectquality = String(pano.get('action[videointerface_selectquality].content')); } catch(e) { result.videointerface_selectquality = 'ERR: ' + e.message; }
    }
    return JSON.stringify(result);
  })()`);
  console.log(r);

  // ======= Search application JS for video URL patterns =======
  console.log('\n\n===== APPLICATION JS VIDEO PATTERNS =====');
  r = await evalJS(ws, "fetch('https://www.360cities.net/assets/application-49bfb7fb474e43e5ed7cefa96a72b36d04619f283136cb63af45aba9861cacd6.js', { credentials: 'include' }).then(function(r) { return r.text().then(function(t) { var results = []; var keywords = ['video.360cities', '4096', '3840', '7680', '8192', 'video_sources', 'add_video_sources', 'videointerface', 'quality', 'resolution', 'download', 'original', 'high_res']; keywords.forEach(function(kw) { var idx = t.indexOf(kw); while(idx !== -1 && results.length < 30) { results.push({keyword: kw, pos: idx, context: t.substring(Math.max(0,idx-100), idx+200)}); idx = t.indexOf(kw, idx + 1); } }); return JSON.stringify(results); }); })");
  console.log(r);

  // ======= HEAD requests via XHR (no-cors mode won't work, try with credentials) =======
  console.log('\n\n===== VIDEO URL HEAD REQUESTS VIA CORS PROXY =====');
  // Instead of fetch, use a new approach - navigate CDP to the URL directly
  var videoUrls = [
    'https://video.360cities.net/rogergiraldolovera/02069529_bosque_andino_amazonico_8k-2048x1024.mp4',
    'https://video.360cities.net/rogergiraldolovera/02069529_bosque_andino_amazonico_8k-4096x2048.mp4',
    'https://video.360cities.net/rogergiraldolovera/02069529_bosque_andino_amazonico_8k-3840x1920.mp4'
  ];

  for (var i = 0; i < videoUrls.length; i++) {
    console.log('\n--- HEAD: ' + videoUrls[i] + ' ---');
    // Use CDP Network.enable + Page.navigate approach
    var headResult = await cdpSend(ws, 'Runtime.evaluate', {
      expression: "new Promise(function(resolve) { var xhr = new XMLHttpRequest(); xhr.open('HEAD', '" + videoUrls[i] + "', true); xhr.withCredentials = true; xhr.onload = function() { resolve(JSON.stringify({status: xhr.status, headers: xhr.getAllResponseHeaders(), contentLength: xhr.getResponseHeader('content-length'), contentType: xhr.getResponseHeader('content-type')})); }; xhr.onerror = function() { resolve(JSON.stringify({error: 'XHR error', status: xhr.status})); }; xhr.send(); })",
      awaitPromise: true
    });
    console.log(headResult.result?.value || JSON.stringify(headResult.result));
  }

  // ======= Check if there are any other video pages with higher res XML =======
  console.log('\n\n===== CHECK ANOTHER VIDEO FOR COMPARISON =====');
  r = await evalJS(ws, "fetch('https://www.360cities.net/video/berlin-wall.xml', { credentials: 'include' }).then(function(r) { return r.text().then(function(t) { return JSON.stringify({status: r.status, body: t.substring(0, 3000)}); }); }).catch(function(e) { return JSON.stringify({error: e.message}); })");
  console.log(r);

  ws.close();
}

main().catch(console.error);
