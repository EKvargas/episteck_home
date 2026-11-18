# Olin Finance I2: intercambios familiares (diseño)

**Fecha:** 2026-11-18 · **Estado:** borrador para aprobación del dueño. No autoriza implementación ni despliegue.
**Base:** `origin/main` `ac2ea50` (Finance I1 cerrado y live; B11 F1–F3 #126, nft al arranque #127).
**Relación con la propuesta v1:** sustituye §5.2, §6.5, §9.1 y la fila I2 de §11 de
[`OLIN_FINANCE_V1.md`](../../architecture/proposals/OLIN_FINANCE_V1.md). El resto de la propuesta (§6.7 integridad,
§6.8 doble conteo, §7.4 permisos, §8.3–8.4 confirmación y memoria) sigue vigente salvo donde este documento diga otra cosa.
Incluye el diseño de **I4a** (web de intercambios), que se implementa en un PR posterior.

**Datos:** todo ejemplo es sintético. Las personas son "Familiar A/B/C", "Fondo F" y "el socio de cambio". Ningún
nombre, importe, identificador, teléfono ni frecuencia real va al repo, que es público.

---

## 1. Intención

El intercambio familiar es el área de finanzas más importante para el dueño. Hoy todo pasa por WhatsApp y no queda
registro. El objetivo es que, con mínimas intervenciones, el dueño sepa **en todo momento**:

- **quién le debe qué**, en qué moneda y de qué cambios viene;
- **dónde está o adónde llegará** ese dinero (cuenta USD, cuenta EUR, efectivo guardado en Venezuela);
- **qué dinero de otros guarda** él (un fondo de un tercero custodiado en su cuenta, prepagos);
- **qué le debe él al socio de cambio** (el cambio todavía no pagado).

El banco detecta los pagos y Olin pregunta por Telegram, con botones, solo lo que el banco no puede saber.

## 2. Cómo funciona hoy (proceso real, en abstracto)

```
1. Si debe el cambio anterior al socio, el dueño se lo paga en EUR      ← el feed EUR lo ve (IBAN del socio)
2. El dueño ofrece dólares en el grupo familiar: "¿quién quiere vender?"
3. Junta las peticiones: Familiar A 120 · propio 40 · Fondo F 60 · …    (en USD)
4. Pide al socio: "necesito 300 USD"
5. El socio transfiere VES a la cuenta central en VES de un familiar    ← captura del pago (Pago Móvil)
6. Ese familiar reparte los VES a los beneficiarios
7. Cada familiar devuelve al dueño en su moneda, a veces acumulado       ← feed USD/EUR, o efectivo
```

Hechos que el diseño respeta:

- **La moneda del trato es el USD.** Cada cambio se cierra en USD con el socio. El dueño convierte USD→EUR con una
  herramienta externa (Oanda) y paga EUR a una cuenta del socio. El socio **paga primero**; el dueño paga ese cambio
  justo antes de pedir el siguiente. Pocos cambios al mes.
- **Un cambio tiene líneas de distinta naturaleza.** En cada línea paga alguien distinto: un familiar, que pasa a
  deber; el propio dueño, que gasta en Venezuela y nadie le debe; o un **fondo custodiado** de un tercero (dinero
  ajeno guardado en la cuenta USD del dueño, del que salen gastos del titular). Línea y beneficiario pueden diferir.
- **Cada familiar paga en una moneda y por una vía:** USD a la cuenta USD (banco); EUR a la cuenta EUR, por el
  equivalente que el dueño calculó; USD en efectivo que le guardan en Venezuela hasta que viaja (es **deuda**, a
  veces con los billetes ya apartados); o **en especie** (p. ej. una gift card) con el valor que fije el dueño.
- **Orden variable:** normalmente el dueño adelanta y el familiar paga después; a veces paga antes (prepago). A veces
  paga varias ventas juntas.
- **El dueño ya escribe el reparto** en el grupo al reenviar la captura del socio ("300: 120 A, 40 mío, 60 fondo…") y a
  veces lo corrige sobre la marcha.
- **El saldo del Fondo F es desconocido** hoy (entró de una sola vez hace tiempo; puede quedar algo o estar agotado).

## 3. Objetivos, no objetivos, anti-objetivos

**Objetivos**

| # | Objetivo | Medida |
| --- | --- | --- |
| G1 | Saldos por persona y moneda, con desglose por cambio, procedencia y "dónde" | `finance_receivables` responde todo desde datos registrados |
| G2 | Una intervención fija por cambio (reenviar captura + reparto, y confirmar) | ≤ 2 toques por cambio; total de intercambios ≤ 10/mes |
| G3 | El banco como red de seguridad: ningún pago al socio ni cobro familiar queda sin explicar | todo movimiento relevante sin explicar genera un pendiente |
| G4 | Cifras solo del banco o del dueño; lo derivado, determinista | tipo implícito, partes en EUR y saldos calculados en Finance, nunca por el LLM |
| G5 | Mismas funciones para chat y web (I4a) | la API REST y las herramientas MCP llaman a la misma capa de servicio |

**No objetivos (I2):** valorar VES; seguir el reparto de VES dentro de Venezuela; registrar el tipo o el margen del
socio; fiscalidad; mover dinero; leer WhatsApp (I6); que los familiares hablen con Olin; clasificar gasto general
(I3); la web (I4a, PR aparte).

**Anti-objetivos (sería un fracaso aunque funcione):**

- Olin inventa o estima una cifra (p. ej. "al fondo le quedarán ~2.000").
- El pago al socio cuenta como gasto o un cobro familiar como ingreso.
- Olin pregunta algo que el banco ya respondió, o pregunta cada movimiento ajeno a los intercambios más de una vez.
- Un dato real (nombre, importe, IBAN, teléfono, referencia) llega al repo, a un log o a la memoria de Hermes.

## 4. Restricciones

- **ADR-0011:** Finance es la fuente de verdad, los hechos son inmutables y nunca mueve dinero. I1 era solo lectura;
  I2 añade **escrituras en el libro propio de Finance** (no dinero). Esto requiere un **ADR-0016** nuevo (§13).
- **ADR-0015:** una petición a Home por operación (`authorize_batch`), sin parámetro de actor. Lecturas: `FINANCE/VIEW`
  sobre `SELF`. Escrituras: `FINANCE/CREATE` sobre `SELF` (Home ya concede *self-access* para cualquier acción,
  `policy/access.py`). Home caído → nada se lee ni se escribe.
- **LLM:** Hermes (`openai-codex`, decisión P2) extrae de texto y capturas y llama a herramientas tipadas. Finance
  valida. Las capturas llevan datos de terceros (cédulas, teléfonos) que ya viajan a OpenAI al reenviarlas; Finance
  **no guarda** ni la imagen ni esos datos (§6.9).
- **Feeds:** sync a las 06:20 y 18:20 UTC (`finance-sync.timer`), PSD2 ≤ 4 accesos/día. La cuenta EUR vía Enable
  Banking trae `counterparty_name` e IBAN del destinatario en las salidas. La cuenta USD vía SimpleFIN trae **solo la
  descripción** (`counterparty_name` vacío): el pagador se reconoce por la descripción normalizada. Los movimientos
  `PENDING` pasan a `BOOKED` con una fila nueva que *supersede* a la anterior.
- **Telegram** (`@EpisteckHome_bot`, solo el dueño) es el canal v1. Que Hermes escriba **por iniciativa propia**
  (cron → Telegram) y los **botones** en esos mensajes **no están verificados** en Hermes 0.21.2.
- **Trabajo en paralelo:** Codex trabaja en Nutrición en el mismo repo. I2 no toca archivos de Nutrición ni de
  `apps/home-hub`. I4a toca el Hub y espera el visto bueno del dueño.
- **Despliegue:** bringup del operador en Nuremberg con build por SHA (`bringup.sh build`, etiqueta
  `org.opencontainers.image.revision`). El esquema se crea con `CREATE TABLE IF NOT EXISTS` al arrancar: I2 solo
  **añade** tablas, no altera las de I1.

## 5. Enfoques considerados

| Enfoque | Qué es | A favor | En contra |
| --- | --- | --- | --- |
| A. Ampliar §6.5 | Máquina de estados por solicitud (`REQUESTED → FUNDED → … → OWED → SETTLED`) más multimoneda, efectivo, fondo y deuda con el socio | Diseño ya revisado | Modela pasos que no existen (acordar la deuda tras la entrega, confirmación del receptor): cada estado es una pregunta más; fondo y socio quedan como añadidos; ~10 tablas |
| **B. Cambio con líneas + cuenta corriente** | Un `Cambio` en USD con líneas (quién paga, para quién, en qué moneda) y, por persona y moneda, un libro de solo altas; los cobros se aplican a líneas | Calca el flujo real; un mismo mecanismo cubre deuda, adelanto, prepago y fondo; menos preguntas | Reescribe §6.5 de la propuesta |
| C. Doble entrada completa | Contabilidad tipo Beancount (activos, pasivos, cuentas por cobrar, gastos, conversiones) | Rigor y generalidad; podría absorber I3 | Mucha maquinaria, difícil de explicar en lenguaje llano, se solapa con I3 |

**Elegido: B** (dueño, 2026-11-18). A añade preguntas sin valor y C es complejidad prematura.

## 6. Modelo

Todas las tablas llevan `workspace_id`. Dinero en enteros de unidades menores + moneda ISO (`money.py`). Las tablas
marcadas *(solo altas)* tienen triggers que impiden `UPDATE`/`DELETE`, como `movement` en I1.

### 6.1 Contrapartes

**`Counterparty`**: `id`, `kind` (`PERSON` | `EXCHANGE_PARTNER` | `FUND`), `label` (etiqueta privada del dueño),
`aliases[]`, `status` (`ACTIVE` | `ARCHIVED`), `home_person_id` opcional (sin uso en I2).

- `PERSON`: `pay_currency` por defecto (`USD` | `EUR`) y `settles_to`: cuenta del workspace donde suele pagar, o
  `CASH_ABROAD`. Determina la moneda de la deuda de sus líneas y el "dónde".
- `EXCHANGE_PARTNER`: el socio de cambio. Lleva sus identificadores de pago (hash de IBAN). Puede haber más de uno.
- `FUND`: fondo custodiado de un tercero. `currency` (USD), `held_in_account_id`, `opening` (`UNKNOWN` |
  `APPROXIMATE` | `CONFIRMED`) y `low_balance_alert_minor` opcional.
- Las contrapartes **no son principales** de Home: figurar como deudor no concede nada (v1 §7.4).

**`PayerRule`** *(solo altas; la última no revocada manda)*: `match_key_hash` → `counterparty_id` o `IGNORE`. La clave
es el hash con *pepper* (`hash_iban` de I1) del IBAN de la contraparte (Enable Banking) o de la **descripción
normalizada** (SimpleFIN: mayúsculas, sin dígitos ni fechas, espacios colapsados). Se crea cuando el dueño contesta
un pendiente con "recordar" (opción por defecto).

### 6.2 Cambios

**`Exchange`**: `id`, `partner_id`, `total_usd_minor`, `delivered_on` (fecha del pago del socio), `evidence`
(`ves_amount_minor`, `ves_reference_hash`, fecha; sin imagen), `created_by_command`. El estado se **deriva**:
`OPEN` (se le debe al socio) o `PAID` (hay un `Funding` vigente que lo incluye).

**`ExchangeLine`**: `id`, `exchange_id`, `payer` (`counterparty_id` de `PERSON`/`FUND`, o `OWNER`), `usd_minor`,
`beneficiary_note` opcional (privada), `debt_currency` (la `pay_currency` del pagador al registrar; se puede corregir).
**Invariante:** Σ `usd_minor` de las líneas vigentes = `total_usd_minor`.

**`Funding`** *(solo altas, revocable con `Reversal`)*: une un conjunto de movimientos EUR salientes hacia el socio con
un conjunto de cambios. Normalmente es 1 pago ↔ 1 cambio; admite 1 pago ↔ varios cambios y 1 cambio ↔ varios pagos.

- **Tipo implícito** = Σ EUR / Σ USD, calculado con enteros y mostrado con 4 decimales. Nunca se guarda como `float`
  ni se teclea.
- **Partes en EUR:** cada línea recibe `usd × tipo`, y el reparto de los céntimos usa el **resto mayor**, de modo que
  Σ partes = Σ EUR pagado exactamente. Es determinista: misma entrada, mismo reparto.
- Un movimiento o un cambio pertenece como mucho a un `Funding` vigente.
- Los enlaces apuntan al movimiento; si un `PENDING` es superado por su `BOOKED`, el enlace se resuelve al vigente.
- **Control de cordura:** si el tipo implícito se desvía más de un **3 %** del de referencia BCE de esa fecha (tabla
  `fx_rate` de I1), el `Funding` se registra igual y se genera un aviso para que el dueño lo revise.

**Enlace automático de un pago al socio** (salida EUR hacia un IBAN conocido del socio, `PENDING` o `BOOKED`):

1. **Candidatos:** cambios `OPEN` con `delivered_on` ≤ fecha del movimiento.
2. **Compatibles:** candidatos cuyo tipo implícito, con ese pago, cae dentro de **±8 %** del BCE.
3. **Exactamente un compatible:** `Funding` automático. En el ciclo normal, el cambio N+1 se registra después del pago
   de N, o tiene otro importe y no es compatible, así que no hay pregunta.
4. **Ninguno compatible:** el pago queda **sin enlazar en espera**. Si un pago siguiente al socio hace que la **suma**
   de los pagos sin enlazar sea compatible con un cambio, se enlazan juntos (pago partido).
   - Si en el sync siguiente sigue sin enlazar, se genera `LINK_FUNDING`, que además ofrece `[Añadir al cambio ya
     pagado de <fecha>]`. Esa opción revierte y rehace ese `Funding`.
5. **Varios compatibles:** `LINK_FUNDING`.

**Deuda con el socio** = Σ `total_usd` de los cambios `OPEN`. Se deriva y no tiene libro propio.

### 6.3 Cuenta corriente

**`LedgerEntry`** *(solo altas)*: `id`, `counterparty_id`, `currency`, `amount_minor` con signo, `kind`,
`effective_on`, `source_ref` (línea, cobro o corrección), `note`.

- **Signo:** `+` el dueño tiene derecho a cobrar (te deben); `−` el dueño guarda dinero de esa contraparte (prepago,
  fondo). **Saldo** (contraparte, moneda) = Σ `amount_minor`.
- `kind`:
  - `CHARGE`: por una línea. En las líneas `USD` nace al registrar el cambio. En las líneas `EUR` nace cuando el cambio
    queda pagado y su parte en EUR es conocida. Hasta entonces la línea se muestra "por fijar: N USD (en EUR al pagar
    al socio)" y no entra en el saldo EUR.
    - **Cifra de la línea EUR** (dueño, 2026-11-18): el dueño calcula en Oanda lo que le deben **el mismo día que paga
      al socio**, así que la regla es su parte exacta de ese pago.
    - **Cifra dicha por el dueño:** si al registrar o corregir el cambio la da ("80 = 73,50 €"), esa manda.
    - **Diferencias pequeñas:** si un cobro deja una diferencia de **1,00 € o menos** con lo pendiente de esa persona
      (en cualquier sentido), se cierra con un `ADJUSTMENT` automático y un aviso `INFO`. Así el redondeo de cada
      lado nunca deja saldos de céntimos.
  - `PAYMENT`: por un cobro (negativo).
  - `OPENING`: saldo inicial dicho por el dueño, con `basis` `APPROXIMATE` o `CONFIRMED` y una nota de procedencia
    obligatoria ("según el dueño, a fecha X").
  - `ADJUSTMENT`, `FORGIVE` (se convierte en regalo) y `REVERSAL` (anula otra entrada por referencia).
