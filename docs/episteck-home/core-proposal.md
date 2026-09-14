# EPISTECK HOME — propuesta del Core mínimo

**Estado:** `ARCHITECTURE APPROVED` · **Decisión actualizada:** 2026-09-14 ·
**Aprobador:** Erick.
**Repositorio:** `EKvargas/episteck` · **Base documental:** `d7ca468`.
**Alcance de esta entrega:** diseño exclusivamente. No autoriza instalación,
configuración, ingestión, conexiones, agentes, frontend ni despliegue.

## 1. Brief de arquitectura

Proponer `episteck_home` como una **app Frappe pequeña de coordinación y
gobierno doméstico**, versionada en este repositorio. Vive junto a ERPNext en
`home.episteck.com`, pero sus conceptos no se fuerzan dentro de Company,
Customer, Employee ni del activo contable de ERPNext.

- **Primera utilidad aprobada:** un organizador genérico y mínimo de
  **Health Journey / Pregnancy Journey**: tareas compartidas, responsables,
  recordatorios, consultas/exámenes planificados y referencias documentales.
  No es una historia clínica, un asesor clínico ni un "modo" dentro de wger.
- **Pregnancy Journey demuestra la composición cross-domain:** coordinación
  doméstica de tareas y citas; wellness opcional y separado; referencias
  clínicas con consentimiento; y, después, gastos explícitamente autorizados.
- **Core:** identidad doméstica mínima, autoridad/consentimiento, procedencia
  y operaciones de dominio acotadas. No es un repositorio universal de vida.
- **ERPNext:** foundation y capacidades administrativas reutilizables sólo
  después de comprobar su encaje; no se activa contabilidad doméstica ahora.
- **Finance Connector, Health y Mind:** contextos separados. Conservan sus
  datos especializados; el Journey coordina sólo elementos administrativos y
  proyecciones autorizadas, nunca copias implícitas.
- **API y futuro MCP:** una misma política de acceso. Los agentes leen vistas
  limitadas y proponen cambios; nunca obtienen DB, shell del host, credenciales
  bancarias, poder de consentimiento ni confirmación en nombre de una persona.
- **Complejidad diferida:** sin microservicios obligatorios para el Core,
  event sourcing, bus de eventos, grafo de conocimiento, motor universal de
  permisos, almacén vectorial ni duplicación de los sistemas especializados.

El [diagrama Archify](core-architecture.html) muestra una arquitectura objetivo,
**no una topología desplegada**. Su [fuente editable](core-architecture.json)
permite regenerarlo. El contenido es español; el visor fijo y su atributo
`html lang` usan el fallback inglés de Archify. Dispone de exportación desde
el visor a SVG, PNG, JPEG, WebP y WebM; la vista es estática por defecto.

## 2. Evidencia y límites existentes

Se leyeron [context.md](../../context.md), [README](../../README.md),
[convención de docs](../README.md), [foundation](foundation.md),
[arquitectura del Mapper](../architecture.md),
[ADR-004](../adr/004-share-frappe-user.md), [infra](../../infra/README.md) y
los runbooks [deploy](../runbooks/deploy.md) y
[ERPNext Custom Fields](../runbooks/erpnext-custom-fields.md).
También se consultó el runbook de foundation indicado por el proyecto:
`/home/frappe/.openclaw/workspace/docs/operating-model/new-client-bootstrap-playbook.md`.
Son fuentes de contexto; **no se ejecutó ninguno de sus procedimientos**.

Hechos documentados: site HOME limpio con Frappe `15.99.0` y ERPNext `15.96.1`,
HTTPS y respaldo existentes, sin app doméstica ni sistemas especializados.
El sitio comercial `erp.episteck.com`, su integración Lead/Flowable y sus
credenciales **no pertenecen al nuevo Core**. Que estén en el mismo repo no
autoriza reutilizarlos para datos del hogar.

Dos discrepancias documentales quedan visibles: `context.md` todavía describe
el usuario Linux `episteck`, superado por ADR-004; `foundation.md` conserva
pasos OAuth/instalación inicial pendientes junto a posteriores anotaciones de
éxito. Se usa la foundation como alcance arquitectónico y ADR-004 como regla
de alojamiento, sin asumir que cada frase histórica sea estado vivo. Esta
fase no audita el sitio ni reabre la foundation o el correo.

