# Diario nutricional: captura sencilla (prototipo desechable)

Explora una pregunta: ¿puede una persona confirmar una porción aproximada con
poca fricción y entender cómo la incertidumbre afecta al aviso diario?

Base: `origin/main` en `f36e851b3ac5a102d41c3621f69a802ac834abcc`.
Rama aislada: `spike/nutrition-intake-review`. No está integrado ni desplegado.

## Abrir y verificar

Sin dependencias, desde la raíz del worktree:

```powershell
Start-Process .\spike\nutrition-intake-prototype\index.html
python -m json.tool docs/architecture/reviews/2026-11-15-nutrition-sugar-review.json > $null
git diff --check
```

Solo estado en memoria. Recargar descarta las entradas de demostración.
Para abrir desde HTTP opcionalmente:

```powershell
python -m http.server 8766 --bind 127.0.0.1 --directory spike/nutrition-intake-prototype
```

## Qué permite probar

- Texto limitado a fixtures de cola y chocolate; cantidades en ml o porciones
  aproximadas explícitas. Otros alimentos pueden registrarse como desconocidos.
- Audio y foto simulados: **no hay micrófono, subida, transcripción ni visión**.
- Borrador → revisión → confirmación; una estimación confirmada sigue siendo una
  estimación. No se cuenta antes de confirmar ni dos veces por pulsar de nuevo.
- Porciones en rango, cantidades indicadas en ml, receta desconocida y referencia
  general alcanzada o cruzada por un rango. La falta de datos no se convierte en cero.
- Referencias ilustrativas de azúcares libres calculadas con 2.000 kcal/día; no se
  elige ni prescribe un objetivo para Ana. La cafeína se mantiene desconocida.

Los intervalos de porción son supuestos de diseño; no expresan probabilidades.
Solo la ficha Original usa la etiqueta alemana de marca (10,6 g/100 ml).
Zero / Light y la receta opcional de chocolate son fixtures sintéticos.

## Requisitos confirmados y entrega futura

El usuario pidió captura real por audio, texto o foto, porciones domésticas
aproximadas corregibles a ml/g y avisos extensibles para alimentos y bebidas.
La demo enseña ese flujo; **todavía no entrega la captura multimodal real**.

El producto deberá:

1. Convertir texto/transcripción/imagen en una propuesta estructurada. Conservar
   el texto original, alimento candidato, variante, porción/rango, unidad,
   supuestos y estado de confirmación. La confianza del reconocimiento y la
   cobertura de nutrientes son conceptos distintos; no inventar porcentajes.
2. Priorizar etiqueta/producto/receta verificables. Permitir aproximar una porción
   sin inventar la composición nutricional de un plato. Una foto puede ser
   insuficiente para volumen, azúcar añadido, ingredientes o preparación.
3. Calcular con el motor determinista de Nutrition, conservando instantánea,
   fecha/fuente y base por 100 g o 100 ml. No convertir ml a g sin una base válida.
   Añadidos y libres son subconjuntos de totales, no cifras que se suman entre sí.
4. Expresar sin registros, datos parciales y valores desconocidos. Una referencia
   superada por el mínimo conocido puede avisarse aunque haya datos faltantes;
   estar por debajo con datos parciales no prueba ausencia de exceso.
5. Conservar persona, hora y zona horaria, comida, correcciones con revisión e
   idempotencia para evitar duplicados. Las preferencias de vaso/taza pueden
   aprenderse solo mediante confirmación, sin ocultar la incertidumbre.
6. Guardar reglas por sustancia/nutriente/preparación y contexto: fuente y versión,
   vigencia, unidad, periodo, operador, severidad y tipo de autoridad
   (`REFERENCE_TARGET`, `USER_CONFIGURED`, `PROFESSIONAL_PROVIDED`). Objetivos
   personales profesionales requieren procedencia; una indicación reportada por
   el usuario debe etiquetarse como tal, sin fingir verificación profesional.
7. Aplicar avisos según el rango: mínimo ya supera, máximo podría superar,
   información insuficiente. Un valor bajo nunca debe presentarse como garantía
   de seguridad. Cafeína se suma en mg/día; alcohol y riesgo alimentario por
   preparación requieren reglas específicas. Evitar un puntaje universal de
   “alimentos malos” o indicaciones de compensación/restricción tras consumirlos.
8. Autorizar en Home antes de recuperar/capturar datos por persona, conservar la
   identidad derivada del servidor y validar revocación. Aprobar G2 no crea
   consentimiento de Ana para que otras personas lean su diario.
9. Concretar proveedor de transcripción/visión y tratamiento de los originales
   (mínimo necesario, retención y acceso). No publicar fotos o audios ni registrar
   su contenido en logs. No enviar datos reales a un proveedor nuevo como efecto
   implícito de esta demo. Registrar capacidades/limitaciones del proveedor.

La aprobación **“G2 es aprobado”** consta en `STATUS.md` y `ROADMAP.md`, con fecha
2026-11-15. No se debe volver a pedir esa aprobación de proyecto para este alcance.
Onboarding y ConsentGrants efectivos siguen pendientes; no se importaron datos reales.

## Evidencia clínica y de producto

[Referencias oficiales](../../docs/architecture/reviews/2026-11-15-pregnancy-food-threshold-references.md)
documenta azúcar, cafeína, alcohol, preparación y diabetes gestacional. No existe
en las fuentes revisadas un límite universal individual de azúcar por embarazo.
La pregunta sobre diagnóstico o indicación profesional de Ana está pendiente de
respuesta; no se supone que tenga diabetes ni se elige un objetivo terapéutico.

Este prototipo usa aritmética JavaScript solo para demostrar rangos. No sustituye
la implementación Decimal del dominio ni pretende ser una entrega productiva.