- Las líneas del **dueño** (`OWNER`) no generan entradas: su parte en EUR queda en la línea como gasto propio (I3 la
  usará). Las líneas de un **fondo** generan `CHARGE` contra el fondo (su saldo negativo se reduce).

**`Receipt`** *(solo altas)*: `kind` (`BANK` | `CASH` | `IN_KIND`), `movement_id` si es `BANK`, `payer_id`,
`currency`, `amount_minor`, `received_on`, `verification` (`BANK_POSTED` | `OWNER_CONFIRMED`) y `description`
(obligatoria en `IN_KIND`, p. ej. "gift card"). Genera su `PAYMENT`. Un ingreso que pertenece a un fondo (un depósito
del titular) es un `Receipt` cuyo pagador es el fondo: su saldo se hace más negativo.

**`Allocation`** *(solo altas, revocable)*: `receipt_id` → `exchange_line_id`, `amount_minor`, `method` (`AUTO_EXACT`
| `AUTO_FIFO` | `OWNER`). Explica **de cuáles cambios** viene lo cobrado; el saldo no depende de ella.

- Invariantes: Σ por cobro ≤ importe del cobro; Σ por línea ≤ deuda de la línea; misma moneda.
- **Regla automática** sobre las líneas abiertas del mismo pagador y moneda:
  1. Si hay un subconjunto cuya deuda pendiente suma exactamente el cobro, se aplica a ese subconjunto (`AUTO_EXACT`).
     Si hay varios, se elige el formado por las líneas más antiguas.
  2. Si no lo hay, se aplica en orden de antigüedad (`AUTO_FIFO`).
  3. El remanente queda **a favor** y se consume con las siguientes líneas de ese pagador.
