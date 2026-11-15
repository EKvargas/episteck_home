# Nutrición de embarazo de Ana: alcance y primer uso real

**Estado:** borrador para acordar el alcance, no autorización de despliegue ni plan
de implementación. **Fecha:** 2026-11-15. **Base examinada:** `origin/main`,
`f36e851b3ac5a102d41c3621f69a802ac834abcc`, actualizada por fetch en esta sesión.
**Worktree:** `nutrition-sugar-review`; rama `spike/nutrition-intake-review`.

## Intención y acuerdos existentes

Ana debe poder registrar lo que come y bebe de forma sencilla, revisar una
estimación y consultar orientación nutricional de embarazo con fuentes visibles.
El patrón se extiende a la alimentación durante el embarazo; no se limita al
azúcar ni a una lista de alimentos etiquetados como malos.

El usuario ya pidió y autorizó:

- Captura por texto, audio o foto; porciones domésticas aproximadas corregibles
  a ml/g y confirmación humana sencilla.
- Cálculo aproximado cuando la información sea suficiente; reconocer cuándo no
  es posible calcular sin inventar composición o cantidades.
- Recomendaciones institucionales por defecto, orientaciones de Episteck
  identificadas como tales y objetivos personales configurables.
- Procedencia visible en toda recomendación aplicada: evidencia original,
  adaptación y razón de activación para esa persona.
- **G2 aprobado**, literalmente «G2 es aprobado», el 2026-11-15. No volver a
  solicitar la misma autorización de proyecto. El onboarding y los permisos
  efectivos no se crean por esa aprobación ni se declaran completados.

La demo existente responde al flujo de porciones y confirmación con fixtures.
Audio y foto allí son simulados; no es el producto ni una integración reutilizable
sin implementar y verificar los requisitos de este documento.

## Qué significa extenderlo a toda la nutrición

| Área | Comportamiento previsto | Límite que debe expresar |
| --- | --- | --- |
| Alimentos y bebidas | Diario por comida, fecha/hora y zona horaria; habituales y recetas | Un día con entradas no prueba que todo el consumo esté registrado |
| Patrón alimentario | Orientación revisada sobre variedad, grupos de alimentos e hidratación | No reducir la alimentación a un contador o puntuación de alimentos malos |
| Energía, proteína, carbohidratos, grasa y fibra | Totales estimados cuando haya datos; referencias apropiadas al contexto | No asignar automáticamente energía individual desde una constante universal |
| Micronutrientes pertinentes | Cobertura de ingesta de hierro, folato, yodo, calcio, B12, vitamina D y otros del catálogo revisado | Ingesta estimada no equivale a estado nutricional, deficiencia ni resultado de laboratorio |
| Exposiciones y límites | Azúcares libres, cafeína y otras reglas respaldadas por fuentes | Distinguir azúcares totales/libres/añadidos, referencias poblacionales y límites individuales |
| Seguridad alimentaria | Reglas por ingrediente, preparación, cocción y pasteurización | Una foto o el nombre del alimento no permiten certificar ausencia de riesgo |
| Suplementos reportados | Registrar producto, composición y cantidad confirmada si se dispone de etiqueta | No convertir una diferencia de ingesta en dosis automática ni mezclar ingesta de alimentos con dosis de suplemento sin distinción |
| Preferencias y restricciones | Dieta, alimentos evitados, alergias declaradas y metas elegidas, con atribución | Una preferencia personal no adquiere respaldo científico por estar activa |

«Toda» define el ámbito de Nutrición. No promete reconocer cualquier plato o
conocer cada nutriente. El catálogo inicial declarará explícitamente qué puede
evaluar, qué solo describe y qué información falta. No se añade diagnóstico,
tratamiento, interpretación de analíticas, glucemia inferida desde comidas,
prescripción automática ni integración clínica/FHIR en este alcance.

## Supuestos propuestos y decisiones pendientes