**Límite importante:** site separado no significa aislamiento de procesos.
ADR-004 comparte usuario `frappe` y bench; los límites del diagrama son
lógicos, no una garantía frente al administrador/host. Antes de habilitar
agentes o almacenar datos sensibles, habrá que aprobar y verificar una
frontera de ejecución que no les permita leer DB, backups, secretos o archivos
del host. No se crea esa infraestructura en esta fase.

## 3. Límites y propiedad de datos

| Contexto | Autoridad / contenido permitido | Lo que no recibe |
| --- | --- | --- |
| `episteck_home` Core, app futura sobre Frappe | Hogares, personas mínimas, permisos de uso, procedencia y registros administrativos confirmados o pendientes claramente diferenciados | Credenciales bancarias, historia clínica, series de wearables, diarios, conversaciones o memorias AI en bruto |
| ERPNext estándar | Foundation instalada; posible reutilización administrativa mediante enlaces explícitos | Person como Employee/Customer; Household como Company; afirmaciones AI en registros contables |
| Finance Connector, futuro | Conexiones bancarias, tokens del proveedor y datos financieros externos; normalización y reconciliación propias | Poder para confirmar hechos del hogar, consentimiento global o asiento automático en ERPNext |
| Health, futuro | Datos clínicos, biométricos, ejercicio, nutrición y sus fuentes | Copias implícitas de esos datos en el Core o acceso de agentes de otros contextos |
| Mind, futuro | Diarios, notas privadas, conversación, memoria AI e hipótesis | Promoción automática de inferencias a hechos del hogar o lectura global de Health/Finance |
| API / MCP futuro | Autenticar, autorizar y serializar vistas mínimas; sin nueva autoridad sobre el dato | CRUD arbitrario, SQL, herramientas de shell, proxy HTTP universal o secretos en respuestas |

En el primer vertical, todo intercambio especializado queda **deshabilitado**.
El Journey puede contener un asunto "consulta planificada" o "examen por
coordinar", pero no diagnóstico, resultado, medicación, observación clínica ni
contenido de documento médico. Un enlace/referencia sólo se muestra a quien
tenga autorización tanto para el Journey como para la fuente.
Más adelante, una proyección mínima puede ser «renovación pendiente el día X»,
con fuente y permiso. Ni un saldo ni un nombre de cita médica son inocuos por
ser resúmenes: también requieren autorización y clasificación. La opción por
defecto para Health/Mind es **ninguna proyección al Core**.

Reglas propuestas de propiedad y acceso:

1. Separar **titular/sujeto**, **ámbito Household**, **responsable de gestión**,
   **sistema de origen** y **actor que creó el registro**. El campo técnico
   `owner` de Frappe no representa automáticamente esas cinco cosas.
2. Ser administrador del hogar permite coordinar asuntos compartidos, no
   consentir por otro adulto ni leer automáticamente su salud, diario o banco.
   La autoridad administrativa del servidor es un límite de confianza distinto.
3. Un bien puede ser individual, compartido, prestado o de titular desconocido;
   pertenecer al inventario no acredita propiedad. No inferir cuotas de propiedad.
4. Denegar por defecto: permiso efectivo = identidad válida ∩ acción permitida
   ∩ pertenencia/objeto ∩ finalidad ∩ consentimiento vigente cuando corresponda.
   Un rol técnico, un scope o una conexión OAuth por sí solos no bastan.
5. Revocar corta nuevas lecturas, extracciones, ingestas y trabajos pendientes
   afectados; se vuelve a comprobar al ejecutar, no sólo al encolar. Lo ya
   exportado no puede «desleerse». Retención, borrado y copias de respaldo son
   decisiones explícitas por clase de dato, no una promesa de borrado instantáneo.
6. En datos conjuntos, no ampliar acceso por la autorización de una sola persona:
   limitar la proyección a la parte autorizada o dejarla bloqueada para revisión.
   Menores y representación se difieren, sin consentimiento implícito del hogar.

## 4. Modelo conceptual mínimo

El [glosario](CONTEXT.md) fija el lenguaje; esta tabla expresa relaciones y
responsabilidades, **no especificaciones de DocTypes**.

