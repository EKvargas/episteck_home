# EPISTECK HOME — lenguaje del dominio

EPISTECK HOME organiza la administración de un hogar sin convertir toda la vida
de sus miembros en un único expediente. Este glosario acompaña una propuesta
de diseño pendiente de aprobación; no describe funcionalidades instaladas.

## Hogar y autoridad

**Household (hogar)**:
Unidad de coordinación doméstica y de acceso a información compartida, con
miembros y responsables explícitos; no implica parentesco ni propiedad común.
_Evitar_: Company, familia, cliente, cuenta bancaria.

**Person (persona)**:
Individuo sobre el que se mantienen referencias mínimas y que puede pertenecer
a más de un hogar; puede existir sin una cuenta de acceso.
_Evitar_: User, Employee, Contact, paciente.

**Membership (pertenencia)**:
Relación temporal entre una persona y un hogar, con responsabilidades
domésticas explícitas; no concede acceso universal a los datos de esa persona.
_Evitar_: propiedad de la persona, permiso global.

**Consent (autorización personal)**:
Manifestación atribuible a una persona que permite un uso concreto de datos
determinados por un destinatario, con propósito, vigencia y revocación.
_Evitar_: aceptación general, rol de administrador, credencial del proveedor.

## Fuentes y conocimiento

**External System (sistema externo)**:
Sistema identificable ajeno al Core que produce o conserva información con su
propia autoridad; no es una conexión individual a ese sistema.
_Evitar_: Data Source, token, integración instalada.

**Data Source (fuente de datos)**:
Origen concreto y delimitado de información, vinculado a un ámbito y a sus
titulares; puede ser una declaración manual o un conjunto de datos externo.
_Evitar_: proveedor genérico, verdad confirmada.

**Integration Event (evento de integración)**:
Registro identificable de un intento de intercambio entre contextos y de su
resultado; procesarlo no confirma la veracidad de su contenido.
_Evitar_: hecho del dominio, extracto bancario, memoria de AI.

**Assertion (afirmación)**:
Valor atribuido a una propiedad de un sujeto, acompañado de procedencia,
tiempo y estado de conocimiento; puede coexistir con afirmaciones discrepantes.
_Evitar_: verdad absoluta, confianza sin evidencia.

**USER_CONFIRMED**:
Afirmación que una persona autorizada confirmó explícitamente en un contexto
y momento concretos, sin borrar la procedencia de la evidencia anterior.
_Evitar_: verdad eterna, aprobado por AI.

**EXTERNAL_REPORTED**:
Afirmación comunicada por una fuente externa identificada, todavía distinta
de una confirmación de su titular.
_Evitar_: USER_CONFIRMED, hecho verificado por el hogar.

**AI_EXTRACTED**:
Afirmación propuesta por extracción de una evidencia identificable mediante
AI, susceptible de errores de lectura aunque exista el documento original.
_Evitar_: dato externo estructurado, hipótesis sin evidencia.

**AI_HYPOTHESIS**:
Inferencia o interpretación producida por AI que va más allá de la extracción
de una evidencia y permanece explícitamente tentativa.
_Evitar_: recuerdo confirmado, diagnóstico, dato observado.

## Primer vertical aprobado

**Health Journey (recorrido de salud)**:
Contenedor de coordinación personal/familiar para elementos autorizados como
tareas, responsables, recordatorios, consultas/exámenes planificados y
referencias documentales. No contiene ni interpreta historia clínica.
_Evitar_: Patient, episodio clínico, historial médico, programa de wellness.

**Pregnancy Journey (recorrido de embarazo)**:
Especialización futura de Health Journey para coordinar el embarazo, sin
convertirse en una recomendación, diagnóstico o sistema clínico.
_Evitar_: modo de wger, plan médico, sustituto de un profesional.

**Journey Item (elemento de recorrido)**:
Unidad de coordinación de un Journey, con responsable, estado, fecha prevista
y referencias autorizadas. No duplica el contenido de una fuente clínica o de
wellness.
_Evitar_: Observation, Encounter, DiagnosticReport, Medication.

**Home Asset (bien doméstico)**:
Bien que el hogar necesita identificar o administrar, con titularidad y
responsable declarados independientemente de su pertenencia al hogar.
_Evitar_: activo contable, inversión, ERPNext Asset.

**Administrative Item (asunto administrativo)**:
Obligación o gestión doméstica concreta, con responsable, estado y, cuando
corresponde, vencimiento y referencia documental.
_Evitar_: workflow genérico, movimiento contable, aviso ya enviado.
