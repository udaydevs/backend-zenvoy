# Zenvoy — Complete Project Context
> This document is the single source of truth for delegating work to an AI agent.
> Read every section before touching any code.

---

## What this project is

Zenvoy is a safety-first navigation web app built for a 48-hour hackathon (Stellaris 2026) at KIET Group of Institutions. Team: Build-Bros (Aniket Singh, Aadi Jain, Uday Pratap Singh).

The core idea: Google Maps routes you fastest. Zenvoy routes you **safest**. It calculates a "Safety Score" for every street segment in Delhi using crime data and AI-detected lighting, then runs a weighted pathfinding algorithm to find the lowest-risk route. It also has a one-click SOS button that sends a real SMS with live GPS coordinates to an emergency contact.

---

## Three repos, three concerns

| Repo | Tech | Status |
|---|---|---|
| `zenvoy-web` | React + Vite + Mapbox GL JS | **Built — see full code below** |
| `zenvoy-backend` | Python + FastAPI + NetworkX + MongoDB | Not built yet |
| `zenvoy-mobile` | React Native + Expo | Not built yet |

This document covers the web repo in full. Backend and mobile are described architecturally so you can build or debug them.

---

## Service map — what each external service does

| Service | Used for | Where |
|---|---|---|
| **Mapbox GL JS** | Renders the dark map tiles the user sees | `zenvoy-web` frontend only |
| **Mapbox Geocoding API** | Turns text ("Hauz Khas Metro") into lat/lng | `zenvoy-web` SearchBar component |
| **Mapillary API v4** | Downloads street-level photos for preprocessing | `zenvoy-backend/scripts/preprocess.py` only. Never called at runtime. |
| **YOLOv8 (Ultralytics)** | Detects streetlights in Mapillary photos → `light_score` | `zenvoy-backend/scripts/preprocess.py` only. Never called at runtime. |
| **MongoDB Atlas** | Stores crime incidents (geospatial) and pre-cached edge safety scores | `zenvoy-backend` reads at runtime |
| **OSMnx + OpenStreetMap** | Downloads Delhi walk graph as GraphML file | One-time script, result stored as `delhi_walk.graphml` |
| **NetworkX** | Runs Dijkstra pathfinding on the graph with custom safety weights | `zenvoy-backend` at runtime |
| **Twilio** | Sends real SMS for SOS feature | `zenvoy-backend/app/sos.py` |
| **ngrok** | Exposes local FastAPI server to web/mobile frontends | Dev only |

**Critical distinction:** Mapillary and YOLOv8 are PREPROCESSING tools only. They run once before the demo to populate MongoDB. They are never called when a user requests a route. The routing engine reads pre-cached scores from MongoDB.

---

## How routing actually works (the core algorithm)

```
User sets origin + destination (lat/lng)
        ↓
Frontend calls GET /route/safe and GET /route/fast simultaneously
        ↓
Backend loads delhi_walk.graphml into memory (done once at startup)
        ↓
For each edge in the graph, safety_cost is pre-computed as:
  safety_cost = length × (1 + crime_penalty + darkness_penalty)

  crime_penalty  = count of crimes within 50m of edge midpoint,
                   normalized 0–1, multiplied by severity weight
                   (queried from MongoDB using $nearSphere geospatial index)

  darkness_penalty = 1 - light_score
                   (light_score is pre-cached in MongoDB from YOLOv8 output,
                    default 0.5 for edges not in demo routes)
        ↓
NetworkX runs Dijkstra twice:
  Fast route:  networkx.shortest_path(G, source, target, weight='length')
  Safe route:  networkx.shortest_path(G, source, target, weight='safety_cost')
        ↓
Backend returns two lists of [lat, lng] coordinates + score_breakdown object
        ↓
Frontend draws both as polylines on Mapbox map
  Safe route = green solid line
  Fast route = red dashed line
```

Mapbox has no involvement in routing. It only draws the lines.

---