- La asignación **nunca genera pregunta**, porque no cambia el saldo. El dueño puede reasignar.
- La búsqueda del subconjunto exacto se limita a las 16 líneas abiertas más antiguas. Por encima, FIFO.

**`HeldCashStatement`** *(solo altas; la última vigente manda)*: `counterparty_id`, `currency`, `amount_minor`,
`stated_on`. El dueño declara "me guarda N en efectivo". Solo cambia **cómo se muestra** la deuda ("N USD · guardados
en efectivo en Venezuela"); el valor mostrado se limita al saldo. Al registrar un cobro en efectivo de esa persona, el
efectivo guardado mostrado baja en ese importe.

### 6.4 Pendientes y avisos

**`PendingItem`** (cola única): `code` corto y único en el workspace (`P7`), `kind`, `requires_answer`, opciones
sugeridas (para botones), `dedupe_key`, `created_at`, `delivered_at`, `resolved_at`, `snooze_until`.

| `kind` | Cuándo | Opciones |
| --- | --- | --- |
| `LINK_FUNDING` | Pago EUR al socio que no se enlazó solo (§6.2: varios compatibles, o ninguno tras un sync) | un botón por cambio abierto, `[Todos]`, `[Añadir al cambio ya pagado de <fecha>]`, `[Registrar el cambio]`, `[No es un cambio]` |
| `PREVIOUS_UNPAID` | Se registró un cambio, **ha corrido al menos un sync después** y el anterior sigue `OPEN` (el pago aún no llegó o fue a un IBAN desconocido) | `[Ya lo pagué: elegir el pago]` (lista pagos EUR salientes recientes, no enlazados), `[Aún no]` |
| `EXPLAIN_INCOMING` | Ingreso en una cuenta vigilada sin `PayerRule` | primero la persona o el fondo cuya deuda pendiente (o una suma de líneas) coincide **exactamente** con el importe, si hay solo una; después el resto con saldo en esa moneda, `[Otro familiar]`, `[No es de intercambios]` (todas recuerdan por defecto) |
| `CONFIRM` | Comando de nivel 2 pendiente de "Sí" (§8.3) | `[Sí]`, `[Corregir]`, `[Cancelar]` |
| `REVIEW_OPENING` | Contraparte con apertura aproximada o desconocida, una vez por semana durante la carga inicial | `[Confirmar]`, `[Más tarde]` |
| `INFO` (sin respuesta) | Avisos: cambio pagado y cerrado, cobro aplicado, tipo fuera de rango, fondo por debajo del umbral | — |

- **Cuentas vigiladas:** la cuenta USD y la cuenta EUR (marca por cuenta, configurable). Las salidas de cualquier
  cuenta EUR se comparan con los IBAN del socio.
- **Al aprender el IBAN del socio** desde un pago elegido (`PREVIOUS_UNPAID`, `LINK_FUNDING`), Finance guarda su hash:
  el dueño **nunca teclea un IBAN**.
- **Ingresos fuera de los intercambios:** no se pregunta por los que vienen de una cuenta propia del workspace
  (IBAN propio) ni por los que coinciden con una regla `IGNORE`. Así, el sueldo se pregunta una sola vez.

**`InterventionLog`**: una fila cada vez que el dueño resuelve un pendiente o confirma algo (v1 §2). Alimenta el
contador mensual.

### 6.5 Fondos

- Un fondo se crea en la carga inicial con `opening=UNKNOWN`. Mientras sea así, Olin muestra "saldo inicial sin
  confirmar; desde <fecha> salieron N USD" y **no** muestra "de los cuales" en la cuenta ni avisa de saldo bajo.
- Si el dueño da un saldo (`APPROXIMATE` o `CONFIRMED`), se registra como `OPENING`. Desde ahí sí aparece "de los
  cuales ≈ N son del fondo" junto a la cuenta que lo contiene, y el aviso de saldo bajo (umbral configurable; 500 USD
  por defecto).
