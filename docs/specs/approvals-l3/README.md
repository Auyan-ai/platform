# Aprobaciones L3 frente a la cola inbound (TLA+)

Especificación TLA+ de la máquina de estados de las aprobaciones L3 y su
concurrencia con los turnos inbound de la misma conversación (issue #341,
ADR 0008). Modela el código de `develop` en `9f30a82`, no la documentación. Si
cambia el código de un paso de la tabla de abajo, hay que revisar su acción.

| Archivo | Qué es |
|---|---|
| `ApprovalsL3.tla` | El modelo: variables, una acción por paso atómico del código, invariantes y propiedades. |
| `ApprovalsL3.cfg` | Configuración de seguridad que TLC puede agotar. |
| `ApprovalsL3Liveness.cfg` | Configuración de liveness, sin simetría. |
| `mutants/*.patch` | Mutantes y bocetos de arreglos, cada uno con su resultado esperado en la cabecera. |
| `../run_tlc.sh` | Corre SANY y TLC (`parse`, `full`, `safety`, `each`, `liveness`, `trace`). |
| `../run_mutants.sh` | Aplica cada mutante a una copia y compara el resultado de TLC con lo esperado. |
| `../tlc_trace.py` | Resume una traza de TLC: una línea por paso con lo que cambió. |

Está en `docs/specs/` y no en `apps/api/` porque no es código de runtime ni un
test de pytest. Es documentación técnica que se ejecuta con una herramienta
aparte. Está escrito en TLA+ y no en PlusCal porque el traductor de PlusCal viene
dentro del mismo `tla2tools.jar`. Así, el texto revisado es exactamente el que
comprueba TLC.

## Cómo correrlo

Hace falta `tla2tools.jar` de la release estable **v1.7.4** de
[github.com/tlaplus/tlaplus](https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4)
(2.274.532 bytes, sha256
`936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`) y Java 11 o
superior. El jar va fuera del repo y nunca en git.

```bash
mkdir -p ~/.cache/tlaplus/v1.7.4
curl -fsSL -o ~/.cache/tlaplus/v1.7.4/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar
sha256sum ~/.cache/tlaplus/v1.7.4/tla2tools.jar
export TLA2TOOLS_JAR=~/.cache/tlaplus/v1.7.4/tla2tools.jar

docs/specs/run_tlc.sh parse      # sintaxis (SANY)
docs/specs/run_tlc.sh full       # espacio de estados completo, solo TypeOK
docs/specs/run_tlc.sh each       # un TLC por invariante: tabla OK / VIOLADA
docs/specs/run_tlc.sh liveness   # un TLC por propiedad temporal
docs/specs/run_tlc.sh trace docs/specs/approvals-l3 ExecAtMostOnce   # traza mínima resumida
docs/specs/run_mutants.sh        # mutantes y bocetos contra lo esperado (unos 8 min)
```

TLC para en la primera violación. Por eso `each` y `liveness` lanzan una corrida
por nombre y así salen todos los contraejemplos. `trace` corre con un solo worker
para que la traza sea la más corta. `OVERRIDE="MaxFaults=0 Skills={\"refund\"}"`
cambia constantes y `ONLY=A,B` limita `each` y `liveness` a esos nombres. TLC
corre sobre una copia en un directorio temporal, así que el repo no se ensucia.
Los logs quedan en `$TLC_OUT`.

## Resultados (TLC v1.7.4, `ApprovalsL3.cfg`)

El espacio completo tiene 1.106.249 estados generados y 426.304 distintos, con
simetría entre operadores y entre workers. Su profundidad es 32 y `TypeOK` se
cumple en todos. TLC lo agota en unos 15 s. La liveness se comprueba sin
simetría, sobre 1.548.089 estados distintos.

| Invariante o propiedad | Resultado | Issue |
|---|---|---|
| `OneTurnAtATime` | OK | |
| `ExecAtMostOnce` | VIOLADA | #376 |
| `OneExecPerOrder` | VIOLADA | #376 |
| `NoExecOnClosedOrder` | VIOLADA | #376 (TOCTOU) |
| `RejectedNeverExecuted` | VIOLADA | #376 |
| `OneOutcomePerApproval` | VIOLADA | #376 |
| `OutcomeIsTruthful` | VIOLADA | #376 |
| `NoWaitingAfterOutcome` | VIOLADA | #376 (punto 5), #377 (punto 2) |
| `NoOrphanEscalation` | VIOLADA | #377, #390 |
| `ExecutedIsApproved` | VIOLADA | #376 |
| `MessagesTaken` | OK | |
| `ApprovalEventuallyFinal` | VIOLADA | sin issue: no hay caducidad (decisión de producto) |

