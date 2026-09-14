# EPISTECK HOME — piloto Health Journey / Pregnancy Journey

**Estado:** `SOURCE MVP READY — NOT INSTALLED` · **Fecha:** 2026-09-14
· **Repositorio:** `EKvargas/episteck`.

## Propósito

Probar que EPISTECK HOME puede coordinar un recorrido familiar sensible con
límites claros entre organización doméstica, wellness, clínica, Mind y Finance.
El piloto organiza; no diagnostica, aconseja clínicamente ni sustituye a un
profesional.

## Alcance del piloto

Un único **Pregnancy Journey** sintético dentro de un Household de prueba. Cada
elemento se captura manualmente y se revisa por una persona autorizada.

| Journey Item sintético | Tipo | Contenido permitido |
| --- | --- | --- |
| Preparar una tarea compartida | `TASK` | Título, responsable, fecha prevista y estado |
| Coordinar una consulta | `APPOINTMENT_PLAN` | Fecha/ventana, responsable y referencia externa autorizada; nunca notas o resultado clínico |
| Preparar un examen | `EXAM_PLAN` | Fecha/ventana, responsable y referencia autorizada; nunca observaciones, diagnóstico o informe |
| Referenciar un documento | `DOCUMENT_REFERENCE` | Descriptor mínimo y puntero controlado; nunca contenido ni URL pública persistente |
| Revisar un gasto pendiente | `EXPENSE_FOLLOW_UP` | Categoría, responsable y estado; no importe, pago ni dato bancario en v0.1 |

No se utilizan datos personales reales para probar estos flujos.

## Modelo mínimo de comportamiento

- **Health Journey:** contenedor de coordinación con Household, persona sujeto,
  participantes y periodo. `Pregnancy Journey` es una especialización de
  configuración, no un nuevo sistema clínico. Su título también es sensible.
- **Journey Item:** registro independiente (no child table que exponga todos
  los Items al leer el Journey) con tipo permitido, título mínimo, responsable,
  estado, fecha/ventana prevista, visibilidad, fuente manual y revisión.
- **Referencia externa:** sólo identificador/referencia controlada y fuente;
  el contenido permanece en FHIR, un archivo controlado u otro contexto.
- **Provenance:** cada valor significativo conserva actor, fuente, hora y uno
  de `USER_CONFIRMED`, `EXTERNAL_REPORTED`, `AI_EXTRACTED` o
  `AI_HYPOTHESIS`. El piloto operativo sólo usa `USER_CONFIRMED`.

Estados de Journey Item: `PLANNED → IN_PROGRESS → DONE`; cancelación explícita
`CANCELLED`. Cambiar el dato o estado crea revisión; no se sobrescribe la
procedencia. `DONE` sólo confirma que la coordinación terminó, no un resultado
clínico ni la normalidad de un examen.

## Autoridad y visibilidad

1. La persona sujeto controla qué elementos son compartidos y puede revocar
   acceso a futuro.
2. Un participante puede coordinar únicamente los elementos que le fueron
   compartidos; no obtiene acceso a otros datos Health, Mind o Finance. Puede
   actualizar el estado de un Item asignado, pero no compartirlo ni ampliar su
   visibilidad.
3. Responsable no significa lector universal: asignar una tarea no revela el
   contenido de una fuente externa.
4. Las acciones de confirmar, compartir y revocar requieren una acción humana
   autenticada; no son herramientas MCP/agent.
5. Por defecto, los elementos son privados para el sujeto hasta compartirlos
   explícitamente con una finalidad doméstica concreta.

## Exclusiones explícitas

- Sin diagnóstico, triaje, consejo clínico, medicación, resultados de prueba,
  observaciones clínicas ni historia médica.
- Sin wger, FHIR, Health Assistant, Medplum, wearable, OpenGym, API, MCP,
  agente, webhooks, notificaciones salientes ni sincronización.
- Sin documentos clínicos reales, adjuntos sensibles, URLs reutilizables,
  credenciales, datos bancarios, importes o pagos.
- Sin Custom Fields, Server Scripts ni configuración manual de ERPNext.

## Criterios de aceptación para la futura implementación

1. Con datos sintéticos, crear y listar un Journey y sus cinco tipos de Item
   permitidos no necesita entidades estándar de ERPNext como Patient, Employee
   o Asset.
2. Un coordinador ve sólo los Items compartidos; un Item privado no revela ni
   su existencia ni su referencia externa.
3. Revocar el acceso bloquea lecturas y cambios futuros, incluida una acción
   que hubiera quedado pendiente.
4. Un cambio conserva revisión, actor, fuente y estado de conocimiento; AI no
   puede transformar un valor en `USER_CONFIRMED`.
5. Una referencia a consulta/examen puede coordinar fecha y responsable sin
   que el sistema acepte contenido clínico.
6. No existe operación API/MCP que confirme, comparta, revoque, consulte la DB
   o recupere secretos en nombre de un agente.

## Estado de implementación y secuencia de entrega

1. La fuente versionada de `apps/episteck_home` define `Care Journey` y `Care Journey Item`, junto con un fixture de cinco Items sintéticos. No fue instalada, migrada ni cargada en `home.episteck.com`.
2. Antes de instalar, decidir la matriz concreta de participantes y probar la política de visibilidad con usuarios no administrativos. Ownership o `shared_with_user` son la única vía de lectura de un Item; Household y responsable no amplían permisos.
3. Realizar UAT de permisos y procedencia; borrar los datos sintéticos con un
   procedimiento aprobado si hiciera falta.
4. Decidir por separado si se introducen notificaciones, referencias de
   documentos o una fuente wellness.

La instalación de wger sigue bloqueada por el gate documentado en
[`wger-capacity-gate.md`](wger-capacity-gate.md). Este mini-spec no autoriza
infraestructura, despliegue ni datos reales.
