# Live Nutrition Hub Implementation Plan

**Goal** — Make the live diary the Nutrition entry point and show what the viewer can do with the Nutrition tools.

**Architecture** — Reuse the existing server-side diary loader and resolved Person context for both Hoy and the signed-in home dashboard. Keep the profile on its existing route. Keep the prototype home in mock mode. Show generic Telegram prompts for actions supported by the agents, with no personal data in links, browser storage, or clipboard content.

**Tech stack** — Next.js App Router, React, CSS modules, existing Nutrition BFF contract, and Playwright.

## Tasks

- [x] Exercise the desired live Home, Nutrition navigation, profile return path, and diary links in Playwright. Confirm that the tests fail on the current UI.
- [x] Replace the live Home demo cards with the diary summary and a route to the Nutrition actions. Retain context switching, no-store responses, and the mock dashboard in mock mode.
- [x] Point mobile and desktop Nutrition navigation to Hoy in live mode. Keep the selected Person, prevent background fetches of private diary data, and keep Nutrition highlighted on both diary and profile routes.
- [x] Put the profile link and a clearly marked Telegram action guide on Hoy. Cover logging, correcting or matching a food, lookup and meal analysis, recipe planning, and closing the day. Preserve unknown nutrient values and distinguish an unmatched food from a matched food that lacks a value.
- [x] Run the app build, unit tests, server-boundary checks, and Playwright tests. Check the diary on desktop and a phone viewport and verify authorized, denied, empty, and partial outcomes.

Browser writes, additional nutrient totals, and live web chat are separate follow-up work. The diary continues to use the existing authenticated read path.
