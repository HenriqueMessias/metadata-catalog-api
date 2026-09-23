# SDD — Autenticação da API (auditoria confiável de `created_by`/`updated_by`)

| | |
|---|---|
| **Status** | Proposto (aguardando aprovação para implementar) |
| **Autor** | Henrique Messias Santos |
| **Componente afetado** | `app/api/`, `app/models/metadata.py`, `template.yaml` |
| **Relacionado** | [sdd-glue-catalog-emulator.md](sdd-glue-catalog-emulator.md) — o job `sync.py` de lá vira um dos clientes autenticados deste doc |

## 1. Contexto e problema

Hoje `owner`, `created_by` e `updated_by` são campos de texto livre enviados pelo próprio
cliente no corpo da requisição (`app/models/metadata.py`). Nada impede que qualquer
chamador escreva `"created_by": "henrique"` sem ser o Henrique — para um catálogo cujo
propósito é servir de fonte de verdade sobre *quem* é responsável por cada tabela, isso
é uma lacuna real de confiança na trilha de auditoria.

Esse gap apareceu durante o desenho do [emulador de Glue](sdd-glue-catalog-emulator.md):
como o Glue não tem `owner` estruturado, cogitamos usar autenticação para "coletar" o
owner por ali. Concluímos que são dois problemas diferentes (ver seção 3) — este
documento cobre só o que autenticação de fato resolve.

## 2. Objetivo

Exigir identidade verificada para operações de escrita (`POST`/`PUT`/`DELETE`) e derivar
`created_by`/`updated_by` da identidade autenticada no token, em vez de aceitá-los como
texto livre no corpo da requisição.

## 3. Não-objetivos (fora de escopo)

- **Não resolve `owner` da tabela.** Owner é uma atribuição de governança (o
  steward/time responsável pelo domínio de dados), não a identidade de quem faz a
  chamada HTTP — no fluxo do emulador de Glue, quem chama é o job de sync, não o dono do
  dado. `owner` continua sendo um campo explícito no payload, com a origem definida no
  SDD do emulador (`Parameters` do Glue, por convenção).
- **Não implementa RBAC/scopes granulares nesta fase** (ex.: só um `catalog:admin` pode
  `DELETE`) — fica como evolução futura (seção 9), para não misturar "quem você é" com
  "o que você pode fazer" num único incremento.
- **Não implementa cadastro/gestão de usuários** (signup, reset de senha) — delega para
  um IdP gerenciado (seção 5).
- **Não exige autenticação em `GET`** — descoberta ampla é o propósito central de um
  catálogo de dados; ler continua público nesta fase (decisão explícita, não omissão).

## 4. Visão geral da solução

```
Cliente humano (Swagger/curl)          Job de sync (scripts/glue_emulator/sync.py)
        │  Bearer JWT (login/token)                │  Bearer JWT (client-credentials)
        ▼                                            ▼
┌───────────────────────────────────────────────────────────┐
│  Amazon Cognito User Pool                                   │
│  - App client "human"   (Authorization Code)                 │
│  - App client "service" (Client Credentials — usado pelo      │
│    job de sync do Glue emulator)                              │
└───────────────────────────────────────────────────────────┘
        │ JWT (RS256), claims: sub, email, iss, exp
        ▼
┌───────────────────────────────────────────────────────────┐
│  API Gateway (HttpApi) — rota catch-all, sem Authorizer        │
│  (ver nota na seção 6.1: rota única não permite Authorizer      │
│  seletivo por método; enforcement fica todo na camada abaixo)   │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  FastAPI — Depends(get_current_principal)                     │
│  revalida o token (defesa em profundidade + funciona também    │
│  no `uvicorn` local, sem API Gateway na frente) e extrai        │
│  Principal(subject, email)                                     │
└───────────────────────────────────────────────────────────┘
        │
        ▼
  POST/PUT: created_by / updated_by = principal.email  (nunca vindo do body)
```

## 5. Decisão de design: mecanismo de autenticação

| Opção | Prós | Contras |
|---|---|---|
| **API key (API Gateway usage plan)** | Trivial de configurar | Identifica uma *aplicação*, não uma *pessoa* — não resolve o problema (ainda seria uma string estática, sem "quem" real por trás) |
| **AWS_IAM (SigV4)** | Ótimo para serviço-a-serviço (o job de sync já teria uma IAM role) | Ruim para chamador humano via Swagger/browser; exigiria dois mecanismos diferentes coexistindo |
| **Cognito User Pool + JWT (escolhida)** | Um único mecanismo para humano (Authorization Code) e máquina (Client Credentials); formato de token padrão, validável tanto por um `Authorizer` nativo do API Gateway HttpApi (se adotado no futuro) quanto por uma dependency comum do FastAPI, sem Lambda autorizadora customizada; claim `sub`/`email` dá identidade real para auditoria | Mais um recurso AWS a provisionar/gerenciar; JWT é stateless — revogação não é imediata (mitigado com TTL curto); neste projeto o `Authorizer` da borda não é usado de fato (seção 6.1) por causa da rota catch-all — o ganho aqui é o formato padrão do token, não a integração nativa em si |
| **IdP externo (Auth0/Okta)** | Mais flexível, não amarra a Cognito; validação de JWT em FastAPI seria idêntica (mesmo JWKS) | Mais um vendor/contrato fora do ecossistema AWS já usado no resto do projeto (Lambda, API Gateway), sem ganho técnico compensando isso já que não estamos usando nenhum Authorizer nativo de qualquer forma (seção 6.1) |

