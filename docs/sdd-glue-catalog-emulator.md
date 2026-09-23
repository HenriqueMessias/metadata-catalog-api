# SDD — Emulador de AWS Glue Data Catalog para geração de dados de teste

| | |
|---|---|
| **Status** | Implementado e validado (`feature/glue-catalog-emulator`) — ver seção 9.1 |
| **Autor** | Henrique Messias Santos |
| **Componente afetado** | Novo: `scripts/glue_emulator/` (ferramenta de suporte, fora do pacote de deploy da API) |
| **Relacionado** | [README.md](../README.md), [template.yaml](../template.yaml), [sdd-api-authentication.md](sdd-api-authentication.md) |

## 1. Contexto e problema

Hoje o Data Catalog API só foi exercitado com dados de teste manuais (fixtures do
`pytest`, exemplos do README). Isso valida a **correção** da API, mas não seu
**comportamento sob dados e volume realistas** — que é justamente o cenário de uso real
descrito na vaga: um serviço alimentado continuamente por crawlers que descobrem tabelas
no data lake (no caso da empresa, via **AWS Glue**) e precisam registrar/atualizar
metadados em escala.

Precisamos de uma forma de gerar dados que:

1. Tenham a **forma real** do que um crawler de Glue produziria (nomes de database/tabela,
   colunas com tipos Hive, localização em S3, etc.) — não apenas dados aleatórios que só
   fazem sentido para o nosso próprio schema.
2. Permitam simular **evolução de schema ao longo do tempo** (uma tabela que ganha/perde
   coluna entre um crawl e outro), para validar o mecanismo de `schema_version`/
   `schema_history` já implementado no serviço.
3. Permitam gerar **volume** (centenas/milhares de tabelas) para observar paginação,
   filtros e latência da API sob carga, não só no caminho feliz de 1 registro.

## 2. Objetivo

Construir um emulador local de AWS Glue Data Catalog que gera tabelas sintéticas
plausíveis e as sincroniza com o Data Catalog API, servindo como gerador de dados de
teste/carga e como prova de conceito da integração real "Glue → Catálogo".

## 3. Não-objetivos (fora de escopo)

- **Não** se conecta a uma conta AWS real nem cria recursos Glue de verdade — é emulação
  local, sem custo e sem credenciais.
- **Não** reimplementa a lógica de um crawler real (inferência de schema a partir de
  arquivos em S3). As colunas/tipos são gerados sinteticamente, já no formato de saída
  que um crawler produziria — não simulamos a *leitura de arquivos*, só a *interface* do
  catálogo resultante.
- **Não** é um teste de carga formal (sem métricas de p95/p99 sob concorrência real) —
  o foco aqui é gerar dados e observar comportamento funcional; benchmarking sério fica
  como evolução futura (seção 9).

## 4. Visão geral da solução

```
┌─────────────────────┐      boto3 (mockado por moto)      ┌──────────────────────┐
│  generator.py        │ ───────────────────────────────▶  │  Glue Data Catalog    │
│  (Faker: tabelas,     │   glue.create_database()           │  (em memória, via     │
│   colunas, tipos)     │   glue.create_table()               │   moto — sem AWS      │
└─────────────────────┘                                     │   real)               │
                                                              └──────────┬───────────┘
                                                                         │ glue.get_tables()
                                                                         ▼
                                                              ┌──────────────────────┐
                                                              │  mapper.py            │
                                                              │  (Glue Table  →       │
                                                              │   MetadataCreate/     │
                                                              │   MetadataUpdate)     │
                                                              └──────────┬───────────┘
                                                                         │ HTTP (httpx)
                                                                         ▼
                                                              ┌──────────────────────┐
                                                              │  Data Catalog API     │
                                                              │  (a aplicação já      │
                                                              │   existente, local)   │
                                                              └──────────────────────┘
```

Três componentes, cada um com uma responsabilidade única (mesmo princípio de separação
de camadas já usado no resto do projeto):

- **`generator.py`** — gera dados sintéticos plausíveis (nomes, tipos, donos) usando
  `Faker`. Não sabe nada sobre Glue nem sobre a API.
- **`glue_catalog.py`** — cria bancos/tabelas no **Glue mockado via `moto`**, usando o
  `boto3` real (`glue.create_database`, `glue.create_table`, `glue.get_tables`, ...).
  Não sabe nada sobre a nossa API.
- **`mapper.py`** — traduz a resposta do Glue (`glue.get_tables()`) para o contrato da
  nossa API (`MetadataCreate`/`MetadataUpdate`). É aqui que ficam as decisões de mapeamento
  (seção 5).
