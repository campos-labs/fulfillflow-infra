# Correlação e limites da observação

Na primeira etapa, dois casos diagnósticos em Kind, sobre FulfillFlow `v1.3.0-rc.1`
(`9e3a135a00db218643633c7165d3106f0c8285e1`), confirmaram a ligação entre
estados públicos e registros dos três workers. Não houve instalação de OpenTelemetry
ou alteração da aplicação. A contribuição é reconstruir o caminho e delimitar a
observação; a conclusão de Notifications sem reenvio já havia sido verificada na
[avaliação de recuperação](../../OPERATIONAL_EVALUATION.md).

A [descoberta offline anterior](discovery-01.json), produzida pelo
[extrator](../../../scripts/observability_discovery.py), relaciona um evento
previamente selecionado em cada uma das nove tentativas de capacidade. É contexto
ilustrativo; não amplia o número de casos integrados desta etapa.

## Cobertura e limites

| Questão | Evidência disponível | O que permite concluir | Limite restante |
| --- | --- | --- | --- |
| Ligar as três mensagens | `message_id`, `correlation_id`, `event_id` e request ID da admissão nos workers | Publicação, recepção persistida e processamento ligados ao mesmo evento | IDs não são spans; não houve retomada de processamento interrompido |
| Localizar a pendência | Consulta `SENT/NOT_RECEIVED`, inventário sem Notifications e consulta posterior `SIMULATED` | Trabalho publicado aguardou consumo e concluiu no novo pod sem reenvio | Não demonstra entrega externa nem superioridade de recuperação |
| Separar resultado e observação | Campos persistidos, logs `DONE`, consultas com relógio monotônico/UTC | Confirmação posterior não coincide necessariamente com resultado registrado | Não identifica commit exato; incerteza entre relógios não medida |
| Interpretar o executor | Diário de intervenção e `worker_restored` antes da consulta final | A espera por rollout adiou deliberadamente a próxima consulta | Não atribuir essa demora à aplicação nem aos atrasos da avaliação de capacidade |
| Investigar HTTP interno | Duração total, códigos, request IDs e projeção de acesso do 503 | Localiza falha de preparação anterior à oferta e contexto de inicialização | Não isola transporte, resposta remota, validação ou exceção original |

## Método e resultados

Cada caso ofereceu **um evento**, com uma réplica por processo. No caso de pendência,
o executor retirou Notifications worker antes da oferta, confirmou ausência do pod,
aguardou Tracking/Order e `SENT/NOT_RECEIVED`, devolveu uma réplica e confirmou
`SIMULATED` e um efeito de cada tipo pelas APIs. Os logs foram confrontados com essas
consultas; não constituíram o único veredito funcional. A troca do pod foi registrada.

| Caso | Referência do executor | Registros correlacionados ao evento | HTTP | Resultado |
| --- | --- | ---: | --- | --- |
| [Saudável](records/healthy-01/) | `7829064` | 9, três message IDs | 13 requisições, zero erros | Tracking/Order e Notifications `SIMULATED` |
| [Pendência](records/pending-02/) | `974dbce` | 9, três message IDs; mais um log de inicialização | 15 requisições, zero erros | `SENT/NOT_RECEIVED` → `SIMULATED`, mesmo evento |

São **dois casos distintos**, não condições equivalentes nem repetições comparativas.
Nove registros de um evento não são nove repetições. Memória mínima amostrada:
4,08 GiB e 4,19 GiB, respectivamente, acima da guarda de 2 GiB; os nós foram parados.
Não há baseline para calcular overhead ou ganho geral de diagnóstico.

No saudável, aceite → confirmação de Notifications foi 2,235 s pelo relógio do
observador. Na pendência, foi 18,765 s, incluindo a intervenção e espera por
`rollout status`. Notifications registrou `DONE` em **10:54:17,021 UTC**;
o executor registrou término da espera em **10:54:31,749 UTC** e confirmou o
resultado em **10:54:31,790 UTC**. Esses valores explicam o procedimento deste
caso, não medem velocidade relativa da aplicação. O log `DONE` é posterior à
operação local, não um relógio exato do commit. Não subtrair medianas, somar etapas
paralelas ou transpor estas observações para campanhas anteriores.