**Propuesta actualizada:** el usuario pidió evaluar reutilizar el agente/bot de
Telegram de Finanzas. Telegram pasa a ser el candidato prioritario para captura
y consulta conversacional, reutilizando home-agent, BFF, Home y svc-nutrition;
Home Hub queda disponible para configuración y visualización detallada. Esta
propuesta no declara que Telegram multiusuario esté implementado ni que el
usuario haya aprobado aún el diseño completo. Interfaz en español y referencias
alemanas/europeas más WHO siguen siendo supuestos del agente por confirmar.
No se presupone que Ana tenga diabetes ni una indicación clínica.

Se preguntó al usuario: «Para su primer uso real, ¿cómo imaginas que Ana
registraría y consultaría lo que come a lo largo de un día?». La respuesta está
pendiente en sus detalles. La pregunta posterior del usuario identifica Telegram
como opción a reutilizar; ya no se propone obligar a Ana a comenzar por la web.
El canal modifica el trabajo de identidad y captura.

La modalidad de texto sirve para una entrega temprana del mismo producto. Audio
y foto siguen siendo requisitos de la experiencia completa. No se consideran
cumplidos mediante controles simulados o una pantalla de adjuntar archivos.

## Recorrido principal y datos necesarios

1. Ana inicia sesión con su propia identidad y, si se elige Telegram, vincula su
   interlocutor de Telegram mediante un flujo verificado fuera del modelo;
   revisa qué información se usa y qué
   comparte, si decide compartir. El acceso propio no requiere inventar un
   ConsentGrant cruzado. El acceso de otra persona sí respeta el modelo Home.
2. Se configura un perfil mínimo confirmado: contexto de embarazo y etapa si es
   necesaria para una regla, preferencias pertinentes, unidades y zona horaria.
   Si se desconoce la etapa, no se aplica una regla que dependa de ella. No pedir
   historia clínica completa ni inferir condiciones a partir del diario.
3. Texto, transcripción o imagen producen un borrador con alimento/producto/receta
   candidatos, porción o rango, unidad, fuente y supuestos. Para varios alimentos,
   el borrador permite revisar cada uno y confirmar el conjunto.
4. Se reutilizan medidas habituales confirmadas por Ana y porciones genéricas
   documentadas, siempre mostrando el supuesto. Solo se pregunta por información
   que cambie materialmente el cálculo o el aviso; se puede guardar una entrada
   incompleta sin forzar una precisión inexistente.
5. Ana confirma o corrige. Se distingue «confirmó que lo consumió» de «la
   composición y cantidad son exactas». Un borrador no suma ingesta real.
6. Nutrition calcula y guarda hechos usados, origen, fecha, unidades, fórmula,
   estimaciones y revisión. Reintentar la misma confirmación no duplica entradas;
   corregir o retirar crea una revisión, no borra silenciosamente el historial.
7. El diario y resumen permiten ver alimentos, rangos, cobertura y avisos, además
   de corregir una porción o completar un dato. No muestran déficit/exceso como
   certeza cuando faltan datos ni invitan a restringir o compensar comidas.
8. Cada aviso ofrece procedencia y configuración accesibles, incluidas las
   razones por las que se aplica o no puede evaluarse una regla.

## Patrón de recomendaciones aplicadas

Se adopta como requisito la separación definida en el informe de esta sesión:
[patrón estructurado](../../architecture/reviews/2026-11-15-nutrition-sugar-review.json),
clave `patron_recomendaciones`.

Por cada regla, no únicamente por perfil, deben existir:

- Identificador y versión, métrica/condición, unidad, periodo, operador y tipo:
  objetivo, mínimo, máximo, evitar o condición de preparación.
- Población, contexto y exclusiones; fuente primaria con título, organización,
  enlace, versión/fecha y fecha de revisión. La fuerza de evidencia solo se
  afirma cuando está documentada.
- Origen visible: institución, adaptación de Episteck, indicación profesional
  o reportada, objetivo personal o propuesta IA pendiente.
- Adaptaciones, supuestos, base energética o factores de conversión usados.
- Activación predeterminada, elección o indicación, con actor/fecha y motivo.
- Evaluación con ingesta/fuentes utilizadas, rango, faltantes y versión de regla.

