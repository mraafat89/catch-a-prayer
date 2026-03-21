// Mock react-leaflet for Jest — render children without map container
import React from 'react';

export const MapContainer = ({ children }: any) => <div data-testid="map-container">{children}</div>;
export const TileLayer = () => null;
export const Marker = ({ children }: any) => <div data-testid="marker">{children}</div>;
export const Popup = ({ children }: any) => <div>{children}</div>;
export const Tooltip = ({ children }: any) => <div>{children}</div>;
export const Polyline = () => null;
export const CircleMarker = () => null;
export const Circle = () => null;
export const useMap = () => ({
  setView: jest.fn(),
  flyTo: jest.fn(),
  fitBounds: jest.fn(),
  getBounds: jest.fn(() => ({ contains: jest.fn(() => true) })),
  getZoom: jest.fn(() => 13),
  on: jest.fn(),
  off: jest.fn(),
});
export const useMapEvents = jest.fn(() => null);
