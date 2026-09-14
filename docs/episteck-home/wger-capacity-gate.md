# EPISTECK HOME — gate de capacidad y compatibilidad para wger

**Estado:** `IN REVIEW` · **Fecha de snapshot:** 2026-09-14 06:10 UTC.

Este documento es una evaluación read-only. No autoriza instalar, descargar ni
configurar wger.

## Resultado preliminar

**NO APTO por ahora.** El host soporta Podman y disco suficiente, pero no tiene
margen de memoria razonable para incorporar la pila oficial actual de wger sin
arriesgar los servicios ERPNext existentes.

## Evidencia del host

| Comprobación | Resultado |
| --- | --- |
| CPU | 3 vCPU; carga 0.39 / 0.23 / 0.15 |
| Memoria | 3.7 GiB total; 1.1 GiB disponible |
| Swap | 4.0 GiB total; 1.4 GiB ya en uso |
| Presión de memoria | PSI instantáneo 0 en ventanas 10/60/300 s; no elimina el riesgo de picos |
| Disco | 46 GiB libres; 37% usado |
| Runtime | Podman 4.9.3 rootless; `podman-compose` 1.0.6; Docker ausente |
| Puertos | 80/443 sólo por nginx; servicios de datos existentes enlazados a loopback |
| Servicios HOME | `home.episteck.com` respondió HTTP 200; nginx, MariaDB y Redis activos |
| Backups ERPNext | cron `bench --site all backup` cada 6 horas; artefactos recientes presentes |

El host ya ejecuta ERPNext/MariaDB, OpenClaw y 11 workloads rootless de Podman,
incluidos Postgres, MinIO, n8n, Flowable, Grafana y telemetría. La documentación
que decía que telemetría estaba detenida está obsoleta: se observó activa. No se
asume que un servicio esté disponible para reutilizar su memoria: liberarlo
sería un cambio operativo separado.

## Implicación de wger actual

wger 2.7 es la versión estable actual. Su Compose oficial incluye como mínimo
web, PostgreSQL, Redis, worker Celery, Celery Beat, nginx y PowerSync; este
último requiere almacenamiento/esquema propio. La pila trae persistencia,
health checks y volúmenes, pero no elimina el consumo acumulado de esos
procesos.

**Bloqueo de compatibilidad:** el Compose oficial actual usa `include` para
PostgreSQL, Redis y PowerSync, y `depends_on` con `condition: service_healthy`.
El proveedor instalado `podman-compose` 1.0.6 no interpreta `include` y aplana
las dependencias perdiendo esas condiciones. Su parser tampoco admite
`!override`, utilizado por la configuración upstream para reemplazar puertos.
No se debe ejecutar ni adaptar informalmente el Compose oficial en este host;
eso perdería el contrato de readiness y puede conservar exposiciones como
`80:80`. Esto no declara que wger sea universalmente incompatible con Podman,
sino que este runtime/proveedor no supera el gate.

## Condiciones para pasar el gate

Antes de instalar, demostrar en una nueva revisión read-only que se cumplen
todas estas condiciones:

1. Baseline bajo carga representativa que demuestre al menos **1 GiB
   `MemAvailable` después de la carga**, sin swap-in ni presión sostenida; o
   migración de wger a un host aislado con recursos propios. Es un umbral
   operacional propuesto, no un requisito oficial de wger.
2. Elegir y validar un proveedor Compose compatible con el upstream fijado,
   incluidos, condiciones de health, paths y sustitución de puertos; no cambiar
   el runtime existente sin una aprobación separada.
3. Límites de memoria/CPU explícitos por contenedor y política de reinicio;
   validar que no degraden ERPNext bajo carga.
4. Reverse proxy nginx a un único puerto loopback; PostgreSQL, Redis y
   PowerSync sin puertos públicos.
5. Volúmenes persistentes y backup/restauración de PostgreSQL + media +
   configuración, incluyendo el procedimiento específico de PowerSync.
6. Secretos fuera de Git y una prueba de reinicio/restauración con datos
   sintéticos.

## Alternativas seguras

- Mantener el piloto Journey manual sobre la futura app Frappe, sin wger.
- Aislar wger en un VPS/VM con memoria dedicada y conectarlo más adelante sólo
  mediante el contrato Health API autorizado.
- Posponer wellness hasta que una consolidación de servicios sea aprobada,
  medida y revertible.

## Fuentes a revalidar antes del despliegue

- [wger 2.7 release notes](https://github.com/wger-project/wger/releases/tag/2.7)
- [Compose oficial de wger](https://github.com/wger-project/docker)
- [Documentación de backups de wger](https://wger.readthedocs.io/en/latest/administration/backup.html)

No se instaló ni se inició ningún contenedor de wger durante esta evaluación.