| Concepto | Identidad y relaciones mínimas | Ubicación objetivo |
| --- | --- | --- |
| Household | ID estable, nombre; varias Membership con Person, rol doméstico y vigencia | Core; no Company estándar |
| Person | ID opaco, nombre mínimo; login opcional; 0..N Membership; datos sensibles no se adjuntan al perfil | Core; no Employee, Contact ni Patient estándar |
| Consent | Persona que autoriza, representación explícita si existe, destinatario, propósito, categorías/objetos, acciones, vigencia, evidencia y revocación; versionado | Core conserva la autorización de uso HOME; la concesión bancaria propia del proveedor queda en Finance Connector |
| Data Source | Origen concreto; ámbito/sujetos; categoría, procedencia, autoridad y estado; 0..1 External System; entrada manual también es fuente | Descriptor mínimo en Core; conexión, payload y cursores especializados fuera |
| External System | Identidad estable del sistema, contexto responsable y referencia del contrato; 1..N Data Source posibles | Catálogo de metadatos en Core cuando exista integración; el sistema real y sus secretos permanecen fuera |
| Integration Event | ID/idempotencia, fuente, tipo/versión, sujeto/ámbito resueltos por servidor, tiempos, correlación, permiso evaluado, resultado e intentos | Recibo mínimo en Core al existir intercambio; payload bruto y detalle del proveedor fuera |

Membership es una relación, no otro sistema de identidad. No se deduplican
personas entre hogares mediante email, nombre o AI; cualquier vinculación
requiere autoridad explícita y no revela otras pertenencias.

Soporte imprescindible, sin plataforma genérica: cada campo significativo
posee una **Assertion** con valor y evidencia; el vertical aprobado añade
**Health Journey**, **Journey Item** y usa **Administrative Item** sólo como
un patrón acotado para tareas, responsables, estado y fecha prevista. Una
afirmación pertenece a un registro y un sujeto; su evidencia puede referenciar
una fuente y, si existe, un evento. Un Journey Item puede referenciar una cita,
examen o documento sin copiar contenido clínico. No se crean historias clínicas,
jerarquías patrimoniales ni un modelo universal de tareas/documentos.

**Fuera de ERPNext inicialmente:** transacciones/saldos bancarios en bruto,
conexiones y tokens financieros; datos clínicos, wearables, ejercicio/nutrición;
diarios, conversaciones, embeddings, memoria AI e hipótesis de Health/Mind.
Los seis conceptos del Core tampoco son hoy datos de ERPNext: son diseño.
Cuando exista la app, algunos vivirán en la misma base Frappe, en su propio
dominio, sin convertirse por ello en entidades estándar ERPNext.

## 5. Procedencia y estados de conocimiento

Se separan tres ejes: **origen**, **estado de conocimiento** y **ciclo de vida**.
`confidence=0.99` no es un permiso ni una confirmación.

| Estado de conocimiento | Significado | Quién puede producirlo |
| --- | --- | --- |
| `USER_CONFIRMED` | Una persona autorizada confirmó el valor exacto mostrado, en ese momento | Sólo acción humana autenticada, con autoridad sobre ese dato |
| `EXTERNAL_REPORTED` | Un sistema externo comunicó ese valor estructurado | Adaptador autorizado; autenticidad de origen no garantiza corrección |
| `AI_EXTRACTED` | AI transcribió/estructuró un dato desde evidencia localizable | Proceso de extracción identificado; siempre pendiente de revisión |
| `AI_HYPOTHESIS` | AI dedujo, interpretó o predijo algo más allá de la evidencia | Proceso de inferencia identificado; nunca dato operativo confirmado |

Metadatos mínimos por afirmación: sujeto, propiedad, valor/tipo/unidad cuando
aplique, ámbito/titular, origen inmutable (`USER_INPUT`, `EXTERNAL`,
`AI_EXTRACTION`, `AI_INFERENCE`), fuente y referencia de evidencia; tiempos
de observación/validez y recepción, estado de conocimiento y revisión.
Para AI: modelo/versión y referencia de ejecución, no el prompt o conversación
completos. Para confirmación: persona, fecha y referencia de la afirmación
exacta revisada. La referencia documental también tiene permisos; no es una
URL pública ni un token de descarga persistente.

Reglas innegociables propuestas:

- Nunca actualizar una extracción/hypothesis «en sitio» para borrar su origen.
  Confirmar crea una nueva revisión/atestación `USER_CONFIRMED` enlazada a la
  afirmación revisada y conserva la cadena hasta la fuente original.
- Una edición posterior crea otra revisión. AI, webhooks o una actualización
  externa no heredan el estado confirmado de la versión anterior.
- `ACTIVE`, `SUPERSEDED` y `RETRACTED` son ciclo de vida independiente; una
  afirmación confirmada puede quedar obsoleta o retractada sin falsificar su
  historia. Revocar un permiso modifica disponibilidad, no veracidad histórica.