- **`sync.py`** — orquestra: lê do Glue via `mapper.py`, chama a API via `httpx`
  (POST para tabela nova, PUT para existente).
- **`cli.py`** — expõe os modos de operação (seção 6) como subcomandos.

#### Decisão de design: como `sync.py` decide POST vs. PUT

A API não expõe busca por identidade exata (`database_name`+`schema_name`+`table_name`) —
só `GET /metadata/{id}` (precisa do id) ou `GET /metadata?search=...` (substring em
`table_name`, não é match exato, pode trazer falsos positivos de outro schema/database
com nome parecido). E o `409` de duplicata não devolve o `id` do registro existente.

Resolvendo isso **dentro do emulador**, sem mudar a API já testada: antes de cada
sincronização, `sync.py` faz `GET /metadata?search=<table_name>` e filtra client-side
pelo trio exato (`database_name`, `schema_name`, `table_name`) para achar o `id`; se
achar, `PUT`; se não achar, `POST`. Isso é ineficiente (`O(n)` chamadas de listagem) para
o modo `load` com milhares de tabelas — aceitável para os volumes deste emulador
(centenas/poucos milhares), mas documentado aqui como limitação conhecida (seção 10),
não uma omissão.

### Decisão de design: por que `moto` em vez de gerar JSON solto?

| Opção | Prós | Contras |
|---|---|---|
| **A — JSON sintético direto** no formato do nosso `MetadataCreate` | Mais simples, zero dependência nova | Não valida o mapeamento Glue→Catálogo, que é justamente o ponto mais relevante para a vaga; dado "parece" real mas não passou pela forma real da API do Glue |
| **B — `moto` + `boto3` real (escolhida)** | `sync.py` chama exatamente as mesmas chamadas boto3 (`get_tables`) que chamaria contra uma conta AWS real; trocar o mock pelo Glue real em produção não exige reescrever `sync.py`, só trocar a fonte de credenciais | Uma dependência a mais (`moto`); mock não cobre 100% dos comportamentos de borda do Glue real |

Optamos por **B**: o ganho de fidelidade (e o fato de `sync.py` virar um candidato real a
job de sincronização de produção — ver seção 9) compensa a dependência extra, que fica
isolada em `requirements-glue-emulator.txt` e nunca entra no pacote da Lambda.

## 5. Mapeamento de campos: Glue Table → `Metadado`

O Glue Data Catalog tem um namespace de **dois níveis** (`Database` → `Table`), enquanto
o nosso modelo tem três (`database_name` → `schema_name` → `table_name`) — herdado de
bancos como Postgres/Redshift/Snowflake. E o Glue não tem conceito nativo de *owner
estruturado* nem de *classificação de sensibilidade* — isso precisa vir de convenções em
`Parameters` (dict livre chave-valor que crawlers/produtores podem preencher), que é
exatamente o padrão usado na prática por times de dados reais.

| Campo `Metadado` | Origem no Glue (`get_tables()`) | Observação |
|---|---|---|
| `database_name` | `Table['DatabaseName']` | 1:1 |
| `table_name` | `Table['Name']` | 1:1 |
| `schema_name` | fixo `"glue"` | Glue não tem 3º nível de namespace; documentamos essa convenção em vez de forçar um campo que não existe |
| `description` | `Table['Description']` | 1:1 |
| `location` | `Table['StorageDescriptor']['Location']` | caminho S3 (ex. `s3://bucket/path/`) |
| `columns[].name` | `StorageDescriptor.Columns[].Name` | 1:1 |
| `columns[].data_type` | `StorageDescriptor.Columns[].Type` | tipos Hive (`string`, `bigint`, `double`, ...), diferente da notação BigQuery (`STRING`, `INT64`) usada nos exemplos do README — o campo já é `str` livre na nossa API, então não há conflito, só vale registrar a diferença de convenção |
| `columns[].nullable` | não existe nativamente por coluna no Glue | assumimos `True` por padrão no emulador |
| `owner.name` / `owner.email` | `Table['Parameters']['owner_name']` / `['owner_email']` | `Table['Owner']` (campo nativo) é só uma string livre, geralmente uma role IAM, não um contato — por isso usamos `Parameters` sintéticos, simulando um crawler "enriquecido" por convenção interna do time |
| `domain` | `Table['Parameters']['domain']` | convenção nossa, não nativa do Glue |
| `classification` (sensibilidade/LGPD) | `Table['Parameters']['data_classification']` | **cuidado**: não confundir com o `Classification` nativo do Glue, que indica *formato de arquivo* (csv/json/parquet), preenchido automaticamente por crawlers reais — é outro conceito, por isso usamos uma chave de `Parameters` com nome diferente |
| `tags` | `Table['Parameters']['tags']` (string separada por vírgula) | Glue tem `TagResource` nativo para tags de recurso, mas é uma API separada (`ResourceArn` → tags) com limites próprios; por simplicidade o emulador usa `Parameters`, como muitos times fazem na prática |
| `schema_version` / `schema_history` | não existe no Glue | gerido inteiramente pela nossa API, a partir do diff de `columns` a cada sync — é o comportamento que queremos validar |
| `created_by` / `updated_by` | fixo `"glue-emulator"` | valor fixo até o [SDD de autenticação](sdd-api-authentication.md) ser implementado — quando isso acontecer, `sync.py` passa a obter esses valores de um token (client-credentials), não mais de um literal |