Una preferencia puede cambiar la meta efectiva sin reescribir la referencia
institucional. Una indicación profesional no se autentica por la sola presencia
del nombre de un profesional. Conflictos entre referencias o reglas se explican;
no se promedian ni se resuelven siempre escogiendo el valor más restrictivo.
Actualizar una guía no reescribe silenciosamente evaluaciones históricas.

Los alimentos tienen su propia procedencia, distinta de la regla: etiqueta,
producto, receta o dato genérico identificable. Si solo hay incertidumbre de
porción pero sí composición, se escala el rango. Si falta composición, la IA no
inventa gramos de nutrientes. Las conversiones ml↔g necesitan una base válida;
folato/ácido fólico y formas de nutrientes tampoco se mezclan sin equivalencia
verificada. Alimentos y suplementos permanecen distinguibles.

El default propuesto para azúcar sigue siendo una referencia institucional de
azúcares libres, con orientación adicional opcional; no una dosis que completar
ni un límite fetal seguro. El catálogo ampliado debe revisarse antes de activar
valores, también para nutrientes que ya aparecen en el código.

### Cobertura mínima propuesta para el primer piloto

Esta es una propuesta del agente para que el piloto ya sirva a la alimentación
del embarazo y no termine siendo otra demo exclusiva de azúcar:

1. Diario de todos los alimentos/bebidas reportados, admitiendo datos desconocidos.
2. Referencias y avisos de azúcares libres y cafeína; alcohol y preparación de
   alimentos relevantes mediante reglas específicas y con preguntas cuando falte
   el dato que cambia el aviso.
3. Orientación institucional sobre patrón alimentario e hidratación, sin inventar
   una cifra personal universal de calorías o agua.
4. Ingesta y cobertura de hierro, folato, yodo, calcio, B12, vitamina D y DHA,
   mostrando solo comparaciones cuyo catálogo/contexto se hayan revisado. La
   ausencia de datos sigue visible; no equivale a carencia clínica.
5. Preferencias y metas personales con procedencia, y registro explícito de los
   suplementos que Ana reporte con composición verificable, sin recomendar dosis
   nuevas a partir de diferencias de ingesta.

Para el resto del catálogo, las cantidades disponibles pueden verse como ingesta;
una comparación no revisada se identifica como no habilitada, no se sustituye
por una constante antigua. Los detalles cuantitativos de cada referencia y su
aplicabilidad forman parte de la entrega de catálogo, no se deducen del título
de esta especificación. El usuario puede ajustar esta cobertura antes de cerrar
el diseño.

**Qué significa revisión:** propuesta del agente: comprobación documentada de
fuentes institucionales primarias vigentes, traducción/unidades/contexto y
adaptaciones, realizada por el equipo y atribuida como revisión de Episteck.
No se declara aval clínico ni se introduce como requisito una firma profesional
para ofrecer orientación institucional básica. Si se pretende una recomendación
terapéutica individual nueva, excede este piloto; una indicación profesional ya
existente puede incorporarse con su procedencia.

## Propiedad, acceso y captura multimodal

No se cambian ADR-0004 y ADR-0008: Nutrition conserva hechos, reglas nutricionales,
configuración y evaluaciones; Home conserva identidad y autorización; Home Hub
presenta; Mealie aporta recetas/planes. No se crea un servicio universal de
recomendaciones, un expediente clínico ni dependencia del runtime Knowledge.

Los nuevos accesos y escrituras deben recorrer una ruta autenticada BFF/gateway
con protección CSRF cuando corresponda. El navegador no recibe credenciales de
proveedor ni acceso directo al puerto interno. Se conserva identidad derivada
del servidor, autorización antes de lectura/escritura y una delegación válida
por operación, incluida corrección y confirmación. URLs, prompts y adjuntos no
pueden cambiar quién actúa. Revocación, sesión inválida y Home no disponible se
prueban en las nuevas rutas, no solo en el servicio previo.