- Discrepancias quedan lado a lado con un conflicto pendiente; no hay
  «último mensaje gana», mezcla silenciosa ni desempate por confianza AI.
- En v0.1 la vista operativa y los vencimientos accionables utilizan sólo
  afirmaciones vigentes `USER_CONFIRMED`. Las otras aparecen como propuestas
  separadas. No hay hipótesis AI activas en el primer vertical manual.

Ejemplo: un documento dice «garantía hasta 30/09»; la extracción AI propone
30/09 (`AI_EXTRACTED`). La persona verifica documento, año y bien, y confirma
una nueva revisión. Una posterior inferencia «probablemente caduca pronto» es
`AI_HYPOTHESIS`, no corrige esa fecha ni crea un recordatorio por sí sola.

Los eventos tienen otro ciclo: `RECEIVED → VALIDATED → APPLIED`; validación
fallida → `REJECTED`; error de aplicación → `FAILED`, con intento posterior
auditado sobre el mismo evento. `APPLIED` sólo significa que se guardó la
proyección/propuesta permitida, **nunca** `USER_CONFIRMED`. Se deduplica por
fuente + ID externo; repetir el mismo ID con contenido distinto se rechaza.
Sin garantía mágica de exactly-once: la aplicación local y su recibo deben
ser atómicos/idempotentes. No se necesita un broker para el Core mínimo.

## 6. API / MCP: contrato propuesto, no endpoints creados

Usar operaciones de dominio versionadas, con listas blancas de campos y
filtros. El futuro adaptador MCP llama a la **misma** autorización que la API;
no crea un atajo a Frappe. `v1` indica un contrato futuro, no una ruta instalada.

| Operación API conceptual | Tool MCP futura | Permiso y límite |
| --- | --- | --- |
| Consultar resumen de un hogar | `home.get_household_summary` | `home:read`; hogar autorizado, sin otras pertenencias ni datos sensibles |
| Listar bienes y asuntos permitidos | `home.list_assets`, `home.list_admin_items` | `assets:read`, `admin:read`; filtro obligatorio por ámbito; salida paginada/minimizada |
| Consultar procedencia de un valor | `home.get_provenance` | `provenance:read`; sólo evidencia visible, sin payload, secretos o URLs firmadas reutilizables |
| Proponer cambio de bien/asunto | `home.propose_change` | `home:propose`; crea propuesta, no modifica el registro confirmado |
| Confirmar/rechazar propuesta | **No se expone por MCP de agentes** | `home:confirm`; persona autenticada y autorizada; versión/valor esperado para evitar carreras |
| Registrar/revocar Consent | **No se expone por MCP de agentes** | `consent:manage`; titular o representante explícito; sin autoampliación |
| Recibir evento de una fuente | **No se expone por MCP de agentes** | `events:ingest`; identidad exclusiva de conector, vinculada a esa fuente; límites de esquema/tamaño e idempotencia |

