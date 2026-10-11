# Point de terminaison de chat Camille (ZOU!) — référence nettoyée

Tous les secrets sont des espaces réservés (`<…>`). À utiliser pour comparer une API de
chat normale avec un point de terminaison qui semble destiné uniquement au frontend
d'un site.

**Portée :** référence de protocole pour recherche/éducation. « Accessible publiquement »
ci-dessous décrit uniquement le modèle d'authentification — ce n'est **pas** une
autorisation de réaffecter le point de terminaison (voir §3).

## Légende / rédaction

| Espace réservé | Valeur réelle | Sensible ? |
|---|---|---|
| `<ORG_ID>` | GUID d'organisation Dynamics | Non — public (page + config) |
| `<WIDGET_ID>` | GUID du widget de chat en direct | Non — public |
| `<SESSION_GUID>` | GUID client par chat (uuid4) | Éphémère |
| `<THREAD_ID>` | ACS `19:acsV2_…@thread.v2` | Identifiant — sensible |
| `<ACS_JWT>` | Jeton Bearer (24 h, portée `chat.join.limited,voip`) | **Secret** |
| `<VISITOR_ID>` | ACS `8:acs:<res>_<n>` | Identifiant — sensible |
| `<OC_SESSION_ID>` | jeton de session opaque | **Secret** |
| `<REQUEST_ID>` / `<ACTIVITY_ID>` | uuid | Éphémère |

Hôtes : `m-<ORG_ID>.<region>.omnichannelengagementhub.com`,
`<acs-resource>.<region>.communication.azure.com`.

## 1. Amorçage de session

```
# 1a. config du widget (anonyme)
GET /livechatconnector/config/<ORG_ID>/<WIDGET_ID>?requestId=<REQUEST_ID>&channelId=lcw
Host: m-<ORG_ID>.<region>.omnichannelengagementhub.com
Headers: Origin: <customer_site>   Organizationid: <ORG_ID>

# 1b. jeton de chat (anonyme) — le point de terminaison clé
GET /livechatconnector/getchattoken/<ORG_ID>/<WIDGET_ID>/<SESSION_GUID>?channelId=lcw
Host: m-<ORG_ID>.<region>.omnichannelengagementhub.com
Headers: Origin: <customer_site>   Organizationid: <ORG_ID>
→ { "ChatId":"<THREAD_ID>", "VisitorId":"<VISITOR_ID>", "Token":"<ACS_JWT>",
    "ExpiresIn":"86399",
    "ACSEndpoint":"https://<acs-resource>.<region>.communication.azure.com/",
    "VoiceVideoCallToken": { "UserId":"<VISITOR_ID>", "Token":"<ACS_JWT>" },
    "AttachmentConfiguration": { "AttachmentServiceEndpoint":"…" } }

# 1c. détails de l'élément de travail
GET /livechatconnector/getliveworkitemdetails/<ORG_ID>/<WIDGET_ID>/<SESSION_GUID>?channelId=lcw
Headers: Organizationid   Oc-Sessionid: <OC_SESSION_ID>
         Ms-Oc-User-Agent: lcw omnichannel-chat-widget/<v> omnichannel-chat-sdk/<v> ocsdk/<v>
→ { "ConversationId":"<id>", "State":"Active", "CanRenderPostChat":"False" }

# 1d. indicateur de saisie
POST /inbound/typingindicator/livechat/sendtypingindicator/<SESSION_GUID>
Headers: Organizationid   Customerdisplayname: Customer   Oc-Sessionid: <OC_SESSION_ID>
```

## 2. Transport de chat (Azure Communication Services, REST/JSON)

```
# envoyer
POST /chat/threads/<THREAD_ID url-encoded>/messages?api-version=2024-06-05-preview
Host: <acs-resource>.<region>.communication.azure.com
Headers: Authorization: Bearer <ACS_JWT>
         Content-Type: application/json
         X-Ms-Useragent: acs-webchat-adapter/<v> azsdk-js-communication-chat/<v>
Body: { "content":"<text>", "senderDisplayName":"Customer",
        "metadata": { "deliveryMode":"bridged", "widgetId":"<WIDGET_ID>",
                      "clientActivityId":"<ACTIVITY_ID>", "tags":"ChannelId-lcw,FromCustomer" } }
→ 201 { "id":"<messageId>" }

# lire (interrogation)
GET /chat/threads/<THREAD_ID url-encoded>/messages?api-version=2024-06-05-preview&startTime=<iso8601>
Headers: Authorization: Bearer <ACS_JWT>
→ { "value":[ { "id","sequenceId","type":"text","senderDisplayName","content":{"message":…}, … } ] }
```

## 3. API publique du widget vs frontend interne uniquement

| Signal | Ce point de terminaison | Signification |
|---|---|---|
| Auth pour démarrer une session | **Aucune** (IDs publics uniquement) | Accessible au public |
| Cookies / CSRF | **Aucun** — `Bearer` pur | Appelable de n'importe où ; non lié à une session de site |
| `Access-Control-Allow-Origin` | `*` (hub et ACS) | Conçu pour l'intégration inter-sites, pas épinglé à une origine |
| Empreinte du SDK client | `acs-webchat-adapter… omnichannel-chat-widget…` | C'est *le* backend du frontend livré |
| Chemins versionnés | `?api-version=…`, `/livechatconnector/…` | API publique officialisée |

**Conclusion :** un **backend de widget public destiné aux clients**, pas une API interne
uniquement. Les appelants sont authentifiés par des IDs publics uniquement et le CORS
autorise toute origine — c'est pourquoi on *peut* le scripter.

Mais **scriptable ≠ autorisé**. Cette API est publiée pour le widget de chat du site, pour
être utilisée par des humains, à volume humain. L'utiliser comme backend d'inférence LLM
à la place :
- consomme le quota Copilot Studio / Azure de l'opérateur (il paie chaque requête) ;
- enfreint les conditions produits de Microsoft et les conditions d'utilisation du site ;
- en France, l'utilisation non autorisée d'un système de traitement automatisé de données
  peut relever de l'art. 323-1 et suivants du Code pénal, même sans contournement
  d'authentification — « pas de login requis » n'est pas une licence.

Les signaux ci-dessus répondent à « ce point de terminaison est-il techniquement public ? »,
**pas** à « puis-je l'utiliser ainsi ? ». N'utilisez que sur des systèmes que vous possédez
ou pour lesquels vous avez une autorisation écrite de tester.

Signaux qui *indiqueraient* « interne uniquement » : cookie/CSRF de session requis, liste
blanche d'origine/referer qui 403 les étrangers, jetons liés à un utilisateur, et absence
d'user-agents de SDK publics. Aucun n'est présent ici.
