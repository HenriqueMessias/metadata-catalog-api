# Data Catalog API

Microsserviço de catálogo de metadados de tabelas do data lake: centraliza **ownership**,
contexto de negócio, estrutura (schema) e sua evolução ao longo do tempo, e classificação
de sensibilidade dos dados — resolvendo o problema recorrente de "quem é o dono dessa
tabela?" / "qual o contexto dela?".

Desenvolvido como case técnico: FastAPI + MongoDB, CRUD completo para a entidade
`Metadado`, orientado a objetos, com Repository Pattern e testes unitários.

## Sumário

- [Arquitetura](#arquitetura)
- [Modelagem de dados](#modelagem-de-dados)
- [Como rodar](#como-rodar)
- [Endpoints](#endpoints)
- [Testes](#testes)
- [Deploy em AWS (Lambda + API Gateway)](#deploy-em-aws-lambda--api-gateway)
- [Decisões técnicas](#decisões-técnicas)
- [Possíveis evoluções](#possíveis-evoluções)

## Arquitetura

O projeto segue uma arquitetura em camadas inspirada em **Ports & Adapters (Hexagonal)**,
com o **Repository Pattern** como abstração de persistência:

```
app/
├── api/routes/     # Camada HTTP: parsing de request/response, status codes
├── services/        # Regras de negócio (unicidade, versionamento de schema)
├── repositories/     # Porta (ABC) + adaptador MongoDB (Motor)
├── models/           # Entidades/Schemas Pydantic (domínio + DTOs de API)
├── core/              # Configuração (env) e ciclo de vida da conexão Mongo
└── main.py            # Composição da aplicação (DI, exception handlers)
```

Fluxo de dependência: `routes → services → repositories (ABC) ← MongoMetadataRepository`.

A camada de `services` (`MetadataService`) **nunca importa Motor/PyMongo diretamente** —
ela depende apenas da abstração `MetadataRepository` (uma classe abstrata em
[`app/repositories/base.py`](app/repositories/base.py)). Isso traz dois ganhos concretos:

1. **Testabilidade real**: os testes unitários do serviço usam um repositório fake
   em memória ([`tests/fakes.py`](tests/fakes.py)), sem subir MongoDB, sem mocks frágeis
   de driver. Os testes de API fazem o mesmo via `dependency_overrides` do FastAPI.
2. **Substituição de infraestrutura sem tocar em regra de negócio** — trocar MongoDB por
   outro backend de persistência exigiria apenas um novo adaptador implementando a
   mesma interface.

Injeção de dependência é feita com o sistema nativo do FastAPI (`Depends`), configurado em
[`app/api/deps.py`](app/api/deps.py).

## Modelagem de dados

A entidade `Metadado` foi modelada para responder diretamente às perguntas do enunciado
(dono, contexto, estrutura, evolução do schema), usando uma única collection (`metadata`)
no MongoDB:

| Campo | Descrição |
|---|---|
| `table_name`, `database_name`, `schema_name` | Identidade física da tabela (índice único composto) |
| `description`, `domain`, `tags` | Contexto de negócio e descoberta (busca/filtro) |
| `owner` (`name`, `email`, `team`) | Ownership — quem responder quando algo quebra |
| `classification` | Sensibilidade do dado (`public`/`internal`/`confidential`/`restricted`), pensando em LGPD |
| `columns` (`name`, `data_type`, `nullable`, `is_pii`, ...) | Estrutura atual da tabela |
| `schema_version` / `schema_history` | Versão atual e snapshots congelados de versões anteriores |
| `location` | Onde o dado físico vive (ex.: `project.dataset.table`, `s3://...`) |
| `created_at/by`, `updated_at/by` | Auditoria básica |

**Evolução de schema**: ao fazer `PUT` alterando a lista `columns`, o serviço detecta a
mudança, congela a versão anterior em `schema_history` e incrementa `schema_version`
automaticamente — sem exigir nenhuma ação extra do cliente da API. Um endpoint dedicado
(`GET /metadata/{id}/schema-history`) devolve a linha do tempo completa.

## Como rodar

Pré-requisitos: Python 3.11+ e um MongoDB acessível (local, Docker ou Atlas).

```bash
git clone https://github.com/<seu-usuario>/<seu-repositorio>.git
cd <seu-repositorio>

python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

pip install -r requirements-dev.txt
```

Suba um MongoDB local (ou use uma instância já existente):

```bash
docker compose up -d
```

Configure as variáveis de ambiente (opcional — os defaults já apontam para
`mongodb://localhost:27017`):

```bash
cp .env.example .env
```

Rode a aplicação:

```bash
uvicorn app.main:app --reload
```

A API sobe em `http://localhost:8000`. Documentação interativa (Swagger) em
`http://localhost:8000/docs`, e o schema OpenAPI em `/openapi.json`.

## Endpoints

Prefixo: `/api/v1`.

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/metadata` | Cadastra o metadado de uma nova tabela |
| `GET` | `/metadata` | Lista/busca metadados (paginação + filtros) |
| `GET` | `/metadata/{id}` | Detalha um metadado |
| `PUT` | `/metadata/{id}` | Atualiza um metadado (parcial) |
| `DELETE` | `/metadata/{id}` | Remove um metadado |
| `GET` | `/metadata/{id}/schema-history` | Histórico de evolução do schema |
| `GET` | `/health` | Liveness probe |

`GET /metadata` aceita `skip`, `limit`, `owner_email`, `domain`, `tag` e `search`
(busca case-insensitive por `table_name`).

### Exemplo — criar um metadado

```bash
curl -X POST http://localhost:8000/api/v1/metadata \
  -H "Content-Type: application/json" \
  -d '{
    "table_name": "orders",
    "database_name": "sales",
    "schema_name": "public",
    "description": "Fact table com uma linha por pedido de cliente.",
    "owner": {"name": "Henrique Messias", "email": "henrique@example.com", "team": "Data Platform"},
    "domain": "sales",
    "classification": "internal",
    "tags": ["fact", "core"],
    "columns": [
      {"name": "order_id", "data_type": "STRING", "nullable": false},
      {"name": "amount", "data_type": "FLOAT64", "nullable": false}
    ],
    "location": "project.sales.orders"
  }'
```

Respostas de erro seguem `{"detail": "..."}`: `404` para metadado inexistente e `409`
para tabela já cadastrada (mesma tripla `database_name` + `schema_name` + `table_name`).

## Testes

```bash
pytest -v
```

Os testes **não dependem de um MongoDB real**: a camada de serviço é testada com um
repositório fake em memória, e os testes de API sobem a aplicação FastAPI real com o
lifespan de conexão ao Mongo substituído por um no-op e o repositório injetado via
`app.dependency_overrides` — exercitando o pipeline HTTP completo (roteamento, validação
Pydantic, exception handlers) sem infraestrutura externa.

- `tests/test_metadata_service.py` — regras de negócio (duplicidade, versionamento de
  schema, not-found)
- `tests/test_metadata_api.py` — contrato HTTP (status codes, ciclo de vida CRUD completo)
- `tests/test_lambda_handler.py` — garante que o entrypoint Lambda importa sem quebrar

## Deploy em AWS (Lambda + API Gateway)

> **Isso não afeta o desenvolvimento local.** `app/lambda_handler.py` e `template.yaml`
> são aditivos: nada em `app/main.py` importa Mangum, e nenhum teste depende de AWS.
> `uvicorn app.main:app --reload` e `pytest` continuam funcionando exatamente como antes,
> sem AWS CLI, sem SAM CLI e sem credenciais configuradas.

A aplicação FastAPI é a mesma em ambos os ambientes — o que muda é só a "porta de entrada":

```
localhost:  uvicorn ──▶ app.main:app
AWS:        API Gateway (HTTP API) ──▶ Lambda ──▶ app.lambda_handler:handler ──▶ app.main:app
```

[`app/lambda_handler.py`](app/lambda_handler.py) embrulha o mesmo objeto `app` com o
[Mangum](https://mangum.io/) (adaptador ASGI → evento Lambda), sem duplicar nenhuma rota
ou regra de negócio. [`template.yaml`](template.yaml) é um template
[AWS SAM](https://docs.aws.amazon.com/serverless-application-model/) que provisiona:

- a função Lambda (Python 3.12, handler `app.lambda_handler.handler`);
- uma **HTTP API** (API Gateway v2) com rota catch-all (`$default`/`ANY`), mais barata e
  com menor latência que uma REST API clássica para esse caso de uso;
- variáveis de ambiente da função (`MONGO_URI`, `MONGO_DB_NAME`, `MONGO_COLLECTION`) —
  reaproveitando o mesmo `pydantic-settings` usado localmente, sem nenhuma mudança de
  código para ler configuração.

Pré-requisitos: [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
e credenciais AWS configuradas.

```bash
sam build
sam deploy --guided \
  --parameter-overrides MongoUri="<sua connection string>" MongoDbName=data_catalog MongoCollection=metadata
```

`sam deploy --guided` cria um `samconfig.toml` local (não versionado) com suas respostas,
para deploys seguintes bastar `sam deploy`. Para testar localmente com o runtime da Lambda
emulado (opcional, além do `uvicorn` normal):

```bash
sam local start-api
```

### O que esse template assume (e onde ele para)

- **MongoDB alcançável publicamente** (ex.: MongoDB Atlas com allowlist de IP), por isso
  não há `VpcConfig` na função por padrão — está comentado no `template.yaml` para o caso
  de usar Amazon DocumentDB ou um Mongo dentro de uma VPC, que exigiria colocar a Lambda
  na mesma VPC/subnets/security groups.
- **Segredos como parâmetro do CloudFormation** (`NoEcho: true`, não fica em texto plano
  no console, mas ainda é menos seguro que resolver em runtime). Para produção, o próximo
  passo seria buscar `MONGO_URI` do AWS Secrets Manager no cold start em vez de injetá-la
  como variável de ambiente.
- **Cliente Motor (assíncrono) reaproveitado entre invocações "quentes"** do mesmo
  container, via `lifespan="auto"` do Mangum — funciona no caso comum, mas é um ponto que
  vale validar sob carga real; se aparecer instabilidade de conexão em produção, a
  alternativa mais simples é trocar para PyMongo síncrono, já que cada invocação da Lambda
  atende uma requisição por vez (sem ganho real de concorrência assíncrona dentro do
  mesmo container).

## Decisões técnicas

- **Repository Pattern + Dependency Inversion**: descrito em [Arquitetura](#arquitetura).
- **Motor (driver async oficial do MongoDB)**: alinhado ao modelo assíncrono do FastAPI,
  evitando bloquear o event loop em I/O de banco.
- **Índice único composto** (`database_name`, `schema_name`, `table_name`): garante
  consistência de identidade no nível do banco, não só na aplicação — protege contra
  condições de corrida em criações concorrentes.
- **Exception handlers centralizados** (`MetadataNotFoundError` → 404,
  `DuplicateMetadataError` → 409): a camada de serviço levanta exceções de domínio, sem
  conhecer HTTP; a tradução para status codes fica isolada em `main.py`.
- **Pydantic v2** para validação de entrada/saída e separação clara entre modelo de
  persistência (`MetadataInDB`) e contratos de API (`MetadataCreate`/`MetadataUpdate`/
  `MetadataResponse`) — evita vazar detalhes de storage (ex.: `_id`) para o contrato
  público sem necessidade.

## Possíveis evoluções

Fora do escopo deste case, mas seriam os próximos passos naturais em produção:

- **Soft delete** (campo `deleted_at`) em vez de remoção física, preservando linhagem
  histórica de tabelas descontinuadas.
- **Autenticação/autorização** (ex.: OAuth2/JWT) para que `owner`/`updated_by` reflitam
  o usuário autenticado, não um campo livre no payload.
- **Lineage entre tabelas** (upstream/downstream) como uma segunda collection
  relacionando `metadata_id`s.
- **Integração com AWS Glue Data Catalog / BigQuery INFORMATION_SCHEMA** para
  auto-descoberta e sincronização de schema real, reduzindo drift entre o catálogo e a
  estrutura física.
- **Observabilidade**: métricas de uso do catálogo (tabelas mais buscadas, sem owner
  definido, etc.) — tratando o serviço como produto interno, com SLAs próprios.