A semântica dos logs vem da referência congelada:
[worker](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/messaging/worker.py)
registra o resultado após a transação local;
[AMQP](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/messaging/amqp.py)
registra recepção após persistência/ACK e publicação após confirmação e registro local.
Esses marcos não reconstruem todas as esperas internas.

## Evidências examináveis

Os 20 arquivos em [records](records/) totalizam aproximadamente 49 kB; JSON/JSONL
permitem leitura direta no GitHub, sem ZIP. São cópias exatas das capturas já
projetadas por campos permitidos, não dumps nem logs brutos. O
[manifesto](manifest.json) identifica seleção, exclusões, caminho original e SHA-256.
As regras de Git preservam esses bytes em Windows/Linux.

| Afirmação | Fontes e campos principais |
| --- | --- |
| Correlação saudável | [worker-records](records/healthy-01/worker-records.json): `message_id`, `correlation_id`, `event_id`, `request_id`; [observações](records/healthy-01/event/observations.jsonl): `accepted`, `public_query` |
| Pendência e conclusão do mesmo evento | [observações](records/pending-02/event/observations.jsonl): `pending_confirmed`, consultas `notifications_pending_observation` e `notifications_observation`; [resultado funcional](records/pending-02/functional.json): checkpoint |
| Pod retirado e substituído | [intervenção](records/pending-02/intervention.jsonl): `observed_pods`; [identidades](records/pending-02/worker-transition.json): `before/after`; [restauração](records/pending-02/restoration.json) |
| Trabalho executado antes da consulta final | [worker-records](records/pending-02/worker-records.json): Notifications `process/DONE`; [observações](records/pending-02/event/observations.jsonl): `worker_restored`, `notifications_simulated` |
| Falha anterior sem oferta | [resultado](records/preparation-failure-01/functional.json): `webhook_offered=false`; [HTTP](records/preparation-failure-01/http-timings.json): GET 503; [projeção de acesso](records/preparation-failure-01/api-log-review.json) |

Os [resumos saudável](healthy-01-review.json) e [de pendência](pending-02-review.json)
são conferências derivadas, não substitutos dos registros. Foram produzidos quando
os originais estavam somente locais; o manifesto desta consolidação identifica o
subconjunto agora publicado. Séries completas de host/startup e capturas não
selecionadas continuam locais. Os hashes dessas séries não significam disponibilidade
pública. Não estão incluídos segredos, kubeconfig, imagem, bancos ou reprodução do host.

Conferência sem Docker, rede ou artefatos locais, a partir da raiz do repositório:

```powershell
uv run --frozen python scripts/verify_observability_evidence.py
```

A verificação confere bytes, cobertura do manifesto, referências, oferta única,
correlação por evento/mensagem, estados públicos e intervalo monotônico declarado.
A CI a executa em Linux/Windows. Não refaz a experiência ou certifica a causa de erros.

## Preparação preservada

| Registro | Resultado e tratamento |
| --- | --- |
| `observability-pilot-01` | Prontidão dos workers não confirmada, antes da oferta; captura de inicialização melhorada |
| `observability-pilot-02` | Webhook recebeu 503 sem confirmação de aceite; não reenviado |
| `observability-inspection-01` | GET posterior retornou lista vazia; não reconstrói persistência no instante do erro |
| `observability-pending-01` | GET prospectivo 503 antes de criar entidades ou retirar worker; fontes selecionadas publicadas acima |
| `observability-pending-02` | Sucessora delimitada com qualificação prévia de GETs; cenário concluído |

