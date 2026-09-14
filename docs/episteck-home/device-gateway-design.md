# EPISTECK HOME — diseño de Episteck Device Gateway

**Estado:** `DESIGN READY — RAW STORE DEFERRED` · **Fecha:** 2026-09-14.
No autoriza aplicación móvil, API, OAuth, webhooks, datos reales ni despliegue.

## Implementation boundary

Raw source records, account connections, encrypted payload references and credentials do **not** belong in the Frappe/ERPNext operational database. The current `episteck_home` source contains no Device Gateway DocTypes, tables, OAuth code or raw health fixtures. Phase D is contract-first: this document's model, idempotency rules and canonical projection contract are the seam for a future isolated Gateway datastore/service. The earliest candidate remains a synthetic `WEIGHT` pipeline; a real Withings connector remains blocked pending explicit OAuth, commercial, retention and isolated-runtime approval.

## Propósito y frontera

El **Device Gateway** es el único límite de Episteck para adquirir y normalizar
datos de dispositivos/health platforms. No es una aplicación clínica, un
proveedor Wellness ni un almacén de acceso familiar implícito.

```text
dispositivo → plataforma/connector → Device Gateway → raw source record
                                                    → canonical measurement
                                                     ├→ Wellness (scoped)
                                                     ├→ Home (summary/reference)
                                                     ├→ FHIR (nunca por defecto)
                                                     └→ Health API/MCP (scoped)
```

Cada envío llega autenticado como **connector**, se vincula a una `Person` y
requiere una autorización de ingesta vigente. Household membership no concede
lectura de medidas ni acceso a cuentas/dispositivos.

## Conectores por tier

| Tier | Ruta | Papel / condición |
| --- | --- | --- |
| 1 | Apple Health → iOS bridge; Health Connect → Android bridge | Hubs de agregación preferidos para dispositivos que el usuario ya sincroniza. Nunca el VPS directamente. |
| 2 | API oficial de proveedor (primero Withings) | Cuando aporta sincronización servidor-a-servidor, mejor ID/procedencia o más fidelidad. Consentimiento OAuth por persona. |
| 3 | Garmin, Fitbit/Google Health, Xiaomi/Amazfit y otros | Sólo tras justificar valor, contrato oficial, coste y mantenimiento. Sin scraping ni credenciales del usuario. |

### Apple Health / HealthKit

HealthKit vive en el dispositivo Apple y exige autorización granular por tipo;
Apple oculta incluso si se concedió lectura y puede limitar el historial
([Apple](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data)).
Por ello no existe un conector VPS→Apple Health:

```text
Apple Watch/device → Apple Health → Episteck iOS app/bridge
  → HTTPS Device Gateway (batch idempotente, por Person y scopes concedidos)
```

El bridge conserva el `HKSourceRevision`/bundle, device metadata y UUID de la
muestra cuando estén disponibles; solicita sólo tipos aprobados y sincroniza
por anchor/checkpoint local. Revocación Apple detiene lecturas y marca el
connector como `CONSENT_REVOKED`; no borra automáticamente raw histórico sin
la política de retención/solicitud de borrado de la Person.

### Android Health Connect

