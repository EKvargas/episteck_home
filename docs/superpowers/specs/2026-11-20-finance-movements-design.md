# Olin Finance: movimientos, resumen y ayuda familiar (diseño)

Estado: borrador para aprobación del dueño (2026-11-20). Es un primer corte de la fase I3
de `docs/architecture/proposals/OLIN_FINANCE_V1.md` (§6.3, §6.8, §8.2). Sustituye allí a
`finance_find_movements` y, para ingreso frente a gasto, a `finance_spending`. Añade una
respuesta nueva a las preguntas de I2 (§5.7).

No cambia ningún ADR. La lectura usa solo datos que Finance ya guarda (ADR-0011,
ADR-0016). La única escritura nueva es una respuesta de I2 del mismo tipo que las que ya
existen.

## 1. Intención

El dueño quiere preguntarle a Olin tres cosas que hoy no puede responder:

1. **"¿Cuánto gasté este mes frente a lo que me entró?"**, contando **solo lo suyo**. No
   son ni gasto ni ingreso lo que mueve por los cambios (pagos al socio de cambio, cobros
   de familiares, el fondo), los favores al socio ni los traspasos entre sus cuentas. La
   compraventa de valores tampoco debería serlo, pero hoy no se puede reconocer (§5.5).
2. **"¿Cuánta ayuda le doy a la familia?"**. La ayuda **sí es gasto suyo** y se informa
   aparte, por persona, por mes y por año. Para el dueño es "muy importante".
3. **"¿Llegó tal movimiento, y a qué cuenta?"**. Ejemplo: canceló una compra online y
   quiere saber si el reembolso ya entró y en cuál de sus cuentas.

Las cifras salen del banco o de los registros confirmados de I2. Las calcula Finance,
nunca el modelo (regla G4 de I2).

## 2. Objetivos, no objetivos y anti-objetivos

**Objetivos**
- Buscar movimientos de todas las cuentas visibles por texto, importe, cuenta, fechas y
  sentido. Cada línea dice qué es para Finanzas.
- Resumen de un mes o de un año, por moneda: ingreso propio, gasto propio y neto. Dentro
  del gasto, la ayuda familiar desglosada por persona. Lo excluido sale aparte, con su
  importe.
- Decir con claridad cuándo un dato está incompleto.
- Que el dueño pueda decir "ese dinero es del socio" la primera vez que llega un favor, y
  que después Finance lo reconozca solo.

**No objetivos (quedan para el resto de I3 o para después)**
- Categorías de gasto, presupuestos, recurrentes y suscripciones.
- Clasificar movimientos a mano (`finance_classify`) o enseñar a Olin que una salida
  concreta fue ayuda. Si el reconocimiento automático (§5.3) se queda corto, será lo
  siguiente.
- Valoración en EUR del resumen. Las monedas nunca se suman.
- Tarjetas o cuentas sin conector. Una tarjeta de crédito que ningún proveedor soporta
  solo aparece como el cargo con el que se paga su factura, y cuenta como gasto ese día.
- Importar extractos (CSV o PDF).
- Traspasos propios entre cuentas de monedas distintas: el dueño no los hace fuera de los
  cambios (decisión del 2026-11-20).

**Anti-objetivos (sería un fracaso aunque funcione)**
- Contar como ingreso un cobro de un familiar o el dinero de un favor al socio, o contar
  como gasto el pago al socio de la parte de la familia.
- Dejar fuera del gasto la ayuda familiar, o no poder decir cuánta fue y a quién.
- Que un traspaso entre cuentas propias cuente como gasto, o que movimientos sin detalle
  (que pueden ser compras de valores) cuenten sin avisar.
- Que un mes con datos que faltan parezca un mes con poco gasto.
- Que el modelo invente o sume cifras, o que vea IBANs o números de cuenta.
- Que una consulta escriba algo, gaste lecturas PSD2 o llame a un banco.

## 3. Restricciones

- Las consultas (`finance_movements`, `finance_summary`) son solo lectura: sin tablas
  nuevas, sin `command_log` y sin conectores. Las lecturas PSD2 son de la sincronización
  y no se tocan (tope de 4 por cuenta y día).
- La respuesta nueva de I2 (§5.7) sigue las reglas de I2: un `movement_role` y una
  `payer_rule` con revocación. No cambia el esquema.
- Autorización como en I1: una sola petición a Home por llamada (ADR-0011 §6, ADR-0015).
  Un rechazo no lee nada.