- **Saldo que cruza a positivo:** el dueño está adelantando los gastos del titular. Olin lo muestra tal cual ("el fondo
  está en +N: lo estás adelantando tú") y no decide nada.
- **Reconstrucción desde la exportación del chat de WhatsApp** (dueño, 2026-11-18: sí; tarea opcional al final de I2):
  1. El dueño exporta el chat del grupo **sin multimedia** y lo envía como fichero al bot.
  2. El fichero se procesa **solo en Nuremberg** con un extractor **determinista** de `svc-finance`, por comando del
     operador. Busca las líneas de reparto ("<importe> <etiqueta>") con un vocabulario de etiquetas del fondo que da
     el dueño. **El chat entero no pasa por el LLM.**
  3. El extractor propone una lista de gastos del fondo con fecha. El dueño la revisa por tandas y confirma los
     totales, junto con el importe y la fecha de la entrada inicial.
  4. Resultado: un `OPENING` `CONFIRMED` con procedencia "reconstruido desde la exportación del chat, confirmado por
     el dueño el X", que sustituye a la apertura `UNKNOWN` mediante `REVERSAL` y entrada nueva.
  5. El fichero se **borra** al terminar. Nunca pasa por el portátil ni por Git; los tests usan un chat sintético.
  - El formato exacto de la exportación (fecha y hora según el idioma del móvil) se verifica con un fichero
    sintético hecho a mano antes de tocar el real.

### 6.6 Lectura: qué ve el dueño

`finance_receivables` y su equivalente REST devuelven, con fecha de consulta:

```
Te deben
• Familiar A   120,00 USD → cuenta USD    · cambios 13/11 (120)
• Familiar B    73,60 EUR → cuenta EUR    · cambio 13/11 (80 USD a 0,9200)
• Familiar C   150,00 USD · guardados en efectivo en Venezuela · apertura aproximada (según el dueño, 18/11)
• Por fijar: Familiar B 50 USD (cambio 20/11, en EUR al pagar al socio)
Guardas de otros
• Fondo F      saldo inicial sin confirmar; desde 18/11 salieron 60,00 USD (cuenta USD)
• Familiar D    20,00 USD a su favor (prepago)
Debes al socio
• 300,00 USD (cambio 20/11)
```

Con subtotales **por moneda**, sin sumar monedas distintas y sin sumar nada a "Disponible" (v1 §6.8). El VES aparece
solo como evidencia del cambio.

### 6.7 Clasificación de movimientos (la parte que I2 necesita)

I2 marca solo lo suyo, en una tabla `MovementRole` *(solo altas, revocable)*: `EXCHANGE_FUNDING` (pago al socio),
`RECEIVABLE_PAYMENT` (cobro familiar), `FUND_DEPOSIT` o `NOT_EXCHANGE` (respuesta "no es de intercambios"). La
clasificación general de gasto e ingreso es I3, que leerá estos roles para no contarlos como gasto ni ingreso. La
parte `OWNER` de un `Funding` es el gasto propio en Venezuela para I3.

### 6.8 Correcciones

Ningún hecho se edita.

- **Corregir un cambio** (líneas o total) crea una versión nueva de las líneas: `REVERSAL` de las entradas antiguas y
  entradas nuevas.
- **Si el cambio ya estaba pagado**, se recalculan **todas** sus partes en EUR con el mismo `Funding`.
- **Las asignaciones afectadas** se revocan y se rehacen con la regla automática.
- **Revertir un `Funding`, un cobro o una regla** sigue el mismo patrón.
- **Límite:** no se puede corregir una línea por debajo de lo ya cobrado sin reasignar antes; el error lo dice con cifras.

### 6.9 Privacidad y almacenamiento

- Etiquetas, alias y notas de beneficiario viven solo en la base de Nuremberg (y su backup cifrado). Nunca en logs,
  salidas de sync ni Git.
- Referencias del pago VES e identificadores de pago: **solo hash con pepper**. No se guardan imágenes, cédulas ni
  teléfonos.
- Los logs del servicio dicen tipos y contadores, nunca nombres ni importes (patrón I1).

## 7. Flujos

**F1. Registrar un cambio** (la intervención fija).

1. El dueño reenvía a Olin la captura del socio con el reparto ("300: 120 A, 40 mío, 60 fondo, 80 B").
2. Hermes extrae el total, las líneas (alias, USD y beneficiario opcional) y, de la captura, el importe VES, la fecha
   y la referencia. Llama a `finance_record_exchange`.
3. Finance:
   - resuelve los alias; si alguno es ambiguo, devuelve `clarification_needed` con candidatos;
   - comprueba Σ líneas = total; si no cuadra, devuelve un error con las dos cifras y Olin pregunta;
   - comprueba que la referencia VES no esté ya registrada; si lo está, devuelve `possible_duplicate`;
   - devuelve el **eco** con un `CONFIRM`: "Cambio 300 USD (13/11): A 120 (USD) · B 80 (EUR, por fijar) · tuyo 40 ·
     Fondo F 60. ¿Registro?" `[Sí] [Corregir]`.
4. Con el "Sí" quedan las líneas y los `CHARGE` USD. Si había un cambio anterior abierto, aparece `PREVIOUS_UNPAID`.

**F2. Pago al socio (banco).** El sync trae una salida EUR hacia un IBAN del socio.

- **Un único cambio abierto:** se crea el `Funding` sola. Fija el tipo, las partes en EUR y los `CHARGE` EUR, y
  manda un aviso `INFO` ("Cerré el cambio del 13/11 con tu pago de 276,00 €; tipo 0,9200").
- **Si no:** `LINK_FUNDING`.
- **Cero intervenciones** en el caso normal.

**F3. Cobro por banco.** Ingreso en una cuenta vigilada.

- **Con `PayerRule`:** se crea el `Receipt BANK_POSTED`, la `Allocation` y un aviso `INFO` ("A te pagó 120 USD; cubre
  el cambio del 13/11; le quedan 0").
- **Sin regla:** `EXPLAIN_INCOMING`. La respuesta crea la regla, y el siguiente cobro de esa persona va solo.

**F4. Cobro en efectivo o en especie.** "C me dio 150 USD" / "B me dio una gift card que cubre 50 USD".

- Llama a `finance_record_receipt` y pasa por el eco + `CONFIRM`.
- **Importes de 500 USD o equivalente, o más:** en I2 el eco lo dice expresamente ("importe alto") y sigue en
  Telegram (decisión del dueño). En I4a pasa a la web.

**F5. Efectivo guardado.** "C me tiene guardados 150". Llama a `finance_mark_held_cash` (nivel 1: solo cambia cómo
se muestra, reversible).

**F6. Consultas.** "¿Cuánto me debe A y de qué cambios?", "¿cuánto le debo al socio?", "¿qué queda del fondo?" →
`finance_receivables` / `finance_exchanges`. Toda cifra sale de la herramienta en ese turno (skill, v1 §8.4).

**F7. Correcciones y regalos.** "No, eran 100 de A y 60 de B" → `finance_correct_exchange` (+ `CONFIRM`).
"Lo de A déjalo como regalo" → `finance_forgive` (+ `CONFIRM`).

**F8. Carga inicial** (una vez, conversación guiada por la skill):

1. Crear las contrapartes: alias, `kind`, moneda y vía de pago. El fondo con `opening=UNKNOWN`.
2. Saldos abiertos de hoy como `OPENING` con procedencia. Cada uno pasa por un `CONFIRM`.
3. El cambio abierto de hoy, por F1.
4. Aprender el IBAN del socio eligiendo uno de sus pagos recientes.
5. Activar las cuentas vigiladas.

**F9. Avisos proactivos.** Un **cron de Hermes** a las 06:35 y 18:35 UTC (15 min después del sync):

- Llama a `finance_pending(for_delivery=true)`, que devuelve los pendientes no entregados y los marca como
  entregados.
- Escribe por Telegram: preguntas con botones y avisos agrupados en un solo mensaje.
- Si no hay nada, **no escribe**.
- Las preguntas sin respuesta se recuerdan en el siguiente envío del día siguiente, como mucho una vez al día por
  pendiente.
- **Los botones resuelven por código:** `finance_resolve_pending(code, choice)`. Así funciona desde cualquier sesión
  de Hermes, aunque el cron corra en otra.
- **Si la prueba previa demuestra que el cron no puede mostrar botones**, el mensaje lleva opciones numeradas y el
  dueño contesta "P7 2". Finance acepta las dos formas.

## 8. Contratos

### 8.1 Herramientas MCP

Sin actor, workspace, token ni SQL; los nombres los resuelve Finance (v1 §8.2).

| Lectura | Escritura |
| --- | --- |
| `finance_receivables(counterparty?)` | `finance_record_exchange(total_usd, lines[], evidence?, delivered_on?)` → `CONFIRM` |
| `finance_exchanges(status?, since?)` | `finance_record_receipt(payer, amount, currency, kind, received_on?, description?)` → `CONFIRM` |
| `finance_pending(for_delivery?)` | `finance_resolve_pending(code, choice, details?)` |
| `finance_explain(ref)`: historial y correcciones | `finance_mark_held_cash(counterparty, amount, currency)` |
| `finance_overview` (I1, sin cambios de contrato) | `finance_correct_exchange(exchange_ref, lines[], reason)` → `CONFIRM` |
| | `finance_reallocate(receipt_ref, allocations[])`, `finance_forgive(target, amount?, reason)` → `CONFIRM` |
| | `finance_setup_counterparty(label, kind, aliases[], pay_currency?, settles_to?)` → `CONFIRM`, `finance_reverse(ref, reason)` → `CONFIRM` |

- **Importes** como cadenas decimales ("120.50") con su moneda; Finance los convierte con `parse_amount` (I1). Nunca
  `float`.
- **Idempotencia y repeticiones reales:**
  - Una escritura con carga idéntica a otra ya **completada** ese día devuelve `possible_duplicate` con
    `[Es otro] [Es el mismo]`, en vez de ignorarse en silencio (dos "C me dio 50 USD" el mismo día pueden ser reales).
  - "Es otro" añade un sufijo de unicidad a la clave.
  - Un reintento del agente sobre un `CONFIRM` todavía abierto devuelve ese mismo `CONFIRM`.
  - En `record_exchange`, la referencia VES (si existe) es la clave natural de duplicado.
  - `resolve_pending` es idempotente por `(code, choice)`.
  - Todo pasa por `run_command` (`command_log`).
- **Acciones de nivel 3 antes de I4a** (decisión del dueño, 2026-11-18): el efectivo ≥ 500 USD y la reversión de
  interpretaciones de hechos bancarios (`Funding`, cobro `BANK_POSTED`, `PayerRule`) se confirman en Telegram con
  `CONFIRM` y eco reforzado hasta que exista I4a. **Nunca** se alteran los movimientos del banco, solo su
  interpretación. ADR-0016 recoge la excepción y su caducidad (al desplegar I4a).
- **Confirmación de nivel 2 en dos fases:**
  1. El comando devuelve `{"status":"confirmation_required","code":"P9","echo":…}` y no escribe nada salvo el
     `PendingItem`.
  2. `finance_resolve_pending("P9","yes")` ejecuta la carga **guardada** (no la reenvía el modelo).
  El riesgo residual de v1 §8.3 sigue aceptado.
- **Rechazos** iguales que en I1 (`session_invalid`, `access_denied`, `service_unavailable`, `feature_off`), más
  `validation_error` (con campo y cifras), `clarification_needed` (con candidatos), `possible_duplicate` e
  `idempotency_conflict`.

### 8.2 API REST (para I4a)

`GET /receivables`, `GET /exchanges`, `GET /pending`, `POST /commands/{type}` (mismo cuerpo que las herramientas, con
`Idempotency-Key`) y `POST /pending/{code}/resolve`. Misma capa de servicio, misma autorización (cabecera
`X-Episteck-Delegation`, como `/overview`). Solo para el puerto loopback `:9935`, alcanzable únicamente por
`www-data` (F1 de B11).

### 8.3 Skill de Hermes

`olin-finance` se amplía:

- **Cuándo usar las herramientas nuevas:** captura y reparto → `record_exchange`; "me dio / me pagó" → `record_receipt`;
  preguntas de deudas → `receivables`.
- **Cifras:** solo de herramientas. Al extraer de una captura se copia el número tal cual, nunca se convierte VES a USD.
- **Confirmaciones:** mostrar el eco con botones y esperar el "Sí". Nunca llamar a `resolve_pending(...,"yes")` sin el
  toque del dueño.
- **Memoria:** prohibido guardar en ella nombres de familiares con importes.

La skill sigue en `/etc/episteck/hermes/skills` (root, no editable por `home-agent`).

## 9. I4a: web de intercambios (diseño; PR aparte)

Página `/finance` en Home Hub, visible si Finance está activado. Usa el patrón de F3b/F3c: adaptador `server-only`,
delegación `svc-finance`, `no-store` y `DataEnvelope`. Secciones:

1. **Te deben** (§6.6).
2. **Guardas de otros.**
3. **Debes al socio.**
4. **Cambios recientes** con sus líneas, tipo y estado.
5. **Pendientes** resolubles con un toque, sin LLM.
6. **Confirmaciones de nivel 3:** efectivo ≥ 500 USD, revertir un cobro bancario. Cuando I4a exista, la herramienta
   MCP para estos casos responde "confírmalo en la web".

Requiere confirmar en el plan de I4a cómo pide el Hub una delegación con audiencia `svc-finance` (el patrón de
Nutrición usa la suya). **No se implementa en I2.**

## 10. Aceptación

Con fixtures sintéticos (unitarios, contrato, matriz de autorización), después con datos reales en Nuremberg.

| # | Escenario | Resultado esperado |
| --- | --- | --- |
| E1 | Ciclo completo: cambio 300 USD (A 120 USD, B 80 EUR, propio 40, Fondo F 60) → pago EUR 276,00 → A paga 120 por banco → B paga 73,60 por banco | Tipo 0,9200; partes 110,40/73,60/36,80/55,20 (Σ 276,00); A y B a 0; al fondo se le cargan 60,00 USD; socio 0; pago al socio no es gasto, cobros no son ingreso |
| E2 | Prepago: B paga 50,00 EUR antes de que se pague al socio | B queda −50,00 (a su favor); al pagar al socio, `CHARGE` 73,60 → saldo 23,60; asignación del crédito por antigüedad |
| E3 | Cobro acumulado | Suma exacta de 2 de 3 líneas → `AUTO_EXACT` en esas 2; cobro sin suma exacta → `AUTO_FIFO` con remanente a favor |
| E4 | Dos cambios abiertos y un pago EUR | `LINK_FUNDING` con botones; `[Todos]` → un `Funding`, tipo común |
| E5 | Pago al socio sin cambio abierto; pago a un IBAN nuevo del socio | `LINK_FUNDING`; al registrar el cambio siguiente, `PREVIOUS_UNPAID` → elegir el pago aprende el IBAN |
| E6 | Ingreso desconocido en la cuenta USD; luego otro del mismo origen; un sueldo en la cuenta EUR | Primero pregunta y regla; el segundo va solo; el sueldo se pregunta una vez (`IGNORE`) |
| E7 | Efectivo 150 USD; efectivo 600 USD; gift card valorada en 50 USD | `CONFIRM` con eco; el de 600 marca "importe alto"; especie con descripción y `OWNER_CONFIRMED` |
| E8 | "C me guarda 150" | La deuda se muestra "guardados en efectivo"; un cobro en efectivo de 100 la deja en 50 |
| E9 | Fondo con apertura desconocida → apertura aproximada 500 → gasto 460 → depósito | Sin "de los cuales" ni avisos mientras sea desconocida; después aviso de saldo bajo; el depósito aumenta lo guardado |
| E10 | Misma captura reenviada dos veces; reintento del agente | `possible_duplicate`; el reintento con la misma carga no tiene efecto; misma clave con otra carga → rechazo |
| E11 | Corrección de un cambio ya pagado | Partes EUR recalculadas; entradas `REVERSAL` y nuevas; asignaciones rehechas; historial visible en `finance_explain` |
| E12 | Tipo implícito un 5 % por encima del BCE; otro un 12 % por debajo | El primero: `Funding` + aviso `INFO`. El segundo: sin enlazar en espera; un segundo pago que completa la suma enlaza ambos |
| E18 | B debe 73,60 € y paga 73,00 €; otro caso paga 75,00 € | 73,00: `ADJUSTMENT` 0,60 + aviso, saldo 0. 75,00: diferencia 1,40 > 1,00 → 1,40 a su favor, sin ajuste |
| E19 | Reconstrucción con un chat **sintético** (formato de exportación real, contenido inventado) | Lista propuesta con fechas; tras confirmar, `OPENING CONFIRMED` sustituye a `UNKNOWN`; el fichero se borra |
| E17 | Ciclo normal con sync cada 12 h: se paga N y se registra N+1 antes del sync | El pago enlaza solo con N (N+1 no es compatible o es posterior); ninguna pregunta; `PREVIOUS_UNPAID` no salta |
| E13 | Autorización de las herramientas nuevas | Matriz de I1 (permitida, sin delegación, caducada, repetida, Home caído, feature off) para lecturas y escrituras; Home caído → nada escrito |
| E14 | Carga y reinicio | Matar el servicio a mitad de un comando: ningún efecto parcial; restaurar el backup: `PRAGMA integrity_check` ok |
| E15 | Las mismas consultas por MCP y por REST | Respuestas idénticas sobre el mismo estado |
| E16 | Prueba previa del cron (§7 F9) | Mensaje proactivo a Telegram; botones o, si no, respuesta por código resuelve el pendiente |

**Aceptación real:** tras el despliegue, el dueño registra los cambios reales de 2–3 semanas. Cada aviso y saldo se
contrasta con el grupo de WhatsApp. Las intervenciones se cuentan en `InterventionLog`. Objetivo: ≤ 2 por cambio y
ningún error de cifra registrado sin eco.

## 11. Decisiones del dueño (2026-11-18)

| Decisión | Detalle |
| --- | --- |
| Enfoque B | §5 |
| Deudas en efectivo de familiares = deuda (con marca "guardado") | §6.3 `HeldCashStatement` |
| Fondo custodiado con saldo inicial desconocido | §6.5 |
| Confirmaciones de nivel 3 en Telegram hasta I4a | §8.1 |
| La cifra EUR se calcula el mismo día del pago al socio | §6.3 |
| Reconstruir el Fondo F desde la exportación del chat | §6.5, tarea opcional al final de I2 |
| Orden: I2 → I4a (PR aparte, con permiso para tocar el Hub) → I3 | §9 |

## 12. Llamadas mías (corregibles)

| Decisión | Por qué |
| --- | --- |
| Registrar un cambio exige `CONFIRM` (nivel 2), aunque el reparto lo escriba el dueño | "Las cifras salen del banco o de mi confirmación"; un toque más por cambio sigue dentro de G2 |
| La deuda EUR de un familiar = su parte exacta del pago al socio (resto mayor) | Es exactamente lo que el dueño adelantó por él; corregible |
| Asignar cobros nunca pregunta (exacto → antigüedad) | No cambia el saldo; reasignable |
| Umbral de tipo: 3 % frente al BCE | Detecta errores de tecleo sin avisar por la variación normal entre fuentes |
| Umbral de fondo bajo: 500 USD por defecto | Configurable; solo con apertura conocida |
| Cron 06:35/18:35 UTC, silencioso si no hay nada | 15 min después del sync; horas razonables en Europa |
| No se guardan imágenes ni datos de terceros de las capturas | v1 P13 abierta; minimiza datos personales |
| Límite de subconjunto exacto: 16 líneas | 2^16 combinaciones es instantáneo; más allá, FIFO |
| Primeras tareas, dos pruebas: (1) cron + botones; (2) **forma** de las descripciones de cobros en la cuenta USD (SimpleFIN), revisada en Nuremberg en solo lectura, sin sacar nombres ni importes | Son los dos mayores riesgos técnicos. Si las descripciones no son estables por remitente, `PayerRule` por descripción no sirve y cada cobro USD se pregunta, con la sugerencia por coincidencia exacta como primer botón (un toque) |
| Enlace de pagos al socio: candidatos por fecha + banda ±8 % frente al BCE; pagos partidos por suma | Evita preguntar en el ciclo normal (pago N justo antes de registrar N+1, con sync cada 12 h) |
| `PREVIOUS_UNPAID` solo después de un sync posterior al registro | Si no, saltaría casi siempre antes de que el banco traiga el pago |
| Repetición idéntica el mismo día → `possible_duplicate` con `[Es otro]` | Ni duplicar por reintento ni perder un cobro real repetido |
| Diferencias de ≤ 1,00 € se ajustan solas, con aviso | Redondeo de Oanda frente al reparto por resto mayor |
| Reconstrucción del fondo con extractor determinista en Nuremberg, sin LLM sobre el chat entero, fichero borrado al terminar | Minimiza datos familiares enviados a OpenAI y retenidos |

## 13. Documentos y cambios que acompañan a I2

- **ADR-0016** "Finance exchanges ledger": escrituras en el libro propio (no dinero), modelo B, confirmación en dos
  fases, idempotencia por contenido. Amplía el punto 7 de ADR-0011.
- **`OLIN_FINANCE_V1.md`:** nota en §5.2, §6.5, §9.1 y §11 (I2) que remite a este documento. Corregir §16 P7 ("amigo en
  España").
- **`DATA_OWNERSHIP.md`:** la fila de Finanzas incluye contrapartes, cambios, cuentas corrientes y pendientes.
- **`STATUS.md`:** sección "Olin Finance I2".
- **Runbook:** cron de Hermes en `home-agent`; bringup de `svc-finance` con el SHA; carga inicial.
- **Tablero de progreso de I2** (como `FINANCE_I1_PROGRESS.md`).

## 14. Lo que queda al builder

Nombres exactos de tablas y columnas, forma de los triggers, normalización precisa de las descripciones de SimpleFIN,
redacción de los mensajes, formato de los códigos de pendiente, el corte de PRs (≤ 800 líneas cada uno) y el orden
interno de las tareas tras la prueba del cron.