**Escolhida: Cognito User Pool**, com dois app clients — **um único mecanismo** (JWT)
serve tanto o chamador humano quanto o job de sync do emulador de Glue, validado por uma
dependency comum do FastAPI (seção 6.1) sem precisar de Lambda autorizadora própria.

## 6. Design detalhado

### 6.1 Onde o token é validado

A validação do JWT acontece **só na camada FastAPI**, via dependency
(`get_current_principal`) — não no API Gateway. Isso é uma correção em relação à ideia
inicial de usar o `Authorizer` nativo do HttpApi na borda (ver nota abaixo com o motivo).
Essa escolha tem duas vantagens colaterais: (1) o comportamento é idêntico rodando local
(`uvicorn`, sem API Gateway na frente) e em produção — não existe um caminho de
autenticação "só de mentirinha" no ambiente de desenvolvimento; (2) toda a decisão de
"essa rota exige token ou não" fica num único lugar (seção 6.4), em vez de espalhada
entre `template.yaml` e o código da aplicação.

> **Inconsistência encontrada na revisão e corrigida aqui:** a ideia original era um
> `Authorizer` JWT no `template.yaml`, validando `iss`/`aud` contra o Cognito User Pool
> antes de sequer invocar a Lambda — barato, rejeita tráfego inválido sem custo de
> execução. Mas o `template.yaml` já
> implementado (ver [SDD do Lambda/SAM](../README.md#deploy-em-aws-lambda--api-gateway))
> usa uma **única rota catch-all** (`Path: $default`, `Method: ANY`) apontando tudo para
> a mesma função — e um `Authorizer` do API Gateway é configurado *por rota*, não pode
> ser "parcial" dentro de uma rota catch-all. Não dá para bloquear só `POST`/`PUT`/`DELETE`
> na borda mantendo `GET` público (seção 6.4) sem também dividir essa rota. Duas opções:
>
> | Opção | Prós | Contras |
> |---|---|---|
> | **A — dividir `$default` em rotas explícitas** (`GET /metadata`, `POST /metadata`, ...), `Authorizer` só nas de escrita | Camada 1 (borda) funciona como desenhado, economiza invocação em chamada não autenticada | Perde a simplicidade de uma única rota catch-all; mais entradas em `template.yaml` para manter sincronizadas com as rotas do FastAPI |
> | **B — Authorizer aplicado à API inteira (`$default`), incluindo `GET`; a "leitura pública" vira uma exceção via credencial anônima/API key de baixo privilégio** | Mantém a rota única | Contradiz a decisão da seção 6.4 (GET público sem fricção); pior experiência para quem só quer descobrir uma tabela |
> | **C — sem `Authorizer` bloqueante na borda; todo o enforcement fica só na camada FastAPI (seção 6.1, item 2)** (escolhida) | Nenhuma mudança estrutural no `template.yaml`; a divisão GET-público/escrita-autenticada já é exatamente o que a dependency do FastAPI faz por rota | Perde a economia de "rejeitar antes de invocar a Lambda" para chamadas de escrita não autenticadas — aceitável no volume deste projeto |
>
> **Escolhida: C.** `template.yaml` continua com a rota catch-all como está; o Cognito User
> Pool é provisionado só como *emissor* de tokens (para o JWT ser validado pela aplicação),
> sem `Authorizer` no `AWS::Serverless::HttpApi`. Revisitar a opção A como evolução futura
> (seção 11) se o volume de tráfego não autenticado justificar economizar invocações.

### 6.2 Novos componentes

- **`app/core/security.py`** — busca e cacheia o JWKS do Cognito (cache em memória,
  reaproveitado entre invocações "quentes" da Lambda, mesmo padrão já usado para a
  conexão do Mongo em `app/core/database.py`); verifica assinatura RS256, `exp`, `aud`,
  `iss`; retorna um `Principal` (`subject`, `email`, `is_service`).
- **`app/api/deps.py`** — nova dependency `get_current_principal` (lê o header
  `Authorization: Bearer ...`, 401 se ausente/inválido), seguindo o mesmo padrão de
  injeção já usado por `get_metadata_repository`/`get_metadata_service`.

### 6.3 Separação entre schema de entrada e modelo interno

`MetadataCreate`/`MetadataUpdate` (`app/models/metadata.py`) hoje aceitam `created_by`/
`updated_by` vindos do cliente. Isso deixa de fazer sentido: esses campos passam a ser
**derivados do token, nunca do corpo da requisição**. Proposta:

- Novos schemas de request `MetadataCreateRequest`/`MetadataUpdateRequest` — idênticos
  aos atuais, porém **sem** `created_by`/`updated_by` no schema público.
- A rota (`app/api/routes/metadata.py`) combina `request.model_dump()` +
  `created_by=principal.email` antes de repassar ao `MetadataService` — o serviço e o
  repositório não mudam, só a rota ganha uma dependência a mais.

### 6.4 Política por rota

| Rota | Autenticação | Justificativa |
|---|---|---|
| `GET /metadata`, `GET /metadata/{id}`, `GET /metadata/{id}/schema-history` | **Não exigida** | Descoberta é o propósito central do catálogo |
| `POST /metadata`, `PUT /metadata/{id}` | **Exigida** | Precisa de `created_by`/`updated_by` confiáveis |
| `DELETE /metadata/{id}` | **Exigida** | Operação destrutiva — sem RBAC ainda (seção 3), mas exigir autenticação já é uma barreira mínima |

## 7. Impacto no emulador de Glue (SDD relacionado)

O `sync.py` do [emulador de Glue](sdd-glue-catalog-emulator.md) passa a precisar de um
token antes de chamar `POST`/`PUT` — via o app client "service" (Client Credentials).
Isso não muda a arquitetura desenhada lá, só adiciona um passo de obtenção de token antes
de cada sincronização. `created_by`/`updated_by` das tabelas sincronizadas pelo emulador
passam a refletir a identidade do app client (ex. `glue-sync-service@...`), o que é
inclusive mais correto do que o texto livre usado nos exemplos atuais do README.

## 8. Testes

Mesmo padrão já usado para o repositório fake em `tests/conftest.py`:
`app.dependency_overrides[get_current_principal] = lambda: Principal(subject="test-user", email="test@example.com")`.
Testes de API continuam herméticos, sem precisar de um Cognito real. Um teste específico
(sem override) cobre o caso de requisição sem token → `401`.

Para teste manual local (Swagger/curl) sem depender de um Cognito real provisionado, um
script auxiliar (`scripts/mint_dev_token.py`) assina um JWT com uma chave de
desenvolvimento própria, aceita **apenas** quando `AUTH_ISSUER` aponta para esse emissor
de dev — nunca em produção.

## 9. Riscos e considerações

- **Isso é mais do que o case técnico original pediu.** Está sendo proposto porque
  apareceu como uma lacuna real durante o desenho do emulador de Glue (auditoria não
  confiável), não porque o enunciado exigia — vale deixar essa justificativa explícita
  se isso for apresentado na entrevista.
- Cognito é mais um recurso de infraestrutura para provisionar e versionar no
  `template.yaml` — custo e complexidade adicionais, ainda que dentro do free tier para
  o volume deste case.
- JWT é stateless: revogar um token comprometido antes do `exp` não é imediato. Mitigado
  com TTL curto (ex. 15–60 min) — não é resolvido neste documento, só reconhecido.
- Cache de JWKS na Lambda precisa de invalidação (rotação de chaves do Cognito) —
  detalhe de implementação a tratar no passo 2 abaixo, não um risco estrutural.

## 10. Plano de implementação (incremental)

1. Provisionar `AWS::Cognito::UserPool` + dois `UserPoolClient` (human/service) no
   `template.yaml`, como emissor de tokens — **sem** `Authorizer` na
   `AWS::Serverless::HttpApi` (decisão C, seção 6.1): a rota continua catch-all, o
   enforcement fica na dependency do FastAPI (passo 3).
2. `app/core/security.py` — verificação de JWT + cache de JWKS.
3. `app/api/deps.py` — dependency `get_current_principal`.
4. Separar `MetadataCreateRequest`/`MetadataUpdateRequest` dos modelos internos; ajustar
   as rotas de escrita para exigir `Depends(get_current_principal)` e derivar
   `created_by`/`updated_by`.
5. Atualizar `tests/conftest.py` com o override de `get_current_principal`; adicionar
   teste de `401` sem token.
6. `scripts/mint_dev_token.py` para teste manual local.
7. Ajustar `scripts/glue_emulator/sync.py` (do SDD do emulador) para obter token via
   client-credentials antes de sincronizar.
8. Atualizar o README com a seção de autenticação (como obter um token de teste, como
   chamar rotas protegidas via Swagger).

## 11. Evoluções futuras

- Dividir a rota catch-all do `template.yaml` em rotas explícitas por método (opção A da
  seção 6.1) e mover o enforcement de escrita para um `Authorizer` na borda, se o volume
  de tráfego não autenticado justificar economizar invocações Lambda.
- RBAC/scopes (`catalog:read`/`catalog:write`/`catalog:admin`) via grupos do Cognito,
  restringindo `DELETE` a um papel administrativo.
- Rate limiting por identidade (usage plans do API Gateway, agora que há um `sub` para
  associar).
- Resolver `owner` automaticamente a partir de um diretório externo (ex. um serviço de
  "quem é dono de qual domínio"), mantendo-o como campo explícito, mas validado/sugerido
  em vez de texto totalmente livre — evolução natural, não coberta aqui.