Las trazas mínimas están en los comentarios de #376 y #377 y en el cuerpo de
#390.

## Qué se modela

Una conversación, un pedido de Shopify y una skill L3. TLC explora las tres
skills, porque `skill` se elige en `Init` entre `Skills`. Los actores
concurrentes son estos:

- **Turnos inbound** (`Workers`). Cada uno reclama de la cola, pasa el pre-check
  de #321, hace el gate L3, escala y entrega su mensaje.
- **Operadores del panel** (`Humans`). Cada uno pulsa Aprobar o Rechazar sobre
  cualquier aprobación creada. La pantalla puede estar desactualizada.
- **Shopify**. El pedido pasa a `shipped` o `cancelled` en cualquier momento.
- **Fallos**, acotados por `MaxFaults`: muere un turno o una petición del panel,
  o vence el lease de un turno (si `LeaseCanExpire`).

No hay caducidad. `pending_approvals.status` solo admite `pending`, `approved` y
`rejected` (`supabase/migrations/20260518000005_add_pending_approvals.sql:17-18`)
y ningún código caduca una aprobación. Por eso el modelo no tiene acción de
expiración.

## Pasos atómicos y lo que los hace atómicos

Todo el acceso a la base pasa por `tenant_scope`, que abre una transacción READ
COMMITTED (`apps/api/db/client.py:83-99`). Cada sentencia ve lo committed en su
inicio. Los efectos de la transacción se ven al hacer COMMIT. Una llamada HTTP
a Shopify o al helpdesk es atómica en el otro lado y no se deshace con un
ROLLBACK.

### Turno inbound

| Acción | Código | Atomicidad |
|---|---|---|
| `Claim` | `apps/api/db/inbound_jobs.py:132-245` (`claim_next_inbound_job`) | Una transacción con `pg_try_advisory_xact_lock(tenant:conversation)` (`:169`), la comprobación de que no hay un `running` con lease vigente (`:177-189`) y `FOR UPDATE` de los jobs vivos (`:198`). El lock se suelta al COMMIT. Desde ahí la exclusión es solo el estado `running` más `locked_until`, que renueva el heartbeat (`apps/api/services/inbound_worker.py:484-494`). |
| `Precheck` | `apps/api/agents/nodes/execute_skill.py:486-489` → `prepare_approval` (`skills/shopify/cancel_order.py:66-82`, `update_shipping_address.py:73-82`, `refund_partial.py:71-89`) | Una lectura HTTP de Shopify. cancel y address lanzan `SkillRefusal` si el pedido está enviado o cancelado (`skills/shopify/_order_guard.py:52-83`). refund solo comprueba el saldo. |
| `GateReuse`, `GateCreate` | `execute_skill.py:537-566`: `get_recent_approval_for_skill` (`db/queries.py:2708-2741`) y `create_pending_approval` (`db/queries.py:2646-2683`) | Una transacción sin locks. Hace un SELECT y después un INSERT. Se modela como un solo paso porque el INSERT no lee nada. Un COMMIT ajeno entre las dos sentencias equivale a uno posterior al paso. |
| `Escalate` | `apps/api/agents/nodes/escalate.py:91-142` | Una transacción con `get_open_escalation_for_conversation`, `insert_escalation` si no hay ninguna abierta, e `insert_message`. Es un solo paso por el mismo argumento: lo único que puede cerrar escalaciones a la vez son los endpoints, y si cierran después de la lectura el resultado es el mismo que si cierran después del paso. |
| `Deliver` | `inbound_worker.py:158` (`_deliver_outcome`), `:534` (`complete_inbound_job`) | Una entrega HTTP. |
| `TurnFault` | `inbound_worker.py:510-529` (`release_inbound_job`, `fail_inbound_job`) | El job vuelve a `pending` y se repite entero. `inbound_already_answered` (`db/inbound_jobs.py:390-412`) busca `metadata.inbound_message_id`. El mensaje de `escalate` no lo lleva (`escalate.py:130-140`), así que un turno que acabó escalando se repite completo. |
| `LeaseExpire` | `inbound_worker.py:484-494` | Si el heartbeat no renueva a tiempo, otro slot reclama el mismo job (`db/inbound_jobs.py:157`). El turno viejo sigue vivo y su heartbeat vuelve a extender el lease (`:247-259`, `WHERE status='running'`). |