## 6. Modos de operação

```bash
python -m scripts.glue_emulator seed  --tables 200  --api-url http://localhost:8000/api/v1
python -m scripts.glue_emulator drift --ratio 0.2    --api-url http://localhost:8000/api/v1
python -m scripts.glue_emulator load  --tables 5000  --api-url http://localhost:8000/api/v1
python -m scripts.glue_emulator rerun --api-url http://localhost:8000/api/v1
```

- **`seed`**: cria N databases/tabelas sintéticas no Glue mockado e sincroniza tudo com a
  API (`POST /metadata`). Caminho feliz.
- **`drift`**: re-executa sobre uma fração (`--ratio`) das tabelas já "descobertas",
  alterando colunas (adiciona/remove/renomeia) para simular um novo crawl, e sincroniza via
  `PUT /metadata/{id}` — valida que `schema_version` incrementa **só** nas tabelas cujas
  colunas de fato mudaram, e que `schema_history` fica correto.
- **`load`**: gera um volume maior e mede tempo de resposta de `POST` individual e de
  `GET /metadata` paginado — observa comportamento de índice/paginação sob volume.
- **`rerun`**: roda o mesmo `seed` de novo sem alterar nada — valida que a API responde
  `409 Conflict` corretamente (idempotência) e que nenhuma tabela duplicada é criada.

## 7. Estrutura de arquivos proposta

```
metadata-catalog-api/
├── scripts/
│   └── glue_emulator/
│       ├── __init__.py
│       ├── __main__.py        # permite `python -m scripts.glue_emulator`
│       ├── cli.py             # argparse: subcomandos seed/drift/load/rerun
│       ├── generator.py       # Faker: nomes, colunas, tipos, "donos" plausíveis
│       ├── glue_catalog.py    # cria/lê o Glue fake via moto + boto3
│       ├── mapper.py          # Glue Table -> payload da API (testável isoladamente)
│       └── sync.py            # chama a API via httpx (POST/PUT)
├── tests/
│   └── test_glue_mapper.py    # testes unitários do mapeamento (sem rede, sem moto)
├── requirements-glue-emulator.txt   # moto, boto3, faker — isolado do requirements.txt da API
└── docs/
    └── sdd-glue-catalog-emulator.md   # este documento
```

`requirements-glue-emulator.txt` fica de fora tanto do `requirements.txt` de produção
quanto do pacote empacotado pela Lambda — adicionar `scripts/` e
`requirements-glue-emulator.txt` ao `.samignore` existente é um passo do plano de
implementação (seção 8).

## 8. Plano de implementação (incremental)

1. Adicionar `requirements-glue-emulator.txt` (`moto[glue]`, `boto3`, `faker`) e atualizar
   `.samignore` para excluir `scripts/` e esse arquivo do pacote de deploy.
2. `generator.py` — dados sintéticos (sem tocar em Glue/API ainda); testável isoladamente.
3. `glue_catalog.py` — cria o Glue mockado (`moto`) e popula com o que `generator.py`
   produz; expõe `list_tables()` usando `glue.get_tables()` de verdade.
4. `mapper.py` — tradução Glue → payload da API, com testes unitários cobrindo casos de
   borda (owner ausente, `Parameters` incompletos, tabela sem colunas).
5. `sync.py` — cliente HTTP (`httpx`) que decide POST vs. PUT e trata `409`/`404`.
6. `cli.py` — os quatro modos da seção 6.
7. Rodar contra a API local (`docker compose up -d` + `uvicorn app.main:app --reload`) e
   registrar os resultados observados (seção 9) — decidir se viram uma seção no README ou
   um relatório separado.

## 9. Critérios de avaliação (o que observar depois de implementado)

