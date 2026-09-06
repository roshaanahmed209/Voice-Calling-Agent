/* Re-export the official Daily IIFE so @vapi-ai/web does not pull the
   broken ESM build from a CDN. dashboard.html loads dist/daily.js first. */
const Daily = globalThis.Daily;
if (!Daily) {
  throw new Error("Daily.js did not load. Check that /daily-shim.js is reached after the Daily script.");
}
export default Daily;