### Panel: aprobar (`apps/api/routers/approvals.py:164-366`)

Aprobar no toma el advisory lock de la conversación.

| Acción | Código | Atomicidad |
|---|---|---|
| `ApproveClick` | `:173-183`, `_reviewable_approval` (`:138-156`), `get_pending_approval` (`db/queries.py:2686-2705`) | Primera transacción. El SELECT no lleva `FOR UPDATE` y la transacción hace COMMIT antes de ejecutar la skill. |
| `ApproveSnapshot` | `skill.execute`: `cancel_order.py:90-91`, `update_shipping_address.py:90-91`, `refund_partial.py:96` | Una lectura HTTP de Shopify y el guard en memoria. refund no tiene guard. Un `SkillRefusal` cae en el `except Exception` (`approvals.py:210-222`) y devuelve `failed` sin tocar la aprobación (`:251-257`). |
| `ApproveMutate` | `cancel_order.py:92-99`, `update_shipping_address.py:92-103`, `refund_partial.py:97-99` | Una mutación HTTP distinta de la lectura anterior. No lleva clave de idempotencia: `requires_idempotency` (`skills/base.py:108`) no se usa en ningún sitio. Si Shopify rechaza `orderCancel` lo modela `CancelRefusedIn`. |
| `ApproveCas` | `:276-284`, `resolve_pending_approval` (`db/queries.py:2906-2939`) | Segunda transacción. El `UPDATE … WHERE status='pending'` bloquea la fila hasta el COMMIT. Si otra transacción la tiene, espera y vuelve a evaluar el WHERE. **El resultado se ignora**: si no actualizó nada, el endpoint sigue igual. |
| `ApproveRelease` | `:303-319`, `release_escalations_after_executed_action` (`services/approval_resolution.py:68-79`) | Misma transacción. Cierra todas las escalaciones abiertas que ve el UPDATE en ese momento. |
| `ApproveDeliver` | `:321-333` | `deliver_message_to_helpdesk` dentro de la transacción, antes del COMMIT. |
| `Commit` | fin del `async with` en `:333` | Se hacen visibles el status y el cierre de escalaciones, y se suelta la fila. |

### Panel: rechazar (`apps/api/routers/approvals.py:374-451`)

Rechazar es una sola transacción con varias sentencias. Tampoco toma el advisory
lock.

| Acción | Código | Atomicidad |
|---|---|---|
| `RejectClick` | `:383` (`_reviewable_approval`) | Un SELECT sin `FOR UPDATE`. |
| `RejectCas` | `:385-392` | El mismo CAS que al aprobar. **El resultado también se ignora.** |
| `RejectRelease` | `:430-435`, `release_approval_escalation` (`services/approval_resolution.py:49-65`) | Cierra solo la escalación `awaiting_human_approval:<id>`. Entre el CAS y este paso corre la llamada a Haiku (`:404-411`) con la transacción abierta. |
| `RejectDeliver` | `:437-445` | Una entrega HTTP antes del COMMIT. |
| `Commit` | fin del `async with` en `:445` | Igual que al aprobar. |

`HumanFault` es la muerte de la petición, por timeout de Cloud Run o por un
reinicio. Hace ROLLBACK de lo no committed. Lo que ya salió a Shopify o al
cliente se queda.

## Invariantes y propiedades