Health Connect es on-device, da permisos granulares y presenta sus propios
límites de background/historial; reads en background e histórico requieren
permisos adicionales ([Android](https://developer.android.com/health-and-fitness/health-connect)).

```text
wearable/vendor app → Health Connect → Episteck Android bridge → Gateway
```

El bridge usa change tokens/checkpoints, `DataOrigin`/package y metadata de
record; no asume que agregados sean equivalentes a muestras raw. Para pasos,
la propia guía recomienda agregación para evitar doble conteo
([Android](https://developer.android.com/health-and-fitness/health-connect/read-data)).

### Withings directo (primer conector futuro)

```text
Withings Body Smart → Withings Cloud → OAuth 2.0 → Device Gateway
```

El flujo exige consentimiento web por Person, `state` antiforgery y un código
de autorización de corta vida; solicitar inicialmente sólo `user.metrics`.
Withings documenta scopes separados para mediciones (`user.metrics`) y
actividad/sueño (`user.activity`) ([OAuth/scopes](https://developer.withings.com/developer-guide/v3/integration-guide/public-health-data-api/get-access/oauth-authorization-url/)).
Guardar refresh tokens cifrados por account-connection, nunca en Home, logs,
MCP o prompts.

| Ruta | Ventaja | Coste/riesgo | Decisión |
| --- | --- | --- | --- |
| A. Withings → Apple Health → bridge | Una sola UX para Apple; incluye lo que el usuario decide compartir. | Depende de teléfono/app/sync, añade latencia y puede perder identidad o tipos; duplica el mismo pesaje si también hay API directa. | Útil como Tier 1, menor prioridad para peso. |
| B. Withings API → Gateway | Server-side, menor latencia operativa, ID/procedencia de Withings y mediciones cloud disponibles; funciona sin bridge activo. | Requiere registro de app, OAuth/refresh/webhooks/polling, términos comerciales y soporte de connector. | **Preferida para WEIGHT/Body Smart**, manteniendo Apple Health como copia/segundo origen. |

No se presupone acceso gratuito/producción: la API y sus planes/condiciones se
validan antes de desarrollo. El usuario puede revocar consentimiento; el
connector debe dejar de sincronizar y registrar el evento.

### Garmin, Fitbit y genéricos

- **Garmin:** integrar sólo mediante Garmin Connect Health API, tras aprobación
  de programa. Ofrece feeds de HR, pasos, sueño, respiración, composición,
  estrés y Pulse Ox tras consentimiento, pero el uso comercial puede requerir
  licencia ([Garmin](https://developer.garmin.com/gc-developer-program/health-api/)).
  Hasta entonces, Garmin→Apple Health/Health Connect es Tier 1.
- **Fitbit:** no basar arquitectura nueva en el Fitbit API heredado. La propia
  SparkyFitness reporta transición a Google Health API; validar la política
  oficial vigente al abrir el connector. Tier 1 sigue disponible vía hub cuando
  el usuario lo configure.
- **Xiaomi/Amazfit/chinos y futuros dispositivos:** primero hub Tier 1 o
  export oficial. No aceptar SDKs opacos, scraping, contraseñas ni Bluetooth
  directo en el VPS. Un connector Tier 3 necesita una ADR de valor/fidelidad,
  privacidad, coste, retención y exit strategy.

## Modelo normalizado mínimo (propuesto)

No se intenta modelar todas las taxonomías. Una fila representa una medición
instantánea o un intervalo explícito. La unidad se normaliza por tipo y se
conserva el original en raw.

```text
HealthMeasurement (canonical)
  id, person_id, measurement_type, value_decimal, unit
  observed_at, observed_end_at?             # end sólo para intervalos
  preferred_raw_record_id, status, quality
  canonical_version, created_at, updated_at

HealthSourceRecord (raw, inmutable salvo estado)
  id, person_id, connector_id, source_system, source_app, source_device
  external_id?, source_record_id?, measurement_type, value, unit
  observed_at, observed_end_at?, raw_payload_encrypted_ref?
  provenance_json, ingestion_batch_id, ingested_at, status, quality
  duplicate_of_raw_id?, canonical_measurement_id?

DeviceConnection
  id, person_id, provider, account_subject_ref, consent_id, scopes,
  credential_secret_ref, status, cursor/checkpoint, last_success_at
```

V0 sólo necesita `WEIGHT`; la lista extensible empieza con `BODY_FAT`,
`LEAN_MASS`, `MUSCLE_MASS`, `RESTING_HEART_RATE`, `HEART_RATE`,
`BLOOD_PRESSURE`, `SLEEP_DURATION`, `SLEEP_STAGE`, `STEPS`, `DISTANCE`,
`ACTIVE_ENERGY`, `SPO2`, `RESPIRATORY_RATE`. Los tipos con múltiples valores
(p. ej. presión arterial) se representan como tipos atómicos o un grupo raw,
nunca en un campo ambiguo.

## Procedencia, deduplicación y fuente preferida

1. **Nunca se sobrescribe raw.** Cada conector conserva proveedor, app,
   device, IDs, tiempo observado, tiempo de ingesta y versión de normalizador.
2. **Idempotencia fuerte:** `(connector_id, external_id)` o
   `(connector_id, source_record_id)` es único cuando existe. Reintentos no
   crean otra fila.
3. **Candidatos duplicados cross-path:** mismo `person`, tipo normalizado,
   ventana de observación, dispositivo (si se conoce) y valor/unidad dentro de
   tolerancia específica por tipo. Sólo se *vinculan*, no se eliminan, y un
   caso ambiguo queda `UNRESOLVED` para regla posterior.
4. **Relación de copia:** Apple/Health Connect source metadata y Withings IDs
   permiten declarar `DERIVED_FROM` / `MIRRORS` cuando se reconoce el mismo
   evento. Jamás inferir equivalencia sólo porque dos pesos ocurren el mismo
   día.
5. **Canónico por tipo y Person:** reglas versionadas. Inicio propuesto:
   `WEIGHT: WITHINGS direct > Apple/Health Connect copy > manual`;
   `RESTING_HEART_RATE: platform/device-native > hub copy > manual`.
   La preferencia elige una proyección; retiene todas las fuentes y puede
   cambiar cuando una conexión se revoca o corrige.

`quality` describe señal/validación (`SOURCE_REPORTED`, `VALIDATED`,
`SUSPECT`, `REVOKED`), no valor clínico. Ninguna regla hace interpretación de
embarazo ni recomendación médica.

## Sync, errores y operaciones

- El bridge/connector crea un `IngestionBatch` con rango/cursor y checksum;
  el Gateway responde recibos idempotentes por record.
- El checkpoint avanza **sólo** después de persistir raw y su resultado de
  normalización. Así un crash repite seguro el rango.
- Reintentos exponenciales con límite y clasificación: `RETRYABLE` (red, 429,
  5xx), `ACTION_REQUIRED` (OAuth/consent), `PERMANENT_REJECT` (schema/owner),
  `QUARANTINED` (payload sospechoso). Alertas humanas no incluyen medidas ni
  tokens.
- Reconciliación periódica de ventana corta busca correcciones/borrados del
  origen. Las operaciones de borrado/retención y export se diseñan antes de
  datos reales.

## Seguridad, consentimiento y AI

- `Person` es el dueño; `Household` sólo obtiene acceso mediante consentimiento
  explícito, propósito, receptor, tipos, periodo y revocación. Una conexión de
  Ana nunca autoriza a Erick por pertenecer al mismo hogar.
- Tokens OAuth cifrados, segregados por connector/person y accesibles sólo al
  worker del connector. Callback allowlisted, state+PKCE cuando el proveedor lo
  permita, secretos fuera de Git y auditoría sin payload sensible.
- Los agentes reciben sólo resultados mínimos autorizados mediante una
  **Health API/MCP de Episteck**, por Person, tipo, rango y propósito. Nunca
  reciben secretos, credenciales, refresh tokens, acceso proveedor o raw
  unrestricted. AI no puede conceder consentimiento, cambiar preferencia,
  enlazar cuentas ni confirmar datos.

## Relaciones con otros contextos

| Contexto | Relación permitida | Exclusión |
| --- | --- | --- |
| Episteck Home / ERPNext | Journey recibe coordinación, resumen autorizado o referencia; ERPNext mantiene operaciones, no raw health. | Sin credenciales, series completas ni acceso implícito por household. |
| FHIR | Futuro sistema clínico y fuente de verdad clínica. Un export/mapeo requiere decisión clínica, consentimiento y contrato específico. | No convertir automáticamente Wellness/device data en FHIR clínico. |
| Wellness provider | Consume un projection/API limitado y puede devolver sus propios datos con source propio. | No es gateway ni dueño de consent/provenance canónica. |
| Mind | Puede recibir sólo una señal/resumen explícitamente consentido. | Sin lectura lateral de medidas raw. |

## Secuencia recomendada

1. Aprobar esta arquitectura y el modelo de consentimiento antes de datos
   reales.
2. Implementar primero el Pregnancy Journey sintético, aún sin Gateway.
3. Antes de cualquier container: ampliar/aislar RAM y aprobar un gate de
   runtime. Después, diseñar API/amenazas y probar con datos sintéticos.
4. Primer connector: Withings `WEIGHT` directo, tras aprobación OAuth/comercial
   y pruebas de deduplicación con Apple Health simulada.