## API contract (backend must implement exactly this)

All endpoints served from `http://localhost:8000`, exposed via ngrok at demo time.

### GET /route/safe
```
Query params: slat, slng, elat, elng (all floats)
Response:
{
  "coordinates": [[lat, lng], [lat, lng], ...],
  "score_breakdown": {
    "lighting_pct": 88,
    "crime_count": 0,
    "crime_severity": "Low",
    "overall_score": 8.6,
    "est_minutes": 13,
    "callouts": ["Passes 2 well-lit main roads", "CCTV detected at 3 intersections"]
  }
}
```

### GET /route/fast
```
Query params: slat, slng, elat, elng (all floats)
Response: same shape as /route/safe
```

### POST /sos
```
Body: { "lat": float, "lng": float, "user_name": string, "contact_number": string }
Response: { "status": "sent", "message": "Alert dispatched" }
```

**CORS:** Backend must allow all origins (`*`) — web and mobile both call it.

**Coordinate format:** Backend returns `[lat, lng]`. Mapbox GL JS requires `[lng, lat]`. The conversion happens in `MapView.jsx` in `coordsToGeoJSON()`. Do not change this.

---

## MongoDB schema

### Collection: `crime_incidents`
```json
{
  "_id": "ObjectId",
  "location": {
    "type": "Point",
    "coordinates": [77.2090, 28.6139]
  },
  "severity": 3,
  "type": "snatch",
  "date": "2024-11-15"
}
```
Index: `{ "location": "2dsphere" }` — must exist for geospatial queries to work.

### Collection: `edge_safety_scores`
```json
{
  "_id": "ObjectId",
  "edge_id": "123456789_987654321",
  "light_score": 0.82,
  "darkness_penalty": 0.18
}
```
`edge_id` format: `{osm_node_u}_{osm_node_v}` — matches the NetworkX graph edge keys from OSMnx.

---

## zenvoy-web — complete file listing

```
zenvoy-web/
├── index.html
├── vite.config.js
├── package.json
├── .env.example
├── .gitignore
├── README.md
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── api.js
    ├── index.css
    └── components/
        ├── MapView.jsx
        ├── SearchBar.jsx
        ├── SafetyPanel.jsx
        └── SOSButton.jsx
```

---

## zenvoy-web — complete source code

### package.json
```json
{
  "name": "zenvoy-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "mapbox-gl": "^3.3.0",
    "@mapbox/mapbox-gl-geocoder": "^5.0.2"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.1",
    "vite": "^5.2.0"
  }
}
```

### vite.config.js
```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

### index.html
```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Zenvoy — Safety-First Navigation</title>
    <link href="https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css" rel="stylesheet" />
    <link rel="stylesheet" href="https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-geocoder/v5.0.0/mapbox-gl-geocoder.css" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

### .env.example
```
VITE_MAPBOX_TOKEN=pk.eyJ1IjoieW91ci11c2VybmFtZSIsImEiOiJ5b3VyLXRva2VuIn0.xxxxxxxx
VITE_API_URL=http://localhost:8000
```

### src/main.jsx
```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

### src/index.css
```css
/* ── Design Tokens ───────────────────────────────────── */
:root {
  --bg-base:        #080d14;
  --bg-surface:     #0e1521;
  --bg-raised:      #141e2e;
  --bg-overlay:     #1a2540;

  --accent-safe:    #00e5a0;
  --accent-safe-dim:#00a370;
  --accent-danger:  #ff4444;
  --accent-warn:    #f5a623;
  --accent-blue:    #3d8ef0;

  --text-primary:   #e8edf5;
  --text-secondary: #8a97b0;
  --text-muted:     #4a5568;
  --text-mono:      #00e5a0;

  --border:         rgba(255,255,255,0.07);
  --border-bright:  rgba(255,255,255,0.14);

  --font-display:   'Syne', sans-serif;
  --font-body:      'DM Sans', sans-serif;
  --font-mono:      'JetBrains Mono', monospace;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;

  --shadow-panel: 0 8px 40px rgba(0,0,0,0.6), 0 1px 0 rgba(255,255,255,0.05);
  --shadow-btn:   0 4px 20px rgba(0,229,160,0.25);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, #root {
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
}