| Nombre | Enunciado |
|---|---|
| `OneTurnAtATime` | Nunca hay dos turnos a la vez sobre la conversación (ADR 0008). |
| `ExecAtMostOnce` | Una aprobación produce como mucho una mutación aceptada por Shopify. |
| `OneExecPerOrder` | El pedido recibe como mucho una mutación L3, aunque haya varias aprobaciones. |
| `NoExecOnClosedOrder` | cancel y address nunca mutan un pedido enviado o cancelado. refund queda fuera porque reembolsar un pedido enviado es legítimo. |
| `RejectedNeverExecuted` | Una aprobación `rejected` no tiene ninguna ejecución. No existe la caducidad. |
| `OneOutcomePerApproval` | El cliente recibe como mucho un resultado (`done` o `rejected`) por aprobación. |
| `OutcomeIsTruthful` | Si el cliente leyó "rechazada", la acción no se ejecutó. |
| `NoWaitingAfterOutcome` | Después del resultado, el cliente no recibe "sigue en revisión" sobre la misma aprobación. |
| `NoOrphanEscalation` | En reposo, toda escalación de gate abierta apunta a una aprobación `pending`. Si no, nadie puede cerrarla desde el panel. |
| `ExecutedIsApproved` | En reposo, lo que se ejecutó en Shopify consta como `approved`. |
| `MessagesTaken` (liveness) | Todo mensaje del cliente acaba reclamado por un turno. |
| `ApprovalEventuallyFinal` (liveness) | Toda aprobación acaba en `approved` o `rejected`. **Se espera que falle**, porque no hay caducidad y nada obliga a un operador a decidir. |

## Contraejemplos

Todos salieron con TLC tal como se habían leído en el código. Cada uno indica la
invariante que lo encuentra.

