# Episteck Home

Versioned Frappe app source for the small, privacy-first EPISTECK HOME core.

This package is installed on `home.episteck.com` as the canonical Home Control
Plane. Its current records and validation identities are synthetic only. It
contains Person/Circle/Care/Consent coordination and actor-aware business APIs,
but no clinical records, device credentials, raw wearable payloads, AI endpoints,
or unrestricted service connectors.

The future Device Gateway owns raw health-source data outside Frappe. Home may
consume only explicitly authorised summaries or references.