::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--bg-overlay); border-radius: 2px; }

.mapboxgl-ctrl-bottom-left,
.mapboxgl-ctrl-bottom-right { display: none; }
.mapboxgl-ctrl-top-right { top: 12px; right: 12px; }

.mapboxgl-ctrl-geocoder {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border-bright) !important;
  border-radius: var(--radius-md) !important;
  box-shadow: var(--shadow-panel) !important;
  color: var(--text-primary) !important;
  font-family: var(--font-body) !important;
  min-width: 280px !important;
}
.mapboxgl-ctrl-geocoder input {
  color: var(--text-primary) !important;
  background: transparent !important;
  font-family: var(--font-body) !important;
  font-size: 14px !important;
}
.mapboxgl-ctrl-geocoder input::placeholder { color: var(--text-muted) !important; }
.mapboxgl-ctrl-geocoder .suggestions {
  background: var(--bg-raised) !important;
  border: 1px solid var(--border-bright) !important;
  border-radius: var(--radius-md) !important;
}
.mapboxgl-ctrl-geocoder .suggestions > li > a {
  color: var(--text-primary) !important;
  font-family: var(--font-body) !important;
}
.mapboxgl-ctrl-geocoder .suggestions > .active > a,
.mapboxgl-ctrl-geocoder .suggestions > li > a:hover {
  background: var(--bg-overlay) !important;
  color: var(--text-primary) !important;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes pulse-ring {
  0%   { transform: scale(1);   opacity: 0.8; }
  100% { transform: scale(2.2); opacity: 0; }
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
```

### src/api.js
```js
// FLIP THIS TO false WHEN BACKEND IS READY
// Then set VITE_API_URL in your .env to the ngrok URL
const USE_MOCK = true;

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const MOCK_SAFE_ROUTE = {
  coordinates: [
    [28.5433, 77.2066],
    [28.5441, 77.2058],
    [28.5449, 77.2049],
    [28.5456, 77.2039],
    [28.5463, 77.2029],
    [28.5470, 77.2018],
    [28.5478, 77.2008],
  ],
  score_breakdown: {
    lighting_pct: 88,
    crime_count: 0,
    crime_severity: 'Low',
    overall_score: 8.6,
    est_minutes: 13,
    callouts: [
      'Passes 2 well-lit main roads',
      'CCTV detected at 3 intersections',
    ],
  },
};

export const MOCK_FAST_ROUTE = {
  coordinates: [
    [28.5433, 77.2066],
    [28.5438, 77.2075],
    [28.5444, 77.2083],
    [28.5455, 77.2072],
    [28.5463, 77.2058],
    [28.5470, 77.2040],
    [28.5478, 77.2008],
  ],
  score_breakdown: {
    lighting_pct: 20,
    crime_count: 4,
    crime_severity: 'High',
    overall_score: 2.8,
    est_minutes: 9,
    callouts: [
      'Dark alley detected by AI vision',
      '3 snatch incidents reported nearby',
    ],
  },
};

export async function getSafeRoute(slat, slng, elat, elng) {
  if (USE_MOCK) { await delay(600); return MOCK_SAFE_ROUTE; }
  const res = await fetch(`${BASE}/route/safe?slat=${slat}&slng=${slng}&elat=${elat}&elng=${elng}`);
  if (!res.ok) throw new Error('Safe route fetch failed');
  return res.json();
}

export async function getFastRoute(slat, slng, elat, elng) {
  if (USE_MOCK) { await delay(600); return MOCK_FAST_ROUTE; }
  const res = await fetch(`${BASE}/route/fast?slat=${slat}&slng=${slng}&elat=${elat}&elng=${elng}`);
  if (!res.ok) throw new Error('Fast route fetch failed');
  return res.json();
}

export async function sendSOS(lat, lng, userName, contactNumber) {
  if (USE_MOCK) { await delay(800); return { status: 'sent', message: 'Alert dispatched (mock)' }; }
  const res = await fetch(`${BASE}/sos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lng, user_name: userName, contact_number: contactNumber }),
  });
  if (!res.ok) throw new Error('SOS send failed');
  return res.json();
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
```

### src/App.jsx
```jsx
import { useState, useCallback } from 'react'
import MapView from './components/MapView'
import SearchBar from './components/SearchBar'
import SafetyPanel from './components/SafetyPanel'
import SOSButton from './components/SOSButton'
import { getSafeRoute, getFastRoute } from './api'

export default function App() {
  const [origin, setOrigin]           = useState(null)  // { label, lat, lng }
  const [destination, setDestination] = useState(null)
  const [safeRoute, setSafeRoute]     = useState(null)
  const [fastRoute, setFastRoute]     = useState(null)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [panelOpen, setPanelOpen]     = useState(false)

  const fetchRoutes = useCallback(async (orig, dest) => {
    setLoading(true)
    setError(null)
    setSafeRoute(null)
    setFastRoute(null)
    setPanelOpen(false)
    try {
      const [safe, fast] = await Promise.all([
        getSafeRoute(orig.lat, orig.lng, dest.lat, dest.lng),
        getFastRoute(orig.lat, orig.lng, dest.lat, dest.lng),
      ])
      setSafeRoute(safe)
      setFastRoute(fast)
      setPanelOpen(true)
    } catch (err) {
      setError('Could not fetch routes. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleOriginSelect = useCallback((place) => {
    setOrigin(place)
    if (destination) fetchRoutes(place, destination)
  }, [destination, fetchRoutes])

  const handleDestinationSelect = useCallback((place) => {
    setDestination(place)
    if (origin) fetchRoutes(origin, place)
  }, [origin, fetchRoutes])

  const handleReset = useCallback(() => {
    setOrigin(null); setDestination(null)
    setSafeRoute(null); setFastRoute(null)
    setPanelOpen(false); setError(null)
  }, [])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <MapView safeRoute={safeRoute} fastRoute={fastRoute} origin={origin} destination={destination} />
      <SearchBar
        onOriginSelect={handleOriginSelect}
        onDestinationSelect={handleDestinationSelect}
        origin={origin} destination={destination}
        loading={loading} onReset={handleReset}
      />
      {error && (
        <div style={{
          position: 'absolute', top: '90px', left: '50%', transform: 'translateX(-50%)',
          background: 'rgba(255,68,68,0.15)', border: '1px solid rgba(255,68,68,0.4)',
          borderRadius: 'var(--radius-md)', padding: '10px 20px', color: '#ff8888',
          fontFamily: 'var(--font-body)', fontSize: '13px', zIndex: 20, animation: 'fadeUp 0.3s ease',
        }}>
          {error}
        </div>
      )}
      {loading && (
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)', display: 'flex',
          flexDirection: 'column', alignItems: 'center', gap: '12px', zIndex: 20,
        }}>
          <div style={{
            width: '36px', height: '36px', border: '2px solid var(--border)',
            borderTopColor: 'var(--accent-safe)', borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
          }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-secondary)', letterSpacing: '0.1em' }}>
            COMPUTING SAFETY MESH...
          </span>
        </div>
      )}
      {safeRoute && fastRoute && (
        <SafetyPanel
          safeRoute={safeRoute} fastRoute={fastRoute}
          open={panelOpen} onToggle={() => setPanelOpen(v => !v)}
        />
      )}
      <SOSButton />
    </div>
  )
}
```

### src/components/MapView.jsx
```jsx
import { useEffect, useRef } from 'react'
import mapboxgl from 'mapbox-gl'

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN

const DELHI_CENTER = [77.2090, 28.6139]
const DELHI_ZOOM   = 12

export default function MapView({ safeRoute, fastRoute, origin, destination }) {
  const containerRef = useRef(null)
  const mapRef       = useRef(null)
  const markersRef   = useRef([])

  useEffect(() => {
    if (mapRef.current) return
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: DELHI_CENTER,
      zoom: DELHI_ZOOM,
      attributionControl: false,
    })
    map.on('load', () => {
      map.addSource('fast-route', { type: 'geojson', data: emptyGeoJSON() })
      map.addLayer({
        id: 'fast-route-line', type: 'line', source: 'fast-route',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#ff4444', 'line-width': 3, 'line-opacity': 0.7, 'line-dasharray': [2, 2] },
      })
      map.addSource('safe-route', { type: 'geojson', data: emptyGeoJSON() })
      map.addLayer({
        id: 'safe-route-glow', type: 'line', source: 'safe-route',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#00e5a0', 'line-width': 8, 'line-opacity': 0.15, 'line-blur': 4 },
      })
      map.addLayer({
        id: 'safe-route-line', type: 'line', source: 'safe-route',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#00e5a0', 'line-width': 3.5, 'line-opacity': 0.95 },
      })
    })
    mapRef.current = map
    return () => map.remove()
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    if (safeRoute?.coordinates) {
      map.getSource('safe-route')?.setData(coordsToGeoJSON(safeRoute.coordinates))
    } else {
      map.getSource('safe-route')?.setData(emptyGeoJSON())
    }
    if (fastRoute?.coordinates) {
      map.getSource('fast-route')?.setData(coordsToGeoJSON(fastRoute.coordinates))
    } else {
      map.getSource('fast-route')?.setData(emptyGeoJSON())
    }
    if (safeRoute?.coordinates?.length) {
      const allCoords = [...(safeRoute.coordinates || []), ...(fastRoute?.coordinates || [])]
      const bounds = allCoords.reduce(
        (b, [lat, lng]) => b.extend([lng, lat]),
        new mapboxgl.LngLatBounds([allCoords[0][1], allCoords[0][0]], [allCoords[0][1], allCoords[0][0]])
      )
      map.fitBounds(bounds, { padding: { top: 120, bottom: 320, left: 60, right: 60 } })
    }
  }, [safeRoute, fastRoute])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    markersRef.current.forEach(m => m.remove())
    markersRef.current = []
    if (origin) {
      const m = new mapboxgl.Marker({ element: createMarkerEl('O', '#3d8ef0') })
        .setLngLat([origin.lng, origin.lat]).addTo(map)
      markersRef.current.push(m)
    }
    if (destination) {
      const m = new mapboxgl.Marker({ element: createMarkerEl('D', '#00e5a0') })
        .setLngLat([destination.lng, destination.lat]).addTo(map)
      markersRef.current.push(m)
    }
  }, [origin, destination])

  return <div ref={containerRef} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} />
}

function emptyGeoJSON() { return { type: 'FeatureCollection', features: [] } }

// Backend returns [lat, lng]. Mapbox needs [lng, lat]. Conversion here.
function coordsToGeoJSON(coords) {
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'LineString', coordinates: coords.map(([lat, lng]) => [lng, lat]) } }],
  }
}

function createMarkerEl(label, color) {
  const el = document.createElement('div')
  el.style.cssText = `width:32px;height:32px;background:${color};border-radius:50% 50% 50% 0;transform:rotate(-45deg);border:2px solid rgba(255,255,255,0.3);display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.5);cursor:default;`
  const inner = document.createElement('span')
  inner.textContent = label
  inner.style.cssText = `transform:rotate(45deg);font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:500;color:#080d14;`
  el.appendChild(inner)
  return el
}
```

### src/components/SearchBar.jsx
```jsx
import { useEffect, useRef, useState } from 'react'
import MapboxGeocoder from '@mapbox/mapbox-gl-geocoder'
import mapboxgl from 'mapbox-gl'

const DELHI_BBOX = [76.84, 28.40, 77.35, 28.88]

export default function SearchBar({ onOriginSelect, onDestinationSelect, origin, destination, loading, onReset }) {
  const originRef    = useRef(null)
  const destRef      = useRef(null)
  const originGeoRef = useRef(null)
  const destGeoRef   = useRef(null)

  useEffect(() => {
    if (originGeoRef.current) return
    const geo = new MapboxGeocoder({
      accessToken: import.meta.env.VITE_MAPBOX_TOKEN, mapboxgl,
      bbox: DELHI_BBOX, placeholder: 'Starting point...', countries: 'in', marker: false,
    })
    geo.addTo(originRef.current)
    geo.on('result', (e) => {
      const [lng, lat] = e.result.center
      onOriginSelect({ label: e.result.place_name, lat, lng })
    })
    originGeoRef.current = geo
  }, [])

  useEffect(() => {
    if (destGeoRef.current) return
    const geo = new MapboxGeocoder({
      accessToken: import.meta.env.VITE_MAPBOX_TOKEN, mapboxgl,
      bbox: DELHI_BBOX, placeholder: 'Where to?', countries: 'in', marker: false,
    })
    geo.addTo(destRef.current)
    geo.on('result', (e) => {
      const [lng, lat] = e.result.center
      onDestinationSelect({ label: e.result.place_name, lat, lng })
    })
    destGeoRef.current = geo
  }, [])

  return (
    <div style={{ position: 'absolute', top: '16px', left: '16px', zIndex: 10, display: 'flex', flexDirection: 'column', gap: '8px', width: '340px', animation: 'fadeUp 0.4s ease' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
        <div style={{ width: '28px', height: '28px', background: 'linear-gradient(135deg, #00e5a0, #3d8ef0)', borderRadius: '7px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 1L13 7L7 13L1 7L7 1Z" stroke="white" strokeWidth="1.5" fill="none"/>
            <circle cx="7" cy="7" r="2" fill="white"/>
          </svg>
        </div>
        <span style={{ fontFamily: 'var(--font-display)', fontSize: '18px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
          ZEN<span style={{ color: 'var(--accent-safe)' }}>VOY</span>
        </span>
      </div>
      <div style={{ position: 'relative' }}>
        <div style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', width: '8px', height: '8px', borderRadius: '50%', background: origin ? '#3d8ef0' : 'var(--text-muted)', zIndex: 1, pointerEvents: 'none', transition: 'background 0.3s' }} />
        <div ref={originRef} className="geocoder-wrapper" />
      </div>
      <div style={{ width: '1px', height: '8px', background: 'var(--border-bright)', marginLeft: '15px' }} />
      <div style={{ position: 'relative' }}>
        <div style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', width: '8px', height: '8px', borderRadius: '2px', background: destination ? 'var(--accent-safe)' : 'var(--text-muted)', zIndex: 1, pointerEvents: 'none', transition: 'background 0.3s' }} />
        <div ref={destRef} className="geocoder-wrapper" />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '4px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', letterSpacing: '0.08em' }}>
          {!origin && !destination && 'SET ORIGIN TO START'}
          {origin && !destination && 'NOW SET DESTINATION'}
          {origin && destination && !loading && 'ROUTES COMPUTED'}
          {loading && 'COMPUTING...'}
        </span>
        {(origin || destination) && (
          <button onClick={onReset} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer', letterSpacing: '0.08em', padding: '2px 6px', borderRadius: '4px' }}>
            CLEAR ×
          </button>
        )}
      </div>
    </div>
  )
}
```

### src/components/SafetyPanel.jsx
See full source in the repo. Key props:
- `safeRoute` — full route response object including `score_breakdown`
- `fastRoute` — full route response object including `score_breakdown`
- `open` — boolean controlling slide-up animation
- `onToggle` — callback to toggle open state

`score_breakdown` shape the component expects:
```js
{
  lighting_pct: number,      // 0-100
  crime_count: number,
  crime_severity: 'Low' | 'Medium' | 'High',
  overall_score: number,     // 0-10
  est_minutes: number,
  callouts: string[]         // 1-2 human-readable strings
}
```

### src/components/SOSButton.jsx
See full source in the repo. Key behaviour:
- Always visible, fixed bottom-right
- Click → confirm state with 3-second auto-send countdown
- Countdown → `handleSend()` → POST /sos → sent/error state
- `SOS_USER_NAME` and `SOS_CONTACT_NUMBER` constants at top of file — update before demo
- Falls back to Delhi centre coordinates (28.6139, 77.2090) if geolocation unavailable

---

## zenvoy-backend — architecture (not built yet)

### Folder structure to create
```
zenvoy-backend/
├── app/
│   ├── main.py          ← FastAPI app, CORS, mounts all routers
│   ├── db.py            ← MongoDB client singleton (pymongo)
│   ├── router.py        ← /route/safe and /route/fast logic
│   ├── safety_score.py  ← crime_penalty + darkness_penalty calculation
│   └── sos.py           ← Twilio SMS call
├── scripts/
│   └── preprocess.py    ← One-time: Mapillary → YOLOv8 → MongoDB
├── data/
│   └── .gitkeep         ← delhi_walk.graphml goes here (gitignored)
├── .env.example
├── requirements.txt
└── README.md
```

### requirements.txt
```
fastapi
uvicorn
osmnx
networkx
pymongo
python-dotenv
twilio
ultralytics
requests
Pillow
```

### .env variables needed
```
MONGO_URI=mongodb+srv://...
TWILIO_SID=ACxxxxxxxxx
TWILIO_TOKEN=xxxxxxxxx
TWILIO_FROM=+1xxxxxxxxxx
```

### app/main.py responsibilities
- FastAPI instance
- CORSMiddleware with `allow_origins=["*"]`
- Load `delhi_walk.graphml` once at startup into a module-level variable
- Mount `/route/safe`, `/route/fast`, `/sos` endpoints

### app/router.py responsibilities
- Accept `slat, slng, elat, elng` floats
- Find nearest OSM nodes to origin and destination using `ox.nearest_nodes(G, lng, lat)`
- For fast route: `networkx.shortest_path(G, source, target, weight='length')`
- For safe route: `networkx.shortest_path(G, source, target, weight='safety_cost')`
- `safety_cost` must be pre-computed on graph edges at startup by reading `edge_safety_scores` from MongoDB
- Return coordinate list as `[[lat, lng], ...]` (note: lat first, lng second — frontend handles the flip)
- Return `score_breakdown` object computed from aggregated edge scores along the route

### app/safety_score.py responsibilities
- `get_crime_penalty(lat, lng, db)` — query `crime_incidents` collection using `$nearSphere` with `$maxDistance: 50`, count results, normalize 0-1
- `get_darkness_penalty(edge_id, db)` — lookup `edge_safety_scores` by `edge_id`, return `darkness_penalty` field (default 0.5 if not found)
- `compute_safety_cost(length, lat, lng, edge_id, db)` — returns `length * (1 + crime_penalty + darkness_penalty)`

### app/sos.py responsibilities
- Accept lat, lng, user_name, contact_number
- Build SMS: `"🚨 ZENVOY SAFETY ALERT\n{user_name} may need help.\nLocation: https://maps.google.com/?q={lat},{lng}\nSent via Zenvoy"`
- Call Twilio API to send SMS
- Return `{ "status": "sent", "message": "Alert dispatched" }`

### Graph startup sequence
```python
# In main.py at module level (runs once):
import osmnx as ox
import networkx as nx
from app.db import get_db

G = ox.load_graphml('data/delhi_walk.graphml')

# Pre-compute safety_cost on all edges
db = get_db()
for u, v, data in G.edges(data=True):
    edge_id = f"{u}_{v}"
    score_doc = db.edge_safety_scores.find_one({"edge_id": edge_id})
    darkness = score_doc["darkness_penalty"] if score_doc else 0.5
    # crime penalty is cheap to compute at startup for demo routes
    # for full graph, default to 0 for edges without crime data
    data['safety_cost'] = data['length'] * (1 + 0 + darkness)
```

### preprocess.py flow (run once before demo)
1. Load `delhi_walk.graphml`
2. For each edge (limit to ~400 edges near demo routes):
   - Compute midpoint lat/lng
   - Call Mapillary API to get nearest street image URL
   - Download image
   - Run YOLOv8 inference → detect streetlights → compute `light_score` from brightness heuristic
   - Insert `{edge_id, light_score, darkness_penalty: 1-light_score}` into `edge_safety_scores`
3. For crime data: insert crime incident documents from Delhi crime CSV into `crime_incidents` with `location` as GeoJSON Point

---

## zenvoy-mobile — architecture (not built yet)

### Stack
- React Native + Expo
- `react-native-maps` for map display
- `expo-location` for GPS

### Key difference from web
- Uses React Native Maps (Google Maps under the hood on Android) instead of Mapbox GL JS
- Same `api.js` structure with `USE_MOCK` flag
- Same mock data shape
- `expo-location` replaces `navigator.geolocation` for SOS

### Coordinate note
Same `[lat, lng]` format from backend. React Native Maps expects `{ latitude, longitude }` objects — conversion needed in the mobile equivalent of `MapView`.

---

## Demo routes (pre-compute everything for these two)

### Route 1: Hauz Khas Metro Station → Hauz Khas Village
- Origin approx: 28.5433, 77.2066
- Destination approx: 28.5478, 77.2008
- Why: shortest path cuts through known dark galis, safe route uses main road

### Route 2: Lajpat Nagar Metro → Central Market
- Why: multiple shortcut alleys vs well-lit main road

For each demo route, pre-cache in MongoDB and verify safe ≠ fast visually on map before demo.

---

## Critical rules for any agent working on this

1. **Never change the coordinate format contract.** Backend returns `[lat, lng]`. Frontend flips to `[lng, lat]` for Mapbox in `coordsToGeoJSON()`. Do not "fix" this — it is intentional.

2. **`USE_MOCK = true` is the safety net.** If backend breaks during demo, flip this and the app works with pre-cached data. Never delete mock data.

3. **CORS must be `allow_origins=["*"]`** on the backend. Both web (localhost:5173) and mobile (ngrok) call it.

4. **The graph file is NOT in the repo.** `delhi_walk.graphml` is gitignored and lives only on the developer's machine. Download command: run `scripts/download_graph.py` which calls `ox.graph_from_place("Delhi, India", network_type="walk")`.

5. **MongoDB `2dsphere` index must exist** on `crime_incidents.location` before crime queries will work. Creating it: `db.crime_incidents.create_index([("location", "2dsphere")])`.

6. **Twilio free tier requires verified "To" numbers.** The contact number in `SOSButton.jsx` and in any test must be verified in the Twilio console first.

7. **Response time must be under 5 seconds.** Load the graph at startup, not per request. Pre-compute `safety_cost` on edges at startup, not per request.

---

## Known issues / watch out for

- `mapboxgl-ctrl-geocoder` mounts into a DOM ref — in React Strict Mode (dev), effects run twice. The `if (originGeoRef.current) return` guard prevents double-mounting.
- `map.isStyleLoaded()` check in `MapView.jsx` is necessary — route updates can fire before the map style is fully loaded, causing silent failures on `getSource()`.
- NetworkX `shortest_path` will throw `NetworkXNoPath` if origin/destination nodes are not connected. Backend must catch this and return a 404 with a clear message.
- OSMnx `nearest_nodes` takes `(G, X, Y)` where X=longitude, Y=latitude — this is counterintuitive. Do not swap them.
