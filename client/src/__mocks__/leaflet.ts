// Mock leaflet for Jest (no canvas/WebGL in jsdom)
const L = {
  map: jest.fn(() => ({
    setView: jest.fn(),
    remove: jest.fn(),
    on: jest.fn(),
    off: jest.fn(),
    flyTo: jest.fn(),
    fitBounds: jest.fn(),
    getBounds: jest.fn(() => ({ contains: jest.fn(() => true) })),
    getZoom: jest.fn(() => 13),
  })),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  marker: jest.fn(() => ({ addTo: jest.fn(), remove: jest.fn(), bindPopup: jest.fn() })),
  icon: jest.fn(() => ({})),
  divIcon: jest.fn(() => ({})),
  latLngBounds: jest.fn(() => ({ extend: jest.fn(), isValid: jest.fn(() => true) })),
  DomEvent: { disableClickPropagation: jest.fn(), disableScrollPropagation: jest.fn() },
  Control: { extend: jest.fn(() => jest.fn()) },
  CRS: { EPSG3857: {} },
};

export default L;
export const { map, tileLayer, marker, icon, divIcon, latLngBounds, DomEvent, Control, CRS } = L;
