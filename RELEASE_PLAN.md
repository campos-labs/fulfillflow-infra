# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Observabilidade: correlação consolidada**, na branch `feature/v1.2-observability`,
a partir de `v1.1.0-rc.1` (`92089b8`). Descoberta offline e dois casos diagnósticos
integrados estão concluídos: fluxo saudável e trabalho publicado aguardando consumo.
O [índice técnico e registros publicados](docs/evidence/observability/README.md)
permitem conferir cobertura e limites sem depender dos artefatos locais selecionados.
Nó parado. **Fatia HTTP saudável concluída** em `observability-http-05`: uma consulta
200, nove conferências funcionais aprovadas e quatro spans ligados corretamente.
[Registros e limites](docs/evidence/observability/README.md#fatia-http-com-opentelemetry)
estão publicados. **Sequência HTTP controlada 03 concluída:** 200 → 503 → 200,
com remoção do pod diagnóstico, erro de transporte localizado no cliente Core e
recuperação funcional após um novo pod Ready. [Evidências publicadas](docs/evidence/observability/README.md#falha-http-controlada-e-recuperação).
Pausa de avaliação de valor: não repetir estes cenários nem ampliar instrumentação,
carga ou nuvem automaticamente. Nenhuma release/merge v1.2 realizada.


**Comparação de capacidade fixa e adaptativa concluída e consolidada na
v1.1.0-rc.1.** O fechamento integra `feature/v1.1-autoscaling-kind` à `main`.
A [página da pré-release](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1)
identifica tag, commit e anexos; as referências medidas permanecem no relatório.

As nove tentativas foram preservadas, incluindo a primeira adaptativa da sessão
interrompida. A continuação terminou com zero posições pendentes. Essas campanhas
permanecem encerradas; novos ensaios pertencem à exploração delimitada da seção 4. Resultados, método, sensibilidade e limites
estão no [relatório de capacidade](docs/SCALING_EVALUATION.md); os três ZIPs em
`docs/evidence/scaling/archives` eliminam a dependência de pastas locais para sua
leitura. A imagem, o código da aplicação e o instrumento medido permanecem congelados.

## 2. Entregas e responsabilidades

| Referência | Entrega e situação |
| --- | --- |
| [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) | Recuperação operacional em Kind; [relatório e evidências](docs/OPERATIONAL_EVALUATION.md) preservados |
| [v1.1.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1) | Pré-release de capacidade fixa/adaptativa, scripts versionados, comparação concluída, gráficos e três pacotes |
| Aplicação consumida | FulfillFlow v1.3.0-rc.1, SHA `9e3a135a00db218643633c7165d3106f0c8285e1`; nenhuma alteração neste fechamento |
| Azure | Terraform e exemplos AKS/ACR são referências ainda não implantadas; não condicionam o aceite local |

README apresenta a entrega e orienta a navegação. DESIGN define contratos e
arquitetura. O guia `k8s/README.md` reúne pré-requisitos e comandos. Os relatórios
registram métodos executados, resultados e respectivas evidências. Este documento
acompanha estado de entrega e decisões futuras, sem duplicar as tabelas analíticas.

## 3. Fechamento e verificação

O [relatório](docs/SCALING_EVALUATION.md) preserva as nove tentativas, a interrupção
do bloco 1 e a análise dos blocos contínuos. Os
[três pacotes e checksums](docs/evidence/scaling/archives) e o
[manifesto](docs/evidence/scaling/manifest.json) permitem reprodução offline;
a qualificação tem seleção identificada de metadados. Scripts permanecem em
`scripts/`, sem depender de launchers `.local.ps1`.

O fechamento inclui revisão visual, inspeção do conteúdo publicável, testes e
checagem de integridade das evidências. A CI Linux/Windows verifica código,
documentos, reprodução offline, schemas e planos Terraform simulados; não executa
a comparação no Kind. Os resultados de CI ficam vinculados ao commit no GitHub.

A [nota da versão](docs/releases/v1.1.0-rc.1.md) resume entrega e limites.
A tag identifica a consolidação; `6932632` identifica o instrumento medido e
`5ca5878`, o coordenador da continuação. Os anexos da release são cópias exatas
dos ZIPs versionados, sem recompactação. Não mover tags nem substituir pacotes
publicados: uma correção posterior deve ter identidade própria.

<a id="3-extensões-possíveis"></a>

## 4. Exploração de observabilidade

### Resultado consolidado

**Questão técnica:** o que podemos localizar entre aceite, resultado por etapa e
confirmação do observador usando sinais existentes? Os dois casos ligaram nove
registros de cada evento às consultas públicas dos três serviços. A contribuição
nova é a reconstrução do caminho e dos limites da observação; conclusão sem reenvio
já estava demonstrada na avaliação de recuperação. Não são nove repetições por caso.

A [matriz de cobertura, método e índice das evidências](docs/evidence/observability/README.md)
concentra a análise. O plano registra somente estado e próximas decisões. A falha
anterior ao envio e a sucessora concluída permanecem separadas. O
[diário anterior à consolidação](https://github.com/campos-labs/fulfillflow-infra/blob/fcff02e0938675af0be51950ba444cca4b0da9a5/RELEASE_PLAN.md#4-exploração-de-observabilidade)
preserva protocolos prospectivos, correções e limites de cada janela.

**Decisão:** encerrar os cenários saudável e de pendência; sem repetição manual ou
carga adicional para confirmá-los. A coleta desses dois casos não mede overhead causal ou
tracing distribuído, nem resolve os 503 históricos. Scripts permanecem versionados;
claims e diretórios existentes não devem ser apagados para forçar novo ensaio.

### Fatia HTTP: captura saudável concluída

**Pergunta:** qual trecho de uma chamada conseguimos localizar que antes aparecia
somente como duração total ou `SERVICE_UNAVAILABLE`? Primeiro, um GET saudável
através de observador → Core → Tracking. A verificação funcional e os IDs públicos
continuam independentes dos traces. Não envolver webhook, workers, carga de escala,
transações SQL instrumentadas ou falha controlada no primeiro passo.

O teste integrado distinguiu dois caminhos do código congelado:
`ServiceClient.read` valida o schema e atende consultas de clientes tipados; a
API pública de carrier-events usa `forward_tracking` → `ServiceClient.request`,
encaminhando status/bytes após conferir Content-Type. A primeira implementação
capturava o caminho tipado e omitia o span cliente da API real; a suíte integrada
rejeitou essa cobertura incompleta antes da consulta no Kind. A correção acompanha
o forwarding sem acrescentar validação de JSON ou mudar o comportamento público.
Isso refina as categorias observáveis, mas não determina a causa dos 503 antigos.

| Parte | Informação pretendida | Limite/aceite |
| --- | --- | --- |
| Observador | Agendamento, início/fim HTTP e contexto enviado | Relógio monotônico próprio, sem atribuir toda espera ao servidor |
| Core servidor e cliente interno | Rota, destino lógico, duração do hop, status/categoria permitida | Ligar contexto e request ID; separar transporte, status remoto e Content-Type |
| Tracking servidor | Entrada/saída da mesma chamada | Ausência de span não prova ausência de execução; conferir captura/exportação |
| Estado público | GET e conteúdo esperado | Telemetria não substitui resultado funcional |

**Implementação:** SDK/OTLP HTTP 1.45.0 em referência própria da branch
`codex/v1.3-http-observability`, derivada da v1.3 congelada. O
[manifesto do runtime](config/http-observability.json) fixa source, lock e digest.
Flag desligada por padrão; apenas duas rotas GET têm spans. O span cliente inclui
transporte e a conferência existente de Content-Type, com marcos
`response_received` e `content_type_validated`. Não há autoinstrumentação genérica,
SQL, AMQP ou workers. A validação funcional permanece no observador.

**Protocolo previamente fixado:** `Invoke-HttpTracePilot.ps1`, saída exclusiva
`observability-http-01`, uma consulta do observador ao evento já persistido no
caso saudável. Nenhum novo webhook ou evento de negócio. Criar Core/Tracking
instrumentados com nomes/seletores próprios no ambiente de observabilidade;
não atualizar os deployments históricos ou migrar o banco. Compartilhar somente
os bancos proprietários existentes para essa leitura. Um receptor OTLP local
limitado recebe até 128 spans e rejeita atributos/eventos fora da allowlist.
Não é um Collector de produção nem uma plataforma de observabilidade.

Preparação/captura até 600 s, mais encerramento limitado; 5 GiB de entrada e 2 GiB durante
os comandos. Capturar resposta pública validada, quatro spans com parentela,
aceites/rejeições do receptor, inventário, memória e métricas de pods quando
presentes. A disponibilidade das métricas é registrada; não inferir overhead
causal. Ao encerrar, solicitar zero réplicas dos clones, conferir os specs
históricos e parar o nó, preservando volumes e resultados. Recursos do diagnóstico
permanecem identificados, impedindo repetição automática.

**Verificação preparatória:** na referência inicial, 923 testes unitários da aplicação passaram,
mais 68 casos focados incluindo os dez testes PowerShell. Após corrigir o caminho
de captura, os 19 casos focados de forwarding/deadlines/cliente passaram;
Mypy e os 12 contratos de importação passaram. Transporte OTLP real até o receptor
local passou; imagem construída e imports testados em container sem rede/volumes.
Os 309 testes de infraestrutura passaram; dois casos adicionais conferem a guarda
e a preservação da amostra que a violou. A CI da aplicação cobre PostgreSQL e
RabbitMQ reais. O launcher aguarda até 20 minutos pela CI aprovada do SHA fixado
antes de iniciar o Kind; falha, referência divergente ou prazo encerrado impedem
a execução. A espera remota é separada do teto de 600 s de preparação/captura local.
A CI completa da referência `045e1ca` foi aprovada antes da tentativa local.

**Preparação interrompida e corrigida:** `observability-http-01` entrou com 5,63 GiB
livres e registrou mínimo de 3,60 GiB, acima da guarda durante a execução. O receptor
não criou pod: os eventos `FailedCreate` identificaram rejeição por Pod Security
`restricted:v1.34`, pela ausência de `seccompProfile`. O rollout terminou sem iniciar
a consulta. As APIs históricas permaneceram intactas, e o nó foi parado.

O manifesto agora declara `RuntimeDefault`, preservando a política restrita. Um
dry-run de Pod na API real rejeitou o manifesto anterior e aceitou o corrigido;
essa verificação não executou a consulta nem comprova captura de traces. Dois testes
de regressão cobrem o contexto de segurança e o registro sanitizado da etapa de falha.
O executor passa a registrar `last_stage`, `query_started` e falhas de comandos sem
stderr bruto. Os 314 testes de infraestrutura, lint e formatação passaram após
a correção. Os oito recursos descartáveis da tentativa, identificados pelo run ID
e com deployments em zero réplicas, foram removidos após a conferência; bancos,
volumes, deployments históricos e evidências da tentativa foram preservados.

**Consulta 02:** uma oferta de GET, 503 em 116 ms observados, quatro spans com mesma
identidade e parentela conferida, três lotes aceitos e zero rejeitados pelo receptor.
Tracking respondeu 503; o span cliente do Core classificou `remote_http_error`, e
Core repassou o status. O resultado funcional continua reprovado; cobertura de trace
não aprova a consulta. A margem mínima amostrada foi 4,31 GiB, acima da guarda.

A inspeção encontrou `CORE_BASE_URL=http://core:8000` no clone Tracking: somente a
ida Core → Tracking havia sido redirecionada. `list_inbox` consulta metadados de
transportadora no Core, inclusive em páginas não vazias. O teste integrado anterior
usava página vazia sem filtro de transportadora e não exercitava essa dependência.
A correção direciona também Tracking → Core ao par diagnóstico, sem alterar contratos,
segredos, dados, recursos ou imagem. O teste de regressão cobre os dois sentidos e
preservação dos manifests originais. Os 315 testes de infraestrutura, lint, formatação
e validação estática passaram após a correção. Os quatro spans localizam a fronteira do 503,
mas não distinguem a operação interna que falhou dentro de Tracking. Não estabelecem
causas dos 503 históricos nem comprovam superioridade geral do diagnóstico.

Naquele ponto, a consulta corretiva ainda era necessária: a configuração incorreta foi comprovada,
mas os spans não preservam a exceção interna que originou o 503. Uma inspeção após
reiniciar o nó encontrou o endpoint histórico do Core não pronto; esse estado não
é apresentado como medição contemporânea à consulta 02. As oito configurações
transitórias da tentativa foram removidas pelo run ID após conferir zero réplicas;
volumes, dados, specs históricos e evidências continuam preservados, com o nó parado.

A sucessora foi identificada em `artifacts/observability-http-03`, com o mesmo evento,
runtime e guardas, com retorno ao clone corrigido. Os diagnósticos locais ficam em
`artifacts/observability-http-01-recovery.json`,
`artifacts/observability-http-02-recovery.json` e
`artifacts/observability-http-02-review.json`. Não são campanhas novas. Preferir o
launcher com as janelas fechadas enquanto a margem aqui ficar abaixo de 5 GiB;
reinicialização não é requisito presumido.

**Execução direta 03 e preparação da sucessora:** após reinício do Docker/WSL e
liberação pontual de caches Linux com containers parados, a entrada registrou 5,11 GiB.
A consulta retornou 503 em aproximadamente 66 ms observados: três spans correlacionados,
dois lotes aceitos e zero rejeitados. O span cliente do Core registrou `transport`,
sem resposta HTTP remota ou span servidor de Tracking. Isso difere da resposta remota
503 da tentativa 02; não comprova uma causa comum. A falta do span, isoladamente,
não prova ausência de processamento. Nó parado e specs históricos preservados.

A sucessora `observability-http-04` acrescentou preparação limitada de comunicação:
GET `/health/ready` nos caminhos observador → Core, Core → Tracking e Tracking → Core,
até três rodadas. Os registros preservam status ou classe/errno de transporte, sem
bodies nem mensagens brutas. Todos os caminhos devem responder 200 antes da única
consulta de negócio. A espera de rollout é mantida; não há retry da consulta medida,
redução de guardas ou mudança de imagem. As consultas de saúde são preparação explícita,
não eventos de negócio nem spans experimentais. A execução 04, descrita abaixo, conferiu esses caminhos no Kind; isso não
atribui causa raiz ao transporte da tentativa 03.
A suíte de 317 testes passou; um teste adicional da sonda HTTP passou na suíte
focada de 14 casos. Lint e formatação aprovados.

**Tentativa 04 e correção do instrumento:** os três caminhos de saúde responderam
200 na primeira rodada; a consulta também respondeu 200, com quatro spans, três
lotes aceitos e zero rejeitados. O verificador confundia o resultado de negócio
`APPLIED` com o status da inbox: `InboxStatus` admite `RECEIVED`, `PROCESSED` e
`REJECTED`. A listagem não expõe o resultado detalhado de negócio. A asserção antiga
era incompatível com o próprio schema e foi corrigida sem alterar a aplicação.

Na sucessora 05, passou-se a exigir um item/total, as três identidades conhecidas (evento externo,
inbox e tracking event), status `PROCESSED`, progresso `COMPLETED`, conclusão registrada
e ausência de código de erro. Preservar cada conferência como booleano independente
dos spans, sem copiar o corpo completo. Testes rejeitam `APPLIED` como status, identidades
divergentes, trabalho pendente e erro. A tentativa 04 mantém o veredito original:
a resposta integral não foi preservada e não pode ser revalidada retrospectivamente.

**Fechamento 05:** execução direta após liberação pontual de cache Linux, com todos
os containers parados antes da preparação e guarda de 5 GiB preservada. Um GET 200,
`PROCESSED` / `COMPLETED`, identidades e ausência de erro conferidos independentemente.
Quatro spans, parentela válida, três lotes aceitos e zero rejeitados. O observador
registrou aproximadamente 152 ms nesta consulta; não é benchmark ou medição de
latência de processamento assíncrono. Métricas de pods indisponíveis; overhead não
medido. Clones em zero réplicas, specs históricos intactos e nó parado.

Os [oito registros selecionados e manifesto](docs/evidence/observability/http-05/)
são cópias exatas, pequenas e examináveis no GitHub. A releitura offline reproduziu
`review.json` a partir dos spans e do resultado funcional; os hashes foram conferidos.
319 testes, lint e formatação passaram antes da execução. A nova capacidade distingue
uma resposta remota de um erro de transporte no hop instrumentado, sem diagnosticar
a exceção dentro de Tracking ou explicar os 503 das campanhas antigas. Encerrar a
fatia saudável; escolher uma perturbação controlada somente se houver uma pergunta
que demande evidência além dessa cobertura.

**Aceite da fatia:** identificar a mesma chamada nas fronteiras instrumentadas,
confrontar resposta pública, relatar marcos ausentes e saúde da exportação. Medir
volume e recursos disponíveis sem alegar overhead causal. Se um trace apenas
reempacotar a informação existente, manter como complemento; se localizar uma
fronteira antes invisível, decidir uma perturbação única com resultado esperado.
Não depender de reproduzir o 503 histórico para justificar continuidade.

Em futura investigação temporal, observar estado de negócio e rollout **em paralelo**,
com diários separados, para não adiar uma consulta deliberadamente até a prontidão.
Não modificar retroativamente os casos atuais: a espera sequencial está documentada.

### Verificação HTTP controlada autorizada

Executar `Invoke-HttpTracePilot.ps1 -Scenario transport-fault` em saída exclusiva.
O contrato está no DESIGN §8.8 e em `http_trace_fault.py`: três consultas ao evento
concluído, sem webhook, falha pela parada da API Tracking clonada e restauração
em `finally`. Preservar os três resultados funcionais, snapshots de spans, intervenção,
restauração e julgamento próprio de cada fase. A consulta durante a falha deve ser
inconclusiva quanto ao estado de negócio, mesmo se o diagnóstico da fronteira aprovar.

A seleção [HTTP 02/03](docs/evidence/observability/http-errors/manifest.json) torna
examináveis a resposta remota e a categoria de transporte anteriores. Esses registros
preparatórios não equivalem a falhas controladas e não determinam causas históricas.
Ao terminar esta única sequência, consolidar o valor acrescentado e pausar antes de
outra fronteira de instrumentação. Métricas indisponíveis limitam a avaliação de custo;
não bloqueiam por si só o diagnóstico funcional.

A tentativa `observability-http-fault-01` iniciou após a CI e as guardas. A fase
`before` confirmou HTTP 200, nove conferências funcionais e quatro spans. Houve
`TypeError` antes da consulta de falha; `restoration.json` confirma o spec original
restaurado e `preservation.json` confirma deployments históricos preservados, com
clones em zero e nó parado. Não há evidência da consulta sob interrupção nesta tentativa.

Foi reproduzido offline um defeito na leitura de EndpointSlice com `endpoints: null`:
o executor tentava percorrer `None`. O payload de endpoints não foi preservado na
01; portanto, a reprodução identifica um caminho compatível, sem afirmar prova da
resposta exata recebida. A sucessora trata a coleção vazia, mantém as guardas e
registra localização de exceção (arquivo/função/linha, sem mensagem ou variáveis).
Testes cobrem endpoints nulos/vazios e retomada com endpoint pronto. Saída sucessora:
`artifacts/observability-http-fault-02`; preservar a 01 sem reclassificação retrospectiva.
A correção passou em 325 testes, lint e formatação. Uma tentativa de liberar cache
com containers parados recuperou a margem local somente até 3,30 GiB; não houve
nova execução integrada nem reconciliação dos recursos. O launcher local
`artifacts/Invoke-HttpFault02.local.ps1` reúne a reconciliação por run ID da 01,
verificação de memória e execução única da 02, preservando volumes e resultados.
Sua sintaxe foi validada; a execução foi realizada posteriormente, conforme o resultado abaixo.


**Resultado da sucessora 02:** a preparação recuperou 6,36 GiB antes do launcher.
A execução confirmou duas consultas 200, com as nove verificações funcionais e quatro
spans válidos em cada trace. Na segunda, o seletor já estava alterado e a amostra de
EndpointSlice tinha zero endpoints prontos; mesmo assim houve span servidor Tracking
e resposta remota 200. O verificador rejeitou corretamente com
`EXPECTED_QUERY_FAILURE_MISSING`. Não houve consulta posterior à restauração, pois a
sequência foi interrompida; o spec do Service foi restaurado, os deployments históricos
preservados, clones zerados e nó parado. Nenhuma escrita de negócio.

O campo `injection.confirmed` da 02 comprova somente a alteração de configuração e a
amostra de endpoints, **não indisponibilidade efetiva do caminho HTTP**. Pool persistente
do cliente Core e convergência de encaminhamento são hipóteses, não causas isoladas.
As duas respostas/traces foram conferidas offline pelo contrato saudável, sem alterar
o julgamento original. Fontes locais: `artifacts/observability-http-fault-02/` e
`artifacts/observability-http-fault-02-offline-review.json`; esta seleção ainda não foi
publicada como pacote de evidências.

Decisão autorizada para a sucessora 03: substituir a alteração de seletor por parada temporária
somente da API Tracking clonada, confirmar término do pod antes da consulta e restaurar
uma réplica antes da conferência final. O mecanismo foi autorizado e implementado prospectivamente no DESIGN/executor.
A sucessora 03 exige zero pods (incluindo terminating), zero endpoints e, após
restauração, novo pod Ready antes da terceira consulta. A execução integrada foi concluída conforme o fechamento abaixo. A revisão exige tanto a intervenção quanto o erro HTTP observado.
Validação: 329 testes, Ruff e formatação aprovados. O launcher local
`artifacts/Invoke-HttpFault03.local.ps1` reconcilia por run ID os recursos da 02 antes
da sucessora, preservando volumes e registros.
Manter Core, receptor OTLP, workers e APIs históricos intactos. Não alterar pooling,
latência, retries ou aplicação apenas para fabricar a resposta esperada. Encerrar aqui
as repetições do mecanismo atual; não ampliar o estudo para investigar rede Kubernetes.

### Fechamento da sequência HTTP controlada

`observability-http-fault-03`, executor `416aef7`, aplicação instrumentada `045e1ca`:
execução direta após liberação pontual de cache, sempre com containers parados na
preparação. Entrada 5,04 GiB, mínimo observado 2,61 GiB; as guardas foram preservadas.
Consulta inicial 200 com nove conferências e quatro spans; ausência do pod e dos
endpoints confirmada; consulta sob interrupção 503 com três spans, erro `transport`
no cliente Core e nenhuma resposta remota. Após restaurar uma réplica, um novo pod
Ready e endpoint disponível precederam o terceiro GET 200 com as mesmas identidades.
Foram oito lotes recebidos cumulativamente, zero rejeitados e onze spans distintos.

O spec do clone foi restaurado, o Service permaneceu intacto, deployments históricos
preservados e nó parado; nenhuma escrita de negócio. Os três julgamentos foram
reproduzidos offline. Os [18 arquivos selecionados e manifesto](docs/evidence/observability/http-fault-03/manifest.json)
estão versionados com bytes preservados; séries completas do host permanecem locais.
API de métricas indisponível: overhead continua não quantificado.

Ganho demonstrado: localizar uma falha conhecida de consulta na fronteira Core →
Tracking, preservando a distinção entre indisponibilidade de observação e resultado
de negócio confirmado antes/depois. Não houve leitura independente durante a falha,
processamento em andamento ou investigação causal dos erros antigos. A restauração
foi comandada pelo executor, não pela política de recuperação. Uma sequência não
comprova superioridade diagnóstica geral nem desempenho da instrumentação.

Encerrar esta fatia e consolidá-la como capacidade diagnóstica complementar. Não
repetir saudável/pendência/HTTP, ampliar para SQL/AMQP, instalar plataformas ou abrir
AKS automaticamente. A próxima decisão pode ser fechamento documental da extensão
ou outra pergunta delimitada, sem condicionar o valor dos resultados já obtidos a
uma nova campanha.

### Guardas para qualquer nova execução

Avisar a janela crítica e conferir tomada, containers e margem: 5 GiB de entrada,
2 GiB durante execução. Não apagar volumes ou reduzir guardas. Antes da janela,
com todos os containers parados, é permitida uma liberação pontual de cache Linux
(`sync` + `drop_caches`), seguida de espera limitada e nova medição. Registrar essa
preparação; não a apresentar como ganho causal. Os procedimentos 03/05 incluíram
cache e a preparação 03 incluiu reinício autorizado de Docker/WSL. Reinícios ficam
restritos à recuperação operacional necessária, com workloads parados; não são uma
rotina de memória, especialmente após o erro de socket do Docker observado. Durante
a medição, não limpar cache nem reiniciar Docker/WSL.
Fixar previamente destino, número de chamadas e teto de tempo; não repetir até passar.
Preparação, testes offline e ajustes rotineiros seguem dentro do escopo; parar diante
de alteração de contrato, risco do ambiente, custo externo ou mudança relevante do
desenho. Manual ou execução direta têm o mesmo valor se o protocolo for equivalente.
Não há nova carga autorizada pelos registros de campanhas já encerradas.

<a id="4-continuidade-condicionada"></a>

### Continuidade após a exploração

Prometheus e verificações de segurança permanecem possibilidades por lacuna
concreta, sem integrar automaticamente este incremento. Se o ganho diagnóstico
for pequeno, registrar complemento breve e voltar à avaliação de viabilidade AKS;
isso não autoriza provisionamento ou migração automática.

**AKS:** extensão opcional de portabilidade e funcionamento selecionado, com prints
e evidências do ambiente efetivamente usado. ACR depende da implantação escolhida.
Os resultados quantitativos do Kind não se tornam resultados de nuvem. Uma
comparação correspondente no AKS exigiria protocolo e repetições próprios;
instrumentação e ambiente não devem mudar juntos numa comparação que pretenda
atribuir efeito somente à instrumentação.

As consultas anteriores não estabeleceram uma configuração Azure provisionável.
Antes de qualquer apply, revisar assinatura, região, quotas, restrições de SKU,
capacidade, acesso, orçamento, encerramento e custos residuais conforme o
[guia Terraform](infra/README.md). Quota positiva não garante alocação. Não iniciar
nuvem, alterar limites de carga ou refatorar a aplicação a partir desta consolidação.

## 5. Preservação e histórico

Os relatórios substituem o diário preparatório na leitura principal. O
[histórico completo até o encerramento](https://github.com/campos-labs/fulfillflow-infra/blob/58f4483e0fdb2e5273b9b533d9173de494818a3c/RELEASE_PLAN.md)
continua acessível por commit imutável; as pastas originais permanecem intactas.
Identificadores como `a2-*`, `b1-p1-*` e nomes históricos de scripts são mantidos
somente para rastrear protocolos e arquivos. Não representam novos incrementos pendentes.

As três pastas de tentativas em cada ZIP são completas. Configurações privadas,
credenciais, dumps e kubeconfigs continuam fora do Git. Os pacotes permitem
conferir dados e gráficos sem o notebook original; não incluem imagem Docker nem
garantem recriação idêntica de hardware/runtime ou restauração de backup independente.
Novas medições exigem ambiente e protocolo identificados, diretórios novos e
encerramento limitado, preservando resultados desfavoráveis e falhas de execução.

Versões seguem a convenção: correções compatíveis incrementam PATCH, capacidades
compatíveis MINOR e mudanças incompatíveis MAJOR; candidatas usam `-rc.N`.
Não reservar automaticamente uma versão para cada ferramenta ou ambiente.