Los agentes no reciben un token Frappe que permita sortear el contrato vía
`/api/resource/*` ni una herramienta `run_method`, `query_db`, `fetch_url` o
`get_secret`. Una credencial específica del adaptador, si finalmente hace
falta, permanece del lado servidor, sin rol System Manager/Administrator.
Los permisos Frappe complementan la política de dominio, no la sustituyen:
la API estándar expone recursos y los tokens operan con los roles del usuario.
Véase [REST de Frappe](https://docs.frappe.io/framework/user/en/api/rest) y
[Users and Permissions](https://docs.frappe.io/framework/user/en/basics/users-and-permissions).

Para MCP remoto, proponer tokens de corta duración y audiencia específica,
scopes mínimos y credenciales diferentes hacia servicios posteriores, sin
token passthrough; la implementación concreta de autenticación queda por
elegir. Es coherente con la especificación fechada
[MCP Authorization 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
Los nombres de scopes anteriores son diseño HOME, no scopes existentes de
Frappe/MCP ni una elección anticipada de proveedor de identidad.

Cada llamada comprueba objeto/campos, finalidad y autorización vigente;
el cliente no decide su Household ni su identidad enviándolos en el body.
Se rechazan acceso cruzado y referencias no autorizadas sin revelar si existen.
Registrar actor, acción, objeto opaco, decisión, permiso/versión y correlación;
no textos privados, tokens ni payloads en logs. Paginación, límites de volumen
y cuotas por principal reducen extracción masiva. El futuro agente carece de
conectividad DB y acceso al filesystem/secretos del host: no basta escribirlo
en su prompt. Adjuntos y texto externo son datos, nunca nuevas instrucciones.

## 7. Primer vertical aprobado

**Health Journey / Pregnancy Journey**: piloto manual con un hogar y adultos
que participen voluntariamente. Coordina tareas, responsables, recordatorios,
consultas/exámenes planificados y referencias documentales. Las entradas de
wellness o clínicas permanecen en sus contextos; no se dan diagnósticos,
consejos clínicos ni acciones externas automáticas.

| Candidato | Valor inicial | Dependencias y coste de error | Evaluación |
| --- | --- | --- | --- |
| Health Journey / Pregnancy Journey | Valor familiar inmediato, coordinación recurrente y demostración cross-domain | Datos íntimos; debe limitarse a organización y referencias, con consentimiento y revisión humana | **Primero aprobado**: prueba identidad, permisos, procedencia y límites entre dominios sin backend clínico |
| Household / Administration + Assets | Coordinación tangible, inventario y vencimientos verificables | Captura manual y revisión humana; sin proveedor externo obligatorio | Segundo vertical de bajo riesgo |
| Finance | Visibilidad de flujos y conciliación | Acceso bancario, normalización, duplicados, reconexión y errores monetarios; importación manual aún exige reglas propias | Después de demostrar el Core; empezar sólo lectura, sin asientos ni pagos |
| Health | Información personal potencialmente valiosa | Datos íntimos, unidades/tiempos, atribución clínica y acceso por persona | Más tarde y separado; el Core no decide diagnósticos ni almacén clínico |
| Mind | Captura/reflexión asistida | Ambigüedad, privacidad de terceros, memoria contaminada e hipótesis difíciles de validar | Más tarde y separado; no convertir conversación en hechos automáticamente |

La aprobación responde a una necesidad familiar concreta. El nombre
**Pregnancy Journey** es un subtipo/configuración futura de Health Journey,
no un sistema médico ni un reemplazo del profesional. «Assets» significa bienes
domésticos, no cartera de inversión, valoración, depreciación ni patrimonio
fiscal.

Criterio propuesto del piloto: 3–5 Journey Items sintéticos, trazables y
revisables; una persona puede corregir un dato y explicar quién lo confirmó y
con qué fuente. No se carga ningún dato personal en esta entrega.

## 8. Qué podría ser la app versionada `episteck_home`

Ubicación propuesta, **sin crearla**: `apps/episteck_home/` en
`EKvargas/episteck`, como paquete Frappe independiente del Mapper y del website.
El directorio `apps/` no existe hoy; es una decisión pendiente, no una convención
ya adoptada ni un nuevo repositorio. La instalación futura en el bench necesita
su propio procedimiento aprobado; no se reutiliza el deploy del Mapper.

**v0.1 propuesto, después de aprobación explícita:**

- Entidades domésticas Household y Person con Membership; autorización de
  usos compartidos/Consent; Health Journey y Journey Items del primer vertical.
- Procedencia por afirmación y revisión humana; fuente manual explícita.
  Un esquema acotado al vertical, no un constructor universal de conocimiento.
- Operaciones de dominio y permisos/validaciones server-side, aplicadas también
  a formularios, importaciones y APIs genéricas para impedir atajos.
- Modelos y permisos que se necesiten, migraciones y pruebas versionados en
  la app; no configuración ad hoc vía Custom Fields/Server Scripts.
- Reutilización de login y Desk Frappe. No frontend propio, dashboards, agentes
  ni selección de un proveedor AI en v0.1.

**No convertir los seis conceptos en seis DocTypes por obligación:** Person,
Household, Consent y los registros del vertical justifican persistencia;
Membership/procedencia pueden ser relaciones o estructuras subordinadas.
Una fuente manual no necesita un catálogo de proveedores. External System,
Data Source externos e Integration Event quedan como contratos de diseño
hasta que una integración aprobada los necesite. El diseño físico de DocTypes
debe justificar entonces cada entidad y sus permisos, no preceder al caso de uso.

**Incrementos posteriores, por aprobación separada:** capacity/runtime gate;
wger aislado como proveedor de wellness; adaptador MCP y runtime restringido;
primera fuente externa y recibos idempotentes; Finance Connector; proyecciones
opt-in de Health/Mind. El gate debe ser satisfactorio antes de instalar wger;
wger no es una dependencia del piloto manual. No se prometen fechas ni se
crean integraciones vacías.

## 9. Decisiones y preguntas para aprobación

Se aplicaron `grill-with-docs` (grilling + domain-modeling) como árbol de
decisiones y prueba de escenarios, `karpathy-guidelines` para reducir alcance
y `archify` para el límite visual. El glosario está localizado en la carpeta
HOME para respetar la convención del repo y no sustituir el `context.md`
comercial. La arquitectura y el vertical Health Journey/Pregnancy Journey
quedan aprobados; **no** quedan aprobadas la implementación, la captura de
datos reales, las integraciones, los agentes ni el despliegue de wger.

Frontera de decisiones actual; responder estas permite formular la siguiente
ronda sin dar por resueltas decisiones dependientes:

1. **Utilidad inicial:** aprobada: Health Journey/Pregnancy Journey mínimo.
   Antes de implementar, concretar los 3–5 Journey Items sintéticos y sus
   campos, sin incorporar contenido clínico.
2. **Participación y autoridad:** ¿quién coordina lo compartido y qué adultos
   participan voluntariamente? Recomendación: un hogar piloto; datos personales
   privados por defecto, compartir explícitamente; menores/representación fuera
   del piloto. No equiparar el rol técnico de Erick a consentimiento ajeno.
3. **Frontera de datos y conocimiento:** aprobada: Finance, Health y Mind se
   mantienen fuera del Core, con los cuatro estados y confirmación humana. FHIR
   es fuente clínica futura; wger sólo wellness tras el gate de capacidad.
4. **Forma de la app:** ¿se acepta una app futura en `apps/episteck_home/` del
   repo actual, separada del Mapper y sin forzar los conceptos a ERPNext estándar?
   Recomendación: sí, sólo con los elementos requeridos por el piloto aprobado.

Árbol dependiente: utilidad → bienes/asuntos concretos y campos mínimos;
participación → matriz de permisos/representación; frontera de datos → evidencia,
retención y borrado; forma de app → diseño físico y procedimiento de instalación.
Estas ramas se mantienen abiertas: no es válido inventar sus respuestas ahora.

Antes de almacenar datos reales deben aprobarse además: adjuntos en Frappe o
sólo referencias a un archivo controlado (recomendación inicial: referencias),
plazos de conservación por clase y tratamiento de backups. Antes de agentes:
frontera efectiva de ejecución y permisos del primer caso. Antes de Finance:
proveedor/fuente y autorización bancaria. Aprobar la arquitectura **no** aprueba
por sí solo ninguno de esos cambios operativos ni autoriza implementarlos.

## 10. Escenarios de aceptación del diseño

Estas son verificaciones para revisar el diseño y, en una fase posterior,
convertir en pruebas. **No afirman que hoy exista un control implementado.**

- Persona sin login sigue siendo Person; crearla no concede consentimiento.
- Dos hogares referencian una persona sin revelar otras pertenencias ni datos.
- Responsable del hogar solicita diario/salud de otro adulto: acceso denegado.
- AI extrae una fecha incorrecta: sólo propuesta; ningún vencimiento confirmado
  cambia hasta revisión humana de la versión exacta.
- Fuente externa contradice un dato confirmado: aparecen dos afirmaciones y
  conflicto; no hay sobrescritura automática.
- Revocación con evento en cola: la comprobación al aplicar lo bloquea;
  reintentar no restaura el permiso ni duplica el registro.
- Agente pide SQL, token bancario, confirmación o consentimiento: no hay tool
  disponible ni ruta alternativa autorizada.
- Evento duplicado conserva su resultado; ID repetido con payload diferente
  se rechaza; un fallo no se registra como aplicación correcta.
- Un Journey Item de consulta contiene responsable, estado y fecha prevista,
  pero no resultado clínico; el enlace a una fuente se deniega sin su permiso.
- Una entrada de wellness desde wger no se instala ni sincroniza antes de un
  gate satisfactorio y una aprobación posterior de integración.

## 11. Validación de esta entrega

Revisión documental y trazabilidad sobre el repo identificado; glosario separado
de implementación; revisión de límites, permisos, conocimiento y preguntas
pendientes; fuente Archify validable y HTML exportable. Los recibos de validación
del diagrama y la revisión visual se informan en el handoff, distinguiendo
checks deterministas, evidencia de navegador e inspección visual real.

No se ejecutan tests de aplicación, UAT de ERPNext, migraciones, API de negocio,
ingestión ni verificaciones operativas: no hubo cambios de producto que probar.
La siguiente acción autorizada es definir el alcance de implementación del
piloto o ejecutar el gate de capacidad como comprobación independiente.
Implementar exige una aprobación explícita posterior con alcance definido.