Na falha de preparação publicada, Core registrou 503 em 10:48:57,231 UTC e Tracking
startup completo em 10:48:57,921 UTC. A ordem sustenta a hipótese de prontidão
incompleta durante inicialização, mas não isola a exceção interna. A sucessora
exigiu três GETs 200 consecutivos antes de qualquer escrita, preservando falhas de
preparação quando presentes; não repetiu admissão. Seu sucesso não prova causalidade.
O [protocolo e diário preservados por commit](https://github.com/campos-labs/fulfillflow-infra/blob/fcff02e0938675af0be51950ba444cca4b0da9a5/RELEASE_PLAN.md#4-exploração-de-observabilidade)
registram limites originais, emendas e pausas. Os resultados anteriores permanecem intactos.

## Decisão

A correlação existente cobre estes dois cenários e merece ser mantida como capacidade
diagnóstica delimitada. Não repetir para obter números melhores ou declarar
superioridade de uma ferramenta que não foi utilizada. Uma extensão deve acrescentar
informação sobre outra fronteira, com nova referência quando modificar o runtime.
O [plano](../../../RELEASE_PLAN.md#4-exploração-de-observabilidade) define a lacuna
HTTP interna, concluída abaixo, e os critérios para eventual continuidade;
não há nova campanha ou nuvem implícita.


## Fatia HTTP com OpenTelemetry

Uma nova referência da aplicação (`045e1ca`, derivada da v1.3 congelada) instrumentou
somente a consulta pública de eventos e seu forwarding para Tracking. A execução
[HTTP 05](http-05/) utilizou um evento já persistido, sem novo webhook ou escrita de
negócio, após verificar os três caminhos de saúde. O executor foi `d911bc7`.

| Conferência | Resultado | Fonte |
| --- | --- | --- |
| Resultado público independente | 200, `PROCESSED` / `COMPLETED`, nove verificações aprovadas | [functional.json](http-05/functional.json) |
| Contexto distribuído | Quatro spans: observador → Core servidor → Core cliente → Tracking servidor | [trace-records.json](http-05/trace-records.json) |
| Cobertura e parentela | Quatro papéis e ligações conferidos; três lotes aceitos, zero rejeitados | [review.json](http-05/review.json) e traces |
| Preparação e encerramento | Caminhos de saúde 200, specs históricos preservados, nó parado | [peer-health](http-05/peer-health.json), [preservation](http-05/preservation.json), [summary](http-05/summary.json) |
| Custo da instrumentação | Não medido; API de métricas indisponível | [resources.json](http-05/resources.json) |

O observador registrou cerca de 152 ms; Core servidor 63,6 ms, cliente interno
45,6 ms e Tracking servidor 42,3 ms. São intervalos aninhados de uma única consulta:
não somar nem subtrair para atribuir causalmente o restante a rede, banco ou overhead.
Os spans não medem commits ou processamento dos workers, nem cobrem as consultas de
metadados que Tracking faz ao Core. Não houve comparação com runtime sem instrumentação.

O ganho demonstrado é localizar fronteiras antes agregadas na duração total. Nas
tentativas preparatórias, a captura distinguiu resposta remota 503 e erro de transporte
no cliente Core. Isso não determina causas dos 503 antigos ou demonstra superioridade
geral do diagnóstico. A tentativa 04 respondeu 200, mas o verificador exigia o status
inexistente `APPLIED`; corrigiu-se a asserção para o contrato da inbox e executou-se
05. Os dados anteriores não foram alterados ou retroativamente aprovados.

Os oito arquivos têm bytes preservados e [SHA-256 próprios](http-05/manifest.json).
[protocol.json](http-05/protocol.json) identifica código, imagem, dependências e guardas.
A revisão foi reproduzida offline com `scripts.http_trace_contract.verify_trace`;
a conferência dos dois casos de workers acima permanece separada. Imagem, bancos,
segredos e séries completas do host não integram esta seleção. A perturbação de transporte foi especificada posteriormente no DESIGN §8.8; não repetir a consulta saudável apenas para obter outro tempo.

### Erros preparatórios HTTP preservados

[Manifesto HTTP 02/03](http-errors/manifest.json): quatro arquivos originais por tentativa,
com SHA-256 e referência da execução. A 02 contém resposta remota 503 e quatro spans;
a 03 contém categoria `transport` no cliente Core e três spans. São observações
preparatórias, sem injeção controlada: não estabelecem a causa original nem explicam
os 503 das campanhas anteriores. Ausência de span isoladamente não prova onde o
processamento parou. O caminho Tracking → Core de metadados não tem span nesta fatia.

O verificador dos vinte registros de workers não cobre esses arquivos HTTP; seus
manifestos permitem conferir os bytes publicados separadamente. A próxima verificação
controlada terá resultado esperado próprio e não exigirá quatro spans no erro de transporte.