1. **Doble ejecución con dos aprobadores** (`ExecAtMostOnce`, #376). La
   comprobación de `pending` (`approvals.py:174`) y el CAS (`:277`) están en
   transacciones distintas, con la skill ejecutándose entre medias. En refund es
   un doble reembolso. En cancel, Shopify probablemente rechaza la segunda
   (supuesto `CancelRefusedIn`, sin verificar).
2. **Se ejecuta una aprobación rechazada** (`RejectedNeverExecuted`,
   `OutcomeIsTruthful`, #376). Los dos endpoints ignoran el resultado del CAS. El
   cliente recibe "rechazada" y "hecho", y la acción queda hecha.
3. **Ejecutada pero pendiente** (`ExecutedIsApproved`, #376). La petición muere
   entre la mutación en Shopify y el COMMIT, y un segundo clic la ejecuta otra
   vez.
4. **Dos "rechazada" por una caída** (`OneOutcomePerApproval`, #376). La
   entrega al helpdesk va dentro de la transacción, antes del COMMIT. Si el
   rechazo muere después de entregar, la aprobación vuelve a `pending` y un
   segundo rechazo vuelve a entregar.
5. **Pedido enviado entre el guard y la mutación** (`NoExecOnClosedOrder`,
   #376). Es un TOCTOU contra Shopify (`cancel_order.py:90-92`) que el código
   no puede cerrar sin una precondición en la propia mutación.
6. **"Sigue en revisión" después del resultado** (`NoWaitingAfterOutcome`,
   #376 y #377). Un turno lee `pending` en el gate y entrega después del
   resultado. La traza más corta pasa por un reintento que repite el turno
   entero, porque el acuse de `escalate` no lleva `inbound_message_id`.
7. **Escalación huérfana** (`NoOrphanEscalation`). Tiene dos causas. La primera
   es secuencial (#377): el gate reutiliza una aprobación `approved` y `escalate`
   abre `awaiting_human_approval:<id>`. La segunda es una carrera (#390): la
   aprobación se ve en el panel antes de que exista su escalación, y un rechazo
   en ese hueco no la cierra.
8. **Aprobación que nunca termina** (`ApprovalEventuallyFinal`). Si el pedido
   sale antes de aprobar, cada intento de aprobar devuelve `failed` y la
   aprobación sigue `pending` para siempre, salvo que alguien la rechace. No hay
   caducidad.

Con `LeaseCanExpire = TRUE` (mutante `lease-vence`), `OneTurnAtATime` también
falla. Si el heartbeat no renueva el lease durante `lease_seconds`, otro slot
reclama el mismo job y corren dos turnos a la vez. Es la semántica de un lease y
ADR 0008 ya la asume, por eso no tiene issue.

## Mutantes: el modelo no es trivial

Solo `OneTurnAtATime` y `MessagesTaken` se cumplen en el modelo actual. Cada una
tiene un mutante que rompe el lock que la sostiene, y TLC encuentra la
violación. `run_mutants.sh` lo comprueba.

| Mutante | Qué rompe | Esperado |
|---|---|---|
| `00-modelo` | Nada: fija los resultados del modelo actual. | la tabla de arriba |
| `claim-sin-exclusion` | `Claim` no mira si otro turno tiene el lease vigente. | `OneTurnAtATime` VIOLADA |
| `lease-nunca-se-suelta` | El turno acaba sin soltar `locked_until` y el lease no vence. | `MessagesTaken` VIOLADA |
| `lease-vence` | El heartbeat no renueva a tiempo. | `OneTurnAtATime` VIOLADA |

## Comprobar el arreglo de #376

`mutants/arreglo-376.patch` es un boceto del diseño de #376. Estas son las
acciones que cambian y cómo:

- **`ApproveClick`.** Es un CAS `pending → executing` comprobado, en una
  sola sentencia. Si se pierde, devuelve 409.
- **`ApproveSnapshot` y `ApproveMutate`.** Si el guard se niega o Shopify
  rechaza, la aprobación vuelve a `pending`.
- **`Cas`.** Lleva el estado de origen: `executing` al aprobar y `pending`
  al rechazar. Un CAS perdido acaba sin mensaje.
- **`ApproveRelease`, `RejectRelease`, `Commit`, `ApproveDeliver` y
  `RejectDeliver`.** La entrega pasa a después del COMMIT.
- **`Reconcile`, que es nueva.** Una `executing` sin dueño se relee de Shopify:
  pasa a `approved` si se ejecutó y a `pending` si no. Nunca se re-ejecuta.
- **`LiveAppr` y `Quiescent`.** `executing` cuenta como viva en el gate, y en
  reposo no queda ninguna.

Con el boceto pasan a OK `ExecAtMostOnce`, `OneExecPerOrder`,
`RejectedNeverExecuted`, `OneOutcomePerApproval`, `OutcomeIsTruthful` y
`ExecutedIsApproved`, sobre 193.736 estados distintos. Siguen VIOLADAS
`NoExecOnClosedOrder` (TOCTOU), `NoWaitingAfterOutcome` (el turno lee en el gate
y entrega después) y `NoOrphanEscalation` (#377 y #390). El mutante
`arreglo-376-gate-sin-executing` muestra por qué el gate tiene que ver las
`executing`. Si no las ve, crea otra aprobación del mismo pedido y
`OneExecPerOrder` falla.

Cuando el arreglo esté en `develop`, estos son los pasos:

1. Cambiar esas acciones en `ApprovalsL3.tla` para que reflejen el código real.
   El boceto sirve de punto de partida.
2. Actualizar la cabecera de `00-modelo.patch` con los nuevos resultados.
3. Borrar `arreglo-376*.patch`, que ya no aplicarán.
4. Correr `run_tlc.sh each` y `run_mutants.sh`.

## Comprobar el arreglo de #377 y #390

`escalate` solo debe abrir la escalación del gate si la aprobación sigue
`pending`, releída en su misma transacción. Eso cubre #377. Además hace falta
una de estas dos:

- **Opción A.** El gate crea la aprobación y su escalación en una transacción
  (`arreglo-escalacion-huerfana`).
- **Opción B.** `escalate` hace `FOR UPDATE` de la aprobación
  (`arreglo-escalacion-huerfana-for-update`).

Con cualquiera de las dos, `NoOrphanEscalation` pasa a OK. Cada parte por
separado falla (`-solo-pending`, `-solo-transaccion`). Las acciones que cambian
son `Escalate` y, en la opción A, `GateCreate`.

## Abstracciones y lo que no se modela

- **El LLM pide la L3 en cada turno.** Es el peor caso. Un turno que no la pide
  no toca aprobaciones ni escalaciones de gate, así que equivale a un mensaje
  que no llegó, y `Arrive` ya es opcional.
- **Un pedido y una skill.** `_same_order_action` siempre es verdadero.
- **Las escalaciones** son solo las de gate (por id de aprobación). No se
  modelan la del `SkillRefusal` ni la que abre `hand_executed_action_to_team`
  cuando el resultado no quedó cerrado. Tampoco se modelan el estado de la
  conversación ni `finalize_agent_resolution`.
- **La entrega al helpdesk** siempre llega. Si falla, no aparece ningún mensaje
  nuevo, así que no puede romper una invariante de mensajes que el modelo sí
  explora.
- **Si Shopify rechaza una mutación** depende del supuesto `CancelRefusedIn`.
  Por defecto Shopify rechaza `orderCancel` sobre un pedido ya cancelado y
  acepta todo lo demás. No está comprobado contra Shopify.
- **Las cotas** (`MaxMsgs`, `MaxApprovals`, `MaxClicks`, `MaxFaults`) son del
  modelo. `GateExhausted` solo existe para que el espacio de estados sea finito.
