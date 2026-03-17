import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.catchaprayer.app',
  appName: 'Catch a Prayer',
  webDir: 'build',
  ios: {
    contentInset: 'automatic',
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1000,
      backgroundColor: '#0f766e', // teal-700
      showSpinner: false,
    },
  },
};

export default config;
