import { getHomeHubServerConfiguration } from './src/integration/home/server-config.ts';

// Keep this synchronous and before the standalone server import: server.js
// binds its TCP listener as soon as it is loaded.
getHomeHubServerConfiguration();
await import('./server.js');
