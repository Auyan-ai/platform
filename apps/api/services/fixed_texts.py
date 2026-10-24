"""Textos fijos para el cliente final, por idioma: sin LLM, deterministas y personalizables.

Todo texto que el cliente recibe sin pasar por el modelo vive aquí, con una entrada por
idioma soportado (`LANGUAGE_CODES`). Un test falla si una clave no los trae todos.

Resolución de `fixed_text(key, language, tenant_default=..., overrides=...)`, para cada
idioma de la cadena `language → idioma por defecto del tenant → es`:

1. el override del tenant en ese idioma, si lo hay;
2. el catálogo en ese idioma.

Un override es un `str` (vale solo para el idioma por defecto del tenant, así los
overrides históricos siguen funcionando) o un `{idioma: texto}`. Los parámetros
(`{address}`, `{comment}`) se rellenan solo en los textos del catálogo, nunca en los del
tenant.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

LANGUAGE_CODES: tuple[str, ...] = ("es", "en", "ca", "fr")
FALLBACK_LANGUAGE = "es"

Texts = dict[str, str]


def _t(es: str, en: str, ca: str, fr: str) -> Texts:
    return {"es": es, "en": en, "ca": ca, "fr": fr}


def _then(base: Texts, tail: Texts) -> Texts:
    return {lang: f"{base[lang]} {tail[lang]}" for lang in LANGUAGE_CODES}


_TEAM_WILL_WRITE = _t(
    "Nuestro equipo ya está avisado y te escribirá en cuanto lo tenga resuelto.",
    "Our team has been notified and will write to you as soon as it is sorted.",
    "El nostre equip ja està avisat i t'escriurà tan bon punt ho tingui resolt.",
    "Notre équipe est prévenue et t'écrira dès que ce sera réglé.",
)

_PASS_TO_TEAM = _t(
    "Paso tu caso a mi equipo para que lo revise y te escriba.",
    "I'm passing your case to my team so they can review it and write to you.",
    "Passo el teu cas al meu equip perquè el revisi i t'escrigui.",
    "Je transmets ton dossier à mon équipe pour qu'elle l'examine et t'écrive.",
)

CATALOG: dict[str, Texts] = {
    # ─── Verificación de identidad (ADR 0013 §10) ────────────────────────────────
    "guest_not_verified": _t(
        "No he podido verificar esos datos. Revisa el número de pedido y el email o "
        "teléfono con el que compraste.",
        "I couldn't verify those details. Please check the order number and the email or "
        "phone number you used to buy.",
        "No he pogut verificar aquestes dades. Revisa el número de comanda i el correu o "
        "telèfon amb què vas comprar.",
        "Je n'ai pas pu vérifier ces informations. Vérifie le numéro de commande et "
        "l'e-mail ou le téléphone utilisés pour l'achat.",
    ),
    "guest_locked": _t(
        "Por seguridad no puedo hacer más comprobaciones en esta conversación. Si quieres, "
        "paso tu caso a una persona del equipo para que te ayude.",
        "For security reasons I can't run any more checks in this conversation. If you "
        "like, I can pass your case to a member of the team to help you.",
        "Per seguretat no puc fer més comprovacions en aquesta conversa. Si vols, passo el "
        "teu cas a una persona de l'equip perquè t'ajudi.",
        "Pour des raisons de sécurité, je ne peux plus faire de vérifications dans cette "
        "conversation. Si tu veux, je transmets ton dossier à une personne de l'équipe "
        "pour qu'elle t'aide.",
    ),
    "guest_paused": _t(
        "Ahora mismo no puedo verificar pedidos. Inténtalo de nuevo en unos minutos o dime "
        "si prefieres que pase tu caso a una persona del equipo.",
        "I can't verify orders right now. Please try again in a few minutes, or tell me if "
        "you'd rather I pass your case to a member of the team.",
        "Ara mateix no puc verificar comandes. Torna-ho a provar d'aquí a uns minuts o "
        "digues-me si prefereixes que passi el teu cas a una persona de l'equip.",
        "Je ne peux pas vérifier de commandes pour le moment. Réessaie dans quelques "
        "minutes ou dis-moi si tu préfères que je transmette ton dossier à une personne "
        "de l'équipe.",
    ),
    # La tienda no responde: no es un fallo de identidad del cliente.
    "commerce_unavailable": _t(
        "Ahora mismo no puedo consultar los pedidos de la tienda. Paso tu caso a una persona "
        "del equipo para que lo revise y te responda.",
        "I can't look up the store's orders right now. I'm passing your case to a member of "
        "the team so they can review it and get back to you.",
        "Ara mateix no puc consultar les comandes de la botiga. Passo el teu cas a una "
        "persona de l'equip perquè el revisi i et respongui.",
        "Je ne peux pas consulter les commandes de la boutique pour le moment. Je "
        "transmets ton dossier à une personne de l'équipe pour qu'elle l'examine et te "
        "réponde.",
    ),
    # ─── Adjuntos y acuses de escalado ───────────────────────────────────────────
    "media_without_text": _t(
        "¡Gracias! Hemos recibido tu archivo, pero no podemos verlo. ¿Nos cuentas por "
        "escrito en qué te podemos ayudar?",
        "Thanks! We received your file, but we can't view it. Could you tell us in writing "
        "how we can help you?",
        "Gràcies! Hem rebut el teu fitxer, però no el podem veure. Ens expliques per escrit "
        "en què et podem ajudar?",
        "Merci ! Nous avons bien reçu ton fichier, mais nous ne pouvons pas le voir. Peux-tu "
        "nous écrire comment nous pouvons t'aider ?",
    ),
    "audio_unavailable": _t(
        "No hemos podido escuchar tu nota de voz. ¿Nos escribes tu consulta, por favor?",
        "We couldn't listen to your voice note. Could you write your question for us, please?",
        "No hem pogut escoltar la teva nota de veu. Ens escrius la teva consulta, si us plau?",
        "Nous n'avons pas pu écouter ton message vocal. Peux-tu nous écrire ta demande, "
        "s'il te plaît ?",
    ),
    "audio_too_long": _t(
        "Tu nota de voz es demasiado larga para procesarla. ¿Nos escribes tu consulta en un "
        "mensaje, por favor?",
        "Your voice note is too long for us to process. Could you write your question in a "
        "message, please?",
        "La teva nota de veu és massa llarga per processar-la. Ens escrius la teva consulta "
        "en un missatge, si us plau?",
        "Ton message vocal est trop long pour être traité. Peux-tu nous écrire ta demande "
        "dans un message, s'il te plaît ?",
    ),
    "download_failed": _t(
        "No hemos podido abrir lo que nos enviaste. ¿Puedes escribirnos tu consulta, por favor?",
        "We couldn't open what you sent us. Could you write your question for us, please?",
        "No hem pogut obrir el que ens has enviat. Ens pots escriure la teva consulta, si us "
        "plau?",
        "Nous n'avons pas pu ouvrir ce que tu nous as envoyé. Peux-tu nous écrire ta "
        "demande, s'il te plaît ?",
    ),
    "unsupported": _t(
        "¿En qué te podemos ayudar? Escríbenos tu consulta, por favor.",
        "How can we help you? Please write your question for us.",
        "En què et podem ajudar? Escriu-nos la teva consulta, si us plau.",
        "Comment pouvons-nous t'aider ? Écris-nous ta demande, s'il te plaît.",
    ),
    "escalation_ack": _t(
        "He pasado tu consulta a nuestro equipo. Te responderán por aquí lo antes posible.",
        "I've passed your question to our team. They'll reply here as soon as possible.",
        "He passat la teva consulta al nostre equip. Et respondran per aquí tan aviat com "
        "sigui possible.",
        "J'ai transmis ta demande à notre équipe. Elle te répondra ici dès que possible.",
    ),
    # ─── Reglas del grafo ────────────────────────────────────────────────────────
    "no_progress": _t(
        "Para no hacerte perder más tiempo, paso tu caso a una persona del equipo, que lo "
        "revisará y te responderá por aquí.",
        "So I don't waste any more of your time, I'm passing your case to a member of the "
        "team, who will review it and reply here.",
        "Per no fer-te perdre més temps, passo el teu cas a una persona de l'equip, que el "
        "revisarà i et respondrà per aquí.",
        "Pour ne pas te faire perdre plus de temps, je transmets ton dossier à une personne "
        "de l'équipe, qui l'examinera et te répondra ici.",
    ),
    "iterations_exhausted": _t(
        "Gracias por escribirnos. He pasado tu consulta a una persona del equipo, "
        "que la revisará y te responderá lo antes posible.",
        "Thanks for writing to us. I've passed your question to a member of the team, who "
        "will review it and reply as soon as possible.",
        "Gràcies per escriure'ns. He passat la teva consulta a una persona de l'equip, que "
        "la revisarà i et respondrà tan aviat com pugui.",
        "Merci de nous avoir écrit. J'ai transmis ta demande à une personne de l'équipe, "
        "qui l'examinera et te répondra dès que possible.",
    ),
    "message_cap": _t(
        "Hemos recibido muchos mensajes en esta conversación y la hemos asignado "
        "a un agente humano para darte la mejor atención posible. "
        "Un miembro del equipo estará contigo en breve.",
        "We've received a lot of messages in this conversation, so we've assigned it to a "
        "human agent to give you the best service possible. A member of the team will be "
        "with you shortly.",
        "Hem rebut molts missatges en aquesta conversa i l'hem assignat a un agent humà per "
        "donar-te la millor atenció possible. Un membre de l'equip serà amb tu en breu.",
        "Nous avons reçu beaucoup de messages dans cette conversation et nous l'avons "
        "confiée à un agent humain pour t'offrir le meilleur service possible. Un membre "
        "de l'équipe sera bientôt avec toi.",
    ),
    "nudge": _t(
        "¿Pudimos resolver tu consulta? Si hay algo más en lo que podamos ayudarte, "
        "estamos aquí. Esta conversación se cerrará automáticamente si no recibimos "
        "respuesta pronto.",
        "Were we able to resolve your question? If there's anything else we can help you "
        "with, we're here. This conversation will close automatically if we don't hear "
        "back soon.",
        "Hem pogut resoldre la teva consulta? Si hi ha res més en què et puguem ajudar, som "
        "aquí. Aquesta conversa es tancarà automàticament si aviat no rebem resposta.",
        "Avons-nous pu répondre à ta demande ? Si nous pouvons t'aider sur autre chose, "
        "nous sommes là. Cette conversation sera clôturée automatiquement si nous ne "
        "recevons pas de réponse bientôt.",
    ),
    # ─── Rechazos de las L3 sobre un pedido ──────────────────────────────────────
    "refusal.order_shipped.address": _t(
        "Tu pedido ya ha salido del almacén, así que no puedo cambiar la dirección "
        "desde aquí. Paso tu caso a mi equipo para que revise qué se puede hacer con "
        "el envío y te escriba.",
        "Your order has already left the warehouse, so I can't change the address from "
        "here. I'm passing your case to my team so they can check what can be done about "
        "the shipment and write to you.",
        "La teva comanda ja ha sortit del magatzem, així que no puc canviar l'adreça des "
        "d'aquí. Passo el teu cas al meu equip perquè revisi què es pot fer amb l'enviament "
        "i t'escrigui.",
        "Ta commande a déjà quitté l'entrepôt, donc je ne peux pas modifier l'adresse "
        "depuis ici. Je transmets ton dossier à mon équipe pour qu'elle regarde ce qui "
        "peut être fait pour l'envoi et t'écrive.",
    ),
    "refusal.order_shipped.cancel": _t(
        "Tu pedido ya ha salido del almacén, así que no puedo cancelarlo desde aquí. "
        "Paso tu caso a mi equipo para que te indique cómo seguir.",
        "Your order has already left the warehouse, so I can't cancel it from here. I'm "
        "passing your case to my team so they can tell you how to proceed.",
        "La teva comanda ja ha sortit del magatzem, així que no la puc cancel·lar des "
        "d'aquí. Passo el teu cas al meu equip perquè t'indiqui com continuar.",
        "Ta commande a déjà quitté l'entrepôt, donc je ne peux pas l'annuler depuis ici. "
        "Je transmets ton dossier à mon équipe pour qu'elle t'indique comment procéder.",
    ),
    "refusal.order_cancelled.address": _t(
        "Tu pedido figura como cancelado, así que no puedo cambiar su dirección. "
        "Paso tu caso a mi equipo para que lo revise y te escriba.",
        "Your order shows as cancelled, so I can't change its address. I'm passing your "
        "case to my team so they can review it and write to you.",
        "La teva comanda figura com a cancel·lada, així que no puc canviar-ne l'adreça. "
        "Passo el teu cas al meu equip perquè el revisi i t'escrigui.",
        "Ta commande apparaît comme annulée, donc je ne peux pas en modifier l'adresse. "
        "Je transmets ton dossier à mon équipe pour qu'elle l'examine et t'écrive.",
    ),
    "refusal.order_cancelled.cancel": _t(
        "Tu pedido ya figura como cancelado. Paso tu caso a mi equipo para que "
        "revise el estado del reembolso y te escriba.",
        "Your order already shows as cancelled. I'm passing your case to my team so they "
        "can check the status of the refund and write to you.",
        "La teva comanda ja figura com a cancel·lada. Passo el teu cas al meu equip perquè "
        "revisi l'estat del reemborsament i t'escrigui.",
        "Ta commande apparaît déjà comme annulée. Je transmets ton dossier à mon équipe "
        "pour qu'elle vérifie l'état du remboursement et t'écrive.",
    ),
    # ─── Devoluciones y cambios (ADR 0014): rechazos que pasan el caso al equipo ─
    "refusal.returns.policy_missing": _then(
        _t(
            "Ahora mismo no puedo gestionar devoluciones ni cambios desde aquí.",
            "I can't handle returns or exchanges from here right now.",
            "Ara mateix no puc gestionar devolucions ni canvis des d'aquí.",
            "Je ne peux pas gérer les retours ni les échanges d'ici pour le moment.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.order_cancelled": _then(
        _t(
            "Tu pedido figura como cancelado, así que no puedo abrir una devolución ni un "
            "cambio.",
            "Your order shows as cancelled, so I can't open a return or an exchange.",
            "La teva comanda figura com a cancel·lada, així que no puc obrir una devolució ni "
            "un canvi.",
            "Ta commande apparaît comme annulée, donc je ne peux pas ouvrir de retour ni "
            "d'échange.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.exchanges_disabled": _then(
        _t(
            "No puedo gestionar cambios desde aquí.",
            "I can't handle exchanges from here.",
            "No puc gestionar canvis des d'aquí.",
            "Je ne peux pas gérer les échanges d'ici.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.product_excluded": _then(
        _t(
            "Según la política de la tienda, este artículo no admite devolución.",
            "Under the store's policy, this item can't be returned.",
            "Segons la política de la botiga, aquest article no admet devolució.",
            "Selon la politique de la boutique, cet article ne peut pas être retourné.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.product_unknown": _then(
        _t(
            "No puedo comprobar desde aquí si este artículo admite devolución.",
            "I can't check from here whether this item can be returned.",
            "No puc comprovar des d'aquí si aquest article admet devolució.",
            "Je ne peux pas vérifier d'ici si cet article peut être retourné.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.delivery_date_unknown": _then(
        _t(
            "No puedo confirmar desde aquí la fecha de entrega de tu pedido.",
            "I can't confirm your order's delivery date from here.",
            "No puc confirmar des d'aquí la data d'entrega de la teva comanda.",
            "Je ne peux pas confirmer d'ici la date de livraison de ta commande.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.outside_window": _then(
        _t(
            "Según la política de la tienda, el plazo para devolver o cambiar este artículo "
            "terminó el {deadline}.",
            "Under the store's policy, the period to return or exchange this item ended on "
            "{deadline}.",
            "Segons la política de la botiga, el termini per tornar o canviar aquest article "
            "va acabar el {deadline}.",
            "Selon la politique de la boutique, le délai pour retourner ou échanger cet "
            "article a pris fin le {deadline}.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.evidence_unreadable": _then(
        _t(
            "Para este motivo hace falta revisar fotos del artículo.",
            "For this reason, the team needs to review photos of the item.",
            "Per aquest motiu cal revisar fotos de l'article.",
            "Pour ce motif, il faut examiner des photos de l'article.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.fees_exceed_refund": _then(
        _t(
            "Los gastos de la devolución superan el importe de lo que devuelves, así que no "
            "puedo abrirla desde aquí.",
            "The return costs are higher than the value of what you're returning, so I can't "
            "open it from here.",
            "Les despeses de la devolució superen l'import del que tornes, així que no la puc "
            "obrir des d'aquí.",
            "Les frais de retour dépassent le montant de ce que tu retournes, donc je ne peux "
            "pas l'ouvrir d'ici.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.shopify_error": _then(
        _t(
            "No he podido preparar la devolución con los datos de la tienda en este momento.",
            "I couldn't prepare the return with the store's data right now.",
            "No he pogut preparar la devolució amb les dades de la botiga en aquest moment.",
            "Je n'ai pas pu préparer le retour avec les données de la boutique pour le moment.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.outcome_unknown": _then(
        _t(
            "No he podido confirmar si tu solicitud ha quedado registrada.",
            "I couldn't confirm whether your request went through.",
            "No he pogut confirmar si la teva sol·licitud ha quedat registrada.",
            "Je n'ai pas pu confirmer si ta demande a bien été enregistrée.",
        ),
        _PASS_TO_TEAM,
    ),
    "refusal.returns.no_longer_possible": _then(
        _t(
            "No he podido abrir la devolución con los datos de tu pedido.",
            "I couldn't open the return with your order details.",
            "No he pogut obrir la devolució amb les dades de la teva comanda.",
            "Je n'ai pas pu ouvrir le retour avec les informations de ta commande.",
        ),
        _PASS_TO_TEAM,
    ),
    # ─── Aprobaciones L3: confirmación, fallo y rechazo ──────────────────────────
    "done.update_shipping_address": _t(
        "Hemos actualizado la dirección de envío de tu pedido.",
        "We've updated the shipping address of your order.",
        "Hem actualitzat l'adreça d'enviament de la teva comanda.",
        "Nous avons mis à jour l'adresse de livraison de ta commande.",
    ),
    "done.cancel_order": _t(
        "Hemos cancelado tu pedido.",
        "We've cancelled your order.",
        "Hem cancel·lat la teva comanda.",
        "Nous avons annulé ta commande.",
    ),
    "done.refund_partial": _t(
        "Hemos procesado el reembolso de tu pedido.",
        "We've processed the refund for your order.",
        "Hem processat el reemborsament de la teva comanda.",
        "Nous avons traité le remboursement de ta commande.",
    ),
    "done.start_return": _t(
        "Hemos iniciado la devolución de tu pedido.",
        "We've started the return of your order.",
        "Hem iniciat la devolució de la teva comanda.",
        "Nous avons lancé le retour de ta commande.",
    ),
    "done.start_exchange": _t(
        "Hemos abierto el cambio de tu pedido.",
        "We've opened the exchange for your order.",
        "Hem obert el canvi de la teva comanda.",
        "Nous avons ouvert l'échange de ta commande.",
    ),
    "done.default": _t(
        "Hemos completado tu solicitud.",
        "We've completed your request.",
        "Hem completat la teva sol·licitud.",
        "Nous avons terminé de traiter ta demande.",
    ),
    "failed": _t(
        "Lo sentimos, no hemos podido completar tu solicitud en este momento. "
        "Un agente de nuestro equipo lo revisará y te contactará en breve.",
        "Sorry, we haven't been able to complete your request at the moment. An agent from "
        "our team will review it and get in touch with you shortly.",
        "Ho sentim, no hem pogut completar la teva sol·licitud en aquest moment. Un agent "
        "del nostre equip ho revisarà i es posarà en contacte amb tu en breu.",
        "Désolés, nous n'avons pas pu traiter ta demande pour le moment. Un agent de notre "
        "équipe va l'examiner et te contactera sous peu.",
    ),
    "rejected": _t(
        "Hemos revisado tu solicitud y, por el momento, no podremos realizarla. {comment}",
        "We've reviewed your request and, for now, we won't be able to carry it out. {comment}",
        "Hem revisat la teva sol·licitud i, de moment, no la podrem dur a terme. {comment}",
        "Nous avons examiné ta demande et, pour le moment, nous ne pourrons pas y donner "
        "suite. {comment}",
    ),
    "address_details": _t(
        "Nueva dirección de envío: {address}.",
        "New shipping address: {address}.",
        "Nova adreça d'enviament: {address}.",
        "Nouvelle adresse de livraison : {address}.",
    ),
    # ─── Gate L3: pendiente de una última comprobación humana ────────────────────
    "gate.update_shipping_address": _t(
        "¡Genial! Ya tengo todos los datos para cambiar la dirección de tu pedido. "
        "Lo paso a mi equipo para una última comprobación y te confirmo en cuanto esté hecho.",
        "Great! I have all the details to change your order's address. I'm passing it to my "
        "team for a final check and I'll confirm as soon as it's done.",
        "Genial! Ja tinc totes les dades per canviar l'adreça de la teva comanda. Ho passo "
        "al meu equip per a una última comprovació i et confirmo tan aviat com estigui fet.",
        "Parfait ! J'ai toutes les informations pour modifier l'adresse de ta commande. Je "
        "la transmets à mon équipe pour une dernière vérification et je te confirme dès "
        "que c'est fait.",
    ),
    "gate.cancel_order": _t(
        "Entendido. Voy a tramitar la cancelación de tu pedido; lo paso a mi equipo "
        "para confirmarlo y te aviso en cuanto esté listo.",
        "Understood. I'm going to process the cancellation of your order; I'm passing it to "
        "my team to confirm it and I'll let you know as soon as it's ready.",
        "Entesos. Tramitaré la cancel·lació de la teva comanda; ho passo al meu equip per "
        "confirmar-ho i t'aviso tan aviat com estigui llest.",
        "Compris. Je vais traiter l'annulation de ta commande ; je la transmets à mon "
        "équipe pour confirmation et je te préviens dès que c'est prêt.",
    ),
    "gate.refund_partial": _t(
        "¡Perfecto! Estoy gestionando el reembolso de tu pedido; lo paso a mi equipo "
        "para confirmarlo y te aviso en cuanto esté hecho.",
        "Perfect! I'm handling the refund for your order; I'm passing it to my team to "
        "confirm it and I'll let you know as soon as it's done.",
        "Perfecte! Estic gestionant el reemborsament de la teva comanda; ho passo al meu "
        "equip per confirmar-ho i t'aviso tan aviat com estigui fet.",
        "Parfait ! Je m'occupe du remboursement de ta commande ; je le transmets à mon "
        "équipe pour confirmation et je te préviens dès que c'est fait.",
    ),
    "gate.start_return": _t(
        "¡Listo! Voy a iniciar la devolución de tu pedido; lo paso a mi equipo para "
        "confirmarlo y te aviso en cuanto esté en marcha.",
        "Done! I'm going to start the return of your order; I'm passing it to my team to "
        "confirm it and I'll let you know as soon as it's under way.",
        "Llest! Iniciaré la devolució de la teva comanda; ho passo al meu equip per "
        "confirmar-ho i t'aviso tan aviat com estigui en marxa.",
        "C'est noté ! Je vais lancer le retour de ta commande ; je le transmets à mon "
        "équipe pour confirmation et je te préviens dès qu'il est en cours.",
    ),
    "gate.start_exchange": _t(
        "¡Listo! Voy a abrir el cambio de tu pedido; lo paso a mi equipo para confirmarlo "
        "y te aviso en cuanto esté en marcha.",
        "Done! I'm going to open the exchange for your order; I'm passing it to my team to "
        "confirm it and I'll let you know as soon as it's under way.",
        "Llest! Obriré el canvi de la teva comanda; ho passo al meu equip per confirmar-ho i "
        "t'aviso tan aviat com estigui en marxa.",
        "C'est noté ! Je vais ouvrir l'échange de ta commande ; je le transmets à mon équipe "
        "pour confirmation et je te préviens dès qu'il est en cours.",
    ),
    "gate.default": _t(
        "¡Perfecto! Ya tengo lo que necesito. Lo paso a mi equipo para una última "
        "comprobación y te confirmo en cuanto esté listo.",
        "Perfect! I have what I need. I'm passing it to my team for a final check and I'll "
        "confirm as soon as it's ready.",
        "Perfecte! Ja tinc el que necessito. Ho passo al meu equip per a una última "
        "comprovació i et confirmo tan aviat com estigui llest.",
        "Parfait ! J'ai ce qu'il me faut. Je le transmets à mon équipe pour une dernière "
        "vérification et je te confirme dès que c'est prêt.",
    ),
    # ─── Espera: el cliente escribe de nuevo y la acción sigue en revisión ───────
    "waiting.update_shipping_address": _t(
        "Tu cambio de dirección sigue en revisión con mi equipo; te confirmo en "
        "cuanto esté hecho. ¡Gracias por la paciencia!",
        "Your address change is still being reviewed by my team; I'll confirm as soon as "
        "it's done. Thanks for your patience!",
        "El teu canvi d'adreça segueix en revisió amb el meu equip; et confirmo tan aviat "
        "com estigui fet. Gràcies per la paciència!",
        "Ton changement d'adresse est toujours en cours de vérification par mon équipe ; je "
        "te confirme dès que c'est fait. Merci de ta patience !",
    ),
    "waiting.cancel_order": _t(
        "Tu cancelación sigue en revisión con mi equipo; te aviso en cuanto esté "
        "lista. ¡Gracias por la paciencia!",
        "Your cancellation is still being reviewed by my team; I'll let you know as soon as "
        "it's ready. Thanks for your patience!",
        "La teva cancel·lació segueix en revisió amb el meu equip; t'aviso tan aviat com "
        "estigui llesta. Gràcies per la paciència!",
        "Ton annulation est toujours en cours de vérification par mon équipe ; je te "
        "préviens dès qu'elle est prête. Merci de ta patience !",
    ),
    "waiting.refund_partial": _t(
        "Tu reembolso sigue en revisión con mi equipo; te aviso en cuanto esté "
        "hecho. ¡Gracias por la paciencia!",
        "Your refund is still being reviewed by my team; I'll let you know as soon as it's "
        "done. Thanks for your patience!",
        "El teu reemborsament segueix en revisió amb el meu equip; t'aviso tan aviat com "
        "estigui fet. Gràcies per la paciència!",
        "Ton remboursement est toujours en cours de vérification par mon équipe ; je te "
        "préviens dès que c'est fait. Merci de ta patience !",
    ),
    "waiting.start_return": _t(
        "Tu devolución sigue en revisión con mi equipo; te aviso en cuanto esté en "
        "marcha. ¡Gracias por la paciencia!",
        "Your return is still being reviewed by my team; I'll let you know as soon as it's "
        "under way. Thanks for your patience!",
        "La teva devolució segueix en revisió amb el meu equip; t'aviso tan aviat com "
        "estigui en marxa. Gràcies per la paciència!",
        "Ton retour est toujours en cours de vérification par mon équipe ; je te préviens "
        "dès qu'il est lancé. Merci de ta patience !",
    ),
    "waiting.start_exchange": _t(
        "Tu cambio sigue en revisión con mi equipo; te aviso en cuanto esté en marcha. "
        "¡Gracias por la paciencia!",
        "Your exchange is still being reviewed by my team; I'll let you know as soon as it's "
        "under way. Thanks for your patience!",
        "El teu canvi segueix en revisió amb el meu equip; t'aviso tan aviat com estigui en "
        "marxa. Gràcies per la paciència!",
        "Ton échange est toujours en cours de vérification par mon équipe ; je te préviens "
        "dès qu'il est lancé. Merci de ta patience !",
    ),
    "waiting.default": _t(
        "Tu solicitud sigue en revisión con mi equipo; te confirmo en cuanto esté "
        "lista. ¡Gracias por la paciencia!",
        "Your request is still being reviewed by my team; I'll confirm as soon as it's "
        "ready. Thanks for your patience!",
        "La teva sol·licitud segueix en revisió amb el meu equip; et confirmo tan aviat com "
        "estigui llesta. Gràcies per la paciència!",
        "Ta demande est toujours en cours de vérification par mon équipe ; je te confirme "
        "dès qu'elle est prête. Merci de ta patience !",
    ),
    # ─── Seguimiento: la acción ya se aprobó y el cliente vuelve a escribir ──────
    "done_followup.update_shipping_address": _t(
        "Tu cambio de dirección ya quedó aplicado. Si necesitas algo más, aquí estoy.",
        "Your address change has already been applied. If you need anything else, I'm here.",
        "El teu canvi d'adreça ja s'ha aplicat. Si necessites res més, sóc aquí.",
        "Ton changement d'adresse est déjà appliqué. Si tu as besoin d'autre chose, je suis là.",
    ),
    "done_followup.cancel_order": _t(
        "Tu cancelación ya quedó registrada. Si necesitas algo más, aquí estoy.",
        "Your cancellation has already been recorded. If you need anything else, I'm here.",
        "La teva cancel·lació ja ha quedat registrada. Si necessites res més, sóc aquí.",
        "Ton annulation est déjà enregistrée. Si tu as besoin d'autre chose, je suis là.",
    ),
    "done_followup.refund_partial": _t(
        "Tu reembolso ya quedó procesado. Si necesitas algo más, aquí estoy.",
        "Your refund has already been processed. If you need anything else, I'm here.",
        "El teu reemborsament ja ha quedat processat. Si necessites res més, sóc aquí.",
        "Ton remboursement est déjà traité. Si tu as besoin d'autre chose, je suis là.",
    ),
    "done_followup.start_return": _t(
        "Tu devolución ya quedó en marcha. Si necesitas algo más, aquí estoy.",
        "Your return is already under way. If you need anything else, I'm here.",
        "La teva devolució ja està en marxa. Si necessites res més, sóc aquí.",
        "Ton retour est déjà en cours. Si tu as besoin d'autre chose, je suis là.",
    ),
    "done_followup.start_exchange": _t(
        "Tu cambio ya quedó en marcha. Si necesitas algo más, aquí estoy.",
        "Your exchange is already under way. If you need anything else, I'm here.",
        "El teu canvi ja està en marxa. Si necessites res més, sóc aquí.",
        "Ton échange est déjà en cours. Si tu as besoin d'autre chose, je suis là.",
    ),
    "done_followup.default": _t(
        "Tu solicitud ya quedó completada. Si necesitas algo más, aquí estoy.",
        "Your request has already been completed. If you need anything else, I'm here.",
        "La teva sol·licitud ja ha quedat completada. Si necessites res més, sóc aquí.",
        "Ta demande est déjà traitée. Si tu as besoin d'autre chose, je suis là.",
    ),
    # ─── Resultado releído de Shopify: nunca promete más de lo que se confirmó ───
    "outcome.update_shipping_address.confirmed": _t(
        "Hemos actualizado la dirección de envío de tu pedido.",
        "We've updated the shipping address of your order.",
        "Hem actualitzat l'adreça d'enviament de la teva comanda.",
        "Nous avons mis à jour l'adresse de livraison de ta commande.",
    ),
    "outcome.update_shipping_address.not_confirmed": _then(
        _t(
            "No hemos podido confirmar el cambio de dirección de tu pedido.",
            "We couldn't confirm the address change on your order.",
            "No hem pogut confirmar el canvi d'adreça de la teva comanda.",
            "Nous n'avons pas pu confirmer le changement d'adresse de ta commande.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "outcome.cancel_order.confirmed": _t(
        "Hemos cancelado tu pedido y el reembolso ya está emitido a tu método de pago "
        "original. Según tu banco, puede tardar unos días en verse en tu cuenta.",
        "We've cancelled your order and the refund has been issued to your original payment "
        "method. Depending on your bank, it may take a few days to show up in your account.",
        "Hem cancel·lat la teva comanda i el reemborsament ja s'ha emès al teu mètode de "
        "pagament original. Segons el teu banc, pot trigar uns dies a veure's al teu compte.",
        "Nous avons annulé ta commande et le remboursement a été émis sur ton moyen de "
        "paiement d'origine. Selon ta banque, il peut falloir quelques jours pour qu'il "
        "apparaisse sur ton compte.",
    ),
    "outcome.cancel_order.refund_pending": _t(
        "Hemos cancelado tu pedido. El reembolso a tu método de pago original está en "
        "proceso con la pasarela de pago.",
        "We've cancelled your order. The refund to your original payment method is being "
        "processed by the payment gateway.",
        "Hem cancel·lat la teva comanda. El reemborsament al teu mètode de pagament original "
        "està en procés amb la passarel·la de pagament.",
        "Nous avons annulé ta commande. Le remboursement sur ton moyen de paiement d'origine "
        "est en cours de traitement par la passerelle de paiement.",
    ),
    "outcome.cancel_order.refund_manual": _then(
        _t(
            "Hemos cancelado tu pedido. Si ya realizaste el pago, la tienda te devolverá el "
            "importe por el mismo medio con el que pagaste.",
            "We've cancelled your order. If you've already paid, the store will refund the "
            "amount by the same means you paid with.",
            "Hem cancel·lat la teva comanda. Si ja has fet el pagament, la botiga et "
            "retornarà l'import pel mateix mitjà amb què vas pagar.",
            "Nous avons annulé ta commande. Si tu as déjà payé, la boutique te remboursera "
            "le montant par le même moyen que celui que tu as utilisé.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "outcome.cancel_order.refund_failed": _then(
        _t(
            "Hemos cancelado tu pedido, pero el reembolso no se ha podido completar de forma "
            "automática.",
            "We've cancelled your order, but the refund couldn't be completed automatically.",
            "Hem cancel·lat la teva comanda, però el reemborsament no s'ha pogut completar "
            "de manera automàtica.",
            "Nous avons annulé ta commande, mais le remboursement n'a pas pu être effectué "
            "automatiquement.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "outcome.cancel_order.not_confirmed": _then(
        _t(
            "No hemos podido confirmar la cancelación de tu pedido.",
            "We couldn't confirm the cancellation of your order.",
            "No hem pogut confirmar la cancel·lació de la teva comanda.",
            "Nous n'avons pas pu confirmer l'annulation de ta commande.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "outcome.refund_partial.confirmed": _t(
        "Hemos emitido el reembolso a tu método de pago original. Según tu banco, puede "
        "tardar unos días en verse en tu cuenta.",
        "We've issued the refund to your original payment method. Depending on your bank, "
        "it may take a few days to show up in your account.",
        "Hem emès el reemborsament al teu mètode de pagament original. Segons el teu banc, "
        "pot trigar uns dies a veure's al teu compte.",
        "Nous avons émis le remboursement sur ton moyen de paiement d'origine. Selon ta "
        "banque, il peut falloir quelques jours pour qu'il apparaisse sur ton compte.",
    ),
    "outcome.refund_partial.refund_pending": _t(
        "El reembolso a tu método de pago original está en proceso con la pasarela de pago.",
        "The refund to your original payment method is being processed by the payment " "gateway.",
        "El reemborsament al teu mètode de pagament original està en procés amb la "
        "passarel·la de pagament.",
        "Le remboursement sur ton moyen de paiement d'origine est en cours de traitement "
        "par la passerelle de paiement.",
    ),
    "outcome.refund_partial.refund_manual": _then(
        _t(
            "La tienda te devolverá el importe por el mismo medio con el que pagaste.",
            "The store will refund the amount by the same means you paid with.",
            "La botiga et retornarà l'import pel mateix mitjà amb què vas pagar.",
            "La boutique te remboursera le montant par le même moyen que celui que tu as "
            "utilisé.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "outcome.refund_partial.refund_failed": _then(
        _t(
            "No hemos podido completar el reembolso de forma automática.",
            "We couldn't complete the refund automatically.",
            "No hem pogut completar el reemborsament de manera automàtica.",
            "Nous n'avons pas pu effectuer le remboursement automatiquement.",
        ),
        _TEAM_WILL_WRITE,
    ),
    # Devoluciones y cambios: se abrió la devolución, nunca "el dinero ya vuelve".
    "outcome.start_return.confirmed": _t(
        "Hemos abierto la devolución de tu pedido.",
        "We've opened the return for your order.",
        "Hem obert la devolució de la teva comanda.",
        "Nous avons ouvert le retour de ta commande.",
    ),
    "outcome.start_return.not_confirmed": _then(
        _t(
            "No hemos podido confirmar que la devolución quedara abierta.",
            "We couldn't confirm that the return was opened.",
            "No hem pogut confirmar que la devolució quedés oberta.",
            "Nous n'avons pas pu confirmer l'ouverture du retour.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "outcome.start_exchange.confirmed": _t(
        "Hemos abierto el cambio de tu pedido.",
        "We've opened the exchange for your order.",
        "Hem obert el canvi de la teva comanda.",
        "Nous avons ouvert l'échange de ta commande.",
    ),
    "outcome.start_exchange.not_confirmed": _then(
        _t(
            "No hemos podido confirmar que el cambio quedara abierto.",
            "We couldn't confirm that the exchange was opened.",
            "No hem pogut confirmar que el canvi quedés obert.",
            "Nous n'avons pas pu confirmer l'ouverture de l'échange.",
        ),
        _TEAM_WILL_WRITE,
    ),
    "returns.ship_to": _t(
        "Envía el artículo a esta dirección: {address}.",
        "Send the item to this address: {address}.",
        "Envia l'article a aquesta adreça: {address}.",
        "Envoie l'article à cette adresse : {address}.",
    ),
    "returns.label": _t(
        "Te enviaremos la etiqueta de devolución.",
        "We'll send you the return label.",
        "T'enviarem l'etiqueta de devolució.",
        "Nous t'enverrons l'étiquette de retour.",
    ),
    "returns.shipping_paid_by_store": _t(
        "El envío de vuelta corre de nuestra cuenta.",
        "Return shipping is on us.",
        "L'enviament de tornada va a càrrec nostre.",
        "Le renvoi est à notre charge.",
    ),
    "returns.shipping_reimbursed": _t(
        "El envío de vuelta va a cargo de la tienda; nuestro equipo te indicará cómo se gestiona.",
        "Return shipping is on the store; our team will tell you how it's handled.",
        "L'enviament de tornada va a càrrec de la botiga; el nostre equip t'indicarà com es "
        "gestiona.",
        "Le renvoi est à la charge de la boutique ; notre équipe t'indiquera comment il est "
        "géré.",
    ),
    "returns.shipping_paid_by_customer": _t(
        "El envío de vuelta corre de tu cuenta.",
        "Return shipping is at your expense.",
        "L'enviament de tornada va a càrrec teu.",
        "Le renvoi est à ta charge.",
    ),
    "returns.shipping_fee": _t(
        "Por el envío de vuelta descontaremos {fee} del reembolso.",
        "We'll deduct {fee} from the refund for return shipping.",
        "Per l'enviament de tornada descomptarem {fee} del reemborsament.",
        "Nous déduirons {fee} du remboursement pour le renvoi.",
    ),
    "returns.shipping_fee_pending": _t(
        "Nuestro equipo te confirmará el coste del envío de vuelta.",
        "Our team will confirm the cost of return shipping.",
        "El nostre equip et confirmarà el cost de l'enviament de tornada.",
        "Notre équipe te confirmera le coût du renvoi.",
    ),
    "returns.refund_after_receipt": _t(
        "Cuando recibamos el artículo y lo revisemos, te devolveremos el dinero en un plazo "
        "de {days} días.",
        "Once we receive and check the item, we'll refund you within {days} days.",
        "Quan rebem l'article i el revisem, et retornarem els diners en un termini de "
        "{days} dies.",
        "Une fois l'article reçu et vérifié, nous te rembourserons sous {days} jours.",
    ),
    "returns.restocking_fee": _t(
        "Por gastos de reposición descontaremos {fee} del reembolso.",
        "We'll deduct {fee} from the refund as a restocking fee.",
        "Per despeses de reposició descomptarem {fee} del reemborsament.",
        "Nous déduirons {fee} du remboursement pour frais de remise en stock.",
    ),
    "returns.nothing_to_refund": _t(
        "Con los gastos de la devolución descontados, no queda importe por devolverte.",
        "Once the return costs are deducted, there's no amount left to refund you.",
        "Amb les despeses de la devolució descomptades, no queda import per retornar-te.",
        "Une fois les frais de retour déduits, il ne reste aucun montant à te rembourser.",
    ),
    "returns.credit_after_receipt": _t(
        "Cuando recibamos el artículo y lo revisemos, te abonaremos el importe en crédito de "
        "la tienda en un plazo de {days} días.",
        "Once we receive and check the item, we'll give you the amount as store credit within "
        "{days} days.",
        "Quan rebem l'article i el revisem, t'abonarem l'import en crèdit de la botiga en un "
        "termini de {days} dies.",
        "Une fois l'article reçu et vérifié, nous te créditerons le montant en avoir sur la "
        "boutique sous {days} jours.",
    ),
    "returns.exchange_ships_now": _t(
        "Te enviaremos el artículo de cambio en cuanto el cambio quede confirmado.",
        "We'll ship the replacement item as soon as the exchange is confirmed.",
        "T'enviarem l'article de canvi tan bon punt el canvi quedi confirmat.",
        "Nous t'enverrons l'article d'échange dès que l'échange sera confirmé.",
    ),
    "returns.exchange_ships_after_receipt": _t(
        "Te enviaremos el artículo de cambio cuando recibamos el que devuelves.",
        "We'll ship the replacement item once we receive the one you're returning.",
        "T'enviarem l'article de canvi quan rebem el que tornes.",
        "Nous t'enverrons l'article d'échange dès réception de celui que tu retournes.",
    ),
    "returns.exchange_difference_absorbed": _t(
        "La diferencia de precio corre de nuestra cuenta.",
        "The price difference is on us.",
        "La diferència de preu va a càrrec nostre.",
        "La différence de prix est à notre charge.",
    ),
    "returns.exchange_no_refund": _t(
        "Según la política de la tienda, la diferencia de precio no se reembolsa.",
        "Under the store's policy, the price difference isn't refunded.",
        "Segons la política de la botiga, la diferència de preu no es reemborsa.",
        "Selon la politique de la boutique, la différence de prix n'est pas remboursée.",
    ),
    "returns.exchange_you_owe": _t(
        "Te quedan por pagar {amount}; nuestro equipo te indicará cómo hacerlo.",
        "You have {amount} left to pay; our team will tell you how.",
        "Et queden per pagar {amount}; el nostre equip t'indicarà com fer-ho.",
        "Il te reste {amount} à payer ; notre équipe t'indiquera comment faire.",
    ),
    "returns.exchange_you_owe_with_fees": _t(
        "Te quedan por pagar {amount}, incluidos los gastos de la devolución; nuestro equipo "
        "te indicará cómo hacerlo.",
        "You have {amount} left to pay, including the return costs; our team will tell you how.",
        "Et queden per pagar {amount}, incloses les despeses de la devolució; el nostre equip "
        "t'indicarà com fer-ho.",
        "Il te reste {amount} à payer, frais de retour compris ; notre équipe t'indiquera "
        "comment faire.",
    ),
    "returns.exchange_refund": _t(
        "Cuando recibamos el artículo, te devolveremos {amount} en un plazo de {days} días.",
        "Once we receive the item, we'll refund {amount} within {days} days.",
        "Quan rebem l'article, et retornarem {amount} en un termini de {days} dies.",
        "Une fois l'article reçu, nous te rembourserons {amount} sous {days} jours.",
    ),
    "returns.exchange_credit": _t(
        "Cuando recibamos el artículo, te abonaremos {amount} en crédito de la tienda en un "
        "plazo de {days} días.",
        "Once we receive the item, we'll give you {amount} as store credit within {days} days.",
        "Quan rebem l'article, t'abonarem {amount} en crèdit de la botiga en un termini de "
        "{days} dies.",
        "Une fois l'article reçu, nous te créditerons {amount} en avoir sur la boutique sous "
        "{days} jours.",
    ),
    "returns.exchange_difference_pending": _t(
        "Nuestro equipo te confirmará si hay alguna diferencia de precio.",
        "Our team will confirm whether there's any price difference.",
        "El nostre equip et confirmarà si hi ha alguna diferència de preu.",
        "Notre équipe te confirmera s'il y a une différence de prix.",
    ),
    "outcome.unsettled": _then(
        _t(
            "No hemos podido confirmar que tu solicitud quedara completada.",
            "We couldn't confirm that your request was completed.",
            "No hem pogut confirmar que la teva sol·licitud hagi quedat completada.",
            "Nous n'avons pas pu confirmer que ta demande a bien été traitée.",
        ),
        _TEAM_WILL_WRITE,
    ),
}


def _override_for(
    overrides: Mapping[str, Any] | None, key: str, language: str, tenant_default: str
) -> str | None:
    raw = (overrides or {}).get(key)
    if isinstance(raw, str):
        text = raw if language == tenant_default else ""
    elif isinstance(raw, Mapping):
        text = raw.get(language)
    else:
        return None
    return text.strip() or None if isinstance(text, str) else None


def fixed_text(
    key: str,
    language: str | None,
    *,
    tenant_default: str = FALLBACK_LANGUAGE,
    overrides: Mapping[str, Any] | None = None,
    **params: str,
) -> str:
    """Texto fijo `key` en `language`, con el override del tenant si lo hay.

    `overrides` mapea clave → `str` (idioma por defecto del tenant) o `{idioma: texto}`.
    Sin texto en `language` se prueba el idioma por defecto del tenant y luego el español.
    """
    texts = CATALOG[key]
    for lang in dict.fromkeys((language, tenant_default, FALLBACK_LANGUAGE)):
        if lang is None:
            continue
        custom = _override_for(overrides, key, lang, tenant_default)
        if custom is not None:
            return custom
        if lang in texts:
            return texts[lang].format(**params) if params else texts[lang]
    raise KeyError(key)