- `seed`: 100% das tabelas geradas retornam `201`, nenhuma colisão inesperada.
- `rerun`: 100% das tabelas retornam `409`, contagem total de documentos não muda.
- `drift`: `schema_version` incrementa **exatamente** nas tabelas cujas colunas mudaram
  (asserção programática comparando antes/depois), e não incrementa nas demais.
- `load`: latência de `GET /metadata` paginado não degrada de forma não-linear conforme
  o volume cresce (indício de que o índice composto do Mongo está sendo usado); tempo
  total de `seed` de N tabelas escala de forma previsível.
- Filtros (`domain`, `tag`, `owner_email`, `search`) retornam resultados corretos contra
  o volume gerado, não só contra os 1-2 registros dos testes unitários existentes.

## 9.1 Validação executada (pós-implementação)

Rodado de ponta a ponta contra a API local real (MongoDB via `docker compose`,
`uvicorn`), não só contra o repositório fake dos testes unitários:

- `seed --tables 30 --databases 3 --seed 42`: 30/30 criadas (`201`), 0 falhas.
- `rerun` (mesmo `--seed`): **`created=0, updated=30, conflicts(409)=0`** — diferente do
  previsto originalmente nesta seção (`409` esperado). `find_existing_id` (seção 4) já
  resolve a identidade antes de decidir POST/PUT, então uma resincronização idêntica vira
  `PUT` idempotente em vez de bater no `409` — mais robusto do que o desenho original
  previa. Confirmado via `GET`: `schema_version` permaneceu `1` (o diff de colunas no
  serviço corretamente não detectou mudança).
- `drift --ratio 0.3`: **bug real encontrado** — de 9 tabelas selecionadas para sofrer
  drift, só 8 tiveram `schema_version` incrementado; a 9ª (`product_purpose.coach_long`)
  ficou com o mesmo conjunto de colunas antes/depois. Causa: `drift_columns()` podia
  sortear para remoção **a própria coluna que acabara de adicionar**, netando zero
  mudança. Corrigido em `generator.py` (excluir a coluna recém-adicionada do conjunto
  removível) + teste de regressão (`test_drift_columns_never_nets_out_to_no_change`,
  varrendo 200 seeds). Reexecutado: `9/9` tabelas corretamente incrementadas para
  `schema_version=2`, com `schema_history[0]` preservando as colunas da versão anterior.
- `load --tables 500 --databases 10`: 500/500 criadas, ~60 req/s (limitado pelo
  lookup `O(n)` já documentado na seção 4/10, não pela API em si). Paginação
  (`GET /metadata`, sem parâmetros) devolveu corretamente 20/500 (limite padrão);
  filtros `domain`, `tag` e `owner_email` retornaram contagens e conteúdo corretos
  contra o volume completo.

Essa validação é exatamente o motivo de o emulador existir (seção 1): o bug do
`drift_columns` não teria aparecido nos testes unitários originais (que não cobriam
esse caso específico) nem seria visível manualmente com 1-2 registros de teste — só
apareceu ao gerar volume e comparar resultado esperado vs. real.

## 10. Riscos e limitações

- `moto` mocka a **interface** do Glue, não o comportamento de um crawler real (que
  infere schema amostrando arquivos) — é fidelidade de formato, não de algoritmo.
- Compatibilidade de versão entre `moto`, `boto3` e `botocore` pode exigir pins específicos
  no `requirements-glue-emulator.txt` — validar na implementação.
- Sem MongoDB real disponível neste ambiente no momento (Docker Desktop não estava
  rodando na sessão) — a execução real do `seed`/`drift`/`load` vai precisar ser validada
  assim que o Mongo estiver acessível.
- Decisão POST vs. PUT via listagem+filtro client-side (seção 4) é `O(n)` por tabela
  sincronizada — se o modo `load` crescer muito além de poucos milhares de registros,
  vale revisitar (ex.: expor um endpoint de busca por identidade exata na API).

## 11. Valor adicional / evoluções futuras

- `sync.py`, como desenhado, é candidato direto a virar um **job de produção real**: uma
  Lambda agendada (`EventBridge` cron, ou acionada por evento de conclusão de um Glue
  Crawler real) que sincroniza o Glue Data Catalog verdadeiro com este serviço — bastaria
  trocar a sessão `moto` por credenciais AWS reais, sem mudar a lógica de mapeamento.
- Teste de carga formal (ex. `locust`/`k6`) usando o modo `load` como gerador de massa de
  dados, se quisermos números de p95/p99 sob concorrência real.
- Suportar leitura de um Glue Data Catalog real (feature-flag `--source real|mock`) como
  segunda fase, uma vez que a lógica de mapeamento já esteja validada contra o mock.
