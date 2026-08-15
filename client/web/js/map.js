/* ============================================================
   Africana Tracker — Live Map (MapLibre GL)
   ============================================================ */
const AfvMap = (() => {
  let map = null;
  let ready = false;
  let acMarker = null;
  let originMarker = null;
  let destMarker = null;
  const trail = [];          // [ [lon,lat], ... ]
  let lastAc = null;         // {lat, lon}
  let followAc = true;

  const STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

  function init() {
    try {
      map = new maplibregl.Map({
        container: 'map',
        style: STYLE,
        center: [20, 5],
        zoom: 2.4,
        attributionControl: false,
        pitchWithRotate: false,
        dragRotate: false,
      });
      map.on('load', () => {
        ready = true;
        _addLayers();
        if (lastAc) _placeAircraft(lastAc.lon, lastAc.lat, lastAc.hdg);
      });
      map.on('dragstart', () => { followAc = false; });
    } catch (e) {
      console.error('Map init failed', e);
    }
  }

  function _addLayers() {
    // Great-circle route line
    map.addSource('route', { type: 'geojson', data: _empty() });
    map.addLayer({
      id: 'route-line', type: 'line', source: 'route',
      paint: {
        'line-color': '#E43350', 'line-width': 2.5, 'line-opacity': 0.55,
        'line-dasharray': [2, 1.5],
      },
    });
    // Flown trail
    map.addSource('trail', { type: 'geojson', data: _empty() });
    map.addLayer({
      id: 'trail-line', type: 'line', source: 'trail',
      paint: { 'line-color': '#FFC94D', 'line-width': 3, 'line-opacity': 0.9 },
      layout: { 'line-cap': 'round', 'line-join': 'round' },
    });
  }

  function _empty() {
    return { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} };
  }

  // Great-circle interpolation between two [lon,lat] points
  function _greatCircle(a, b, n = 96) {
    const toRad = d => d * Math.PI / 180, toDeg = r => r * 180 / Math.PI;
    const lat1 = toRad(a[1]), lon1 = toRad(a[0]), lat2 = toRad(b[1]), lon2 = toRad(b[0]);
    const d = 2 * Math.asin(Math.sqrt(
      Math.sin((lat2 - lat1) / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2));
    if (d === 0) return [a, b];
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const f = i / n;
      const A = Math.sin((1 - f) * d) / Math.sin(d);
      const B = Math.sin(f * d) / Math.sin(d);
      const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
      const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
      const z = A * Math.sin(lat1) + B * Math.sin(lat2);
      pts.push([toDeg(Math.atan2(y, x)), toDeg(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
    }
    return pts;
  }

  function _apEl(label, cls) {
    const el = document.createElement('div');
    el.className = 'map-ap ' + cls;
    el.innerHTML = `<span class="map-ap-dot"></span><span class="map-ap-lbl">${label}</span>`;
    return el;
  }

  function setRoute(origin, dest, oIcao, dIcao) {
    if (!ready) { setTimeout(() => setRoute(origin, dest, oIcao, dIcao), 400); return; }
    if (originMarker) originMarker.remove();
    if (destMarker) destMarker.remove();
    if (!origin || !dest) return;
    const o = [origin[1], origin[0]], d = [dest[1], dest[0]];  // [lon,lat]
    map.getSource('route').setData({
      type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: _greatCircle(o, d) },
    });
    originMarker = new maplibregl.Marker({ element: _apEl(oIcao, 'origin') }).setLngLat(o).addTo(map);
    destMarker = new maplibregl.Marker({ element: _apEl(dIcao, 'dest') }).setLngLat(d).addTo(map);
    followAc = true;
    const b = new maplibregl.LngLatBounds(o, o);
    b.extend(d);
    map.fitBounds(b, { padding: 80, duration: 900, maxZoom: 6 });
  }

  function _placeAircraft(lon, lat, hdg) {
    if (!acMarker) {
      const el = document.createElement('div');
      el.className = 'map-aircraft';
      el.innerHTML = `<svg viewBox="0 0 24 24" width="34" height="34"><path fill="#fff" stroke="#E43350" stroke-width="1" d="M12 2l1.5 6.5L22 13v2l-8.5-2.2L13 20l2 1.2V22l-3-1-3 1v-.8L11 20l-.5-7.2L2 15v-2l8.5-4.5L12 2z"/></svg>`;
      acMarker = new maplibregl.Marker({ element: el, rotationAlignment: 'map' }).setLngLat([lon, lat]).addTo(map);
    } else {
      acMarker.setLngLat([lon, lat]);
    }
    acMarker.setRotation(hdg || 0);
  }

  function updateAircraft(lat, lon, hdg) {
    lastAc = { lat, lon, hdg };
    if (!ready) return;
    if (!lat && !lon) return;
    _placeAircraft(lon, lat, hdg);
    trail.push([lon, lat]);
    if (trail.length > 4000) trail.shift();
    map.getSource('trail').setData({
      type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: trail },
    });
    if (followAc) map.easeTo({ center: [lon, lat], duration: 900 });
  }

  function clearTrail() {
    trail.length = 0;
    if (ready && map.getSource('trail')) map.getSource('trail').setData(_empty());
  }

  function recenter() {
    followAc = true;
    if (ready && lastAc) map.easeTo({ center: [lastAc.lon, lastAc.lat], zoom: 7, duration: 800 });
  }

  return { init, setRoute, updateAircraft, clearTrail, recenter };
})();
