# EPISTECK HOME — gate comparativo de proveedores Wellness

**Estado:** `DECISION READY FOR APPROVAL` · **Fecha:** 2026-09-14 ·
**Alcance:** investigación y diseño. No autoriza instalar, descargar, probar
contenedores, crear cuentas ni conectar datos.

## Decisión propuesta

1. **POC Wellness: no desplegar proveedor todavía.** El primer incremento sigue
   siendo el `Pregnancy Journey` sintético. Cuando se apruebe un POC de ejercicio
   aislado y con datos sintéticos, **Lyftr** es el candidato condicional a
   medir primero para Exercise + Nutrition básica. Es una prueba desechable,
   no una adopción de producto. **openGym** queda como alternativa que sólo se
   evaluaría para Exercise, nunca como Health backend ni fuente de dispositivos.
2. **Arquitectura de largo plazo:** `Episteck Device Gateway` es dueño de los
   datos de dispositivos; seleccionar proveedores intercambiables para
   `Exercise` y, después, `Nutrition`. wger sigue siendo el benchmark funcional
   y candidato serio para un host aislado, pero no para este VPS hoy.
3. **Lyftr no es aún una dependencia de producto.** Es una beta joven con un
   diseño atractivo y ligero; su API y esquema siguen pre-1.0. Puede ser objeto
   de una prueba medida posterior, no el contrato sobre el que Episteck basa
   integraciones.
4. **SparkyFitness es referencia de producto/UX, no base de producción.** Su
   licencia es source-available y no comercial sin permiso explícito.

Esto mantiene el Pregnancy Journey independiente de todos los proveedores y
deja FHIR fuera de Wellness.

## Evidencia y límite de las cifras

| Clase | Hecho |
| --- | --- |
| **Medido en este VPS** | 3.7 GiB RAM total, ~1.1 GiB `MemAvailable`, 4.0 GiB swap con ~1.4–1.5 GiB usada; Podman rootless 4.9.3 y `podman-compose` 1.0.6. Disco/CPU sí tienen margen. Véase [gate wger](wger-capacity-gate.md). |
| **Documentado upstream** | Topología, licencia, funciones y mecanismos descritos abajo, enlazados a los repositorios/guías propietarios. No equivale a consumo observado. |
| **Estimación** | No hay presupuestos de RAM publicados y comparables para Lyftr u openGym. Dos procesos/contenedores no prueban que exista margen: imágenes, picos de inicio, cachés y carga real importan. |

**Respuesta de recursos:** wger está **no aprobado** sin ampliar/aislar recursos
y resolver Compose. Lyftr y openGym son *posibles de medir*, no aprobados para
instalar: el primero usa web+API+SQLite y el segundo web+API+JSON, pero no hay
medición upstream ni margen suficiente demostrado en el host. Por tanto,
**ningún candidato está aprobado para una prueba de runtime sin primero mejorar
RAM o liberar/medir margen bajo carga y aprobar un plan de prueba reversible.**
La recomendación operativa es ampliar RAM antes del siguiente paso que implique
containers; no hace falta para implementar el Journey sintético en Frappe.

## Matriz de decisión (1 bajo — 5 alto)

Puntuación cualitativa de ajuste para Episteck, no benchmark de rendimiento.
`—` significa fuera de alcance o no debe decidirse por ello.

| Criterio | wger 2.7 | Lyftr | openGym | SparkyFitness (referencia) |
| --- | ---: | ---: | ---: | ---: |
| Funcionalidad Wellness | 5 | 3 | 2 | 5 |
| UX de ejercicio | 3 | 4 | 5 | 4 |
| Nutrición | 5 | 3 | 1 | 5 |
| Mediciones corporales | 5 | 1 (peso) | 1 (peso) | 5 |
| API / contrato integrable | 5 | 3 | 2 | 4 |
| Calidad de integración | 4 | 2 | 2 | 4 |
| Huella de recursos esperada | 1 | 4* | 4* | 1 |
| Compatibilidad Podman actual | 0 (gate fallido) | 1* | 1* | — |
| Backup / restore | 3 | 3 | 3 | 3 |
| Multiusuario | 4 | 2 | 2 | 4 |
| Madurez / estabilidad | 5 | 1 | 2 | 3 |
| Licencia / uso comercial | 3 (AGPL) | 5 | 1 (AGPL + media sin resolver) | 0 |
| Experiencia móvil | 5 | 3 (Android; iOS planeado) | 4 (PWA/Android) | 4 |
| Lock-in de proveedor | 4 | 4 | 4 | 1 |
| Complejidad operativa | 1 | 4 | 4 | 1 |