La publicación de audio/foto requiere proveedores concretos para transcripción y
visión, capacidades y límites verificados, límites de archivo y tratamiento de
los originales definido. **Propuesta del agente:** procesar con retención mínima
y eliminación tras extracción por defecto; no guardar originales salvo elección
explícita. Concretar destinos, retención y alcance antes del primer uso real de
cada modalidad. No enviar contenido personal a proveedores nuevos como efecto
de evaluar esta especificación; no incluirlo en logs o fixtures.

Telegram es una alternativa a decidir, no un canal ya listo para Ana. El estado
documenta el bot limitado al propietario y el BFF usa un runtime fijo. Añadir
su cuenta a una allowlist sin diseñar la asociación remitente→actor podría hacer
que sus mensajes actúen con la identidad del propietario. Si se elige Telegram,
la identidad de cada interlocutor, su autorización y la separación de conversación
son requisitos previos, no una tarea de configuración superficial.

### Reutilización del agente y bot de Telegram

La conexión de Nutrition **ya existe en la base documentada**:
`docs/architecture/AGENTS.md` describe home-agent conectado al MCP nutricional y
`deploy/gateway/nginx-mcp-gateway.conf` define `/gateway/nutrition/` junto a Home y
Finance. `G1_6_VALIDATION.md` registra pruebas históricas de Nutrition por Hermes.
No se verificó el runtime desplegado en esta revisión ni se enviaron mensajes.
No hace falta diseñar un agente nuevo por dominio ni almacenar el diario en
memoria de Hermes: Nutrition continúa siendo la fuente del diario y del cálculo.

Reutilizable: interfaz conversacional, despliegue del agente, integración MCP,
gateway y patrón de fuentes/delegación. Se necesita un comportamiento nutricional
específico para borrador, confirmación, corrección, procedencia y falta de datos;
las reglas de Finance no resuelven ese flujo por sí solas.

El mismo bot público puede ser la entrada de ambas personas, pero el transporte
debe aportar un contexto confiable por interlocutor, no un actor elegido en el
prompt. Antes de añadir a Ana se debe concretar y probar:

- Vinculación y revocación Telegram↔Home verificadas; no confiar en nombre visible,
  texto del mensaje o un `person_id` indicado por el modelo.
- Delegación por persona/solicitud, sustituyendo el único enlace global cuando
  corresponda. No alternar un runtime global entre Erick y Ana.
- Sesiones MCP, historial, resúmenes, memoria, borradores y adjuntos aislados por
  persona/conversación; una conversación grupal no habilita compartir salud.
- Herramientas y permisos por dominio. La vinculación de Ana para Nutrition no
  otorga acceso a Finance del propietario ni reutiliza su grant. El filtro de
  herramientas es complementario a la autorización del servidor, no su sustituto.
- Confirmación vinculada al borrador, persona y revisión; un mensaje o botón
  antiguo no confirma otra ingesta ni duplica la anterior.
- Prueba intercalada de dos interlocutores con autorías y sujetos distintos;
  negación de accesos cruzados, de Finance no autorizado y después de revocar.
- Inspección del soporte real de voz/foto en la versión/configuración de Hermes.
  Tener transporte de medios no prueba transcripción, visión ni cálculo fiables.

Si esa asociación multiusuario requiere más trabajo que el piloto web, se debe
mostrar ese costo al usuario; no afirmar que Telegram reduce automáticamente el
trabajo total. No cambiar el bot productivo ni el grant de Finance como efecto de
esta evaluación.

## Distancia al uso real: evidencia y brechas

