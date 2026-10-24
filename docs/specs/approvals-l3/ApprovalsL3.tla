----------------------------- MODULE ApprovalsL3 -----------------------------
(***************************************************************************)
(* Aprobaciones L3 frente a la cola inbound (issue #341, ADR 0008).        *)
(*                                                                         *)
(* Modela lo que hace el código de `develop` (084955e, con el arreglo de   *)
(* #376 del PR #395), no lo que dice la documentación. Cada acción es un   *)
(* paso atómico del código; README.md cita el archivo:línea y la           *)
(* transacción que lo hace atómico. El modelo de antes del arreglo es el   *)
(* mutante mutants/antes-376.patch.                                        *)
(*                                                                         *)
(* Una conversación, un pedido y una skill L3 (`skill`, elegida en Init    *)
(* entre `Skills`). Actores concurrentes:                                  *)
(*   - Workers: slots del worker de `inbound_jobs` que corren turnos.      *)
(*   - Humans: operadores que pulsan Aprobar o Rechazar en el panel.       *)
(*   - Recoverers: la recuperación de `executing` colgadas, una por        *)
(*     instancia de Cloud Run.                                             *)
(*   - Shopify: el pedido puede salir o cancelarse en cualquier momento.   *)
(*   - Fallos: caída del proceso, respuesta de Shopify perdida o lease     *)
(*     vencido, acotados por MaxFaults.                                    *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Humans,           \* operadores del panel
    Workers,          \* slots del worker de la cola
    Recoverers,       \* bucles de limpieza, uno por instancia de Cloud Run (main.py:80-100)
    Skills,           \* subconjunto de {"cancel", "address", "refund"}
    MaxMsgs,          \* mensajes del cliente que llegan al webhook
    MaxApprovals,     \* filas de pending_approvals que puede crear el gate
    MaxClicks,        \* clics de cada operador
    MaxFaults,        \* caídas, respuestas perdidas y leases vencidos, en total
    LeaseCanExpire,   \* el heartbeat puede no renovar el lease a tiempo
    CancelRefusedIn,  \* estados en los que Shopify rechaza orderCancel (supuesto)
    RecoverWhileRunning \* la recuperación puede ver `executing` una petición viva

ASSUME
    /\ Skills \subseteq {"cancel", "address", "refund"} /\ Skills # {}
    /\ MaxMsgs \in Nat /\ MaxApprovals \in Nat \ {0}
    /\ MaxClicks \in Nat /\ MaxFaults \in Nat
    /\ LeaseCanExpire \in BOOLEAN
    /\ CancelRefusedIn \subseteq {"open", "shipped", "cancelled"}
    /\ RecoverWhileRunning \in BOOLEAN

Ids         == 1..MaxApprovals
Attempts    == 0..(MaxClicks * Cardinality(Humans))
Guarded     == {"cancel", "address"}   \* skills que llaman a ensure_order_changeable
OrderStates == {"open", "shipped", "cancelled"}
ApprStates  == {"none", "pending", "executing", "approved", "failed", "rejected"}
Final       == {"approved", "failed", "rejected"}
Outcomes    == {"done", "failed", "rejected"}
MsgKinds    == {"gate", "waiting", "followup_done", "refused"} \cup Outcomes
Results     == {"none", "applied", "refused", "notapplied", "unknown"}
TurnPcs     == {"idle", "reuse", "precheck", "gate", "escalate", "deliver"}
HumanPcs    == {"idle", "a_claim", "a_snap", "a_mut", "a_settle", "a_del", "r_cas", "r_del"}
RecPcs      == {"idle", "settle", "deliver"}

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

VARIABLES
    skill,      \* la L3 de este comportamiento
    order,      \* estado del pedido en Shopify
    execs,      \* mutaciones que Shopify aceptó: <<[a, at]>>
    appr,       \* status COMMITTED de cada fila de pending_approvals
    attempt,    \* pending_approvals.execution_attempt
    openEsc,    \* escalaciones del gate abiertas (awaiting_human_approval:<id>)
    teamEsc,    \* escalaciones abiertas por hand_approval_to_team, por approval id
    unknownOut, \* historia: aprobaciones cerradas como `failed` por resultado desconocido
    inbox,      \* mensajes que recibió el cliente, en orden: <<[k, a]>>
    arrived,    \* mensajes del cliente ya encolados
    unclaimed,  \* jobs pendientes sin reclamar
    faults,     \* fallos consumidos
    tpc, tAppr, tKind, lease,           \* estado de cada turno
    hpc, hAppr, hClicks, hAtt, hRes,    \* estado de cada petición del panel
    rpc, rAppr, rAtt, rRes              \* estado de cada recuperación

shopVars  == <<skill, order, execs>>
dbVars    == <<appr, attempt, openEsc, teamEsc, unknownOut>>
queueVars == <<arrived, unclaimed, faults>>
turnVars  == <<tpc, tAppr, tKind, lease>>
humanVars == <<hpc, hAppr, hClicks, hAtt, hRes>>
recVars   == <<rpc, rAppr, rAtt, rRes>>
vars      == <<shopVars, dbVars, inbox, queueVars, turnVars, humanVars, recVars>>

TypeOK ==
    /\ skill \in Skills
    /\ order \in OrderStates
    /\ execs \in Seq([a : Ids, at : OrderStates])
    /\ appr \in [Ids -> ApprStates]
    /\ attempt \in [Ids -> Attempts]
    /\ openEsc \subseteq Ids
    /\ teamEsc \subseteq Ids
    /\ unknownOut \subseteq Ids
    /\ inbox \in Seq([k : MsgKinds, a : Ids \cup {0}])
    /\ arrived \in 0..MaxMsgs
    /\ unclaimed \in 0..(MaxMsgs + MaxFaults)
    /\ faults \in 0..MaxFaults
    /\ tpc \in [Workers -> TurnPcs]
    /\ tAppr \in [Workers -> Ids \cup {0}]
    /\ tKind \in [Workers -> MsgKinds \cup {"none"}]
    /\ lease \in [Workers -> BOOLEAN]
    /\ hpc \in [Humans -> HumanPcs]
    /\ hAppr \in [Humans -> Ids]
    /\ hClicks \in [Humans -> 0..MaxClicks]
    /\ hAtt \in [Humans -> Attempts]
    /\ hRes \in [Humans -> Results]
    /\ rpc \in [Recoverers -> RecPcs]
    /\ rAppr \in [Recoverers -> Ids]
    /\ rAtt \in [Recoverers -> Attempts]
    /\ rRes \in [Recoverers -> Results]

Init ==
    /\ skill \in Skills
    /\ order = "open"
    /\ execs = <<>>
    /\ appr = [i \in Ids |-> "none"]
    /\ attempt = [i \in Ids |-> 0]
    /\ openEsc = {}
    /\ teamEsc = {}
    /\ unknownOut = {}
    /\ inbox = <<>>
    /\ arrived = 0
    /\ unclaimed = 0
    /\ faults = 0
    /\ tpc = [w \in Workers |-> "idle"]
    /\ tAppr = [w \in Workers |-> 0]
    /\ tKind = [w \in Workers |-> "none"]
    /\ lease = [w \in Workers |-> FALSE]
    /\ hpc = [h \in Humans |-> "idle"]
    /\ hAppr = [h \in Humans |-> 1]
    /\ hClicks = [h \in Humans |-> 0]
    /\ hAtt = [h \in Humans |-> 0]
    /\ hRes = [h \in Humans |-> "none"]
    /\ rpc = [r \in Recoverers |-> "idle"]
    /\ rAppr = [r \in Recoverers |-> 1]
    /\ rAtt = [r \in Recoverers |-> 0]
    /\ rRes = [r \in Recoverers |-> "none"]

ExecCount(a) == Cardinality({i \in DOMAIN execs : execs[i].a = a})

\* Lo que Skill.reconcile encuentra en Shopify, sobre un estado dado.
\*   cancel:  el pedido figura cancelado, lo cancelara quien lo cancelara.
\*   address: el pedido ya tiene la dirección pedida (una sola dirección en el modelo).
\*   refund:  hay un reembolso con la marca de esta aprobación.
FoundIn(a, o, ex) ==
    CASE skill = "cancel"  -> o = "cancelled"
      [] skill = "address" -> Len(ex) > 0
      [] skill = "refund"  -> \E i \in DOMAIN ex : ex[i].a = a
Found(a) == FoundIn(a, order, execs)

(***************************************************************************)
(* Entorno: el cliente escribe; Shopify cambia el pedido.                  *)
(***************************************************************************)
Arrive ==
    /\ arrived < MaxMsgs
    /\ arrived' = arrived + 1
    /\ unclaimed' = unclaimed + 1
    /\ UNCHANGED <<shopVars, dbVars, inbox, faults, turnVars, humanVars, recVars>>

Ship ==
    /\ order = "open"
    /\ order' = "shipped"
    /\ UNCHANGED <<skill, execs, dbVars, inbox, queueVars, turnVars, humanVars, recVars>>

MerchantCancel ==
    /\ order = "open"
    /\ order' = "cancelled"
    /\ UNCHANGED <<skill, execs, dbVars, inbox, queueVars, turnVars, humanVars, recVars>>

(***************************************************************************)
(* Turnos inbound (services/inbound_worker.py, db/inbound_jobs.py).        *)
(***************************************************************************)
LeaseHeld(w) == tpc[w] # "idle" /\ lease[w]
StaleTurn    == \E v \in Workers : tpc[v] # "idle" /\ ~lease[v]

\* claim_next_inbound_job: advisory xact lock + "no hay running con lease vigente".
\* Reclamar un job con el lease vencido no para al turno viejo: su heartbeat
\* vuelve a extender el lease (UPDATE ... WHERE status='running').
Claim(w) ==
    /\ tpc[w] = "idle"
    /\ \A v \in Workers : ~LeaseHeld(v)
    /\ unclaimed > 0 \/ StaleTurn
    /\ tpc' = [tpc EXCEPT ![w] = "reuse"]
    /\ lease' = [v \in Workers |-> v = w \/ tpc[v] # "idle"]
    /\ tAppr' = [tAppr EXCEPT ![w] = 0]
    /\ tKind' = [tKind EXCEPT ![w] = "none"]
    /\ unclaimed' = 0
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, faults, humanVars, recVars>>

\* get_recent_approval_for_skill: pending, executing o approved, la más reciente.
\* Las failed y rejected no cuentan: esa acción se puede pedir otra vez.
LiveAppr == {i \in Ids : appr[i] \in {"pending", "executing", "approved"}}
FreeIds  == {i \in Ids : appr[i] = "none"}

Reuse(w) ==
    LET r == Max(LiveAppr) IN
    /\ tAppr' = [tAppr EXCEPT ![w] = r]
    /\ tKind' = [tKind EXCEPT ![w] =
                   IF appr[r] = "approved" THEN "followup_done" ELSE "waiting"]
    /\ tpc' = [tpc EXCEPT ![w] = "escalate"]

\* execute_skill.py:721-737: reusa una aprobación viva antes de prepare (#386).
PreReuse(w) ==
    /\ tpc[w] = "reuse"
    /\ IF LiveAppr # {}
         THEN Reuse(w)
         ELSE /\ tpc' = [tpc EXCEPT ![w] = "precheck"]
              /\ UNCHANGED <<tAppr, tKind>>
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, lease, humanVars, recVars>>

\* El LLM pide la L3. prepare relee el pedido: cancel y address rechazan uno
\* enviado o cancelado (SkillRefusal); refund solo mira el saldo.
Precheck(w) ==
    /\ tpc[w] = "precheck"
    /\ IF skill \in Guarded /\ order # "open"
         THEN /\ tpc' = [tpc EXCEPT ![w] = "deliver"]
              /\ tKind' = [tKind EXCEPT ![w] = "refused"]
         ELSE /\ tpc' = [tpc EXCEPT ![w] = "gate"]
              /\ UNCHANGED tKind
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, tAppr, lease, humanVars, recVars>>

\* Gate L3, una transacción (execute_skill.py:800-839): get_recent_approval_for_skill
\* y, si no hay ninguna viva, create_pending_approval.
GateReuse(w) ==
    /\ tpc[w] = "gate"
    /\ LiveAppr # {}
    /\ Reuse(w)
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, lease, humanVars, recVars>>

GateCreate(w) ==
    /\ tpc[w] = "gate"
    /\ LiveAppr = {}
    /\ FreeIds # {}
    /\ LET n == Min(FreeIds) IN
         /\ appr' = [appr EXCEPT ![n] = "pending"]
         /\ tAppr' = [tAppr EXCEPT ![w] = n]
    /\ tKind' = [tKind EXCEPT ![w] = "gate"]
    /\ tpc' = [tpc EXCEPT ![w] = "escalate"]
    /\ UNCHANGED <<shopVars, attempt, openEsc, teamEsc, unknownOut, inbox, queueVars,
                   lease, humanVars, recVars>>

\* Cota del modelo, no del código: sin ids libres el turno termina sin L3.
GateExhausted(w) ==
    /\ tpc[w] = "gate"
    /\ LiveAppr = {}
    /\ FreeIds = {}
    /\ tpc' = [tpc EXCEPT ![w] = "idle"]
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, tAppr, tKind, humanVars, recVars>>

\* Nodo escalate, una transacción: si no hay ninguna escalación abierta (del gate
\* o del equipo) crea la del gate (reason awaiting_human_approval:<id>); si la
\* hay, la reutiliza. Inserta el mensaje al cliente en la misma transacción.
Escalate(w) ==
    /\ tpc[w] = "escalate"
    /\ openEsc' = IF openEsc = {} /\ teamEsc = {} THEN {tAppr[w]} ELSE openEsc
    /\ tpc' = [tpc EXCEPT ![w] = "deliver"]
    /\ UNCHANGED <<shopVars, appr, attempt, teamEsc, unknownOut, inbox, queueVars,
                   tAppr, tKind, lease, humanVars, recVars>>

\* _deliver_outcome tras el grafo y complete_inbound_job.
Deliver(w) ==
    /\ tpc[w] = "deliver"
    /\ inbox' = Append(inbox, [k |-> tKind[w], a |-> tAppr[w]])
    /\ tpc' = [tpc EXCEPT ![w] = "idle"]
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, tAppr, tKind, humanVars, recVars>>

\* Excepción (fail_inbound_job con backoff), shutdown (release_inbound_job) o
\* muerte del proceso: el job vuelve a pending y se repite entero. Lo ya
\* committed se queda. inbound_already_answered no salva un turno que acabó
\* en escalate: ese mensaje no lleva metadata.inbound_message_id.
TurnFault(w) ==
    /\ tpc[w] # "idle"
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ unclaimed' = unclaimed + 1
    /\ tpc' = [tpc EXCEPT ![w] = "idle"]
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, tAppr, tKind, humanVars, recVars>>

\* El heartbeat no renueva a tiempo (event loop bloqueado, BD caída).
LeaseExpire(w) ==
    /\ LeaseCanExpire
    /\ LeaseHeld(w)
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, unclaimed, tpc, tAppr, tKind,
                   humanVars, recVars>>

(***************************************************************************)
(* Cierre de una ejecución (services/approval_execution.py:190-371).       *)
(* settle_executing_approval es un CAS desde `executing` con el mismo      *)
(* execution_attempt (db/queries.py:2966-2998). En la misma transacción:   *)
(*   applied    -> approved; release_escalations_after_executed_action     *)
(*                 cierra todas las abiertas, o, si el equipo tiene que    *)
(*                 rematarla (`fu`), hand_approval_to_team.                *)
(*   refused    -> failed; hand_approval_to_team.                          *)
(*   notapplied -> pending; nada más.                                      *)
(*   unknown    -> failed; hand_approval_to_team; sin mensaje al cliente.  *)
(* hand_approval_to_team (approval_resolution.py:142-163) cierra todas las *)
(* abiertas y abre una del equipo.                                         *)
(***************************************************************************)
SettleTo(res) ==
    CASE res = "applied"    -> "approved"
      [] res = "notapplied" -> "pending"
      [] OTHER              -> "failed"

CanSettle(a, at) == appr[a] = "executing" /\ attempt[a] = at

SettleDb(a, res, fu) ==
    /\ appr' = [appr EXCEPT ![a] = SettleTo(res)]
    /\ IF res = "notapplied"
         THEN UNCHANGED <<openEsc, teamEsc>>
         ELSE IF res = "applied" /\ ~fu
         THEN /\ openEsc' = {}
              /\ teamEsc' = {}
         ELSE /\ openEsc' = {}
              /\ teamEsc' = {a}
    /\ unknownOut' = IF res = "unknown" THEN unknownOut \cup {a} ELSE unknownOut
    /\ UNCHANGED attempt

\* Con mensaje al cliente, que se entrega después del COMMIT.
Tells(res) == res \in {"applied", "refused"}
OutcomeKind(res) == IF res = "applied" THEN "done" ELSE "failed"

(***************************************************************************)
(* Panel: routers/approvals.py. Ningún paso toma el advisory lock de la    *)
(* conversación. Cada transacción del panel es un paso: sus CAS bloquean   *)
(* la fila hasta el COMMIT, y quien espera vuelve a evaluar el WHERE.      *)
(***************************************************************************)
CanClick(h) == hpc[h] = "idle" /\ hClicks[h] < MaxClicks

\* _reviewable_approval (approvals.py:135-150): SELECT sin FOR UPDATE; si no
\* está pending, 409. La pantalla puede estar desactualizada.
ApproveClick(h, a) ==
    /\ CanClick(h)
    /\ appr[a] # "none"
    /\ hClicks' = [hClicks EXCEPT ![h] = @ + 1]
    /\ hAppr' = [hAppr EXCEPT ![h] = a]
    /\ hpc' = [hpc EXCEPT ![h] = IF appr[a] = "pending" THEN "a_claim" ELSE "idle"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hAtt, hRes, recVars>>

RejectClick(h, a) ==
    /\ CanClick(h)
    /\ appr[a] # "none"
    /\ hClicks' = [hClicks EXCEPT ![h] = @ + 1]
    /\ hAppr' = [hAppr EXCEPT ![h] = a]
    /\ hpc' = [hpc EXCEPT ![h] = IF appr[a] = "pending" THEN "r_cas" ELSE "idle"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hAtt, hRes, recVars>>

\* approvals.py:201-213, claim_pending_approval (db/queries.py:2907-2935): CAS
\* pending -> executing con execution_attempt + 1. Si no actualiza nada, 409 sin
\* ejecutar. load_execution_context va en la misma transacción.
ApproveClaim(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] = "a_claim"
    /\ IF appr[a] = "pending"
         THEN /\ appr' = [appr EXCEPT ![a] = "executing"]
              /\ attempt' = [attempt EXCEPT ![a] = @ + 1]
              /\ hAtt' = [hAtt EXCEPT ![h] = attempt[a] + 1]
              /\ hpc' = [hpc EXCEPT ![h] = "a_snap"]
         ELSE /\ hpc' = [hpc EXCEPT ![h] = "idle"]
              /\ UNCHANGED <<appr, attempt, hAtt>>
    /\ UNCHANGED <<shopVars, openEsc, teamEsc, unknownOut, inbox, queueVars, turnVars,
                   hAppr, hClicks, hRes, recVars>>

\* skill.execute: snapshot_before_mutation y, en cancel/address,
\* ensure_order_changeable (cancel_order.py:97-98, update_shipping_address.py:111-112).
\* El SkillRefusal en el primer claim es `Refused` (approval_execution.py:158-159);
\* en uno posterior se reconcilia (:162, :181-184).
ApproveSnapshot(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] = "a_snap"
    /\ IF skill \in Guarded /\ order # "open"
         THEN /\ hRes' = [hRes EXCEPT ![h] =
                            IF hAtt[h] > 1 /\ Found(a) THEN "applied" ELSE "refused"]
              /\ hpc' = [hpc EXCEPT ![h] = "a_settle"]
         ELSE /\ hpc' = [hpc EXCEPT ![h] = "a_mut"]
              /\ UNCHANGED hRes
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hAppr, hClicks, hAtt, recVars>>

\* La mutación en Shopify, en otra petición HTTP: entre el snapshot y aquí el
\* pedido puede haber cambiado.
\*   refund: find_refund antes de mutar (refund_partial.py:110-121) y refundCreate
\*           @idempotent con la aprobación como clave (shopify.py:1165): nunca dos reembolsos de
\*           la misma aprobación.
\*   cancel: Shopify rechaza orderCancel en CancelRefusedIn (ShopifyRejected es
\*           MutationNotApplied): NotApplied en el primer claim
\*           (approval_execution.py:160-161) y reconciliación después.
\* Con un fallo, la respuesta se pierde: Shopify pudo aplicarla o no, y
\* reconcile (:166-187) la encuentra (applied) o no se sabe (unknown), también si
\* la lectura de reconcile falla.
MutateEffect(h, applied) ==
    LET a == hAppr[h] IN
    /\ execs' = IF applied /\ ~(skill = "refund" /\ ExecCount(a) > 0)
                  THEN Append(execs, [a |-> a, at |-> order]) ELSE execs
    /\ order' = IF applied /\ skill = "cancel" THEN "cancelled" ELSE order

ShopifyRefuses == skill = "cancel" /\ order \in CancelRefusedIn

ApproveMutate(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] = "a_mut"
    /\ hpc' = [hpc EXCEPT ![h] = "a_settle"]
    /\ \/ /\ skill = "refund" /\ ExecCount(a) > 0
          /\ hRes' = [hRes EXCEPT ![h] = "applied"]
          /\ UNCHANGED <<order, execs, faults>>
       \/ /\ ~(skill = "refund" /\ ExecCount(a) > 0)
          /\ ShopifyRefuses
          /\ hRes' = [hRes EXCEPT ![h] =
                        IF hAtt[h] > 1 /\ Found(a) THEN "applied" ELSE "notapplied"]
          /\ UNCHANGED <<order, execs, faults>>
       \/ /\ ~(skill = "refund" /\ ExecCount(a) > 0)
          /\ ~ShopifyRefuses
          /\ MutateEffect(h, TRUE)
          /\ hRes' = [hRes EXCEPT ![h] = "applied"]
          /\ UNCHANGED faults
       \/ /\ ~(skill = "refund" /\ ExecCount(a) > 0)
          /\ faults < MaxFaults
          /\ faults' = faults + 1
          /\ \E applied \in IF ShopifyRefuses THEN {FALSE} ELSE BOOLEAN :
               /\ MutateEffect(h, applied)
               /\ \E res \in IF FoundIn(a, order', execs') THEN {"applied", "unknown"}
                                                          ELSE {"unknown"} :
                    hRes' = [hRes EXCEPT ![h] = res]
    /\ UNCHANGED <<skill, dbVars, inbox, arrived, unclaimed, turnVars, hAppr, hClicks, hAtt,
                   recVars>>

\* approval_execution.py:190-371. El CAS perdido es 409 sin escribir ni entregar.
ApproveSettle(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] = "a_settle"
    /\ IF CanSettle(a, hAtt[h])
         THEN \E fu \in BOOLEAN :
                /\ SettleDb(a, hRes[h], fu)
                /\ hpc' = [hpc EXCEPT ![h] = IF Tells(hRes[h]) THEN "a_del" ELSE "idle"]
         ELSE /\ hpc' = [hpc EXCEPT ![h] = "idle"]
              /\ UNCHANGED dbVars
    /\ UNCHANGED <<shopVars, inbox, queueVars, turnVars, hAppr, hClicks, hAtt, hRes, recVars>>

\* deliver_after_commit (approval_execution.py:396-409).
ApproveDeliver(h) ==
    /\ hpc[h] = "a_del"
    /\ inbox' = Append(inbox, [k |-> OutcomeKind(hRes[h]), a |-> hAppr[h]])
    /\ hpc' = [hpc EXCEPT ![h] = "idle"]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, turnVars, hAppr, hClicks, hAtt, hRes, recVars>>

\* approvals.py:299-318, una transacción: reject_pending_approval
\* (db/queries.py:2938-2963), CAS solo desde pending; si no actualiza nada, 409.
\* Después, el mensaje y release_approval_escalation (solo la del gate de esta
\* aprobación). La redacción con Haiku va antes, fuera de la transacción.
RejectCas(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] = "r_cas"
    /\ IF appr[a] = "pending"
         THEN /\ appr' = [appr EXCEPT ![a] = "rejected"]
              /\ openEsc' = openEsc \ {a}
              /\ hpc' = [hpc EXCEPT ![h] = "r_del"]
         ELSE /\ hpc' = [hpc EXCEPT ![h] = "idle"]
              /\ UNCHANGED <<appr, openEsc>>
    /\ UNCHANGED <<shopVars, attempt, teamEsc, unknownOut, inbox, queueVars, turnVars,
                   hAppr, hClicks, hAtt, hRes, recVars>>

\* approvals.py:320, después del COMMIT.
RejectDeliver(h) ==
    /\ hpc[h] = "r_del"
    /\ inbox' = Append(inbox, [k |-> "rejected", a |-> hAppr[h]])
    /\ hpc' = [hpc EXCEPT ![h] = "idle"]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, turnVars, hAppr, hClicks, hAtt, hRes, recVars>>

\* La petición muere (timeout de Cloud Run, reinicio). Lo committed se queda:
\* tras el claim, la aprobación sigue `executing` hasta la recuperación.
HumanFault(h) ==
    /\ hpc[h] # "idle"
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ hpc' = [hpc EXCEPT ![h] = "idle"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, unclaimed, turnVars, hAppr, hClicks,
                   hAtt, hRes, recVars>>

(***************************************************************************)
(* Recuperación (approval_execution.py:412-458): el job de limpieza lista  *)
(* las `executing` con reviewed_at de hace más de STALE_EXECUTION = 15 min *)
(* (db/queries.py:3001-3020), lee Shopify con reconcile(cause=None) y      *)
(* cierra con el mismo CAS por execution_attempt. Nunca ejecuta.           *)
(* Supuesto (approval_execution.py:67-69): pasados 15 min ninguna petición *)
(* sigue viva, porque Cloud Run corta a los 300 s. RecoverWhileRunning =   *)
(* TRUE lo quita.                                                          *)
(***************************************************************************)
Running(a) == \E h \in Humans : hpc[h] \in {"a_snap", "a_mut", "a_settle"}
                                 /\ hAppr[h] = a /\ hAtt[h] = attempt[a]

RecoverRead(r, a) ==
    /\ rpc[r] = "idle"
    /\ appr[a] = "executing"
    /\ RecoverWhileRunning \/ ~Running(a)
    /\ rAppr' = [rAppr EXCEPT ![r] = a]
    /\ rAtt' = [rAtt EXCEPT ![r] = attempt[a]]
    /\ rpc' = [rpc EXCEPT ![r] = "settle"]
    \* reconcile(cause=None): Applied si lo encuentra, NotApplied si no (:181-186);
    \* si la lectura falla, Unknown (:175-180).
    /\ \/ /\ rRes' = [rRes EXCEPT ![r] = IF Found(a) THEN "applied" ELSE "notapplied"]
          /\ UNCHANGED faults
       \/ /\ faults < MaxFaults
          /\ faults' = faults + 1
          /\ rRes' = [rRes EXCEPT ![r] = "unknown"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, unclaimed, turnVars, humanVars>>

RecoverSettle(r) ==
    /\ rpc[r] = "settle"
    /\ IF CanSettle(rAppr[r], rAtt[r])
         THEN \E fu \in BOOLEAN :
                /\ SettleDb(rAppr[r], rRes[r], fu)
                /\ rpc' = [rpc EXCEPT ![r] = IF Tells(rRes[r]) THEN "deliver" ELSE "idle"]
         ELSE /\ rpc' = [rpc EXCEPT ![r] = "idle"]
              /\ UNCHANGED dbVars
    /\ UNCHANGED <<shopVars, inbox, queueVars, turnVars, humanVars, rAppr, rAtt, rRes>>

RecoverDeliver(r) ==
    /\ rpc[r] = "deliver"
    /\ inbox' = Append(inbox, [k |-> OutcomeKind(rRes[r]), a |-> rAppr[r]])
    /\ rpc' = [rpc EXCEPT ![r] = "idle"]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, turnVars, humanVars, rAppr, rAtt, rRes>>

(***************************************************************************)
(* Especificación                                                          *)
(***************************************************************************)
TurnStep(w) ==
    \/ Claim(w) \/ PreReuse(w) \/ Precheck(w) \/ GateReuse(w) \/ GateCreate(w)
    \/ GateExhausted(w) \/ Escalate(w) \/ Deliver(w)

HumanStep(h) ==
    \/ ApproveClaim(h) \/ ApproveSnapshot(h) \/ ApproveMutate(h) \/ ApproveSettle(h)
    \/ ApproveDeliver(h) \/ RejectCas(h) \/ RejectDeliver(h)

RecoverStep(r) == (\E a \in Ids : RecoverRead(r, a)) \/ RecoverSettle(r) \/ RecoverDeliver(r)

Next ==
    \/ Arrive \/ Ship \/ MerchantCancel
    \/ \E r \in Recoverers : RecoverStep(r)
    \/ \E w \in Workers : (TurnStep(w) \/ TurnFault(w) \/ LeaseExpire(w))
    \/ \E h \in Humans : \/ \E a \in Ids : (ApproveClick(h, a) \/ RejectClick(h, a))
                         \/ HumanStep(h)
                         \/ HumanFault(h)

\* Un turno, una petición o una recuperación ya empezados avanzan, y el job de
\* limpieza corre periódicamente; nadie está obligado a escribir, a pulsar ni a
\* enviar el pedido.
Spec ==
    /\ Init /\ [][Next]_vars
    /\ \A w \in Workers : WF_vars(TurnStep(w))
    /\ \A h \in Humans : WF_vars(HumanStep(h))
    /\ \A r \in Recoverers : WF_vars(RecoverStep(r))

Perms == Permutations(Humans) \cup Permutations(Workers) \cup Permutations(Recoverers)

(***************************************************************************)
(* Propiedades                                                             *)
(***************************************************************************)
OutcomeCount(a) == Cardinality({i \in DOMAIN inbox : inbox[i].a = a /\ inbox[i].k \in Outcomes})
Quiescent ==
    /\ \A w \in Workers : tpc[w] = "idle"
    /\ \A h \in Humans : hpc[h] = "idle"
    /\ \A r \in Recoverers : rpc[r] = "idle"
    /\ unclaimed = 0
    /\ \A a \in Ids : appr[a] # "executing"

\* ADR 0008: nunca hay dos turnos a la vez sobre la misma conversación.
OneTurnAtATime == Cardinality({w \in Workers : tpc[w] # "idle"}) <= 1

\* La L3 se ejecuta como mucho una vez por aprobación.
ExecAtMostOnce == \A a \in Ids : ExecCount(a) <= 1

\* Y como mucho una vez por pedido: un pedido no acumula dos aprobaciones ejecutadas.
OneExecPerOrder == Len(execs) <= 1

\* cancel y address nunca mutan un pedido enviado o cancelado (refund sí puede:
\* reembolsar un pedido enviado es legítimo y no tiene guard).
NoExecOnClosedOrder ==
    skill \in Guarded => \A i \in DOMAIN execs : execs[i].at = "open"

\* Una aprobación rechazada nunca se ejecuta (no existe la caducidad).
RejectedNeverExecuted == \A a \in Ids : (appr[a] = "rejected" => ExecCount(a) = 0)

\* Lo ejecutado nunca vuelve a pending: un pending se puede volver a aprobar.
ExecutedNeverPending == \A a \in Ids : (ExecCount(a) > 0 => appr[a] # "pending")

\* El cliente recibe un solo resultado por aprobación...
OneOutcomePerApproval == \A a \in Ids : OutcomeCount(a) <= 1

\* ...que dice la verdad: "rechazada" o "no se pudo" solo si no se ejecutó...
OutcomeIsTruthful ==
    \A i \in DOMAIN inbox :
        (inbox[i].k \in {"rejected", "failed"} => ExecCount(inbox[i].a) = 0)

\* ...y que ningún "sigue en revisión" contradice después.
NoWaitingAfterOutcome ==
    \A i, j \in DOMAIN inbox :
        (i < j /\ inbox[i].k \in Outcomes /\ inbox[j].k = "waiting")
            => inbox[i].a # inbox[j].a

\* En reposo, toda escalación de gate abierta apunta a una aprobación pending
\* (si no, nadie puede cerrarla desde el panel y la conversación queda escalada).
NoOrphanEscalation == Quiescent => (\A a \in openEsc : appr[a] = "pending")

\* En reposo, lo ejecutado en Shopify consta como aprobado, o como failed con el
\* resultado desconocido y el caso en manos del equipo (lo que #376 manda hacer
\* ante la duda).
ExecutedIsApproved ==
    Quiescent => \A a \in Ids :
        ExecCount(a) > 0 => \/ appr[a] = "approved"
                            \/ appr[a] = "failed" /\ a \in unknownOut

\* Liveness. Los mensajes del cliente siempre se acaban reclamando.
MessagesTaken == unclaimed > 0 ~> unclaimed = 0

\* Liveness. Una ejecución siempre se cierra: la cierra su petición o la recuperación.
ExecutionSettles == \A a \in Ids : appr[a] = "executing" ~> appr[a] # "executing"

\* Liveness. Toda aprobación acaba en un estado final. Se espera que FALLE:
\* no hay caducidad y nada obliga a un humano a decidir.
ApprovalEventuallyFinal == \A a \in Ids : appr[a] = "pending" ~> appr[a] \in Final
=============================================================================