\* Estimación por topología documentada, no medición ni aprobación de runtime.

## A. wger 2.7 — benchmark funcional, candidato para host aislado

- La release 2.7 incluye Health Hub/importaciones móviles de Apple Health y
  Health Connect, sueño y categorías de medición tipadas; conserva modelos de
  ejercicios, rutinas, peso y nutrición. También contiene cambios rompientes
  de API, por lo que una integración debe fijar versión y contract-testearse
  ([release 2.7](https://github.com/wger-project/wger/releases/tag/2.7)).
- Tiene REST API documentada, usuarios, API keys y export/backups documentados;
  es el único candidato aquí con una historia madura de nutrición y modelo
  Wellness amplio ([API](https://wger.readthedocs.io/en/latest/api.html),
  [backup](https://wger.readthedocs.io/en/latest/administration/backup.html)).
  Existe además un MCP separado, aún en evolución; no debe tratarse como
  requisito ni como acceso de agentes: el contrato de Episteck será su propia
  API autorizada.
- Aporta planificación/registro de ejercicio y nutrición, catálogo y UI; **no
  aporta** la abstracción multivendor, consentimiento doméstico, deduplicación
  o fuente canónica de Episteck.
- El código es **AGPL-3.0-or-later**: puede usarse comercialmente, pero exige
  revisión legal de obligaciones de copyleft de red y de licencias separadas
  del contenido de ejercicios/ingredientes. El coste es la pila:
  web, PostgreSQL, Redis, Celery worker/beat, nginx y PowerSync según el
  [Compose oficial](https://github.com/wger-project/docker). En este host el
  Compose usa funciones que el proveedor actual no interpreta; el gate previo
  sigue vigente.

**Veredicto:** serio para una VM/VPS dedicado con restore probado. No para el
POC actual ni para decidir Device Gateway.

## B. Lyftr — candidato ligero, aún beta

- Upstream describe Go/Gin + SQLite, React/TypeScript/Vite y nginx; el Compose
  publica dos servicios de aplicación (web y backend) y un volumen SQLite,
  no Postgres/Redis/worker ([repositorio](https://github.com/Cawlumm/lyftr),
  [Compose](https://github.com/Cawlumm/lyftr/blob/main/docker-compose.yml)).
  Pero usa `depends_on: service_healthy`, por lo que el `podman-compose` actual
  tampoco es una ruta de instalación segura. Es una topología pequeña, no una
  medición de memoria ni garantía de Podman.
- Ofrece JWT/refresh auth, cuentas, workouts/programas/PRs, peso y macros con
  búsqueda Open Food Facts. Tiene endpoints HTTP granulares bajo `/api/v1`
  para workouts, weight y food, pero no una especificación externa estable,
  OAuth de servicio ni MCP upstream. `API_CHANGES.md` ya registra cambios
  rompientes de `/weight` dentro de v1: se fija release y se prueban contratos
  antes de depender de él.
- SQLite usa WAL pero configura un único connection pool/escritor. Facilita un
  backup coherente con `VACUUM INTO`/copia con la app
  detenida o SQLite backup API y restore de un fichero, pero permite un escritor
  a la vez. No se aceptará una simple copia live del DB WAL como prueba de
  backup. Una
  incidencia upstream de bloqueo de SQLite confirma que debe probarse
  concurrencia, backup y recuperación antes de depender de ella
  ([issue #25](https://github.com/Cawlumm/lyftr/issues/25)).
- Es MIT, con Android/React Native disponible. PWA e iOS están en roadmap,
  no son capacidades que se puedan prometer
  ([roadmap](https://github.com/Cawlumm/lyftr#roadmap)). Las releases son
  `v0.1.0-beta.*` y el propio proyecto se declara beta; la creación reciente y
  cambios frecuentes reducen su madurez. La rama principal revisada estaba por
  delante de `v0.1.0-beta.6`; hallazgos de main no son una garantía de release.

**Veredicto:** candidato **condicional** al POC sintético por API granular,
MIT y persistencia simple; **no maduro** para dependencia estratégica ni fuente
de datos. Si se evalúa: pin de release, sandbox aislado, contract tests y
prueba de concurrencia/restore primero.

## C. openGym — alternativa especializada de ejercicio

- Se centra claramente en entrenamiento: rutinas semanales, ejercicios,
  sesiones guiadas, supersets/cardio, progresión, PRs y peso; no pretende
  nutrición ([README](https://github.com/DuarteSantos8/openGym)). Su PWA es
  instalable; el móvil nativo es opcional, mientras que la app self-hosted
  soporta perfiles/sincronización.
- Topología upstream: `web` (nginx/React) + `api` Node/WebAuthn, un descargador
  one-shot de media (~140 MB) y `./data` en JSON; no hay servidor de base de
  datos
  ([arquitectura](https://github.com/DuarteSantos8/openGym#how-it-works)).
  Backup/restauración es el directorio de datos con procedimiento consistente;
  el modelo JSON obliga a verificar integridad, concurrencia y recovery, no
  sólo copiar archivos activos.
- Incluye OpenAPI para su cliente y un MCP de **solo lectura**, local, que lee
  `./data`; el MCP carece de auth de red y los writes/token auth aún están
  planeados ([MCP](https://github.com/DuarteSantos8/openGym/tree/main/mcp)).
  Su API de aplicación persiste/expone el perfil entero (`GET`/`PUT /api/data`)
  con revisión optimista, no recursos externos granulares con scopes.
  Eso contradice el límite de Episteck: no se expondrá dicho MCP a agentes ni
  se le darán permisos de archivos. Una futura integración debe ser una API
  acotada servicio-a-servicio o export, no montaje de datos.
- Tiene passkeys y perfiles, pero su proyecto es joven y AGPL-3.0: un servicio
  modificado que se ofrezca por red requiere revisión legal de obligaciones.
  La media se descarga en un servicio one-shot (~140 MB) y sus derechos entre
  Gym Visual/ExerciseDB/AscendAPI están explícitamente sin resolver; AGPL no
  concede esos activos. Podman requiere ajustar resolver DNS y probar Compose
  con sus condiciones de `service_completed_successfully`; el provider actual
  no ofrece esa garantía. El coach opcional queda fuera de cualquier prueba.

**Veredicto:** alternativa **Exercise-only** creíble, pero no Nutrition, no
Device Gateway y no una decisión de producción hasta resolver media/licencia y
aprobar prueba aislada de API/backup/multiusuario.

## D. SparkyFitness — patrón de producto, no candidato

El proyecto concentra nutrición, ejercicio, sueño, mediciones, permisos de
familia e integraciones Apple Health/Health Connect/Withings/Garmin/Fitbit
([integraciones](https://github.com/CodeWithCJ/SparkyFitness#health--device-integrations)).
Es valioso como referencia para: dashboard separado por persona, permisos
granulares, visualización de tendencias, import/export y UX de conexión.

No debe convertirse en fundamento de EPISTECK: su licencia restringe el uso
directo o indirecto con ventaja comercial sin permiso previo por escrito. Es
source-available, no open source: no se reutiliza su implementación, sólo se
estudian patrones de producto
([licencia](https://github.com/CodeWithCJ/SparkyFitness/blob/main/LICENSE)).
Además, la cadencia de releases muestra
migraciones PostgreSQL y conectores que cambian (Fitbit se reemplaza por Google
Health API); ilustra precisamente por qué Episteck debe poseer el Gateway.

## Arquitectura recomendada de largo plazo

```text
Person / Consent
        │
Episteck Device Gateway ──► raw + canonical HealthMeasurement
        │                         │
        ├─ iOS / HealthKit bridge  ├─► Exercise provider (openGym o futuro)
        ├─ Android / Health Connect├─► Nutrition provider (decidir después)
        └─ direct Withings OAuth   └─► Episteck Home: sólo resúmenes/referencias
                                      FHIR: clínica; Mind: separado
```

El primer conector futuro recomendado es **Withings Body Smart → Withings
OAuth API → Device Gateway**, únicamente con `user.metrics` y inicialmente
`WEIGHT`. Es server-side, conserva la identidad de medición del proveedor y no
depende de que un iPhone sincronice; requiere alta de aplicación, consentimiento
OAuth, gestión segura de refresh tokens y revisión comercial. No se implementa
con esta decisión.

Para una comparación específica de Withings y el contrato de datos, véase
[device-gateway-design.md](device-gateway-design.md).

## Snapshot reproducible de fuentes

Investigación de fuente realizada el 2026-09-14: wger `2.7` (release
`65a1d40`), Lyftr `v0.1.0-beta.6` y main `d33ab25`, openGym `v1.3.7`/main
`a68a88d`, SparkyFitness `v1.7.0`/main `a1ed61d`. Las puntuaciones son
juicios arquitectónicos ordinales; no son mediciones de consumo ni auditorías
de seguridad/licencia.