- Nunca se suman monedas distintas (ADR-0011 §4).
- Hechos inmutables: un PENDING que el banco sustituyó por un BOOKED no se cuenta dos
  veces (`supersedes_id`).
- Repo público: pruebas y documentación solo con datos sintéticos.
- Python 3.11 con los pines de `requirements.lock`, también en las pruebas (lección de
  #140).
- No se tocan archivos de Nutrition ni de Home Hub.

## 4. Enfoques considerados

| Enfoque | Qué es | Coste | Decisión |
| --- | --- | --- | --- |
| **A. Herramientas sobre las cuentas conectadas** | Búsqueda y resumen, con la interpretación derivada de los datos de I2, los IBAN propios y reglas fijas | Medio, sin tablas nuevas | **Elegido por el dueño (2026-11-20)** |
| B. A más extractos de la tarjeta de crédito | Lo mismo, más importar el extracto mensual como cuenta "según extracto" | Medio. Necesita el formato real del extracto | Aplazado. Se decide tras unas semanas de uso de A |
| C. I3 completo | Tabla `Classification`, categorías, reglas, recurrentes | Grande (8–12 días según la propuesta) | Descartado ahora. No es lo que se pidió |

A no cierra el paso a C. La interpretación derivada de A será, en I3, el valor por
defecto, que una clasificación del dueño podrá sustituir.

## 5. Diseño

### 5.1 Qué es cada movimiento (interpretación derivada)

Solo se interpreta la versión vigente de cada movimiento: la que no ha sido sustituida.
Los datos de I2 se buscan por la **raíz** (`movement_root`), igual que hace el matcher.
Se aplica la primera regla que encaja:

| # | Condición | `kind` | En el resumen |
| --- | --- | --- | --- |
| 1 | Financiación viva sobre la raíz | `EXCHANGE` (pago al socio, ref `F<n>`, con su parte propia, §5.4) | excluido: socio. La parte propia cuenta como gasto (§5.4) |
| 2 | Recibo BANK vivo sobre la raíz | `FUND` si el pagador es de tipo FUND; si no, `FAMILY` (cobro de `<label>`, ref `R<n>`) | excluido: fondo o familia |
| 3 | Rol vivo sobre la raíz: `FUND_DEPOSIT` → `FUND`; `EXCHANGE_FUNDING` → `EXCHANGE`; `RECEIVABLE_PAYMENT` → `FAMILY`; `PARTNER_SIDE` → `PARTNER_FAVOR` (§5.7) | según el rol | excluido |
| 4 | Pregunta abierta de I2 sobre la raíz (`LINK_FUNDING:<raíz>` o `EXPLAIN_INCOMING:<raíz>`) | `UNCLEAR` (ref `P<n>`) | aparte: sin aclarar |
| 5 | IBAN de la contraparte en `partner_identifier` | `EXCHANGE` | excluido: socio |
| 6 | IBAN de la contraparte en `own_identifier` | `OWN_TRANSFER` | excluido: traspasos |
| 7 | Entrada (> 0) sin rol vivo `NOT_EXCHANGE` cuya clave de pagador (`incoming_key`, la del matcher, con `FINANCE_DESCRIPTION_RULES`) tiene una regla viva. Si la regla apunta a una contraparte PERSON → `FAMILY`; a EXCHANGE_PARTNER → `PARTNER_FAVOR`; a FUND → `FUND` | según la contraparte | excluido |
| 8 | Salida de una cuenta USD por Zelle a una persona reconocida como familiar (§5.3) | `FAMILY_HELP` (ayuda a `<label>`) | **gasto**, y ayuda familiar |
| 9 | Emparejado como traspaso (§5.2) | `OWN_TRANSFER` | excluido: traspasos |
| 10 | Resto | `OWN` (gasto si < 0, ingreso si > 0) | gasto o ingreso |

- **Todo lo que va al socio o viene de su lado queda fuera**, aunque no sea un cambio:
  la regla 5 se aplica también con el rol `NOT_EXCHANGE`. Un favor (alguien de su lado manda
  dólares y el dueño le paga en euros) no es dinero del dueño (decisión del 2026-11-20).
- Con un recibo de un pagador de tipo FUND hay siempre también un rol `FUND_DEPOSIT`. Por
  eso la regla 2 mira el tipo del pagador (decisión mía, tras la revisión).
- La regla de pagador `IGNORE` y el rol `NOT_EXCHANGE` no deciden nada por sí mismos: el
  movimiento sigue por las reglas siguientes.
- Las reglas 5 y 7 cubren el historial anterior al arranque de I2, donde el matcher no
  creó financiaciones ni recibos.
- No hay regla de compraventa de valores: el banco no describe esos movimientos (§5.5).

### 5.2 Traspasos entre cuentas propias (emparejamiento)

Dos movimientos vigentes forman un traspaso si cumplen todo esto:
- están en cuentas distintas, ambas visibles para quien pregunta;
- tienen la misma moneda y el mismo importe absoluto, con signo contrario;
- sus fechas (`booking_date`, si no `value_date`) distan como mucho 5 días naturales
  (cubre unos 3 días hábiles);
- a ninguno le aplicó una regla de la 1 a la 8;
- ninguno es un PENDING sin sucesor de más de 5 días (`stale_pending`).

El emparejamiento es uno a uno y determinista. Primero los pares más cercanos en fecha;
en empate, por orden de `rowid`. Se calcula sobre el periodo pedido ampliado 5 días por
cada lado, para que un traspaso a caballo de dos meses quede emparejado en ambos.

### 5.3 Ayuda familiar

La ayuda familiar es **gasto del dueño**. El resumen la da también aparte, por persona.
Tiene tres fuentes:

1. **La parte propia de un cambio.** Son las líneas de un cambio cuyo pagador es el
   dueño (`OWNER`). La decide el beneficiario de la línea (decisión del dueño):
   - con beneficiario es **ayuda** a esa persona. Si el beneficiario coincide con el
     `label` o un alias de una contraparte PERSON, se usa su `label`; si no, el texto
     tal cual;
   - sin beneficiario es **gasto propio** del dueño (sus gastos en Venezuela). Cuenta en
     el gasto, pero no en la ayuda.

   El importe en EUR de cada línea propia sale de la parte `OWNER` de la financiación
   (`funding_share`). Si hay varias líneas propias, esa parte se reparte en proporción a
   su USD, con redondeo de mayor resto para que las partes sumen exactamente. Si I2 ya
   calcula el importe por línea, se usa ese. Cuenta en la fecha del último pago de la
   financiación, y solo cuando todos sus pagos están BOOKED.
2. **Deudas perdonadas.** Las entradas `FORGIVE` vivas, descontadas sus reversiones,
   cuentan en su moneda y en el mes de su `effective_on`, como ayuda a esa contraparte
   (decisión del dueño).
3. **Zelle a un familiar** (regla 8). Es una salida de una cuenta USD cuyo concepto
   empieza por una pasarela de salida ("ZELLE PAYMENT TO", "ZELLE TO") y cuyo destinatario
   coincide con un familiar conocido. Un familiar es conocido cuando alguna vez pagó al
   dueño: su nombre de remitente (`sender_text`) sale de una entrada con recibo vivo o
   con regla de pagador hacia una contraparte PERSON. Coinciden si, sin la pasarela y
   normalizados como `description_key`, los dos nombres tienen al menos 2 palabras y uno
   contiene todas las del otro.

   Un Zelle a alguien que nunca le pagó no se reconoce: cuenta como gasto `OWN` y Olin
   lo dice si se pregunta por la ayuda.

### 5.4 `finance_summary`: resumen de un mes o un año

`finance_summary(period?)`. `period` es `YYYY-MM` o `YYYY`; por defecto, el mes actual
según la fecha UTC del reloj del servicio. No acepta periodos futuros ni anteriores a 24
meses atrás.

Solo cuentan los movimientos BOOKED vigentes cuya fecha cae en el periodo. Por cada
moneda con alguna cuenta visible o alguna cifra de ayuda:
- `income`: suma de `OWN` mayores que 0.
- `spending`: la suma de estos importes, todos en valor absoluto, con su desglose:
  - `bank`: `OWN` menores que 0;
  - `zelle_help`: `FAMILY_HELP`;
  - `exchange_own`: partes propias de cambios sin beneficiario;
  - `exchange_help`: partes propias de cambios con beneficiario;
  - `forgiven`: deudas perdonadas.
- `family_help`: total (`zelle_help` + `exchange_help` + `forgiven`) y `by_person` (cada
  `label` con su importe, de mayor a menor). Está incluida en `spending`, no se suma
  aparte.
- `net` = `income` − `spending`.
- `excluded`: suma y número por grupo, separando entradas y salidas: `own_transfers`,
  `exchange` (los pagos al socio enteros, de los que sale la parte propia),
  `partner_favor`, `family` y `fund`.
- `undescribed`: número y sumas (entradas y salidas) de los movimientos `OWN` del periodo
  sin nombre ni concepto (§5.5). Sí cuentan en ingreso y gasto; el campo solo avisa.
- `unclear`: número y sumas de `UNCLEAR`. Van aparte y no entran ni en ingreso ni en
  gasto. Un pago al socio sin aclarar puede llevar parte propia que aún no cuenta.
- `pending_bank`: número y sumas de los PENDING del periodo que siguen sin asentar. No
  cuentan.
- `top_spending`: los 5 mayores gastos `OWN`, con el formato de una línea de
  `finance_movements`.

Las cifras van como en `finance_overview`: `amount_minor` y su texto con `format_minor`.

**Completitud.** `complete` es false y `incomplete_reasons` dice por qué cuando:
- `in_progress`: el periodo incluye hoy;
- `history_starts_late`: alguna cuenta tiene su primer movimiento después del inicio del
  periodo;
- `account_stale`: alguna cuenta está desactualizada o su conexión pide reautorización;
- `hidden_accounts`: hay cuentas que quien pregunta no puede ver;
- `exchanges_without_split`: hay pagos al socio en el periodo sin financiación viva, así
  que su parte propia no se conoce (historial anterior a I2 o preguntas sin responder).

La respuesta lista también las `accounts` incluidas, con el formato de §5.6.

### 5.5 Movimientos sin detalle y censo de campos

**Hecho (comprobación de solo lectura en el nodo, 2026-11-20).** La cuenta de efectivo
del bróker llega por Enable Banking con solo importe y fecha. Ninguno de sus movimientos
trae nombre, concepto, IBAN ni id del proveedor. Así que la compraventa de valores no se
puede distinguir de un pago con tarjeta, y la búsqueda por texto no encuentra nada en esa
cuenta (por importe y fecha, sí).

**Decisión del dueño.**
- No hay regla de inversión en este corte:
  - una compra suelta cuenta como gasto;
  - el resumen avisa con `undescribed` (§5.4) y la skill lo dice.

**Censo.** El conector de Enable Banking cuenta, en cada consulta de movimientos de una
cuenta, cuántas filas traen cada campo descriptivo:
- `remittance_information`;
- nombre de `creditor` o `debtor`;
- `bank_transaction_code`;
- `note`;
- `merchant_category_code`;
- `reference_number`.

Escribe una línea de log con la referencia de la cuenta, el total de filas y esos
recuentos: nombres de campo y números, nunca valores.

**Lo que no cambia.** Ni lo que se guarda ni la identidad de los movimientos. Esas filas
no tienen id del proveedor y se identifican por una huella que incluye nombre y concepto,
así que guardar texto nuevo en ellas las duplicaría en la siguiente sincronización.

Tras dos sincronizaciones, el operador lee esa línea. Si el bróker manda algún campo
descriptivo, el siguiente paso es otro diseño: guardar ese texto aparte, fuera de la
identidad del movimiento, y añadir la regla de inversión.

### 5.6 `finance_movements`: búsqueda

`finance_movements(text?, amount?, account?, direction?, since?, until?, limit?)`

| Parámetro | Regla |
| --- | --- |
| `text` | Entre 2 y 60 caracteres. Se compara contra el nombre de la contraparte y el concepto **completos** (en el servidor), sin distinguir mayúsculas ni acentos. Con varias palabras, deben aparecer todas. |
| `amount` | Decimal en texto. Compara el valor absoluto exacto, en cualquier moneda. |
| `account` | Id de cuenta (como en `finance_overview`) o nombre de institución, sin distinguir mayúsculas. Si no existe, devuelve `unknown_account` con la lista de nombres válidos. |
| `direction` | `in` o `out`. |
| `since`, `until` | `YYYY-MM-DD`. Por defecto, los últimos 90 días hasta hoy. Rango máximo: 400 días. |
| `limit` | Por defecto 20; como máximo 50. |

**Resultado**: `{"ok": true, "since", "until", "total_matches", "truncated",
"movements": [...], "accounts": [...]}`. Los movimientos van del más reciente al más
antiguo. Cada línea lleva:
- `date`, `account` (id e institución), `amount` y `amount_minor` con signo, `currency`;
- `status` (`BOOKED` o `PENDING`) y `stale_pending`: true si sigue PENDING sin sucesor más
  de 5 días. Suele ser una retención anulada o un cargo que el banco aún no asentó;
- `who` y `text`, saneados (§5.8);
- `kind` (§5.1) y, si aplica, `about` (el `label` de I2) y `ref` (`F<n>`, `R<n>` o
  `P<n>`), para seguir con `finance_explain`;
- en un `EXCHANGE` con financiación: `own_part` (la parte propia sin beneficiario) y
  `help` (lista de `about` con su importe).

`accounts` lista cada cuenta consultada con `synced_at` (último éxito de su conexión),
`history_from` (fecha del movimiento más antiguo guardado) y `stale` (mismo criterio que
`finance_overview`). Así, "no está" se distingue de "aún no se ha sincronizado".

### 5.7 Favores al socio: respuesta nueva en I2

Caso real: alguien del lado del socio (un familiar suyo) le manda dólares al dueño por
Zelle y el dueño le paga al socio en euros. Es un favor; no es dinero del dueño.

- **Pregunta.** La pregunta `EXPLAIN_INCOMING` ofrece una opción nueva, `PARTNER`, "es
  del socio (un favor)". Solo se ofrece cuando hay exactamente un socio activo.
- **Al elegirla** se escribe el rol `PARTNER_SIDE` sobre la raíz (valor nuevo de
  `MovementRoleKind`; el esquema no cambia). Si `remember` no es false, se escribe también
  una regla de pagador con la clave del remitente hacia la contraparte del socio.
- **Matcher.** Una entrada cuya regla apunta a una contraparte EXCHANGE_PARTNER recibe el
  rol `PARTNER_SIDE` sin recibo ni pregunta (como `IGNORE`, pero apartada como favor).
- **Deshacer.** Los caminos de `NOT_EXCHANGE` cubren también `PARTNER_SIDE`: reabrir la
  pregunta, revocar la regla, `unhide` y `close_settled_questions`.
- **Skill.** La opción se muestra como "Es del socio (un favor)".
- **Euros al socio.** Los euros que el dueño paga en el favor ya quedan fuera por la
  regla 5. Su pregunta `LINK_FUNDING` se contesta con `NOT_EXCHANGE`, como hoy.

### 5.8 Lo que ve el modelo

Hasta ahora el modelo veía saldos y etiquetas de la familia. Esto añade nombres de
comercios y conceptos bancarios, que llegan al proveedor del modelo. Para limitarlo:

- `who` es el nombre de la contraparte o, si falta, el concepto. Se quitan las palabras
  con dígitos y la palabra que sigue a una que termina en `#` (como `description_key`).
  Se quita también el prefijo de pasarela (como `sender_text`). Máximo 40 caracteres.
- `text` es el concepto con la misma limpieza, conservando mayúsculas y minúsculas.
  Máximo 80 caracteres.
- No salen IBANs, hashes, ids de movimiento ni `provider_tx_id`. La búsqueda por `text`
  se hace en el servidor sobre el texto completo. Así, un número de pedido encuentra su
  movimiento aunque luego no se muestre.
- Como mucho 50 líneas por llamada. Los logs llevan solo tipos y cuentas.

### 5.9 Autorización

Es la misma petición única que hace `overview`: `Requirement(SELF, "VIEW")` más VIEW de
cada titular, con el mismo filtro de cuentas por titular. Además, quien pregunta debe
tener el rol OWNER en el workspace, porque la interpretación revela datos de I2 (como
`ReceivablesService`). El workspace debe estar ACTIVE. Los rechazos son los de I1:
`session_invalid`, `access_denied`, `service_unavailable` y `feature_off`. El acceso de
otros miembros (I5) se decidirá entonces.

Las cuentas ocultas no aparecen, no emparejan traspasos y solo cuentan en
`hidden_accounts`. Las cifras de ayuda que vienen de I2 (partes propias y deudas
perdonadas) sí aparecen: son datos del workspace, no de una cuenta.

### 5.10 Contrato de errores

Los errores de dominio usan la forma de I2: `{"ok": false, "error": <code>}`, más
`accounts` en `unknown_account`. Códigos: `bad_text`, `bad_amount`, `bad_date`,
`bad_range`, `bad_direction`, `bad_limit`, `bad_period` y `unknown_account`. Cualquier
otra excepción devuelve `internal_error` sin el mensaje.

### 5.11 REST

Lo exponen `GET /movements` y `GET /summary`, con los mismos parámetros como query.
Llaman a la misma función del servicio: el chat y la web leen lo mismo (ADR-0011). Las
negativas se mapean como en `/overview`, y los errores de dominio como en
`api_receivables`. Ninguna ruta pública nueva: nginx sigue exponiendo solo
`/connect/callback`.

### 5.12 Skill de Olin

`deploy/hermes/home-agent/skills/olin-finance/SKILL.md` pasa a la versión 2.1.0:
- **Cuándo usarlas**: "¿cuánto gasté este mes?", "¿cuánto me entró?", "¿cuánta ayuda le
  di a la familia este año?", "¿cuánto le mandé a <alias>?", "¿llegó el reembolso de …?",
  "¿en qué cuenta entró …?", "busca el pago de …".
- **Respuesta del resumen**: ingreso, gasto y neto por moneda, copiados del resultado.
  Luego la ayuda familiar (total y por persona) como parte del gasto. Después, en una
  línea, lo apartado (familia, socio, favores, fondo, traspasos) y lo sin aclarar. Si
  `complete` es false, decirlo con su motivo. Si hay `undescribed`, decir cuántos
  movimientos sin detalle cuentan y que pueden incluir compras de valores. Nunca sumar
  monedas.
- **Búsqueda en cuentas sin concepto**: el texto no encuentra nada en ellas. Para "¿llegó
  el reembolso?", buscar también por importe.
- **Búsqueda**: buscar primero en todas las cuentas con el texto del comercio. Si no hay
  nada, decir hasta qué fecha está sincronizada cada cuenta (`synced_at`). Un
  `stale_pending` se describe como "retenido, probablemente anulado", nunca como cobrado.
- **Tarjeta no conectada**: sus compras y reembolsos no se ven; solo el pago de su factura.
- **La opción `PARTNER`** se muestra en `EXPLAIN_INCOMING` como "Es del socio (un favor)".
- **Requisitos del skill**: `requires_tools` añade `mcp__finance__finance_movements` y
  `mcp__finance__finance_summary`. El skill debe cubrir todos los códigos de error y
  opciones nuevos (lo comprueba `deploy/hermes/tests/test_olin_finance_skill.py`).

### 5.13 Despliegue

- Tras dos sincronizaciones, leer la línea del censo de §5.5 en el log del servicio.
- Imagen nueva con el SHA del merge. Se instala con el `bringup` del runbook de I2
  (build, smoke de registro de herramientas MCP, install, verify) y se reinstala el skill
  (`install-olin-finance.sh`).
- Sin cambios de esquema ni de configuración. Rollback: reinstalar la imagen anterior y
  el skill anterior. Un rol `PARTNER_SIDE` escrito por la imagen nueva sería desconocido
  para la anterior. Por eso, antes de un rollback se comprueba en solo lectura que no hay
  ninguno; si lo hay, se revoca primero con la imagen nueva.
- Una prueba de humo en Telegram: una pregunta del mes, una de ayuda y una búsqueda.

## 6. Pruebas de aceptación (sintéticas)

| # | Escenario | Resultado esperado |
| --- | --- | --- |
| M1 | Nómina (+) y compras (−) en la cuenta EUR | Ingreso, gasto y neto exactos; `kind` OWN |
| M2 | Traspaso de la cuenta EUR A a la cuenta EUR B, con 2 días de diferencia | Ambos `OWN_TRANSFER`; fuera de ingreso y gasto |
| M3 | Traspaso a un IBAN propio sin la otra cuenta conectada | `OWN_TRANSFER` por la regla 6 |
| M4 | Pago al socio con financiación viva; otro previo al arranque (solo IBAN del socio); otro marcado `NOT_EXCHANGE` | Los tres `EXCHANGE` y excluidos; el segundo y el tercero activan `exchanges_without_split` |
| M5 | Zelle de un familiar con recibo BANK; otro anterior al arranque con regla de pagador | Ambos `FAMILY` con `about`; excluidos |
| M6 | Entrada con pregunta EXPLAIN_INCOMING abierta | `UNCLEAR` con `ref` P<n>; aparte |
| M7 | PENDING y su BOOKED | Cuenta una sola vez |
| M8 | PENDING de hace 9 días sin sucesor | `stale_pending` true; fuera del resumen |
| M9 | Periodo con cuentas EUR y USD | Dos bloques; ninguna cifra mezcla monedas |
| M10 | Búsqueda "reembolso" sin acentos ni mayúsculas, con número de pedido en el concepto | Se encuentra; `text` sin el número |
| M11 | Cuenta oculta para quien pregunta | No aparece, no empareja; `hidden_accounts` |
| M12 | Home niega, no responde o la sesión es inválida | Refusal de I1; no se lee el repositorio |
| M13 | Cuenta con conexión `REAUTH_REQUIRED` | `complete` false con `account_stale` |
| M14 | Traspaso el día 30 que llega el día 2 del mes siguiente | Emparejado en ambos meses |
| M15 | Nada en el resultado contiene un IBAN, un hash o un id | Comprobado con un patrón sobre el JSON |
| M16 | Cambio con una línea propia con beneficiario, una sin beneficiario y una de un familiar; financiación en EUR | Gasto: `exchange_help` y `exchange_own` repartidos por USD, que suman la parte OWNER exacta; la línea del familiar no cuenta; `by_person` con el beneficiario |
| M17 | Financiación con un pago aún PENDING | Su parte propia no cuenta todavía |
| M18 | `FORGIVE` en USD y su reversión en otro mes | Ayuda en el mes del perdón; la reversión la descuenta en el suyo |
| M19 | Zelle de salida a un familiar que antes pagó por Zelle; y otro a un desconocido | El primero `FAMILY_HELP` en gasto y ayuda; el segundo `OWN` |
| M20 | Movimientos sin nombre ni concepto en una cuenta; una consulta de Enable Banking con filas mixtas | `OWN` y contados en `undescribed`; el censo registra solo nombres de campo y recuentos, y lo guardado no cambia |
| M21 | Favor: entrada de un remitente nuevo, respuesta `PARTNER` con `remember`; después, otra del mismo remitente | La primera, `PARTNER_FAVOR` con rol; la segunda, rol sin pregunta; ambas fuera de ingreso |
| M22 | Deshacer la respuesta `PARTNER` | Rol y regla revocados; vuelve la pregunta |
| M23 | Resumen de un año | Igual a la suma de sus 12 meses, por moneda |

## 7. Lo que queda al constructor

- Dónde vive el código (módulo o servicio nuevo junto a `FinanceService` y los repos), y
  cómo se comparte la autorización de `overview` sin duplicarla.
- Cómo cargar de una vez los datos de I2 por llamada. Requisito: 13 meses de 4 cuentas
  en menos de 1 s en el nodo.
- La forma exacta de los errores de dominio en REST, siguiendo `api_receivables`.
- Los textos del skill, dentro de las reglas de §5.12.

## 8. Decisiones del dueño y decisiones mías

**Del dueño (2026-11-20):**
- Enfoque A, solo con cuentas conectadas; la tarjeta solo se ve al pagar su factura.
- Separar lo suyo de lo de la familia, y buscar en todas las cuentas.
- Apartar la compraventa de valores. El bróker no la describe (§5.5): el dueño
  eligió el censo (A); la regla de plan fijo (B) no aplica en su caso.
- No hay traspasos propios entre monedas fuera de los cambios.
- La ayuda familiar es gasto suyo y se informa aparte, con estas fuentes:
  - la parte propia de un cambio es ayuda si tiene beneficiario y gasto propio si no;
  - perdonar una deuda es ayuda en el mes del perdón;
  - también manda ayuda por Zelle desde la cuenta USD.
- Los favores al socio quedan fuera, con una respuesta nueva que se recuerda.

**Mías (puede corregirlas):**
- Nombres y forma de las herramientas: `finance_movements`, y `finance_summary` con mes o
  año.
- Rangos: ventana de 90 días por defecto y máximo de 400; emparejar en ±5 días.
- En el resumen cuentan solo los BOOKED; `top_spending` de 5.
- Autorización: se exige el rol OWNER.
- El periodo por defecto sale de la fecha UTC.
- El saneado de §5.8 y el REST incluido.
- Detalles de las reglas:
  - la regla 2 mira el tipo de pagador;
  - el beneficiario sin contraparte cuenta tal cual;
  - el reparto de la parte propia es proporcional al USD;
  - la fecha de la parte propia es la del último pago BOOKED;
  - el criterio de coincidencia de nombres en Zelle.
