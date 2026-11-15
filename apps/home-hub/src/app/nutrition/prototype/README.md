# Estudio visual desechable: nutrición de Ana

Tres estructuras en la ruta existente de Nutrición, dentro del AppShell real.
Pregunta: ¿Ana entiende mejor el diario empezando por un resumen, por las comidas
o por nutrientes y fuentes? No es implementación del diario productivo.

## Abrir

Desde `apps/home-hub`, con las dependencias del lockfile instaladas:

```powershell
npm run prototype:ana
```

El runner fuerza desarrollo + `MOCK` y escucha únicamente en loopback.

- A, **Mi día**: http://127.0.0.1:3015/app/nutrition?prototype=ana&variant=A
- B, **Diario visual**: http://127.0.0.1:3015/app/nutrition?prototype=ana&variant=B
- C, **Con contexto**: http://127.0.0.1:3015/app/nutrition?prototype=ana&variant=C

Las flechas flotantes y las teclas izquierda/derecha cambian la variante. Las
teclas no se interceptan al escribir ni al usar un diálogo. El parámetro de URL
permite compartir una variante. No se monta en producción ni en modo LIVE.

## Dirección visual y variantes

Se conserva la paleta del tema activo de Home Hub, sus iconos Phosphor y la
estructura de navegación. En el tema inicial: fondo `#f5ede4`, superficie
`#fffdfa`, texto `#2b1f1a`, acento `#c4643c`, texto/acento fuerte `#923f1e` y
secundario `#57704e`. No son colores de riesgo clínico.

Tipografía del sistema de temas, con fallback local Segoe UI para cuerpo y
Georgia para titulares si los tokens de fuente no resuelven. Se usa acento fuerte
para las acciones principales. Lectura alineada a la izquierda y densidad móvil.

- A divide resumen/captura y muestra después diario y contexto nutricional.
- B hace del diario cronológico el elemento principal, con un resumen lateral.
- C utiliza una lista de nutrientes y un panel de explicación de la selección.

Las propuestas cambian jerarquía y estructura, no solo color. Se revisó que las
variantes mantuvieran fuentes e incertidumbre sin convertir la página en una
competición de barras al 100%. La dirección recomendada por el agente para probar
es A como portada y el diario de B; **Ana todavía no eligió una variante**.

## Recorrido clicable

1. Abrir el chat simulado y pulsar «Enviar ejemplo de bebida».
2. Revisar la versión de producto y el supuesto de vaso pequeño. Antes de
   confirmar, el borrador no aparece en el diario.
3. Confirmar y abrir los mismos registros en la app.
4. Corregir la bebida a 150 ml; volver al chat y preguntar «¿Qué llevo hoy?».
5. Abrir fuentes: separar referencia institucional, adaptación, origen del
   alimento y cantidad. Cambiar el objetivo personal simulado conserva la fuente.
6. Probar chocolate sin receta: queda desconocido, no cero. Abrir Semana y
   seleccionar un día vacío. En «Estado y límites» también se puede probar un
   día completo sin registros.

Voz y foto cargan ejemplos escritos claramente identificados. No hay micrófono,
subida, transcripción, visión ni mensajes enviados a Telegram. Todos los datos
de ingesta, micronutrientes y semana son ficticios. Solo se utiliza como fuente
de ejemplo la etiqueta alemana de cola, junto con enlaces institucionales ya
documentados; no se activa un perfil clínico para Ana.

El mismo estado en memoria alimenta app y chat simulado. Cambiar variantes lo
conserva; recargar la página lo descarta. No hay Nutrition API, base de datos,
historial durable ni sincronización real. El contador de revisión ilustra una
corrección; no implementa el registro de auditoría productivo.

## Verificar

```powershell
npx tsc --noEmit --incremental false
npx eslint src/app/nutrition/page.tsx src/app/nutrition/prototype/AnaNutritionPrototype.tsx
npm run test:server-boundary
node --check test-support/start-ana-nutrition-prototype.mjs
```

Se comprobó manualmente en navegador la captura/confirmación, corrección,
fuentes, objetivo personal, datos desconocidos, semana, cambio de variantes y
pantalla móvil de 390 px. No se añaden tests para esta maqueta desechable.

El entorno Node 22.12.0 emite una advertencia de motor durante `npm ci` para
eslint-visitor-keys; los comandos de tipos y lint deben verificarse por su salida,
no suponerse a partir de la instalación. No se modificó el lockfile.

La selección visual pendiente se incorporará a la especificación; el código
productivo se implementará siguiendo ese diseño, con autorización por persona,
persistencia fiable y las pruebas del flujo real. El estudio se conserva en la
rama de prototipo, fuera de main.
