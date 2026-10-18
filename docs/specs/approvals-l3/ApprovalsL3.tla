----------------------------- MODULE ApprovalsL3 -----------------------------
(***************************************************************************)
(* Aprobaciones L3 frente a la cola inbound (issue #341, ADR 0008).        *)
(*                                                                         *)
(* Modela lo que hace el código de `develop` (9f30a82), no lo que dice la  *)
(* documentación. Cada acción es un paso atómico del código; README.md     *)
(* cita el archivo:línea y la transacción o el lock que lo hace atómico.   *)
(*                                                                         *)
(* Una conversación, un pedido y una skill L3 (`skill`, elegida en Init    *)
(* entre `Skills`). Actores concurrentes:                                  *)
(*   - Workers: slots del worker de `inbound_jobs` que corren turnos.      *)
(*   - Humans: operadores que pulsan Aprobar o Rechazar en el panel.       *)
(*   - Shopify: el pedido puede salir o cancelarse en cualquier momento.   *)
(*   - Fallos: caída del proceso o lease vencido, acotados por MaxFaults.  *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets, TLC

CONSTANTS
    Humans,           \* operadores del panel
    Workers,          \* slots del worker de la cola
    NoOne,            \* nadie tiene el lock de fila
    Skills,           \* subconjunto de {"cancel", "address", "refund"}
    MaxMsgs,          \* mensajes del cliente que llegan al webhook
    MaxApprovals,     \* filas de pending_approvals que puede crear el gate
    MaxClicks,        \* clics de cada operador
    MaxFaults,        \* caídas de proceso más leases vencidos, en total
    LeaseCanExpire,   \* el heartbeat puede no renovar el lease a tiempo
    CancelRefusedIn   \* estados en los que Shopify rechaza orderCancel (supuesto)

ASSUME
    /\ Skills \subseteq {"cancel", "address", "refund"} /\ Skills # {}
    /\ NoOne \notin Humans
    /\ MaxMsgs \in Nat /\ MaxApprovals \in Nat \ {0}
    /\ MaxClicks \in Nat /\ MaxFaults \in Nat
    /\ LeaseCanExpire \in BOOLEAN
    /\ CancelRefusedIn \subseteq {"open", "shipped", "cancelled"}

Ids         == 1..MaxApprovals
Guarded     == {"cancel", "address"}   \* skills que llaman a ensure_order_changeable
OrderStates == {"open", "shipped", "cancelled"}
ApprStates  == {"none", "pending", "approved", "rejected"}
Final       == {"approved", "rejected"}
Outcomes    == {"done", "rejected"}
MsgKinds    == {"gate", "waiting", "followup_done", "refused"} \cup Outcomes
TurnPcs     == {"idle", "precheck", "gate", "escalate", "deliver"}
HumanPcs    == {"idle", "a_snap", "a_mut", "a_cas", "a_rel", "a_del",
                "r_cas", "r_rel", "r_del", "commit"}

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

VARIABLES
    skill,      \* la L3 de este comportamiento
    order,      \* estado del pedido en Shopify
    execs,      \* mutaciones que Shopify aceptó: <<[a, at]>>
    appr,       \* status COMMITTED de cada fila de pending_approvals
    lockedBy,   \* lock de fila que deja un UPDATE ... WHERE status='pending'
    openEsc,    \* escalaciones del gate abiertas (committed), por approval id
    inbox,      \* mensajes que recibió el cliente, en orden: <<[k, a]>>
    arrived,    \* mensajes del cliente ya encolados
    unclaimed,  \* jobs pendientes sin reclamar
    faults,     \* fallos consumidos
    tpc, tAppr, tKind, lease,           \* estado de cada turno
    hpc, hAppr, hClicks, hTent, hRel    \* estado de cada petición del panel

shopVars  == <<skill, order, execs>>
dbVars    == <<appr, lockedBy, openEsc>>
queueVars == <<arrived, unclaimed, faults>>
turnVars  == <<tpc, tAppr, tKind, lease>>
humanVars == <<hpc, hAppr, hClicks, hTent, hRel>>
vars      == <<shopVars, dbVars, inbox, queueVars, turnVars, humanVars>>

TypeOK ==
    /\ skill \in Skills
    /\ order \in OrderStates
    /\ execs \in Seq([a : Ids, at : OrderStates])
    /\ appr \in [Ids -> ApprStates]
    /\ lockedBy \in [Ids -> Humans \cup {NoOne}]
    /\ openEsc \subseteq Ids
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
    /\ hTent \in [Humans -> {"none", "approved", "rejected"}]
    /\ hRel \in [Humans -> SUBSET Ids]

Init ==
    /\ skill \in Skills
    /\ order = "open"
    /\ execs = <<>>
    /\ appr = [i \in Ids |-> "none"]
    /\ lockedBy = [i \in Ids |-> NoOne]
    /\ openEsc = {}
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
    /\ hTent = [h \in Humans |-> "none"]
    /\ hRel = [h \in Humans |-> {}]

(***************************************************************************)
(* Entorno: el cliente escribe; Shopify cambia el pedido.                  *)
(***************************************************************************)
Arrive ==
    /\ arrived < MaxMsgs
    /\ arrived' = arrived + 1
    /\ unclaimed' = unclaimed + 1
    /\ UNCHANGED <<shopVars, dbVars, inbox, faults, turnVars, humanVars>>

Ship ==
    /\ order = "open"
    /\ order' = "shipped"
    /\ UNCHANGED <<skill, execs, dbVars, inbox, queueVars, turnVars, humanVars>>

MerchantCancel ==
    /\ order = "open"
    /\ order' = "cancelled"
    /\ UNCHANGED <<skill, execs, dbVars, inbox, queueVars, turnVars, humanVars>>

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
    /\ tpc' = [tpc EXCEPT ![w] = "precheck"]
    /\ lease' = [v \in Workers |-> v = w \/ tpc[v] # "idle"]
    /\ tAppr' = [tAppr EXCEPT ![w] = 0]
    /\ tKind' = [tKind EXCEPT ![w] = "none"]
    /\ unclaimed' = 0
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, faults, humanVars>>

\* El LLM pide la L3. prepare_approval relee el pedido: cancel y address
\* rechazan uno enviado o cancelado (SkillRefusal); refund solo mira el saldo.
Precheck(w) ==
    /\ tpc[w] = "precheck"
    /\ IF skill \in Guarded /\ order # "open"
         THEN /\ tpc' = [tpc EXCEPT ![w] = "deliver"]
              /\ tKind' = [tKind EXCEPT ![w] = "refused"]
         ELSE /\ tpc' = [tpc EXCEPT ![w] = "gate"]
              /\ UNCHANGED tKind
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, tAppr, lease, humanVars>>

LiveAppr == {i \in Ids : appr[i] \in {"pending", "approved"}}
FreeIds  == {i \in Ids : appr[i] = "none"}

\* Gate L3, una transacción: get_recent_approval_for_skill (pending o approved,
\* la más reciente) y, si no hay, create_pending_approval.
GateReuse(w) ==
    /\ tpc[w] = "gate"
    /\ LiveAppr # {}
    /\ LET r == Max(LiveAppr) IN
         /\ tAppr' = [tAppr EXCEPT ![w] = r]
         /\ tKind' = [tKind EXCEPT ![w] =
                        IF appr[r] = "approved" THEN "followup_done" ELSE "waiting"]
    /\ tpc' = [tpc EXCEPT ![w] = "escalate"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, lease, humanVars>>

GateCreate(w) ==
    /\ tpc[w] = "gate"
    /\ LiveAppr = {}
    /\ FreeIds # {}
    /\ LET n == Min(FreeIds) IN
         /\ appr' = [appr EXCEPT ![n] = "pending"]
         /\ tAppr' = [tAppr EXCEPT ![w] = n]
    /\ tKind' = [tKind EXCEPT ![w] = "gate"]
    /\ tpc' = [tpc EXCEPT ![w] = "escalate"]
    /\ UNCHANGED <<shopVars, lockedBy, openEsc, inbox, queueVars, lease, humanVars>>

\* Cota del modelo, no del código: sin ids libres el turno termina sin L3.
GateExhausted(w) ==
    /\ tpc[w] = "gate"
    /\ LiveAppr = {}
    /\ FreeIds = {}
    /\ tpc' = [tpc EXCEPT ![w] = "idle"]
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, tAppr, tKind, humanVars>>

\* Nodo escalate, una transacción: si no hay escalación abierta crea la del
\* gate (reason awaiting_human_approval:<id>); si la hay, la reutiliza.
\* Inserta el mensaje al cliente en la misma transacción.
Escalate(w) ==
    /\ tpc[w] = "escalate"
    /\ openEsc' = IF openEsc = {} THEN {tAppr[w]} ELSE openEsc
    /\ tpc' = [tpc EXCEPT ![w] = "deliver"]
    /\ UNCHANGED <<shopVars, appr, lockedBy, inbox, queueVars, tAppr, tKind, lease, humanVars>>

\* _deliver_outcome tras el grafo y complete_inbound_job.
Deliver(w) ==
    /\ tpc[w] = "deliver"
    /\ inbox' = Append(inbox, [k |-> tKind[w], a |-> tAppr[w]])
    /\ tpc' = [tpc EXCEPT ![w] = "idle"]
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, tAppr, tKind, humanVars>>

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
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, tAppr, tKind, humanVars>>

\* El heartbeat no renueva a tiempo (event loop bloqueado, BD caída).
LeaseExpire(w) ==
    /\ LeaseCanExpire
    /\ LeaseHeld(w)
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ lease' = [lease EXCEPT ![w] = FALSE]
    /\ UNCHANGED <<shopVars, dbVars, inbox, arrived, unclaimed, tpc, tAppr, tKind, humanVars>>

(***************************************************************************)
(* Panel: routers/approvals.py. Ningún paso toma el advisory lock de la    *)
(* conversación. El UPDATE de resolve_pending_approval es un CAS sobre     *)
(* status='pending' que deja la fila bloqueada hasta el COMMIT, pero los   *)
(* dos endpoints ignoran su resultado.                                     *)
(***************************************************************************)
CanClick(h) == hpc[h] = "idle" /\ hClicks[h] < MaxClicks

\* _reviewable_approval: SELECT sin FOR UPDATE; si no está pending, 403.
ApproveClick(h, a) ==
    /\ CanClick(h)
    /\ appr[a] # "none"
    /\ hClicks' = [hClicks EXCEPT ![h] = @ + 1]
    /\ hAppr' = [hAppr EXCEPT ![h] = a]
    /\ hpc' = [hpc EXCEPT ![h] = IF appr[a] = "pending" THEN "a_snap" ELSE "idle"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hTent, hRel>>

RejectClick(h, a) ==
    /\ CanClick(h)
    /\ appr[a] # "none"
    /\ hClicks' = [hClicks EXCEPT ![h] = @ + 1]
    /\ hAppr' = [hAppr EXCEPT ![h] = a]
    /\ hpc' = [hpc EXCEPT ![h] = IF appr[a] = "pending" THEN "r_cas" ELSE "idle"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hTent, hRel>>

\* skill.execute: get_order_snapshot y, en cancel/address, ensure_order_changeable.
\* El SkillRefusal cae en el except de approve_action: execution_status=failed,
\* la aprobación sigue pending y no sale mensaje.
ApproveSnapshot(h) ==
    /\ hpc[h] = "a_snap"
    /\ hpc' = [hpc EXCEPT ![h] =
                 IF skill \in Guarded /\ order # "open" THEN "idle" ELSE "a_mut"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hAppr, hClicks, hTent, hRel>>

\* La mutación en Shopify, en otra petición HTTP: entre el snapshot y aquí el
\* pedido puede haber cambiado. Shopify no recibe clave de idempotencia.
ApproveMutate(h) ==
    /\ hpc[h] = "a_mut"
    /\ IF skill = "cancel" /\ order \in CancelRefusedIn
         THEN /\ hpc' = [hpc EXCEPT ![h] = "idle"]
              /\ UNCHANGED <<order, execs>>
         ELSE /\ execs' = Append(execs, [a |-> hAppr[h], at |-> order])
              /\ order' = IF skill = "cancel" THEN "cancelled" ELSE order
              /\ hpc' = [hpc EXCEPT ![h] = "a_cas"]
    /\ UNCHANGED <<skill, dbVars, inbox, queueVars, turnVars, hAppr, hClicks, hTent, hRel>>

\* UPDATE ... WHERE status='pending': espera si otra transacción tiene la fila;
\* tras su COMMIT vuelve a evaluar el WHERE (READ COMMITTED).
Cas(h, status, next) ==
    LET a == hAppr[h] IN
    /\ lockedBy[a] \in {NoOne, h}
    /\ IF appr[a] = "pending"
         THEN /\ lockedBy' = [lockedBy EXCEPT ![a] = h]
              /\ hTent' = [hTent EXCEPT ![h] = status]
         ELSE /\ UNCHANGED lockedBy
              /\ hTent' = [hTent EXCEPT ![h] = "none"]
    /\ hpc' = [hpc EXCEPT ![h] = next]
    /\ UNCHANGED <<shopVars, appr, openEsc, inbox, queueVars, turnVars, hAppr, hClicks, hRel>>

ApproveCas(h) == hpc[h] = "a_cas" /\ Cas(h, "approved", "a_rel")
RejectCas(h)  == hpc[h] = "r_cas" /\ Cas(h, "rejected", "r_rel")

\* release_escalations_after_executed_action: cierra todas las abiertas que
\* el UPDATE ve en ese momento (también si el CAS no hizo nada).
ApproveRelease(h) ==
    /\ hpc[h] = "a_rel"
    /\ hRel' = [hRel EXCEPT ![h] = openEsc]
    /\ hpc' = [hpc EXCEPT ![h] = "a_del"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hAppr, hClicks, hTent>>

\* release_approval_escalation: solo la del gate de esta aprobación.
RejectRelease(h) ==
    /\ hpc[h] = "r_rel"
    /\ hRel' = [hRel EXCEPT ![h] = openEsc \cap {hAppr[h]}]
    /\ hpc' = [hpc EXCEPT ![h] = "r_del"]
    /\ UNCHANGED <<shopVars, dbVars, inbox, queueVars, turnVars, hAppr, hClicks, hTent>>

\* deliver_message_to_helpdesk corre DENTRO de la transacción, antes del COMMIT.
ApproveDeliver(h) ==
    /\ hpc[h] = "a_del"
    /\ inbox' = Append(inbox, [k |-> "done", a |-> hAppr[h]])
    /\ hpc' = [hpc EXCEPT ![h] = "commit"]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, turnVars, hAppr, hClicks, hTent, hRel>>

RejectDeliver(h) ==
    /\ hpc[h] = "r_del"
    /\ inbox' = Append(inbox, [k |-> "rejected", a |-> hAppr[h]])
    /\ hpc' = [hpc EXCEPT ![h] = "commit"]
    /\ UNCHANGED <<shopVars, dbVars, queueVars, turnVars, hAppr, hClicks, hTent, hRel>>

\* COMMIT: se hacen visibles el status y el cierre de escalaciones; se suelta la fila.
Commit(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] = "commit"
    /\ appr' = IF hTent[h] = "none" THEN appr ELSE [appr EXCEPT ![a] = hTent[h]]
    /\ lockedBy' = IF lockedBy[a] = h THEN [lockedBy EXCEPT ![a] = NoOne] ELSE lockedBy
    /\ openEsc' = openEsc \ hRel[h]
    /\ hpc' = [hpc EXCEPT ![h] = "idle"]
    /\ hTent' = [hTent EXCEPT ![h] = "none"]
    /\ hRel' = [hRel EXCEPT ![h] = {}]
    /\ UNCHANGED <<shopVars, inbox, queueVars, turnVars, hAppr, hClicks>>

\* La petición muere (timeout de Cloud Run, reinicio): ROLLBACK de lo no
\* committed. Lo que ya salió a Shopify o al cliente no se deshace.
HumanFault(h) ==
    LET a == hAppr[h] IN
    /\ hpc[h] # "idle"
    /\ faults < MaxFaults
    /\ faults' = faults + 1
    /\ lockedBy' = IF lockedBy[a] = h THEN [lockedBy EXCEPT ![a] = NoOne] ELSE lockedBy
    /\ hpc' = [hpc EXCEPT ![h] = "idle"]
    /\ hTent' = [hTent EXCEPT ![h] = "none"]
    /\ hRel' = [hRel EXCEPT ![h] = {}]
    /\ UNCHANGED <<shopVars, appr, openEsc, inbox, arrived, unclaimed, turnVars, hAppr, hClicks>>

(***************************************************************************)
(* Especificación                                                          *)
(***************************************************************************)
TurnStep(w) ==
    \/ Claim(w) \/ Precheck(w) \/ GateReuse(w) \/ GateCreate(w)
    \/ GateExhausted(w) \/ Escalate(w) \/ Deliver(w)

HumanStep(h) ==
    \/ ApproveSnapshot(h) \/ ApproveMutate(h) \/ ApproveCas(h) \/ ApproveRelease(h)
    \/ ApproveDeliver(h) \/ RejectCas(h) \/ RejectRelease(h) \/ RejectDeliver(h)
    \/ Commit(h)

Next ==
    \/ Arrive \/ Ship \/ MerchantCancel
    \/ \E w \in Workers : (TurnStep(w) \/ TurnFault(w) \/ LeaseExpire(w))
    \/ \E h \in Humans : \/ \E a \in Ids : (ApproveClick(h, a) \/ RejectClick(h, a))
                         \/ HumanStep(h)
                         \/ HumanFault(h)

\* Un turno o una petición ya empezados avanzan; nadie está obligado a escribir,
\* a pulsar ni a enviar el pedido.
Spec ==
    /\ Init /\ [][Next]_vars
    /\ \A w \in Workers : WF_vars(TurnStep(w))
    /\ \A h \in Humans : WF_vars(HumanStep(h))

Perms == Permutations(Humans) \cup Permutations(Workers)

(***************************************************************************)
(* Propiedades                                                             *)
(***************************************************************************)
ExecCount(a)    == Cardinality({i \in DOMAIN execs : execs[i].a = a})
OutcomeCount(a) == Cardinality({i \in DOMAIN inbox : inbox[i].a = a /\ inbox[i].k \in Outcomes})
Quiescent ==
    /\ \A w \in Workers : tpc[w] = "idle"
    /\ \A h \in Humans : hpc[h] = "idle"
    /\ unclaimed = 0

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

\* El cliente recibe un solo resultado por aprobación...
OneOutcomePerApproval == \A a \in Ids : OutcomeCount(a) <= 1

\* ...que dice la verdad...
OutcomeIsTruthful ==
    \A i \in DOMAIN inbox : (inbox[i].k = "rejected" => ExecCount(inbox[i].a) = 0)

\* ...y que ningún "sigue en revisión" contradice después.
NoWaitingAfterOutcome ==
    \A i, j \in DOMAIN inbox :
        (i < j /\ inbox[i].k \in Outcomes /\ inbox[j].k = "waiting")
            => inbox[i].a # inbox[j].a

\* En reposo, toda escalación de gate abierta apunta a una aprobación pending
\* (si no, nadie puede cerrarla desde el panel y la conversación queda escalada).
NoOrphanEscalation == Quiescent => (\A a \in openEsc : appr[a] = "pending")

\* En reposo, lo ejecutado en Shopify consta como aprobado.
ExecutedIsApproved ==
    Quiescent => (\A a \in Ids : (ExecCount(a) > 0 => appr[a] = "approved"))

\* Liveness. Los mensajes del cliente siempre se acaban reclamando.
MessagesTaken == unclaimed > 0 ~> unclaimed = 0

\* Liveness. Toda aprobación acaba en un estado final. Se espera que FALLE:
\* no hay caducidad y nada obliga a un humano a decidir.
ApprovalEventuallyFinal == \A a \in Ids : appr[a] = "pending" ~> appr[a] \in Final
=============================================================================