| Capacidad | Estado comprobado o documentado | Falta para Ana |
| --- | --- | --- |
| Infraestructura Home/BFF/Hub/Nutrition/proveedores | Operativa según STATUS; no se inspeccionó producción en esta revisión | Comprobar acceso y disponibilidad del despliegue que se vaya a publicar |
| Cálculo determinista y separación planificado/real | Código y pruebas locales sintéticas | Unidades domésticas/volumen, rangos, hechos congelados, idempotencia y revisiones |
| Autorización por persona | Código y pruebas locales; evidencia histórica en STATUS | Identidad propia de Ana y pruebas con rutas nuevas; compartir/revocar si lo elige |
| Perfil de embarazo | Creador existente y referencias fijas | Contexto validado y catálogo vigente por regla; no usar constantes antiguas como perfil individual |
| Diario en la app | Nutrition LIVE muestra resumen de perfil | Crear, revisar, confirmar, corregir, consultar y recuperar un diario real |
| Azúcar y cafeína | No están en el mapa canónico actual | Fuente válida, mapeo, clasificación y regla con datos faltantes |
| Cobertura parcial | UNKNOWN existe; daily_gap_v2 marca KNOWN si algún alimento informa el nutriente | Cobertura por entrada y nutriente; no presentar suma parcial como total completo |
| Historial reproducible | La lectura vuelve a consultar valores del proveedor | Congelar los hechos usados y versionar correcciones y reglas |
| Preferencias efectivas | user_goals se guarda, pero el cálculo de gap usa targets | Resolver metas por regla y explicar procedencia y conflictos |
| Transparencia de avisos | Diseño y demo; UI LIVE transmite categoría general | Catálogo, evaluación trazable y detalle de cada aviso en interfaz y exportación autorizada |
| Audio y foto | Simulados en el spike, sin integración productiva | Captura, extracción real, revisión, permisos, proveedores y retención |
| Uso cotidiano por Ana | Sin evidencia de onboarding ni piloto real | Prueba con ella, continuidad tras recarga, corrección, recuperación y criterios de salida |

### Referencias antiguas: brecha concreta antes del piloto

