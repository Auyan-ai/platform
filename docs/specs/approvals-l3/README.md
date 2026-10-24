# Aprobaciones L3 frente a la cola inbound (TLA+)

Especificación TLA+ de la máquina de estados de las aprobaciones L3 y su
concurrencia con los turnos inbound de la misma conversación (issue #341,
ADR 0008). Modela el código de `develop` en `084955e`, con el arreglo de #376
(PR #395), no la documentación. Si cambia el código de un paso de las tablas de
abajo, hay que revisar su acción. El modelo de antes del arreglo (`9f30a82`) se
conserva como el mutante `mutants/antes-376.patch`.

| Archivo | Qué es |
|---|---|
| `ApprovalsL3.tla` | El modelo: variables, una acción por paso atómico del código, invariantes y propiedades. |
| `ApprovalsL3.cfg` | Configuración de seguridad que TLC puede agotar. |
| `ApprovalsL3Liveness.cfg` | Configuración de liveness, sin simetría. |
| `mutants/*.patch` | Mutantes, cada uno con su resultado esperado en la cabecera. |
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
docs/specs/run_mutants.sh        # mutantes contra lo esperado (unos 6 min)
```

TLC para en la primera violación. Por eso `each` y `liveness` lanzan una corrida
por nombre y así salen todos los contraejemplos. `trace` corre con un solo worker
para que la traza sea la más corta. `OVERRIDE="MaxFaults=0 Skills={\"refund\"}"`
cambia constantes y `ONLY=A,B` limita `each` y `liveness` a esos nombres. TLC
corre sobre una copia en un directorio temporal, así que el repo no se ensucia.
Los logs quedan en `$TLC_OUT`.

## Resultados (TLC v1.7.4, `ApprovalsL3.cfg`)

Con el arreglo de #376, el espacio completo tiene 741.857 estados generados y
262.630 distintos, con simetría entre operadores, entre workers y entre
recuperaciones. Su profundidad es 29 y `TypeOK` se cumple en todos. TLC lo agota
en unos 11 s. La liveness se comprueba sin simetría, sobre 1.209.257
estados distintos. La columna "Antes" es el mutante `antes-376` (426.304 estados
distintos).

| Invariante o propiedad | Antes (`9f30a82`) | Con #395 (`084955e`) | Issue |
|---|---|---|---|
| `OneTurnAtATime` | OK | OK | |
| `ExecAtMostOnce` | VIOLADA | OK | #376 |
| `RejectedNeverExecuted` | VIOLADA | OK | #376 |
| `OneOutcomePerApproval` | VIOLADA | OK | #376 |
| `OutcomeIsTruthful` | VIOLADA | OK | #376 |
| `ExecutedIsApproved` | VIOLADA | OK | #376 |
| `ExecutedNeverPending` | (nueva) | OK | #376 |
| `OneExecPerOrder` | VIOLADA | VIOLADA | #376 antes; #399 con el arreglo |
| `NoExecOnClosedOrder` | VIOLADA | VIOLADA | #392 (TOCTOU) |
| `NoWaitingAfterOutcome` | VIOLADA | VIOLADA | #391, #377 (punto 2) |
| `NoOrphanEscalation` | VIOLADA | VIOLADA | #377, #390, #393 |
| `MessagesTaken` | OK | OK | |
| `ExecutionSettles` | (nueva) | OK | #376 |
| `ApprovalEventuallyFinal` | VIOLADA | VIOLADA | sin issue: no hay caducidad (decisión de producto) |

Las seis invariantes de #376 pasan con el arreglo y siguen fallando en
`antes-376`. `OneExecPerOrder` ya no falla por la carrera de #376. Falla por un
camino que el arreglo abre (contraejemplo 9). Las trazas de antes están en los
comentarios de #376 y #377 y en el cuerpo de #390.

## Qué se modela

Una conversación, un pedido de Shopify y una skill L3. TLC explora las tres
skills, porque `skill` se elige en `Init` entre `Skills`. Los actores
concurrentes son estos:

- **Turnos inbound** (`Workers`). Cada uno reclama de la cola, reutiliza una
  aprobación viva o pasa el pre-check de #321, hace el gate L3, escala y entrega
  su mensaje.
- **Operadores del panel** (`Humans`). Cada uno pulsa Aprobar o Rechazar sobre
  cualquier aprobación creada. La pantalla puede estar desactualizada.
- **Recuperaciones** (`Recoverers`). `_cleanup_loop` corre en cada instancia de
  Cloud Run (`apps/api/main.py:80-100`), así que puede haber dos a la vez.
- **Shopify**. El pedido pasa a `shipped` o `cancelled` en cualquier momento.
- **Fallos**, acotados por `MaxFaults`. Muere un turno o una petición del panel,
  se pierde la respuesta de una mutación, falla la lectura de una recuperación,
  o vence el lease de un turno (si `LeaseCanExpire`).

No hay caducidad. Ningún código caduca una aprobación, así que el modelo no tiene
acción de expiración. Los estados de `pending_approvals.status` son los de
`apps/api/services/approval_execution.py:3-9`: `pending`, `executing`,
`approved`, `failed` y `rejected`.

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
| `PreReuse` | `execute_skill.py:721-737` (#386) | Una transacción de lectura: `get_recent_approval_for_skill`. Si hay una aprobación viva (`pending`, `executing` o `approved`) la reutiliza y va a `escalate` sin pasar por `prepare`. |
| `Precheck` | `apps/api/agents/nodes/execute_skill.py:743-745` → `prepare` (`skills/shopify/cancel_order.py:75-89`, `update_shipping_address.py:96-103`, `refund_partial.py:84-100`) | Una lectura HTTP de Shopify. cancel y address lanzan `SkillRefusal` si el pedido está enviado o cancelado (`skills/shopify/_order_guard.py:52-83`). refund solo comprueba el saldo. |
| `GateReuse`, `GateCreate` | `execute_skill.py:800-839`: `get_recent_approval_for_skill` (`db/queries.py:2708-2742`, cuenta `pending`, `executing` y `approved`) y `create_pending_approval` (`db/queries.py:2646-2683`) | Una transacción sin locks. Hace un SELECT y después un INSERT. Se modela como un solo paso porque el INSERT no lee nada. Un COMMIT ajeno entre las dos sentencias equivale a uno posterior al paso. |
| `Escalate` | `apps/api/agents/nodes/escalate.py:91-142` | Una transacción con `get_open_escalation_for_conversation`, `insert_escalation` si no hay ninguna abierta, e `insert_message`. Es un solo paso por el mismo argumento: lo único que puede cerrar escalaciones a la vez son los endpoints, y si cierran después de la lectura el resultado es el mismo que si cierran después del paso. Con #395, `hand_approval_to_team` también abre una escalación. Si `escalate` lee antes de su COMMIT, quedan abiertas la del gate y la del equipo. El modelo no explora ese orden (ver Pendiente). Solo afecta a `NoOrphanEscalation`, que ya falla. |
| `Deliver` | `inbound_worker.py:158` (`_deliver_outcome`), `:534` (`complete_inbound_job`) | Una entrega HTTP. |
| `TurnFault` | `inbound_worker.py:510-529` (`release_inbound_job`, `fail_inbound_job`) | El job vuelve a `pending` y se repite entero. `inbound_already_answered` (`db/inbound_jobs.py:390-412`) busca `metadata.inbound_message_id`. El mensaje de `escalate` no lo lleva (`escalate.py:130-140`), así que un turno que acabó escalando se repite completo. |
| `LeaseExpire` | `inbound_worker.py:484-494` | Si el heartbeat no renueva a tiempo, otro slot reclama el mismo job (`db/inbound_jobs.py:157`). El turno viejo sigue vivo y su heartbeat vuelve a extender el lease (`:247-259`, `WHERE status='running'`). |

### Panel: aprobar (`apps/api/routers/approvals.py:165-262`)

Aprobar no toma el advisory lock de la conversación. Cada transacción del panel
es un solo paso. Su CAS bloquea la fila hasta el COMMIT y quien espera vuelve a
evaluar el WHERE, así que dos transacciones sobre la misma fila se serializan.

| Acción | Código | Atomicidad |
|---|---|---|
| `ApproveClick` | `:176-177`, `_reviewable_approval` (`:135-150`) | Primera transacción. Un SELECT sin `FOR UPDATE`. Si no está `pending`, 409. |
| `ApproveClaim` | `:201-213`, `claim_pending_approval` (`db/queries.py:2907-2935`) | Segunda transacción. CAS `pending → executing` con `execution_attempt + 1` y **resultado comprobado**: si no actualiza nada, 409 sin ejecutar. `load_execution_context` va en la misma transacción. |
| `ApproveSnapshot` | `execute_once` (`services/approval_execution.py:137-163`): `snapshot_before_mutation` y `ensure_order_changeable` (`cancel_order.py:97-98`, `update_shipping_address.py:111-112`) | Una lectura HTTP de Shopify y el guard en memoria. En el primer claim, un `SkillRefusal` es `Refused` (`:158-159`). En uno posterior se reconcilia (`:162`, `reconcile` en `:166-187`). |
| `ApproveMutate` | `cancel_order.py:99-106`, `update_shipping_address.py:113-124`, `refund_partial.py:110-128` | Una mutación HTTP distinta de la lectura. refund busca antes su reembolso por la marca de la aprobación (`:110-121`) y manda `refundCreate @idempotent` con la aprobación como clave (`integrations/shopify.py:1165`). cancel y address no admiten clave. Si Shopify rechaza (`ShopifyRejected`, que es `MutationNotApplied`), el primer claim da `NotApplied` (`approval_execution.py:160-161`). Con un fallo, la respuesta se pierde y `reconcile` la encuentra o no se sabe (`Unknown`). |
| `ApproveSettle` | `settle` (`approval_execution.py:190-371`), `settle_executing_approval` (`db/queries.py:2966-2998`) | Tercera transacción. CAS desde `executing` **con el mismo `execution_attempt`**: `approved` si consta aplicada, `pending` solo si consta que no se aplicó (`NotApplied`), `failed` si una regla la rechazó (`Refused`) o si no se sabe (`Unknown`). En la misma transacción, el mensaje y `release_escalations_after_executed_action` (todo resuelto) o `hand_approval_to_team` (`approval_resolution.py:142-163`). Un CAS perdido es 409 sin escribir ni entregar. |
| `ApproveDeliver` | `deliver_after_commit` (`approval_execution.py:396-409`) | Una entrega HTTP **después del COMMIT**. Solo `Applied` ("hecho") y `Refused` ("no se pudo") llevan mensaje. |

### Panel: rechazar (`apps/api/routers/approvals.py:270-326`)

| Acción | Código | Atomicidad |
|---|---|---|
| `RejectClick` | `:280-288` (`_reviewable_approval`) | Un SELECT sin `FOR UPDATE`. La redacción con Haiku (`:291-298`) va después, fuera de toda transacción. |
| `RejectCas` | `:299-318`, `reject_pending_approval` (`db/queries.py:2938-2963`) | Una transacción. CAS **solo desde `pending`**, con resultado comprobado: una `executing` da 409 y el cliente no recibe "rechazada". Después, el mensaje y `release_approval_escalation`, que cierra solo la escalación del gate de esta aprobación. |
| `RejectDeliver` | `:320` | Una entrega HTTP después del COMMIT. |

`HumanFault` es la muerte de la petición, por timeout de Cloud Run o por un
reinicio. Lo committed se queda. Tras el claim, la aprobación queda `executing`
hasta que la cierra una recuperación.

### Recuperación (`services/approval_execution.py:412-458`)

| Acción | Código | Atomicidad |
|---|---|---|
| `RecoverRead` | `list_stale_executing_approvals` (`db/queries.py:3001-3020`), `reconcile(cause=None)` (`approval_execution.py:418`) | Lista las `executing` con `reviewed_at` de hace más de `STALE_EXECUTION` = 15 min (`:67-69`) y lee Shopify. `Applied` si la encuentra, `NotApplied` si no, `Unknown` si la lectura falla. **Nunca ejecuta.** |
| `RecoverSettle` | `settle` con el `execution_attempt` que leyó (`:427-434`) | El mismo CAS que `ApproveSettle`. |
| `RecoverDeliver` | `deliver_after_commit` | Igual que al aprobar. |

La recuperación solo ve una `executing` si ninguna petición viva tiene ese
claim. Es el supuesto de `STALE_EXECUTION`: Cloud Run corta cada petición a los
300 s. El mutante `recuperacion-con-peticion-viva` lo quita.

## Invariantes y propiedades

| Nombre | Enunciado |
|---|---|
| `OneTurnAtATime` | Nunca hay dos turnos a la vez sobre la conversación (ADR 0008). |
| `ExecAtMostOnce` | Una aprobación produce como mucho una mutación aceptada por Shopify. |
| `OneExecPerOrder` | El pedido recibe como mucho una mutación L3, aunque haya varias aprobaciones. |
| `NoExecOnClosedOrder` | cancel y address nunca mutan un pedido enviado o cancelado. refund queda fuera porque reembolsar un pedido enviado es legítimo. |
| `RejectedNeverExecuted` | Una aprobación `rejected` no tiene ninguna ejecución. |
| `ExecutedNeverPending` | Una aprobación ejecutada nunca vuelve a `pending`, desde donde se podría aprobar otra vez. |
| `OneOutcomePerApproval` | El cliente recibe como mucho un resultado ("hecho", "no se pudo" o "rechazada") por aprobación. |
| `OutcomeIsTruthful` | Si el cliente leyó "rechazada" o "no se pudo", la acción no se ejecutó. |
| `NoWaitingAfterOutcome` | Después del resultado, el cliente no recibe "sigue en revisión" sobre la misma aprobación. |
| `NoOrphanEscalation` | En reposo, toda escalación de gate abierta apunta a una aprobación `pending`. Si no, nadie puede cerrarla desde el panel. |
| `ExecutedIsApproved` | En reposo, lo que se ejecutó en Shopify consta como `approved`, o como `failed` por resultado desconocido y con el caso en manos del equipo. Esa segunda salida es la que #376 manda tomar ante la duda. |
| `MessagesTaken` (liveness) | Todo mensaje del cliente acaba reclamado por un turno. |
| `ExecutionSettles` (liveness) | Toda `executing` acaba cerrada, por su petición o por una recuperación. |
| `ApprovalEventuallyFinal` (liveness) | Toda aprobación acaba en `approved`, `failed` o `rejected`. **Se espera que falle**, porque no hay caducidad y nada obliga a un operador a decidir. |

"En reposo" (`Quiescent`) es sin turnos, peticiones ni recuperaciones en curso,
sin jobs sin reclamar y sin ninguna `executing`.

## Contraejemplos

### Antes del arreglo (mutante `antes-376`)

1. **Doble ejecución con dos aprobadores** (`ExecAtMostOnce`, #376). La
   comprobación de `pending` y el CAS estaban en transacciones distintas, con la
   skill ejecutándose entre medias.
2. **Se ejecuta una aprobación rechazada** (`RejectedNeverExecuted`,
   `OutcomeIsTruthful`, #376). Los dos endpoints ignoraban el resultado del CAS.
3. **Ejecutada pero pendiente** (`ExecutedIsApproved`, #376). La petición moría
   entre la mutación y el COMMIT, y un segundo clic la ejecutaba otra vez.
4. **Dos "rechazada" por una caída** (`OneOutcomePerApproval`, #376). La entrega
   iba antes del COMMIT.

### Con el arreglo

5. **Pedido enviado entre el guard y la mutación** (`NoExecOnClosedOrder`,
   #392). Es un TOCTOU contra Shopify (`cancel_order.py:97-99`) que el código no
   puede cerrar sin una precondición en la propia mutación. #395 no lo toca.
6. **"Sigue en revisión" después del resultado** (`NoWaitingAfterOutcome`, #391
   y #377). Un turno lee la aprobación viva y entrega después del resultado.
7. **Escalación huérfana** (`NoOrphanEscalation`, #377, #390, #393). El gate
   reutiliza una aprobación ya resuelta y `escalate` abre su escalación, o un
   rechazo cae en el hueco entre crear la aprobación y su escalación.
8. **Aprobación que nunca termina** (`ApprovalEventuallyFinal`). Si nadie la
   rechaza ni la aprueba, sigue `pending`. No hay caducidad.
9. **Segunda ejecución tras un resultado desconocido** (`OneExecPerOrder`,
   #399). Necesita un fallo. Traza mínima de 22 pasos, con
   `refund` o `address`:

   ```
   12. ApproveClaim     appr = <<"executing", "none">>
   14. ApproveMutate    execs = <<[a |-> 1]>>, hRes = h1 :> "unknown"   (respuesta perdida, reconcile falla)
   15. ApproveSettle    appr = <<"failed", "none">>, teamEsc = {1}
   16. PreReuse         (failed no cuenta como viva)
   18. GateCreate       appr = <<"failed", "pending">>
   20. ApproveClaim     appr = <<"failed", "executing">>
   22. ApproveMutate    execs = <<[a |-> 1], [a |-> 2]>>
   ```

   Una aprobación cerrada como `failed` por resultado desconocido puede estar
   aplicada en Shopify. `get_recent_approval_for_skill` ignora las `failed`
   (`db/queries.py:2733`), así que el cliente vuelve a pedirla, el gate crea otra
   aprobación y, si un operador la aprueba, refund reembolsa dos veces. La marca
   y la clave de idempotencia son por aprobación, así que no lo frenan. En cancel
   no pasa porque el pre-check ve el pedido cancelado. Lo único que lo frena hoy
   es que el operador lea la escalación del equipo antes de aprobar. Sin fallos
   (`sin-fallos`) se cumple.

Con `LeaseCanExpire = TRUE` (mutante `lease-vence`), `OneTurnAtATime` también
falla. Es la semántica de un lease y ADR 0008 ya la asume, por eso no tiene
issue.

## Mutantes: el modelo no es trivial

Cada pieza del arreglo y cada lock que sostiene una propiedad que se cumple
tiene un mutante que la quita, y TLC encuentra la violación. `run_mutants.sh`
lo comprueba.

| Mutante | Qué cambia | Esperado |
|---|---|---|
| `00-modelo` | Nada: fija los resultados del modelo actual. | la tabla de arriba |
| `antes-376` | El modelo de `9f30a82`, antes de #395. | las seis de #376 VIOLADAS |
| `gate-sin-executing` | El gate no ve las `executing`. Sin fallos. | `OneExecPerOrder` VIOLADA |
| `settle-sin-attempt` | El CAS de cierre no compara `execution_attempt`. | `ExecutedNeverPending` VIOLADA |
| `recuperacion-con-peticion-viva` | La recuperación cierra el claim de una petición viva. | `ExecAtMostOnce` VIOLADA |
| `sin-fallos` | `MaxFaults = 0`. | `OneExecPerOrder` OK |
| `claim-sin-exclusion` | `Claim` no mira si otro turno tiene el lease vigente. | `OneTurnAtATime` VIOLADA |
| `lease-nunca-se-suelta` | El turno acaba sin soltar `locked_until` y el lease no vence. | `MessagesTaken` VIOLADA |
| `lease-vence` | El heartbeat no renueva a tiempo. | `OneTurnAtATime` VIOLADA |

`settle-sin-attempt` necesita las dos recuperaciones. Las dos leen la misma
`executing` sin aplicar, una la reabre, un operador la reclama y la ejecuta, y
la otra la vuelve a dejar `pending` con su lectura vieja.
`recuperacion-con-peticion-viva` muestra que el arreglo depende de que
`STALE_EXECUTION` sea mayor que la vida de una petición. Con address la segunda
mutación sale. Con refund la frena la clave de idempotencia.

## Qué cambió en el modelo con #395

- **`ApproveClaim`, que es nueva.** Es el CAS `pending → executing` comprobado,
  con `execution_attempt + 1`.
- **`ApproveSnapshot` y `ApproveMutate`.** Dan un resultado (`applied`,
  `refused`, `notapplied` o `unknown`) en vez de escribir. refund lleva marca y
  clave de idempotencia. La respuesta perdida es un fallo nuevo.
- **`ApproveSettle`, que sustituye a `ApproveCas`, `ApproveRelease` y
  `Commit`.** Es el CAS desde `executing` con el mismo `execution_attempt`.
- **`RejectCas`.** CAS solo desde `pending` y comprobado, en una transacción con
  su cierre de escalación. Desaparecen `RejectRelease` y el lock de fila
  (`lockedBy`), porque ya ningún paso del panel deja una fila bloqueada entre
  dos pasos del modelo.
- **`ApproveDeliver` y `RejectDeliver`.** Van después del COMMIT.
- **`RecoverRead`, `RecoverSettle` y `RecoverDeliver`, que son nuevas.**
- **`teamEsc`, que es nueva.** Son las escalaciones de `hand_approval_to_team`.
  Cuentan como abiertas para `Escalate`, igual que en
  `get_open_escalation_for_conversation`.
- **`PreReuse`, que es nueva.** No es de #395: viene de #386, que reutiliza la
  aprobación viva antes de `prepare` (`execute_skill.py:721-737`).

## Pendiente

Los arreglos de #377, #390 y #393 se modelarán cuando entre el PR de
`fix/l3-approval-escalations`. Los bocetos de antes (`arreglo-escalacion-huerfana*`)
se quitaron porque ya no aplican al modelo nuevo. Siguen en el historial de este
PR, en `376dbec`. Al modelarlos, hay que partir `Escalate`, `ApproveSettle` y
`RejectCas` en lectura y escritura. Hoy pueden ser atómicos porque `escalate` no
lee la aprobación. Con el arreglo la leerá, y un rechazo sin COMMIT entre su CAS
y su cierre vuelve a importar. Lo mismo pasa con una `hand_approval_to_team` sin
COMMIT que `escalate` todavía no ve.

## Abstracciones y lo que no se modela

- **El LLM pide la L3 en cada turno.** Es el peor caso. Un turno que no la pide
  no toca aprobaciones ni escalaciones de gate, así que equivale a un mensaje
  que no llegó, y `Arrive` ya es opcional.
- **Un pedido y una skill.** `_same_order_action` siempre es verdadero. address
  tiene una sola dirección, así que `reconcile` la encuentra si hubo cualquier
  mutación.
- **Las escalaciones** son las de gate (por id de aprobación) y las de
  `hand_approval_to_team`. No se modelan la del `SkillRefusal` del pre-check, el
  estado de la conversación ni `finalize_agent_resolution`. Si el equipo tiene
  que rematar la acción (`team_followup_reason`) se elige de forma no
  determinista.
- **La entrega al helpdesk** siempre llega, o no llega porque muere la petición.
  Si falla, no aparece ningún mensaje nuevo, así que no puede romper una
  invariante de mensajes.
- **Shopify.** Si rechaza una mutación depende del supuesto `CancelRefusedIn`:
  rechaza `orderCancel` sobre un pedido ya cancelado y acepta todo lo demás. No
  está comprobado contra Shopify. `orderCancel` es asíncrono. El modelo lo
  cubre solo en parte, porque `reconcile` puede devolver `unknown` aunque la
  mutación se aplicara. La clave `@idempotent` de refund se supone dentro de sus
  24 h. Pasado ese plazo la cubre la marca del reembolso.
- **Las lecturas que fallan.** Si falla `snapshot_before_mutation` o la lectura
  previa de refund, es `MutationNotApplied`. El modelo lo cubre con el rechazo de
  Shopify, que acaba igual. No se modela que falle la lectura de `reconcile` tras
  un `SkillRefusal` en un claim posterior.
- **Las cotas** (`MaxMsgs`, `MaxApprovals`, `MaxClicks`, `MaxFaults`) son del
  modelo. `GateExhausted` solo existe para que el espacio de estados sea finito.
  `execution_attempt` queda acotado por el número de clics.
