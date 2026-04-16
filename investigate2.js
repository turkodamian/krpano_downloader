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

  // ======= 2. FETCH videoplayer.js via Chrome =======
  console.log('===== 2. VIDEOPLAYER.JS PLUGIN =====');
  var r = await evalJS(ws, "fetch('https://www.360cities.net/assets/krpano/plugins/videoplayer.js?v=119pr4', { credentials: 'include' }).then(function(r) { return r.text(); })");
  console.log(typeof r === 'string' ? r.substring(0, 15000) : r);

  // ======= 3. FETCH videointerface.xml =======
  console.log('\n\n===== 3. VIDEOINTERFACE.XML =====');
  r = await evalJS(ws, "fetch('https://www.360cities.net/krpano_templates/xml/skin/videointerface.xml?cache=202511', { credentials: 'include' }).then(function(r) { return r.text(); })");
  console.log(typeof r === 'string' ? r.substring(0, 15000) : r);

  // ======= FETCH video_async.js =======
  console.log('\n\n===== VIDEO_ASYNC.JS =====');
  r = await evalJS(ws, "fetch('https://www.360cities.net/assets/video_async-567bce58ffa6fffc0fe4ccecf04d0ccd8b9a0885a819ca323e87c7c6c42b4602.js', { credentials: 'include' }).then(function(r) { return r.text(); })");
  console.log(typeof r === 'string' ? r.substring(0, 20000) : r);

  // ======= Check init_360video and process_video_metadata functions =======
  console.log('\n\n===== INIT_360VIDEO FUNCTION =====');
  r = await evalJS(ws, "String(window.init_360video)");
  console.log(typeof r === 'string' ? r.substring(0, 5000) : r);

  console.log('\n\n===== PROCESS_VIDEO_METADATA FUNCTION =====');
  r = await evalJS(ws, "String(window.process_video_metadata)");
  console.log(typeof r === 'string' ? r.substring(0, 5000) : r);

  console.log('\n\n===== INITIALISE_VIDEO FUNCTION =====');
  r = await evalJS(ws, "String(window.initialiseVideo)");
  console.log(typeof r === 'string' ? r.substring(0, 5000) : r);

  console.log('\n\n===== INITIALISE_VIDEO_PAGE FUNCTION =====');
  r = await evalJS(ws, "String(window.initialiseVideoPage)");
  console.log(typeof r === 'string' ? r.substring(0, 5000) : r);

  // ======= Check the actual krpano XML config URL from page =======
  console.log('\n\n===== PAGE INLINE SCRIPT WITH XML CONFIG =====');
  r = await evalJS(ws, `(function() {
    var scripts = document.querySelectorAll('script:not([src])');
    var results = [];
    scripts.forEach(function(s, i) {
      var text = s.textContent;
      if (text.indexOf('xml') !== -1 && (text.indexOf('pano') !== -1 || text.indexOf('video') !== -1 || text.indexOf('embedpano') !== -1)) {
        results.push({ index: i, content: text.substring(0, 3000) });
      }
    });
    return JSON.stringify(results);
  })()`);
  console.log(r);

  // ======= Network: monitor while starting video playback =======
  console.log('\n\n===== NETWORK MONITORING DURING PLAYBACK =====');
  await cdpSend(ws, 'Network.enable', {});

  var networkRequests = [];
  var netListener = function(data) {
    var parsed = JSON.parse(data.toString());
    if (parsed.method === 'Network.requestWillBeSent') {
      var url = parsed.params.request.url;
      if (url.indexOf('.mp4') !== -1 || url.indexOf('.xml') !== -1 || url.indexOf('video') !== -1 || url.indexOf('krpano') !== -1) {
        networkRequests.push({
          url: url,
          method: parsed.params.request.method,
          type: parsed.params.type
        });
      }
    }
    if (parsed.method === 'Network.responseReceived') {
      var url2 = parsed.params.response.url;
      if (url2.indexOf('.mp4') !== -1 || url2.indexOf('.xml') !== -1) {
        networkRequests.push({
          responseUrl: url2,
          status: parsed.params.response.status,
          headers: parsed.params.response.headers
        });
      }
    }
  };
  ws.on('message', netListener);

  // Try to click play or start the video
  r = await evalJS(ws, `(function() {
    // Try to find and click the play button
    var playBtn = document.querySelector('.play-button, .vjs-play-control, [class*=play], #play_video, .video-play');
    if (playBtn) { playBtn.click(); return 'clicked play button: ' + playBtn.className; }

    // Try to find the splash video overlay and click it
    var splash = document.getElementById('splash_video');
    if (splash) { splash.click(); return 'clicked splash_video'; }

    // Try calling playVideo
    if (typeof window.playVideo === 'function') { window.playVideo(); return 'called playVideo()'; }

    return 'no play mechanism found';
  })()`);
  console.log('Play trigger: ' + r);

  // Wait for network activity
  await new Promise(function(r) { setTimeout(r, 5000); });

  console.log('\nCollected network requests:');
  console.log(JSON.stringify(networkRequests, null, 2));
  ws.removeListener('message', netListener);

  // ======= Check the krpano XML URL from the page source =======
  console.log('\n\n===== KRPANO XML URL FROM PAGE =====');
  r = await evalJS(ws, `(function() {
    var html = document.documentElement.outerHTML;
    var xmlMatch = html.match(/krpano_templates\\/xml\\/[^'"]+/g);
    var videoXmlMatch = html.match(/video[^'"]*\\.xml[^'"']*/g);
    var embedMatch = html.match(/embedpano\\([^)]+\\)/g);
    return JSON.stringify({ xmlMatches: xmlMatch, videoXmlMatches: videoXmlMatch, embedMatches: embedMatch ? embedMatch.map(function(m) { return m.substring(0, 500); }) : null });
  })()`);
  console.log(r);

  // ======= Try fetching the video XML config directly =======
  console.log('\n\n===== VIDEO XML CONFIG FETCH =====');
  var xmlUrls = [
    'https://www.360cities.net/krpano_templates/xml/video/andean-amazon-rainforest.xml',
    'https://www.360cities.net/krpano_video_xml/andean-amazon-rainforest',
    'https://www.360cities.net/video/andean-amazon-rainforest.xml',
    'https://www.360cities.net/krpano_templates/xml/video360.xml'
  ];
  for (var i = 0; i < xmlUrls.length; i++) {
    console.log('\n--- ' + xmlUrls[i] + ' ---');
    r = await evalJS(ws, "fetch('" + xmlUrls[i] + "', { credentials: 'include' }).then(function(r) { return r.text().then(function(t) { return JSON.stringify({status: r.status, body: t.substring(0, 2000)}); }); }).catch(function(e) { return JSON.stringify({error: e.message}); })");
    console.log(r);
  }

  // ======= Try HEAD requests to higher res video URLs =======
  console.log('\n\n===== HEAD REQUESTS TO VIDEO URLS =====');
  var videoBase = 'https://video.360cities.net/rogergiraldolovera/02069529_bosque_andino_amazonico_8k';
  var resolutions = [
    '-2048x1024.mp4',
    '-3840x1920.mp4',
    '-4096x2048.mp4',
    '-7680x3840.mp4',
    '-8192x4096.mp4',
    '.mp4',
    '-original.mp4',
    '-source.mp4'
  ];
  for (var j = 0; j < resolutions.length; j++) {
    var url = videoBase + resolutions[j];
    console.log('\n--- ' + url + ' ---');
    r = await evalJS(ws, "fetch('" + url + "', { method: 'HEAD', credentials: 'include' }).then(function(r) { return JSON.stringify({status: r.status, headers: Object.fromEntries(r.headers.entries())}); }).catch(function(e) { return JSON.stringify({error: e.message}); })");
    console.log(r);
  }

  ws.close();
}

main().catch(console.error);