`services/nutrition/app/reference/pregnancy_targets.py` incluye hierro **30 mg**
y yodo **230 µg** como referencias fijas. Al consultar las tablas vigentes de
DGE el 2026-11-15 figuran hierro **27 mg** y yodo **220 µg** para embarazo.
Esto es una comparación de catálogo, **no una indicación de dosis para Ana**.
[DGE hierro](https://www.dge.de/wissenschaft/referenzwerte/eisen/),
[DGE yodo](https://www.dge.de/wissenschaft/referenzwerte/jod/).

Las pruebas actuales incluso fijan un valor anterior de yodo. Que pasen prueba
consistencia del código, no vigencia científica. La revisión debe cubrir todo el
catálogo y distinguir ingesta dietética, suplementación, máximos y condiciones.
La actualización alemana de embarazo de julio de 2026 es una fuente candidata
de partida, no prueba de que todas sus reglas estén ya verificadas o codificadas:
[Gesund ins Leben 2026](https://www.gesund-ins-leben.de/fuer-fachkreise/familien-vor-und-in-der-schwangerschaft/handlungsempfehlungen/).

## Entregas propuestas y puerta de primer uso

Orden propuesto, sin estimaciones de calendario hasta cerrar canal y proveedores:

1. **Catálogo y contexto revisados:** inventariar y validar referencias actuales,
   publicar solo reglas revisadas y registrar incompatibilidades/faltantes.
2. **Acceso de Ana y persistencia fiable:** onboarding propio, unidades/rangos,
   instantáneas, confirmación idempotente y correcciones con revisión.
3. **Piloto conversacional por texto, preferentemente Telegram si se resuelve su
   identidad multiusuario:** diario y resumen reales,
   catálogo inicial revisado, fuentes visibles y configuración por regla. Es una
   entrega parcial explícita; no sustituye los requisitos de audio/foto.
4. **Audio real:** proveedor y retención concretados; transcripción editable y
   confirmación en el mismo diario. Error de transcripción no crea una ingesta.
5. **Foto real:** alimentos candidatos y límites visibles; permitir etiqueta o
   receta y no inferir ingredientes/volumen con falsa precisión.
6. **Cierre de uso cotidiano:** prueba con Ana de las modalidades entregadas,
   medición de latencia/costo/fallos, respaldo/restauración de Nutrition y permisos.

No se asigna un porcentaje de avance: infraestructura funcionando y una demo no
equivalen a producto cotidiano. No es una activación de configuración pendiente;
faltan entregas funcionales. El detalle implementable viene después del acuerdo
de este diseño mediante `superpowers:writing-plans`.

### Condiciones de aceptación del piloto por texto

- Ana inicia sesión como ella misma y accede a su diario; otra persona sin
  autorización no lo lee ni lo modifica. Un permiso compartido revocado deja de
  funcionar. El acceso propio y el acceso cruzado se prueban por separado.
- Puede describir una comida con varios alimentos y una bebida, corregir una
  porción, confirmar y verla después de recargar. Una confirmación reintentada no
  duplica; la corrección conserva revisión y recalcula de forma explicable.
- Vaso aproximado, cantidad indicada y receta desconocida se distinguen. Un
  cambio posterior del proveedor no cambia silenciosamente el consumo pasado.
- Cada recomendación identifica fuente/autor, versión, adaptación y razón de
  activación. Cambiar una meta personal no borra la referencia original.
- Días vacíos, cobertura parcial y rangos que cruzan una referencia se presentan
  sin ceros o garantías de seguridad falsos.
- El catálogo publicado fue revisado y los objetivos de ingesta no se convierten
  en dosis de suplemento, diagnóstico ni órdenes de compensación alimentaria.
- Fallo de proveedor, Home no disponible, sesión expirada, reintento y corrección
  simultánea no filtran datos ni dejan entradas duplicadas o inconsistentes.
- El despliegue y respaldo de los nuevos datos son verificables; Ana completa el
  flujo en su móvil sin asistencia técnica continua. Se recogen dificultades
  reales antes de ampliar alcance. No se promete reconocimiento perfecto.
- Si Telegram es el canal, las verificaciones de interlocutor, aislamiento y
  delegación anteriores pasan con dos personas. Finance del propietario conserva
  su comportamiento y Ana no obtiene acceso por compartir bot.

Audio y foto completos exigen además una prueba real por modalidad, incluyendo
error de extracción, archivo rechazado, cancelación, no confirmado y limpieza de
originales según política. La demo no satisface estos criterios.

## Verificaciones realizadas en esta evaluación

Solo datos sintéticos y pruebas locales; sin cambios productivos ni lectura de
registros personales. No se revalidaron hosts, despliegues ni backups en vivo.

- Dominio Nutrition: **9 pruebas pasan**.
- Servicio, etapa F y autorización seleccionadas: **26 pruebas pasan**.
- Contrato, carga, modelo de perfil y selección de sujeto de Home Hub: **88 pruebas pasan**.

Total: 123 comprobaciones focalizadas del estado existente; no son una prueba
end-to-end del producto propuesto ni una certificación del contenido clínico.
Comandos y resultado estructurado:
[evaluación JSON](../../architecture/reviews/2026-11-15-ana-nutrition-readiness.json).

## Decisiones que no se deben dar por tomadas

- Canal inicial y recorrido cotidiano de Ana, idioma y país de referencias.
- Si acepta comenzar por texto mientras se completan audio/foto.
- Proveedor(s) y tratamiento de medios reales; no se eligieron por este documento.
- Datos contextuales necesarios para reglas personales; no se atribuye a Ana un
  diagnóstico, objetivo energético ni indicación profesional que no haya declarado.

No hay una nueva solicitud de aprobación G2. Las preguntas anteriores definen el
producto y su entrega, no vuelven a autorizar el mismo uso del dominio.

## Revisión de preparación para planificar

Un revisor independiente leyó este borrador. Identificó cuatro cuestiones de
alcance: canal/idioma/país, aceptación del piloto por texto, cobertura mínima del
catálogo y significado de revisión. Las dos primeras ya estaban pendientes de
respuesta del usuario. Las dos últimas se concretaron arriba como propuestas
del agente, sin atribuirlas al usuario ni añadir una puerta clínica implícita.
No señaló otra decisión previa necesaria de arquitectura o implementación.

El documento está listo para discutir esas decisiones; aún no es una
especificación final aprobada ni un plan ejecutable.
